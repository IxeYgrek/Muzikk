"""Jellyfin music library mirror.

Muzikk keeps a local index of the Jellyfin albums so that "already owned"
badges are instant and do not hit Jellyfin on every search. Matching is done by
release MBID first, then release group MBID, then a normalised artist/title key.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..matching.normalize import extension_of, fuzzy_key
from ..models import LibraryAlbum, LibraryArtist
from . import settings as settings_service
from .jellyfin import JellyfinClient, container_is_lossless
from .musicbrainz import MusicBrainzClient

logger = logging.getLogger(__name__)

OWNED_EXACT = "owned"
OWNED_PROBABLE = "probable"

# Cap the per-run MusicBrainz backfill so a first sync stays fast.
BACKFILL_LIMIT = 250


@dataclass(slots=True)
class OwnershipMatch:
    status: str
    album_id: int
    jellyfin_id: str
    is_lossless: bool
    formats: list[str]
    path: str | None
    year: int | None
    track_count: int

    @property
    def upgradable(self) -> bool:
        return not self.is_lossless


class OwnershipIndex:
    """In-memory lookup built once per request batch."""

    def __init__(self, session: Session) -> None:
        rows = session.execute(
            select(
                LibraryAlbum.id,
                LibraryAlbum.jellyfin_id,
                LibraryAlbum.release_mbid,
                LibraryAlbum.release_group_mbid,
                LibraryAlbum.fuzzy_key,
                LibraryAlbum.is_lossless,
                LibraryAlbum.formats,
                LibraryAlbum.path,
                LibraryAlbum.year,
                LibraryAlbum.track_count,
            )
        ).all()

        self._by_release: dict[str, tuple] = {}
        self._by_group: dict[str, tuple] = {}
        self._by_fuzzy: dict[str, tuple] = {}

        for row in rows:
            if row.release_mbid:
                self._by_release.setdefault(row.release_mbid.lower(), row)
            if row.release_group_mbid:
                self._by_group.setdefault(row.release_group_mbid.lower(), row)
            if row.fuzzy_key:
                self._by_fuzzy.setdefault(row.fuzzy_key, row)

    @staticmethod
    def _to_match(row: tuple, status: str) -> OwnershipMatch:
        return OwnershipMatch(
            status=status,
            album_id=row.id,
            jellyfin_id=row.jellyfin_id,
            is_lossless=bool(row.is_lossless),
            formats=list(row.formats or []),
            path=row.path,
            year=row.year,
            track_count=row.track_count or 0,
        )

    def lookup(
        self,
        *,
        release_group_mbid: str | None = None,
        release_mbids: Iterable[str] | None = None,
        artist: str | None = None,
        album: str | None = None,
    ) -> OwnershipMatch | None:
        for mbid in release_mbids or ():
            row = self._by_release.get((mbid or "").lower())
            if row:
                return self._to_match(row, OWNED_EXACT)

        if release_group_mbid:
            row = self._by_group.get(release_group_mbid.lower())
            if row:
                return self._to_match(row, OWNED_EXACT)

        key = fuzzy_key(artist, album)
        if key and key.strip("|"):
            row = self._by_fuzzy.get(key)
            if row:
                return self._to_match(row, OWNED_PROBABLE)
        return None


def _formats_from_containers(containers: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for container in containers:
        value = (container or "").lower().strip()
        if value and value not in seen:
            seen.append(value)
    return sorted(seen)


def _parse_date(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


async def sync_library(session: Session) -> dict[str, int]:
    """Refresh the local mirror of the Jellyfin music library."""
    jellyfin_settings = settings_service.load(session, "jellyfin")
    client = JellyfinClient(jellyfin_settings)
    if not client.configured or not client.api_key:
        raise RuntimeError("Jellyfin is not configured")

    library_ids = list(jellyfin_settings.music_library_ids or [])
    albums = await client.get_albums(library_ids or None)
    tracks = await client.get_audio_files(library_ids or None)

    containers_by_album: dict[str, list[str]] = {}
    paths_by_album: dict[str, str] = {}
    for track in tracks:
        album_id = track.get("AlbumId") or track.get("ParentId")
        if not album_id:
            continue
        container = (track.get("Container") or "").lower()
        if not container:
            container = extension_of(track.get("Path") or "")
        if container:
            containers_by_album.setdefault(album_id, []).append(container)
        path = track.get("Path")
        if path and album_id not in paths_by_album:
            paths_by_album[album_id] = path

    existing = {row.jellyfin_id: row for row in session.execute(select(LibraryAlbum)).scalars()}
    seen_ids: set[str] = set()
    created = updated = 0

    for album in albums:
        jellyfin_id = album.get("Id")
        if not jellyfin_id:
            continue
        seen_ids.add(jellyfin_id)

        providers = album.get("ProviderIds") or {}
        release_mbid = providers.get("MusicBrainzAlbum") or providers.get("MusicBrainzRelease")
        group_mbid = providers.get("MusicBrainzReleaseGroup")
        artist_mbid = providers.get("MusicBrainzAlbumArtist") or providers.get("MusicBrainzArtist")

        album_artists = album.get("AlbumArtists") or []
        album_artist = album.get("AlbumArtist") or (
            album_artists[0].get("Name") if album_artists else ""
        )
        containers = containers_by_album.get(jellyfin_id, [])
        formats = _formats_from_containers(containers)
        is_lossless = bool(formats) and all(container_is_lossless(item) for item in formats)

        row = existing.get(jellyfin_id)
        if row is None:
            row = LibraryAlbum(jellyfin_id=jellyfin_id)
            session.add(row)
            created += 1
        else:
            updated += 1

        row.name = album.get("Name") or ""
        row.album_artist = album_artist or ""
        row.album_artist_id = album_artists[0].get("Id") if album_artists else None
        row.release_mbid = (release_mbid or None) and release_mbid.lower()
        row.release_group_mbid = (group_mbid or None) and group_mbid.lower()
        row.artist_mbid = (artist_mbid or None) and artist_mbid.lower()
        row.fuzzy_key = fuzzy_key(album_artist, album.get("Name"))
        row.year = album.get("ProductionYear")
        row.path = album.get("Path") or paths_by_album.get(jellyfin_id)
        row.track_count = album.get("ChildCount") or len(containers)
        row.formats = formats
        row.is_lossless = is_lossless
        row.genres = list(album.get("Genres") or [])
        row.date_created = _parse_date(album.get("DateCreated"))
        row.image_tag = (album.get("ImageTags") or {}).get("Primary")

    removed = 0
    for jellyfin_id, row in existing.items():
        if jellyfin_id not in seen_ids:
            session.delete(row)
            removed += 1

    session.commit()

    artists = await client.get_artists(library_ids or None)
    existing_artists = {row.jellyfin_id: row for row in session.execute(select(LibraryArtist)).scalars()}
    seen_artists: set[str] = set()
    for artist in artists:
        jellyfin_id = artist.get("Id")
        if not jellyfin_id:
            continue
        seen_artists.add(jellyfin_id)
        row = existing_artists.get(jellyfin_id)
        if row is None:
            row = LibraryArtist(jellyfin_id=jellyfin_id)
            session.add(row)
        mbid = (artist.get("ProviderIds") or {}).get("MusicBrainzArtist")
        row.name = artist.get("Name") or ""
        row.mbid = (mbid or None) and mbid.lower()
        row.fuzzy_key = fuzzy_key(artist.get("Name"), None)
        row.album_count = artist.get("AlbumCount") or 0
        row.image_tag = (artist.get("ImageTags") or {}).get("Primary")

    for jellyfin_id, row in existing_artists.items():
        if jellyfin_id not in seen_artists:
            session.delete(row)

    session.commit()

    backfilled = await backfill_release_groups(session)

    return {
        "albums": len(albums),
        "created": created,
        "updated": updated,
        "removed": removed,
        "artists": len(artists),
        "release_groups_backfilled": backfilled,
    }


async def backfill_release_groups(session: Session) -> int:
    """Resolve the release group of albums that only carry a release MBID.

    Jellyfin usually stores ``MusicBrainzAlbum`` (the release) but not the
    release group, while browsing happens at release group level. Filling the
    gap makes the green check mark reliable.
    """
    rows = (
        session.execute(
            select(LibraryAlbum)
            .where(LibraryAlbum.release_mbid.is_not(None))
            .where(LibraryAlbum.release_group_mbid.is_(None))
            .limit(BACKFILL_LIMIT)
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0

    client = MusicBrainzClient(settings_service.load(session, "musicbrainz"))
    if not client.configured:
        return 0

    resolved = 0
    for row in rows:
        try:
            release = await client.get_release(row.release_mbid)
        except Exception as exc:  # noqa: BLE001 - a single bad MBID must not stop the sync
            logger.debug("Release group backfill failed for %s: %s", row.release_mbid, exc)
            continue
        group = (release or {}).get("release-group") or {}
        group_id = group.get("id")
        if group_id:
            row.release_group_mbid = group_id.lower()
            resolved += 1
    session.commit()
    return resolved
