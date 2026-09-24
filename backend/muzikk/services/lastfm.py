"""Last.fm: scrobbling, and reading a listener's taste.

Last.fm splits credentials in two, and the split is the whole reason this file
exists next to the ListenBrainz one. The API key and shared secret identify
*Muzikk*, registered once per install at last.fm/api/account/create. What makes
a recommendation personal is the listener's username, which needs no
credential at all to read: their charts are public. Only writing — scrobbling —
needs a session key, obtained by having the listener approve the application.

Unlike ListenBrainz, Last.fm answers with names rather than MusicBrainz
identifiers. It does return an ``mbid`` for many artists, and only those are
used: guessing an MBID from a name is how an album by a namesake ends up in
the library, which is a mistake the matcher already had to be taught to avoid.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from .base import HttpService, ServiceError, ServiceNotConfigured, normalize_base_url
from .settings import LastfmSettings

logger = logging.getLogger(__name__)

AUTH_PAGE = "https://www.last.fm/api/auth/"

# Last.fm refuses a scrobble for anything shorter than this, and ignores one
# submitted before half the track has played.
MIN_SCROBBLE_SECONDS = 30


class LastfmError(ServiceError):
    """A Last.fm refusal, carrying the numeric code it answers with."""

    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__("lastfm", message)
        self.code = code


class LastfmClient(HttpService):
    service_name = "lastfm"

    def __init__(self, settings: LastfmSettings) -> None:
        super().__init__(normalize_base_url(settings.url))
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.enabled and self.base_url and self.settings.api_key)

    def _signature(self, params: dict[str, Any]) -> str:
        """The md5 Last.fm expects on every authenticated call.

        Every parameter except the format is sorted by name, concatenated as
        name then value with no separator, and the shared secret appended.
        """
        joined = "".join(
            f"{key}{params[key]}" for key in sorted(params) if key not in ("format", "callback")
        )
        return hashlib.md5(  # noqa: S324 - the algorithm is imposed by Last.fm
            (joined + self.settings.api_secret).encode("utf-8")
        ).hexdigest()

    async def _call(
        self, method: str, params: dict[str, Any], *, signed: bool = False, write: bool = False
    ) -> dict[str, Any]:
        if not self.configured:
            raise ServiceNotConfigured(self.service_name)
        if signed and not self.settings.api_secret:
            raise LastfmError("A Last.fm API secret is required for this operation")

        body = {key: value for key, value in params.items() if value not in (None, "")}
        body["method"] = method
        body["api_key"] = self.settings.api_key
        if signed:
            body["api_sig"] = self._signature(body)
        body["format"] = "json"

        if write:
            payload = await self.request("POST", self.base_url, data=body)
        else:
            payload = await self.request("GET", self.base_url, params=body)

        # An error can arrive inside a 200 response, so the body is checked too.
        if isinstance(payload, dict) and payload.get("error"):
            raise LastfmError(
                str(payload.get("message") or "Last.fm refused the call"),
                int(payload.get("error") or 0),
            )
        return payload or {}

    # ------------------------------------------------------- authorisation

    async def request_token(self) -> str:
        """Start the approval flow and return the token to send the user with."""
        payload = await self._call("auth.getToken", {}, signed=True)
        return str(payload.get("token") or "")

    def authorize_url(self, token: str) -> str:
        return f"{AUTH_PAGE}?api_key={self.settings.api_key}&token={token}"

    async def session_for_token(self, token: str) -> dict[str, str]:
        """Exchange an approved token for a session key that never expires."""
        payload = await self._call("auth.getSession", {"token": token}, signed=True)
        found = payload.get("session") or {}
        return {
            "key": str(found.get("key") or ""),
            "name": str(found.get("name") or ""),
        }

    # --------------------------------------------------------------- writing

    async def now_playing(
        self,
        session_key: str,
        *,
        artist: str,
        title: str,
        album: str = "",
        duration: float | None = None,
    ) -> None:
        if not session_key or not artist or not title:
            return
        await self._call(
            "track.updateNowPlaying",
            {
                "artist": artist,
                "track": title,
                "album": album,
                "duration": int(duration) if duration else None,
                "sk": session_key,
            },
            signed=True,
            write=True,
        )

    async def scrobble(
        self,
        session_key: str,
        *,
        artist: str,
        title: str,
        album: str = "",
        duration: float | None = None,
        mbid: str | None = None,
        listened_at: int | None = None,
    ) -> None:
        if not session_key or not artist or not title:
            return
        await self._call(
            "track.scrobble",
            {
                "artist": artist,
                "track": title,
                "album": album,
                "duration": int(duration) if duration else None,
                "mbid": mbid,
                "timestamp": int(listened_at or time.time()),
                "sk": session_key,
            },
            signed=True,
            write=True,
        )

    # --------------------------------------------------------------- reading

    async def top_artists(
        self, username: str, *, limit: int = 25, period: str = "3month"
    ) -> list[dict[str, Any]]:
        """The artists this account played most. Public, so no session needed."""
        if not self.configured or not username:
            return []
        try:
            payload = await self._call(
                "user.getTopArtists", {"user": username, "limit": limit, "period": period}
            )
        except ServiceError as exc:
            logger.debug("Last.fm top artists failed for %s: %s", username, exc.message)
            return []
        found = (payload.get("topartists") or {}).get("artist") or []
        return [item for item in found if isinstance(item, dict)]

    async def top_albums_for_tag(self, tag: str, *, limit: int = 100) -> list[dict[str, Any]]:
        """Albums a genre is best known for, ordered by how often it is tagged.

        MusicBrainz can list everything carrying a tag but has no notion of
        popularity, so this is used to order its results rather than to replace
        them: matching is by name, and nothing is navigated to by identifier.
        """
        if not self.configured or not tag:
            return []
        try:
            payload = await self._call("tag.getTopAlbums", {"tag": tag, "limit": limit})
        except ServiceError as exc:
            logger.debug("Last.fm top albums failed for %s: %s", tag, exc.message)
            return []

        found = (payload.get("topalbums") or {}).get("album") or []
        results: list[dict[str, Any]] = []
        for item in found:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            artist = ((item.get("artist") or {}).get("name") or "").strip()
            if not name or not artist:
                continue
            results.append({"album": name, "artist": artist})
        return results

    async def similar_artists(
        self, *, name: str = "", mbid: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Artists Last.fm puts next to this one, keeping only the identified ones."""
        if not self.configured or not (name or mbid):
            return []
        try:
            payload = await self._call(
                "artist.getSimilar",
                {"artist": name or None, "mbid": mbid, "limit": limit, "autocorrect": 1},
            )
        except ServiceError as exc:
            logger.debug("Last.fm similar artists failed for %s: %s", mbid or name, exc.message)
            return []

        found = (payload.get("similarartists") or {}).get("artist") or []
        results: list[dict[str, Any]] = []
        for item in found:
            if not isinstance(item, dict):
                continue
            artist_mbid = (item.get("mbid") or "").strip()
            # A name without an identifier cannot be resolved safely.
            if not artist_mbid:
                continue
            results.append(
                {
                    "artist_mbid": artist_mbid,
                    "name": item.get("name") or "",
                    "score": float(item.get("match") or 0.0),
                }
            )
        return results[:limit]

    async def test_connection(self) -> dict[str, Any]:
        """Check the key against a call that needs nothing else."""
        if not self.configured:
            raise ServiceNotConfigured(self.service_name)
        payload = await self._call(
            "artist.getInfo", {"mbid": "83d91898-7763-47d7-b03b-b92132375c47"}
        )
        artist = (payload.get("artist") or {}).get("name") or ""
        return {"artist": artist, "has_secret": bool(self.settings.api_secret)}
