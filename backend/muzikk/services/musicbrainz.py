"""MusicBrainz web service client.

Targets a self-hosted instance first and optionally falls back to the public
server, which is rate limited to one request per second.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any
from urllib.parse import urlsplit

from .. import __version__
from .base import HttpService, RateLimiter, ServiceError, ServiceNotConfigured, normalize_base_url
from .settings import MusicBrainzSettings

logger = logging.getLogger(__name__)

_LUCENE_SPECIALS = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')

CACHE_TTL_SECONDS = 600
CACHE_MAX_ENTRIES = 2000

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = asyncio.Lock()

_limiters: dict[str, RateLimiter] = {}


def escape_lucene(value: str) -> str:
    return _LUCENE_SPECIALS.sub(r"\\\1", value or "")


def _limiter(key: str, per_second: float) -> RateLimiter:
    limiter = _limiters.get(key)
    if limiter is None or limiter._interval != (1.0 / per_second if per_second > 0 else 0.0):
        limiter = RateLimiter(per_second)
        _limiters[key] = limiter
    return limiter


async def _cache_get(key: str) -> Any | None:
    async with _cache_lock:
        entry = _cache.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            _cache.pop(key, None)
            return None
        return value


async def _cache_set(key: str, value: Any) -> None:
    async with _cache_lock:
        if len(_cache) >= CACHE_MAX_ENTRIES:
            oldest = sorted(_cache.items(), key=lambda item: item[1][0])[: CACHE_MAX_ENTRIES // 4]
            for cache_key, _ in oldest:
                _cache.pop(cache_key, None)
        _cache[key] = (time.monotonic() + CACHE_TTL_SECONDS, value)


def clear_cache() -> None:
    _cache.clear()


class MusicBrainzClient(HttpService):
    service_name = "musicbrainz"

    def __init__(self, settings: MusicBrainzSettings) -> None:
        super().__init__(normalize_base_url(settings.url))
        self.settings = settings
        self.public_url = normalize_base_url(settings.public_url)
        self.user_agent = f"Muzikk/{__version__} ( {settings.contact} )"

    @property
    def configured(self) -> bool:
        return bool(self.base_url or (self.settings.use_public_fallback and self.public_url))

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": self.user_agent, "Accept": "application/json"}

    def _limiter_for(self, url: str) -> RateLimiter:
        """Rate limiter of the host being called, whatever field holds it.

        Putting musicbrainz.org in the "local server" field is a natural thing
        to do, and it used to fire ten requests per second at a service that
        allows one, which answers 503 and looks like a broken search.
        """
        host = (urlsplit(url).hostname or "local").lower()
        per_second = self.settings.rate_limit_per_second
        if host == "musicbrainz.org" or host.endswith(".musicbrainz.org"):
            per_second = min(self.settings.public_rate_limit_per_second or 1.0, 1.0)
        return _limiter(host, per_second)

    async def _get(self, path: str, params: dict[str, Any], *, use_cache: bool = True) -> Any:
        query = {**params, "fmt": "json"}
        cache_key = f"{path}?{sorted(query.items())}"
        if use_cache:
            cached = await _cache_get(cache_key)
            if cached is not None:
                return cached

        errors: list[str] = []

        if self.base_url:
            try:
                await self._limiter_for(self.base_url).acquire()
                result = await self.request(
                    "GET", f"{self.base_url}{path}", params=query, headers=self._headers()
                )
                if use_cache:
                    await _cache_set(cache_key, result)
                return result
            except ServiceError as exc:
                errors.append(f"local: {exc.message}")
                logger.warning("MusicBrainz local instance failed for %s (%s)", path, exc.message)

        # Retrying the same host would only earn a second refusal.
        if (
            self.settings.use_public_fallback
            and self.public_url
            and self.public_url != self.base_url
        ):
            await self._limiter_for(self.public_url).acquire()
            try:
                result = await self.request(
                    "GET", f"{self.public_url}{path}", params=query, headers=self._headers()
                )
                if use_cache:
                    await _cache_set(cache_key, result)
                return result
            except ServiceError as exc:
                errors.append(f"public: {exc.message}")

        if not errors:
            raise ServiceNotConfigured(self.service_name)
        raise ServiceError(self.service_name, "; ".join(errors))

    # ------------------------------------------------------------- searching

    async def search_release_groups(
        self,
        text: str,
        *,
        limit: int = 30,
        offset: int = 0,
        primary_type: str | None = None,
    ) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            return {"count": 0, "offset": 0, "release-groups": []}

        query = text
        if primary_type:
            query = f"({text}) AND primarytype:{escape_lucene(primary_type)}"

        params: dict[str, Any] = {"query": query, "limit": limit, "offset": offset, "dismax": "true"}
        try:
            return await self._get("/ws/2/release-group", params)
        except ServiceError:
            # Some search servers reject dismax; retry with a structured query.
            escaped = escape_lucene(text)
            structured = f'releasegroup:({escaped}) OR artist:({escaped})'
            if primary_type:
                structured = f"({structured}) AND primarytype:{escape_lucene(primary_type)}"
            return await self._get(
                "/ws/2/release-group",
                {"query": structured, "limit": limit, "offset": offset},
            )

    async def search_artists(self, text: str, *, limit: int = 20) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            return {"count": 0, "artists": []}
        try:
            return await self._get("/ws/2/artist", {"query": text, "limit": limit, "dismax": "true"})
        except ServiceError:
            return await self._get(
                "/ws/2/artist", {"query": f"artist:({escape_lucene(text)})", "limit": limit}
            )

    async def search_labels(self, text: str, *, limit: int = 25) -> dict[str, Any]:
        """Find a record label by name, to reach everything it published."""
        text = (text or "").strip()
        if not text:
            return {"count": 0, "labels": []}
        try:
            return await self._get("/ws/2/label", {"query": text, "limit": limit, "dismax": "true"})
        except ServiceError:
            return await self._get(
                "/ws/2/label", {"query": f"label:({escape_lucene(text)})", "limit": limit}
            )

    async def search_recordings(self, text: str, *, limit: int = 25) -> dict[str, Any]:
        """Find a track by name, to reach the albums holding it.

        Search results already carry the releases each recording appears on,
        which is what makes "I only remember one song" work.
        """
        text = (text or "").strip()
        if not text:
            return {"count": 0, "recordings": []}
        try:
            return await self._get(
                "/ws/2/recording", {"query": text, "limit": limit, "dismax": "true"}
            )
        except ServiceError:
            return await self._get(
                "/ws/2/recording",
                {"query": f"recording:({escape_lucene(text)})", "limit": limit},
            )

    async def releases_for_groups(
        self, group_mbids: list[str], *, per_group: int = 3
    ) -> list[dict[str, Any]]:
        """A few editions per album, enough to find a cover and an owner.

        Search results for release groups carry no edition identifiers. The
        album page has them (it browsed the group) and that is why its sleeve
        shows up while the search tile stays empty.
        """
        ids = [mbid for mbid in group_mbids if mbid]
        if not ids:
            return []
        query = " OR ".join(f"rgid:{mbid}" for mbid in ids)
        limit = min(100, max(len(ids) * per_group, len(ids)))
        payload = await self._get("/ws/2/release", {"query": query, "limit": limit})
        return (payload or {}).get("releases") or []

    async def search_release_groups_by_tag(
        self, tag: str, *, limit: int = 40, offset: int = 0, primary_type: str = "album"
    ) -> dict[str, Any]:
        query = f'tag:"{escape_lucene(tag)}" AND primarytype:{escape_lucene(primary_type)}'
        return await self._get(
            "/ws/2/release-group", {"query": query, "limit": limit, "offset": offset}
        )

    async def search_recent_release_groups(
        self, *, start: str, end: str, limit: int = 40, offset: int = 0, primary_type: str = "album"
    ) -> dict[str, Any]:
        query = (
            f"firstreleasedate:[{start} TO {end}] "
            f"AND primarytype:{escape_lucene(primary_type)} AND status:official"
        )
        return await self._get(
            "/ws/2/release-group",
            {"query": query, "limit": limit, "offset": offset},
        )

    # -------------------------------------------------------------- lookups

    async def get_release_group(self, mbid: str) -> dict[str, Any]:
        return await self._get(
            f"/ws/2/release-group/{mbid}", {"inc": "artists+genres+tags+ratings+url-rels"}
        )

    async def browse_releases_for_group(self, mbid: str, *, limit: int = 100) -> dict[str, Any]:
        return await self._get(
            "/ws/2/release",
            {
                "release-group": mbid,
                "inc": "media+labels+artist-credits+release-groups",
                "limit": limit,
            },
        )

    async def get_release(self, mbid: str) -> dict[str, Any]:
        return await self._get(
            f"/ws/2/release/{mbid}",
            {
                "inc": (
                    "recordings+artist-credits+labels+release-groups+media"
                    "+genres+discids+artist-rels"
                )
            },
        )

    async def get_label(self, mbid: str) -> dict[str, Any]:
        return await self._get(f"/ws/2/label/{mbid}", {"inc": "tags+genres+url-rels"})

    async def browse_releases_for_label(
        self, label_mbid: str, *, limit: int = 100, offset: int = 0
    ) -> dict[str, Any]:
        """Editions published by a label.

        MusicBrainz attaches labels to releases, not to release groups, so a
        catalogue has to be walked edition by edition and folded back into
        albums by the caller.
        """
        return await self._get(
            "/ws/2/release",
            {
                "label": label_mbid,
                "inc": "release-groups+artist-credits",
                "limit": limit,
                "offset": offset,
            },
        )

    async def get_artist(self, mbid: str) -> dict[str, Any]:
        return await self._get(f"/ws/2/artist/{mbid}", {"inc": "genres+tags+url-rels+aliases"})

    async def browse_artist_release_groups(
        self, artist_mbid: str, *, limit: int = 100, offset: int = 0
    ) -> dict[str, Any]:
        return await self._get(
            "/ws/2/release-group",
            {"artist": artist_mbid, "limit": limit, "offset": offset, "inc": "artist-credits"},
        )

    async def test_connection(self) -> dict[str, Any]:
        """Probe the instance and report whether text search is available."""
        result: dict[str, Any] = {"lookup": False, "search": False, "source": None}
        if self.base_url:
            try:
                await self._limiter_for(self.base_url).acquire()
                await self.request(
                    "GET",
                    f"{self.base_url}/ws/2/artist/b7ffd2af-418f-4be2-bdd1-22f8b48613da",
                    params={"fmt": "json"},
                    headers=self._headers(),
                )
                result["lookup"] = True
                result["source"] = "local"
            except ServiceError as exc:
                result["error"] = exc.message
            if result["lookup"]:
                try:
                    await self._limiter_for(self.base_url).acquire()
                    payload = await self.request(
                        "GET",
                        f"{self.base_url}/ws/2/release-group",
                        params={"query": "discovery", "limit": 1, "fmt": "json"},
                        headers=self._headers(),
                    )
                    result["search"] = bool(payload and "release-groups" in payload)
                except ServiceError as exc:
                    result["search_error"] = exc.message

        if (
            not result["search"]
            and self.settings.use_public_fallback
            and self.public_url
            and self.public_url != self.base_url
        ):
            try:
                await self._limiter_for(self.public_url).acquire()
                payload = await self.request(
                    "GET",
                    f"{self.public_url}/ws/2/release-group",
                    params={"query": "discovery", "limit": 1, "fmt": "json"},
                    headers=self._headers(),
                )
                result["search"] = bool(payload and "release-groups" in payload)
                result["source"] = result["source"] or "public"
                result["fallback_used"] = True
            except ServiceError as exc:
                result["fallback_error"] = exc.message

        if not result["lookup"] and not result["search"]:
            raise ServiceError(self.service_name, result.get("error") or "unreachable")
        return result
