"""Cover Art Archive client with an on-disk cache.

Covers are fetched once and then served by Muzikk itself, so the browser never
talks to coverartarchive.org and the import pipeline reuses the same bytes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import httpx

from .. import __version__
from ..config import get_env_config
from .base import ServiceError, normalize_base_url
from .settings import CoverArtSettings

COVER_USER_AGENT = f"Muzikk/{__version__} ( muzikk@localhost )"

logger = logging.getLogger(__name__)

VALID_SIZES = (250, 500, 1200)
NEGATIVE_TTL_SECONDS = 7 * 24 * 3600
_locks: dict[str, asyncio.Lock] = {}


def _lock_for(key: str) -> asyncio.Lock:
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


def purge_cache() -> int:
    """Drop every cached cover, including the "no cover" markers.

    Pointing the setting at the wrong host makes every lookup answer 404, which
    would otherwise keep the covers hidden for a week after the fix.
    """
    cache_dir = get_env_config().cache_dir / "covers"
    removed = 0
    for path in cache_dir.glob("*"):
        if path.suffix not in (".jpg", ".missing"):
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:  # noqa: PERF203 - one bad file must not stop the purge
            logger.warning("Could not remove cached cover %s", path)
    return removed


class CoverArtClient:
    service_name = "coverart"

    def __init__(self, settings: CoverArtSettings) -> None:
        self.settings = settings
        self.base_url = normalize_base_url(settings.url) or "https://coverartarchive.org"
        self.cache_dir = get_env_config().cache_dir / "covers"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _closest_size(size: int) -> int:
        return min(VALID_SIZES, key=lambda candidate: abs(candidate - size))

    def front_url(self, mbid: str, *, entity: str = "release", size: int | None = None) -> str:
        resolved = self._closest_size(size or self.settings.preferred_size)
        return f"{self.base_url}/{entity}/{mbid}/front-{resolved}"

    def _cache_paths(self, mbid: str, entity: str, size: int) -> tuple[Path, Path]:
        stem = f"{entity}_{mbid}_{size}"
        return self.cache_dir / f"{stem}.jpg", self.cache_dir / f"{stem}.missing"

    async def get_front(
        self, mbid: str, *, entity: str = "release", size: int | None = None
    ) -> bytes | None:
        """Return the front cover bytes, using the cache when available."""
        if not mbid:
            return None
        resolved = self._closest_size(size or self.settings.preferred_size)
        image_path, missing_path = self._cache_paths(mbid, entity, resolved)

        if image_path.exists() and image_path.stat().st_size > 0:
            return image_path.read_bytes()
        if missing_path.exists() and time.time() - missing_path.stat().st_mtime < NEGATIVE_TTL_SECONDS:
            return None

        async with _lock_for(f"{entity}:{mbid}:{resolved}"):
            if image_path.exists() and image_path.stat().st_size > 0:
                return image_path.read_bytes()

            url = self.front_url(mbid, entity=entity, size=resolved)
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(25.0, connect=8.0), follow_redirects=True
                ) as client:
                    response = await client.get(url, headers={"User-Agent": COVER_USER_AGENT})
            except httpx.HTTPError as exc:
                logger.debug("Cover art fetch failed for %s: %s", mbid, exc)
                return None

            if response.status_code == 404:
                missing_path.write_bytes(b"")
                return None
            if response.status_code >= 400 or not response.content:
                return None

            image_path.write_bytes(response.content)
            missing_path.unlink(missing_ok=True)
            return response.content

    def remember(self, mbid: str, *, entity: str, size: int | None, data: bytes) -> None:
        """Keep bytes under a cache key, so the next tile does not start over."""
        resolved = self._closest_size(size or self.settings.preferred_size)
        image_path, missing_path = self._cache_paths(mbid, entity, resolved)
        image_path.write_bytes(data)
        missing_path.unlink(missing_ok=True)

    def is_exhausted(self, mbid: str, *, entity: str, size: int | None) -> bool:
        """Whether the editions of this group were already tried and had no art."""
        resolved = self._closest_size(size or self.settings.preferred_size)
        marker = self.cache_dir / f"{entity}_{mbid}_{resolved}.exhausted"
        if not marker.exists():
            return False
        if time.time() - marker.stat().st_mtime > NEGATIVE_TTL_SECONDS:
            marker.unlink(missing_ok=True)
            return False
        return True

    def mark_exhausted(self, mbid: str, *, entity: str, size: int | None) -> None:
        resolved = self._closest_size(size or self.settings.preferred_size)
        (self.cache_dir / f"{entity}_{mbid}_{resolved}.exhausted").write_bytes(b"")

    async def get_front_with_fallback(
        self,
        release_mbid: str | None,
        release_group_mbid: str | None,
        *,
        size: int | None = None,
    ) -> bytes | None:
        if release_mbid:
            data = await self.get_front(release_mbid, entity="release", size=size)
            if data:
                return data
        if release_group_mbid:
            return await self.get_front(release_group_mbid, entity="release-group", size=size)
        return None

    async def test_connection(self) -> dict[str, object]:
        """Check the service answers, without depending on one album having art.

        A 404 still proves the host is the archive and is reachable, so it is
        reported as a success with a nuance.
        """
        # Nevermind, one of the most reliably illustrated release groups.
        probe = "1b022e01-4da6-387b-8658-8678046e4cef"
        url = f"{self.base_url}/release-group/{probe}/front-250"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, connect=8.0), follow_redirects=True
            ) as client:
                response = await client.get(url, headers={"User-Agent": COVER_USER_AGENT})
        except httpx.HTTPError as exc:
            raise ServiceError(
                self.service_name, f"unreachable ({exc.__class__.__name__})"
            ) from exc

        content_type = response.headers.get("Content-Type", "")
        return {
            "url": self.base_url,
            "status": response.status_code,
            "cover_found": response.status_code == 200 and content_type.startswith("image/"),
        }

    def cached_path(self, mbid: str, *, entity: str = "release", size: int | None = None) -> Path:
        resolved = self._closest_size(size or self.settings.preferred_size)
        return self._cache_paths(mbid, entity, resolved)[0]
