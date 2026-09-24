"""ListenBrainz: submitting listens, and reading a taste back out of them.

ListenBrainz fits Muzikk unusually well because it speaks MusicBrainz
identifiers natively. A similar-artist lookup answers with artist MBIDs, which
is exactly what the library index, the ownership match and the acquisition
pipeline are already keyed on, so nothing has to be resolved by name.

Two hosts are involved. The main API carries listens and statistics and needs
the listener's token to write. The Labs API carries the similarity models, is
open, and is explicitly documented as experimental — every call here treats an
error as "no data" rather than as a failure worth surfacing.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .base import HttpService, ServiceError, ServiceNotConfigured, normalize_base_url
from .settings import ListenBrainzSettings

logger = logging.getLogger(__name__)

# A listen is submitted once the track is over, so a generous timeout only
# delays a background task, never the listener.
SUBMIT_TIMEOUT = 15.0


class ListenBrainzClient(HttpService):
    service_name = "listenbrainz"

    def __init__(self, settings: ListenBrainzSettings) -> None:
        super().__init__(normalize_base_url(settings.url))
        self.settings = settings
        self.labs_url = normalize_base_url(settings.labs_url)

    @property
    def configured(self) -> bool:
        return bool(self.settings.enabled and self.base_url)

    def _headers(self, token: str | None = None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Token {token}"
        return headers

    # --------------------------------------------------------------- writing

    async def validate_token(self, token: str) -> dict[str, Any]:
        """Check a token and return the account it belongs to."""
        if not self.base_url:
            raise ServiceNotConfigured(self.service_name)
        return await self.request(
            "GET", "/1/validate-token", headers=self._headers(token)
        ) or {}

    async def submit_listen(
        self,
        token: str,
        *,
        artist: str,
        title: str,
        album: str = "",
        recording_mbid: str | None = None,
        release_mbid: str | None = None,
        artist_mbid: str | None = None,
        duration: float | None = None,
        listened_at: int | None = None,
        playing_now: bool = False,
    ) -> None:
        """Send one listen, or announce what is playing right now.

        A "playing now" entry carries no timestamp and is not a listen: it
        expires on its own, which is why the two share this method.
        """
        if not self.configured:
            raise ServiceNotConfigured(self.service_name)
        if not token or not artist or not title:
            return

        info: dict[str, Any] = {
            "artist_name": artist,
            "track_name": title,
        }
        if album:
            info["release_name"] = album

        mapping: dict[str, Any] = {}
        if recording_mbid:
            mapping["recording_mbid"] = recording_mbid
        if release_mbid:
            mapping["release_mbid"] = release_mbid
        if artist_mbid:
            mapping["artist_mbids"] = [artist_mbid]
        if duration:
            mapping["duration"] = int(duration)
        if mapping:
            info["additional_info"] = mapping

        listen: dict[str, Any] = {"track_metadata": info}
        if not playing_now:
            listen["listened_at"] = int(listened_at or time.time())

        payload = {
            "listen_type": "playing_now" if playing_now else "single",
            "payload": [listen],
        }
        await self.request(
            "POST",
            "/1/submit-listens",
            json=payload,
            headers=self._headers(token),
            timeout=SUBMIT_TIMEOUT,
            expect_json=False,
        )

    # --------------------------------------------------------------- reading

    async def top_artists(self, username: str, *, count: int = 25, range_: str = "month") -> list[dict[str, Any]]:
        """The artists this account listened to most, newest window first.

        Answers 204 with no body while the statistics are still being computed
        for a fresh account, which is reported as an empty list.
        """
        if not self.configured or not username:
            return []
        try:
            payload = await self.request(
                "GET",
                f"/1/stats/user/{username}/artists",
                params={"count": count, "range": range_},
                headers=self._headers(),
            )
        except ServiceError as exc:
            logger.debug("ListenBrainz top artists failed for %s: %s", username, exc.message)
            return []
        return ((payload or {}).get("payload") or {}).get("artists") or []

    async def fresh_releases(self, *, days: int = 30, limit: int = 60) -> list[dict[str, Any]]:
        """Records just out, or about to be, across the whole service.

        Answers with release group identifiers, which is what makes this usable
        as a source: a MusicBrainz date range query finds everything catalogued
        in a window, this finds what people are actually about to listen to.
        """
        if not self.configured:
            return []
        try:
            payload = await self.request(
                "GET",
                "/1/explore/fresh-releases/",
                # Only what is already out: an unreleased record cannot be found
                # by any provider, and would sit in the grid as a dead end.
                params={"days": min(days, 90), "sort": "release_date", "future": "false"},
                headers=self._headers(),
            )
        except ServiceError as exc:
            logger.debug("ListenBrainz fresh releases failed: %s", exc.message)
            return []

        found = ((payload or {}).get("payload") or {}).get("releases") or []
        results: list[dict[str, Any]] = []
        for row in found:
            group = (row.get("release_group_mbid") or "").strip()
            if not group:
                continue
            results.append(
                {
                    "release_group_mbid": group,
                    "title": row.get("release_name") or "",
                    "artist": row.get("artist_credit_name") or "",
                    "artist_mbid": (row.get("artist_mbids") or [None])[0],
                    "date": row.get("release_date") or "",
                    "primary_type": row.get("release_group_primary_type") or "Album",
                }
            )
        return results[:limit]

    async def similar_artists(self, artist_mbid: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Artists the listening data puts next to this one.

        The Labs API answers with a list of lists, and includes the seed artist
        itself, so both are flattened and filtered out here.
        """
        if not self.configured or not self.labs_url or not artist_mbid:
            return []
        try:
            payload = await self.request(
                "GET",
                f"{self.labs_url}/similar-artists/json",
                params={
                    "artist_mbids": artist_mbid,
                    "algorithm": self.settings.similar_algorithm,
                },
                headers={"Accept": "application/json"},
            )
        except ServiceError as exc:
            # Documented as experimental; a miss must not break a page.
            logger.debug("ListenBrainz similar artists failed for %s: %s", artist_mbid, exc.message)
            return []

        rows: list[dict[str, Any]] = []
        for entry in payload or []:
            if isinstance(entry, list):
                rows.extend(item for item in entry if isinstance(item, dict))
            elif isinstance(entry, dict):
                rows.append(entry)

        found: list[dict[str, Any]] = []
        for row in rows:
            mbid = (row.get("artist_mbid") or "").strip()
            if not mbid or mbid.lower() == artist_mbid.lower():
                continue
            found.append(
                {
                    "artist_mbid": mbid,
                    "name": row.get("artist_credit_name") or row.get("name") or "",
                    "score": float(row.get("score") or 0.0),
                }
            )
        found.sort(key=lambda item: -item["score"])
        return found[:limit]

    async def test_connection(self) -> dict[str, Any]:
        """Probe the API, and the Labs host the recommendations depend on."""
        if not self.base_url:
            raise ServiceNotConfigured(self.service_name)
        details: dict[str, Any] = {"api": False, "labs": False}
        await self.request("GET", "/1/latest-import", params={"user_name": "listenbrainz"}, headers=self._headers())
        details["api"] = True
        try:
            await self.request(
                "GET",
                f"{self.labs_url}/similar-artists/json",
                params={
                    "artist_mbids": "83d91898-7763-47d7-b03b-b92132375c47",
                    "algorithm": self.settings.similar_algorithm,
                },
                headers={"Accept": "application/json"},
            )
            details["labs"] = True
        except ServiceError as exc:
            details["labs_error"] = exc.message
        return details
