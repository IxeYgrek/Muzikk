"""qBittorrent WebUI API client (v2)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..services.base import ServiceError, ServiceNotConfigured, normalize_base_url
from ..services.settings import QbittorrentSettings

logger = logging.getLogger(__name__)

COMPLETED_STATES = {
    "uploading",
    "stalledUP",
    "pausedUP",
    "queuedUP",
    "forcedUP",
    "checkingUP",
    "stoppedUP",
}
FAILED_STATES = {"error", "missingFiles", "unknown"}
STALLED_STATES = {"stalledDL", "queuedDL", "metaDL", "checkingDL", "allocating"}


class QbittorrentClient:
    service_name = "qbittorrent"

    def __init__(self, settings: QbittorrentSettings) -> None:
        self.settings = settings
        self.base_url = normalize_base_url(settings.url)
        self._client: httpx.AsyncClient | None = None
        self._authenticated = False

    @property
    def configured(self) -> bool:
        return bool(self.settings.enabled and self.base_url)

    def _host_header(self) -> str:
        return urlsplit(self.base_url).netloc or self.base_url

    async def _ensure_client(self) -> httpx.AsyncClient:
        if not self.configured:
            raise ServiceNotConfigured(self.service_name)
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=f"{self.base_url}/api/v2",
                timeout=httpx.Timeout(30.0, connect=8.0),
                follow_redirects=True,
                headers={"Referer": self.base_url, "Origin": self.base_url},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._authenticated = False

    async def login(self, *, force: bool = False) -> None:
        if self._authenticated and not force:
            return
        client = await self._ensure_client()
        if not self.settings.username:
            # Authentication bypassed for whitelisted clients.
            self._authenticated = True
            return
        try:
            response = await client.post(
                "/auth/login",
                data={"username": self.settings.username, "password": self.settings.password},
            )
        except httpx.HTTPError as exc:
            raise ServiceError(self.service_name, f"unreachable ({exc.__class__.__name__})") from exc

        body = response.text.strip()

        # Success is a 200 with "Ok." up to 5.1, an empty 204 from 5.2 onwards.
        # The session cookie is kept by the client whatever its name, which
        # changed to QBT_SID_<port> in 5.2 as well.
        if 200 <= response.status_code < 300 and body in ("", "Ok."):
            self._authenticated = True
            return

        if response.status_code == 401:
            raise ServiceError(
                self.service_name,
                f'refused the login of "{self.settings.username}" (HTTP 401). Check the Web UI '
                "user and password. On qBittorrent 5.1 and older this code can also mean the "
                f"Host header was rejected: untick \"Enable Host header validation\" or add "
                f"{self._host_header()} to the whitelist.",
                401,
            )
        if response.status_code == 403:
            raise ServiceError(
                self.service_name,
                "refused (HTTP 403): qBittorrent bans an IP for a while after a few failed "
                f"logins, restart the container to clear it - {body[:120]}",
                403,
            )
        raise ServiceError(
            self.service_name,
            f'rejected the login of "{self.settings.username}" (HTTP '
            f"{response.status_code}, answered {body[:80]!r}). Check the Web UI user and "
            "password, or leave the user empty if qBittorrent bypasses authentication "
            "for this subnet.",
            response.status_code,
        )

    async def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        expect_json: bool = True,
        retry: bool = True,
    ) -> Any:
        await self.login()
        client = await self._ensure_client()
        try:
            response = await client.request(method, path, params=params, data=data, files=files)
        except httpx.HTTPError as exc:
            raise ServiceError(self.service_name, f"unreachable ({exc.__class__.__name__})") from exc

        if response.status_code in (401, 403) and retry:
            self._authenticated = False
            await self.login(force=True)
            return await self._call(
                method, path, params=params, data=data, files=files,
                expect_json=expect_json, retry=False,
            )

        if response.status_code >= 400:
            raise ServiceError(
                self.service_name,
                f"HTTP {response.status_code} on {path} - {response.text[:200]}",
                response.status_code,
            )
        if not expect_json:
            return response.text
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    async def version(self) -> str:
        return str(await self._call("GET", "/app/version", expect_json=False)).strip()

    async def preferences(self) -> dict[str, Any]:
        return await self._call("GET", "/app/preferences") or {}

    async def categories(self) -> dict[str, Any]:
        return await self._call("GET", "/torrents/categories") or {}

    async def ensure_category(self) -> None:
        category = self.settings.category
        if not category:
            return
        existing = await self.categories()
        if category in existing:
            return
        try:
            await self._call(
                "POST",
                "/torrents/createCategory",
                data={"category": category, "savePath": self.settings.save_path},
                expect_json=False,
            )
        except ServiceError as exc:
            logger.warning("Unable to create the qBittorrent category %s: %s", category, exc.message)

    def _add_parameters(self) -> dict[str, Any]:
        paused = "true" if self.settings.add_paused else "false"
        return {
            "category": self.settings.category,
            "savepath": self.settings.save_path,
            # "paused" was renamed "stopped" in qBittorrent 5.0; sending both
            # keeps every version happy.
            "paused": paused,
            "stopped": paused,
            "autoTMM": "false",
            "contentLayout": "Original",
        }

    async def add_torrent_file(self, content: bytes, filename: str = "muzikk.torrent") -> None:
        await self.ensure_category()
        data: dict[str, Any] = self._add_parameters()
        await self._call(
            "POST",
            "/torrents/add",
            data=data,
            files={"torrents": (filename, content, "application/x-bittorrent")},
            expect_json=False,
        )

    async def add_magnet(self, magnet: str) -> None:
        await self.ensure_category()
        await self._call(
            "POST",
            "/torrents/add",
            data={"urls": magnet, **self._add_parameters()},
            expect_json=False,
        )

    async def info(self, info_hash: str) -> dict[str, Any] | None:
        payload = await self._call(
            "GET", "/torrents/info", params={"hashes": info_hash.lower()}
        )
        if isinstance(payload, list) and payload:
            return payload[0]
        return None

    async def files(self, info_hash: str) -> list[dict[str, Any]]:
        payload = await self._call("GET", "/torrents/files", params={"hash": info_hash.lower()})
        return payload if isinstance(payload, list) else []

    async def delete(self, info_hash: str, *, delete_files: bool) -> None:
        await self._call(
            "POST",
            "/torrents/delete",
            data={"hashes": info_hash.lower(), "deleteFiles": "true" if delete_files else "false"},
            expect_json=False,
        )

    async def test_connection(self) -> dict[str, Any]:
        version = await self.version()
        preferences = await self.preferences()
        return {
            "version": version,
            "save_path": preferences.get("save_path"),
            "category": self.settings.category,
        }
