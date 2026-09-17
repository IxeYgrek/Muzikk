"""Torrent provider: Prowlarr for searching, qBittorrent for downloading."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..models import Indexer
from ..services.base import HttpService, ServiceError, ServiceNotConfigured, normalize_base_url
from ..services.settings import ProwlarrSettings
from . import bencode
from .base import AlbumQuery, Candidate, CandidateFile, DownloadHandle, DownloadStatus, Provider
from .qbittorrent import COMPLETED_STATES, FAILED_STATES, QbittorrentClient

logger = logging.getLogger(__name__)

PRIVACY_GROUPS = {
    "public": "torrent_public",
    "semiprivate": "torrent_public",
    "semi-private": "torrent_public",
    "private": "torrent_private",
}


class ProwlarrClient(HttpService):
    service_name = "prowlarr"

    def __init__(self, settings: ProwlarrSettings) -> None:
        super().__init__(normalize_base_url(settings.url))
        self.settings = settings
        self.headers = {"X-Api-Key": settings.api_key, "Accept": "application/json"}

    @property
    def configured(self) -> bool:
        return bool(self.settings.enabled and self.base_url and self.settings.api_key)

    async def list_indexers(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/api/v1/indexer") or []

    async def search(
        self,
        query: str,
        *,
        indexer_ids: list[int],
        categories: list[int],
        limit: int,
        search_type: str = "search",
    ) -> list[dict[str, Any]]:
        params: list[tuple[str, Any]] = [("query", query), ("limit", limit), ("type", search_type)]
        # Prowlarr rejects comma separated lists: each value needs its own pair.
        for indexer_id in indexer_ids:
            params.append(("indexerIds", indexer_id))
        for category in categories:
            params.append(("categories", category))

        try:
            return await self.request("GET", "/api/v1/search", params=params) or []
        except ServiceError as exc:
            if search_type != "search" and exc.status_code in (400, 404):
                logger.info("Prowlarr rejected the %s search type, retrying as free text", search_type)
                return await self.search(
                    query,
                    indexer_ids=indexer_ids,
                    categories=categories,
                    limit=limit,
                    search_type="search",
                )
            raise

    async def fetch_release(self, download_url: str) -> tuple[str, bytes | str]:
        """Return ``("torrent", bytes)`` or ``("magnet", uri)``."""
        if download_url.startswith("magnet:"):
            return "magnet", download_url
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(45.0, connect=10.0), follow_redirects=False
            ) as client:
                response = await client.get(download_url, headers=self.headers)
                # Some indexers answer with a redirect to a magnet link.
                hops = 0
                while response.is_redirect and hops < 5:
                    location = response.headers.get("location") or ""
                    if location.startswith("magnet:"):
                        return "magnet", location
                    response = await client.get(location, headers=self.headers)
                    hops += 1
        except httpx.HTTPError as exc:
            raise ServiceError(self.service_name, f"cannot fetch the release ({exc})") from exc

        if response.status_code >= 400:
            raise ServiceError(
                self.service_name, f"HTTP {response.status_code} while fetching the release"
            )
        content = response.content
        if content[:1] == b"d":
            return "torrent", content
        text = content[:2000].decode("utf-8", errors="ignore").strip()
        if text.startswith("magnet:"):
            return "magnet", text
        raise ServiceError(self.service_name, "the downloaded file is not a torrent")

    async def test_connection(self) -> dict[str, Any]:
        status = await self.request("GET", "/api/v1/health")
        indexers = await self.list_indexers()
        music = [
            item
            for item in indexers
            if any(
                (category.get("id") or 0) // 1000 == 3
                for category in (item.get("capabilities") or {}).get("categories") or []
            )
        ]
        return {
            "indexers": len(indexers),
            "music_indexers": len(music),
            "health_issues": len(status or []),
        }


class TorrentProvider(Provider):
    """One instance per privacy group, searching all of its indexers at once."""

    kind = "torrent"

    def __init__(
        self,
        group: str,
        indexers: list[Indexer],
        prowlarr: ProwlarrClient,
        qbittorrent: QbittorrentClient,
        settings: ProwlarrSettings,
    ) -> None:
        self.group = group
        self.key = group
        self.label = "Trackers privés" if group == "torrent_private" else "Trackers publics"
        self.indexers = indexers
        self.prowlarr = prowlarr
        self.qbittorrent = qbittorrent
        self.settings = settings
        self._by_id = {indexer.prowlarr_id: indexer for indexer in indexers}

    @property
    def enabled(self) -> bool:
        return bool(
            self.prowlarr.configured
            and self.qbittorrent.configured
            and any(indexer.enabled for indexer in self.indexers)
        )

    async def search(self, query: AlbumQuery) -> list[Candidate]:
        if not self.enabled:
            raise ServiceNotConfigured("prowlarr")

        indexer_ids = [indexer.prowlarr_id for indexer in self.indexers if indexer.enabled]
        seen: set[str] = set()
        candidates: list[Candidate] = []

        for term in query.search_terms()[:2]:
            try:
                results = await self.prowlarr.search(
                    term,
                    indexer_ids=indexer_ids,
                    categories=list(self.settings.categories),
                    limit=self.settings.result_limit,
                    search_type="music" if self.settings.use_music_search else "search",
                )
            except ServiceError as exc:
                logger.warning("Prowlarr search failed for %r: %s", term, exc.message)
                continue

            for result in results:
                guid = result.get("guid") or result.get("downloadUrl") or result.get("title")
                if not guid or guid in seen:
                    continue
                seen.add(guid)

                indexer = self._by_id.get(result.get("indexerId") or -1)
                info_hash = (result.get("infoHash") or "").lower() or None
                magnet = result.get("magnetUrl")
                if not info_hash and magnet:
                    info_hash = bencode.magnet_info_hash(magnet)

                candidates.append(
                    Candidate(
                        provider_key=self.key,
                        provider_label=(indexer.name if indexer else result.get("indexer") or self.label),
                        kind=self.kind,
                        title=result.get("title") or "",
                        size=int(result.get("size") or 0),
                        seeders=result.get("seeders"),
                        leechers=result.get("leechers"),
                        download_url=result.get("downloadUrl"),
                        magnet_url=magnet,
                        info_hash=info_hash,
                        indexer_id=result.get("indexerId"),
                        indexer_privacy=(indexer.privacy if indexer else "public"),
                        publish_date=result.get("publishDate"),
                        extra={
                            "guid": guid,
                            "search_term": term,
                            "min_seeders": indexer.min_seeders if indexer else 1,
                            "indexer_priority": indexer.priority if indexer else 50,
                        },
                    )
                )

            if len(candidates) >= self.settings.result_limit:
                break

        return candidates

    async def inspect(self, candidate: Candidate) -> Candidate:
        """Read the torrent file list, which is the only reliable content proof."""
        if candidate.files_inspected or not self.settings.inspect_torrent_files:
            return candidate
        if not candidate.download_url and not candidate.magnet_url:
            return candidate

        source = candidate.download_url or candidate.magnet_url or ""
        try:
            kind, payload = await self.prowlarr.fetch_release(source)
        except ServiceError as exc:
            candidate.reasons.append(f"torrent file unavailable: {exc.message}")
            return candidate

        if kind == "magnet":
            candidate.magnet_url = str(payload)
            candidate.info_hash = candidate.info_hash or bencode.magnet_info_hash(str(payload))
            candidate.reasons.append("magnet only, file list unknown before download")
            return candidate

        content = bytes(payload)  # type: ignore[arg-type]
        try:
            name, files = bencode.list_files(content)
        except bencode.BencodeError as exc:
            candidate.reasons.append(f"unreadable torrent: {exc}")
            return candidate

        candidate.files = [CandidateFile(filename=path, size=size) for path, size in files]
        candidate.files_inspected = True
        candidate.info_hash = candidate.info_hash or bencode.info_hash(content)
        candidate.extra["torrent_name"] = name
        candidate.extra["torrent_bytes"] = content
        if not candidate.size:
            candidate.size = sum(size for _, size in files)
        return candidate

    async def enqueue(self, candidate: Candidate) -> DownloadHandle:
        content = candidate.extra.get("torrent_bytes")
        info_hash = candidate.info_hash

        if content is None and candidate.download_url:
            kind, payload = await self.prowlarr.fetch_release(candidate.download_url)
            if kind == "torrent":
                content = bytes(payload)  # type: ignore[arg-type]
                info_hash = info_hash or bencode.info_hash(content)
            else:
                candidate.magnet_url = str(payload)
                info_hash = info_hash or bencode.magnet_info_hash(str(payload))

        if content is not None:
            info_hash = info_hash or bencode.info_hash(content)
            if not info_hash:
                raise ServiceError("qbittorrent", "unable to compute the torrent info hash")
            await self.qbittorrent.add_torrent_file(content)
        elif candidate.magnet_url:
            if not info_hash:
                raise ServiceError("qbittorrent", "magnet link without a usable info hash")
            await self.qbittorrent.add_magnet(candidate.magnet_url)
        else:
            raise ServiceError("prowlarr", "candidate has neither a torrent file nor a magnet link")

        return DownloadHandle(
            client="qbittorrent",
            external_id=info_hash,
            payload={
                "title": candidate.title,
                "indexer": candidate.provider_label,
                "size": candidate.size,
            },
        )

    async def status(self, handle: DownloadHandle) -> DownloadStatus:
        try:
            torrent = await self.qbittorrent.info(handle.external_id)
        except ServiceError as exc:
            return DownloadStatus(state="downloading", message=exc.message)

        if torrent is None:
            return DownloadStatus(state="queued", message="torrent not visible in qBittorrent yet")

        state = str(torrent.get("state") or "")
        progress = float(torrent.get("progress") or 0.0) * 100
        size = int(torrent.get("size") or 0)
        downloaded = int(torrent.get("completed") or torrent.get("downloaded") or 0)
        speed = int(torrent.get("dlspeed") or 0)
        eta = torrent.get("eta")
        content_path = torrent.get("content_path") or torrent.get("save_path")

        if state in COMPLETED_STATES or progress >= 100.0:
            return DownloadStatus(
                state="completed",
                progress=100.0,
                size=size,
                downloaded=downloaded,
                content_path=content_path,
            )
        if state in FAILED_STATES:
            return DownloadStatus(
                state="failed",
                progress=progress,
                size=size,
                downloaded=downloaded,
                message=f"qBittorrent reported {state}",
            )

        return DownloadStatus(
            state="downloading" if speed > 0 else "queued",
            progress=progress,
            size=size,
            downloaded=downloaded,
            speed=speed,
            eta=int(eta) if isinstance(eta, (int, float)) and eta and eta < 8640000 else None,
            content_path=content_path,
            message=state,
        )

    async def abort(self, handle: DownloadHandle) -> None:
        try:
            await self.qbittorrent.delete(handle.external_id, delete_files=True)
        except ServiceError as exc:
            logger.warning("Unable to remove torrent %s: %s", handle.external_id, exc.message)

    async def finalize(self, handle: DownloadHandle, *, keep_source: bool) -> None:
        if keep_source:
            # Files were hardlinked, the torrent keeps seeding.
            return
        try:
            await self.qbittorrent.delete(handle.external_id, delete_files=True)
        except ServiceError as exc:
            logger.warning("Unable to clean up torrent %s: %s", handle.external_id, exc.message)


def group_for_privacy(privacy: str | None) -> str:
    return PRIVACY_GROUPS.get((privacy or "public").lower().replace("_", "-"), "torrent_public")
