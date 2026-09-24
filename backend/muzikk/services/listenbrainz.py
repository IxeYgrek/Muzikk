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


def _fresh_rows(releases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fresh release rows reduced to what a card needs."""
    found: list[dict[str, Any]] = []
    for row in releases:
        group = (row.get("release_group_mbid") or "").strip()
        if not group:
            continue
        found.append(
            {
                "release_group_mbid": group,
                "title": row.get("release_name") or "",
                "artist": row.get("artist_credit_name") or "",
                "artist_mbid": (row.get("artist_mbids") or [None])[0],
                "date": row.get("release_date") or "",
                "primary_type": row.get("release_group_primary_type") or "Album",
            }
        )
    return found


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

    async def _stats(
        self, username: str, entity: str, *, count: int, range_: str
    ) -> list[dict[str, Any]]:
        """One statistics page, or nothing at all.

        Answers 204 with no body while the figures are still being computed for
        a fresh account, which arrives here as an empty list rather than as a
        failure worth reporting.
        """
        if not self.configured or not username:
            return []
        try:
            payload = await self.request(
                "GET",
                f"/1/stats/user/{username}/{entity}",
                params={"count": count, "range": range_},
                headers=self._headers(),
            )
        except ServiceError as exc:
            logger.debug("ListenBrainz %s stats failed for %s: %s", entity, username, exc.message)
            return []
        return ((payload or {}).get("payload") or {}).get(entity.replace("-", "_")) or []

    async def top_artists(
        self, username: str, *, count: int = 25, range_: str = "all_time"
    ) -> list[dict[str, Any]]:
        """The artists this account listened to most.

        The window defaults to everything: a listener with a few hundred listens
        has almost nothing in a one-month slice, and a taste read from too few
        plays produces suggestions that look drawn from a hat.
        """
        return await self._stats(username, "artists", count=count, range_=range_)

    async def top_release_groups(
        self, username: str, *, count: int = 25, range_: str = "all_time"
    ) -> list[dict[str, Any]]:
        """The albums this account listened to most.

        Album-level taste is sharper than artist-level: somebody who plays one
        record of an artist over and over is saying something more precise than
        somebody who plays a bit of everything.
        """
        return await self._stats(username, "release-groups", count=count, range_=range_)

    async def top_genres(self, username: str, *, range_: str = "all_time") -> list[str]:
        """The genres this account actually listens to, most played first."""
        rows = await self._stats(username, "genre-activity", count=25, range_=range_)
        found = [
            ((row.get("genre") or "").strip().lower(), int(row.get("listen_count") or 0))
            for row in rows
            if row.get("genre")
        ]
        found.sort(key=lambda item: -item[1])
        return [name for name, _ in found]

    async def personal_fresh_releases(
        self, username: str, *, days: int = 60
    ) -> list[dict[str, Any]]:
        """Records just out by artists this account listens to.

        Different from the sitewide list: this one is filtered to the listener's
        own artists, which is what makes it worth a shelf of its own.
        """
        if not self.configured or not username:
            return []
        try:
            payload = await self.request(
                "GET",
                f"/1/user/{username}/fresh_releases",
                params={"days": min(days, 90), "sort": "release_date", "future": "false"},
                headers=self._headers(),
            )
        except ServiceError as exc:
            logger.debug("ListenBrainz user fresh releases failed for %s: %s", username, exc.message)
            return []
        return _fresh_rows(((payload or {}).get("payload") or {}).get("releases") or [])

    async def recommended_playlist_tracks(self, username: str) -> list[dict[str, Any]]:
        """Tracks from the playlists ListenBrainz builds for this account.

        Weekly Jams and Weekly Exploration are the finest signal the service
        offers, but they are lists of tracks and Muzikk thinks in albums, so only
        the release each track belongs to is kept.
        """
        if not self.configured or not username:
            return []
        try:
            index = await self.request(
                "GET",
                f"/1/user/{username}/playlists/recommendations",
                headers=self._headers(),
            )
        except ServiceError as exc:
            logger.debug("ListenBrainz recommendation playlists failed: %s", exc.message)
            return []

        tracks: list[dict[str, Any]] = []
        for entry in (index or {}).get("playlists") or []:
            playlist = (entry or {}).get("playlist") or {}
            identifier = str(playlist.get("identifier") or "")
            mbid = identifier.rstrip("/").rsplit("/", 1)[-1]
            if not mbid:
                continue
            # "jams" is what the listener already knows, "exploration" is not.
            title = (playlist.get("title") or "").lower()
            familiar = "jam" in title
            try:
                detail = await self.request(
                    "GET", f"/1/playlist/{mbid}", headers=self._headers()
                )
            except ServiceError:
                continue
            for item in ((detail or {}).get("playlist") or {}).get("track") or []:
                extension = (item.get("extension") or {}).get(
                    "https://musicbrainz.org/doc/jspf#track"
                ) or {}
                release = (extension.get("release_identifier") or "").rstrip("/").rsplit("/", 1)[-1]
                artists = item.get("creator") or ""
                if not release:
                    continue
                tracks.append(
                    {
                        "release_mbid": release,
                        "title": item.get("album") or item.get("title") or "",
                        "artist": artists,
                        "familiar": familiar,
                        "playlist": playlist.get("title") or "",
                    }
                )
        return tracks

    async def top_release_groups_for_artist(
        self, artist_mbid: str, *, limit: int = 5
    ) -> list[dict[str, Any]]:
        """An artist's most listened albums, best first.

        Used so a suggested artist is represented by the record people actually
        play rather than by whatever their discography lists first.
        """
        if not self.configured or not artist_mbid:
            return []
        try:
            payload = await self.request(
                "GET",
                f"/1/popularity/top-release-groups-for-artist/{artist_mbid}",
                headers=self._headers(),
            )
        except ServiceError as exc:
            logger.debug("ListenBrainz artist popularity failed for %s: %s", artist_mbid, exc.message)
            return []

        found: list[dict[str, Any]] = []
        for row in payload or []:
            group = (row.get("release_group") or {}) or {}
            mbid = (group.get("mbid") or row.get("release_group_mbid") or "").strip()
            if not mbid:
                continue
            found.append(
                {
                    "release_group_mbid": mbid,
                    "title": group.get("name") or (row.get("release") or {}).get("name") or "",
                    "artist": (row.get("artist") or {}).get("name") or "",
                    "date": (row.get("release") or {}).get("date") or "",
                    "listen_count": int(row.get("total_listen_count") or 0),
                }
            )
        return found[:limit]

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

        rows = ((payload or {}).get("payload") or {}).get("releases") or []
        return _fresh_rows(rows)[:limit]

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
