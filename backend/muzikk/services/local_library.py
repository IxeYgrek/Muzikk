"""The library index Muzikk builds for itself.

In local mode nothing describes the music but the files, so Muzikk walks the
library folder, reads the tags of every audio file and fills the very tables
the Jellyfin mirror fills. Everything above this module keeps working
unchanged: the ownership badges, the library pages and the play queue never
look at where a row came from, only at the identifier it carries.

Those identifiers are derived from the path and prefixed with ``local:``, so
they can never be mistaken for a Jellyfin one. A rescan reads only the files
whose size or modification time moved, which is what keeps the minutes of the
first walk from being paid twice.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from ..matching.normalize import (
    LOSSLESS_EXTENSIONS,
    extension_of,
    fuzzy_key,
    normalize_artist,
)
from ..models import LibraryAlbum, LibraryArtist, LibraryTrack
from . import metadata as metadata_service
from . import settings as settings_service
from . import tags as tags_service
from .library_index import backfill_release_groups

logger = logging.getLogger(__name__)

PREFIX = "local:"
ARTIST_PREFIX = "local:a:"
TRACK_PREFIX = "local:t:"

# Drop the identity map this often so a first walk of tens of thousands of
# files does not keep every row in memory. Writes themselves commit after
# each folder: holding a write lock across the next mutagen pass is what
# made login fail with "database is locked" on a first-run library.
EXPIRE_EVERY = 100

# Kept short so a genre list stays a filter rather than a dump of the tags.
MAX_GENRES = 12


def _key(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:24]


def album_item_id(path: Path | str) -> str:
    folder = path.as_posix() if isinstance(path, Path) else str(path).replace("\\", "/")
    return PREFIX + _key(folder)


def track_item_id(path: Path | str) -> str:
    file = path.as_posix() if isinstance(path, Path) else str(path).replace("\\", "/")
    return TRACK_PREFIX + _key(file)


def artist_item_id(name: str) -> str:
    return ARTIST_PREFIX + _key(normalize_artist(name) or name.strip().lower())


def is_local_id(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)


@dataclass(slots=True)
class _Track:
    path: str
    size: int
    mtime: float
    title: str = ""
    artist: str = ""
    album: str = ""
    track: int | None = None
    disc: int | None = None
    duration: float | None = None
    container: str = ""
    is_lossless: bool = False
    recording_mbid: str | None = None


@dataclass(slots=True)
class _Album:
    path: str
    name: str = ""
    album_artist: str = ""
    release_mbid: str | None = None
    release_group_mbid: str | None = None
    artist_mbid: str | None = None
    year: int | None = None
    genres: list[str] = field(default_factory=list)
    formats: list[str] = field(default_factory=list)
    is_lossless: bool = False
    bit_depth: int | None = None
    sample_rate: int | None = None
    newest_mtime: float = 0.0
    tracks: list[_Track] = field(default_factory=list)


def _signature(tracks: list[_Track] | list[LibraryTrack]) -> dict[str, tuple[int, float]]:
    """What a folder looked like last time, file by file.

    Modification times come back from the filesystem with more precision than
    SQLite keeps, so they are rounded before being compared. Without that, a
    library would look entirely new on every single scan.
    """
    return {row.path: (int(row.size or 0), round(float(row.mtime or 0.0), 3)) for row in tracks}


def _first(values: list[int | None]) -> int | None:
    for value in values:
        if value:
            return int(value)
    return None


def _inspect(folder: metadata_service.FolderInfo, known: dict[str, tuple[int, float]]) -> _Album | None:
    """Read an album folder, or report that it has not moved.

    Runs in a worker thread: it is all filesystem and mutagen, and a library
    of any size would otherwise hold the event loop for minutes.
    """
    entries: list[_Track] = []
    for path in folder.files:
        try:
            stat = path.stat()
        except OSError as exc:
            logger.debug("Cannot stat %s: %s", path, exc)
            continue
        entries.append(
            _Track(path=str(path), size=stat.st_size, mtime=round(stat.st_mtime, 3))
        )

    if not entries:
        return None
    if _signature(entries) == known:
        return None

    album = _Album(path=str(folder.path))
    albums: list[str] = []
    album_artists: list[str] = []
    artists: list[str] = []
    dates: list[str] = []
    release_mbids: list[str] = []
    group_mbids: list[str] = []
    artist_mbids: list[str] = []
    genres: list[str] = []
    depths: list[int | None] = []
    rates: list[int | None] = []

    for entry in entries:
        read = tags_service.read_file(Path(entry.path))
        entry.title = read.title or Path(entry.path).stem
        entry.artist = read.artist or read.albumartist
        entry.album = read.album
        entry.track = read.track
        entry.disc = read.disc
        entry.duration = read.duration
        entry.container = read.extension
        entry.is_lossless = read.extension in LOSSLESS_EXTENSIONS
        entry.recording_mbid = (read.recording_mbid or None) and read.recording_mbid.lower()

        albums.append(read.album)
        album_artists.append(read.albumartist)
        artists.append(read.artist)
        dates.append(read.date)
        release_mbids.append(read.release_mbid)
        group_mbids.append(read.release_group_mbid)
        artist_mbids.append(read.artist_mbid)
        genres.extend(read.genres or [])
        depths.append(read.bit_depth)
        rates.append(read.sample_rate)

    guessed_artist, guessed_title, guessed_year = metadata_service.titles_from_path(folder)
    album.name = metadata_service.common_value(albums) or guessed_title
    album.album_artist = (
        metadata_service.common_value(album_artists)
        or metadata_service.common_value(artists)
        or guessed_artist
    )

    date = metadata_service.common_value(dates)
    album.year = int(date[:4]) if date[:4].isdigit() else guessed_year

    release = metadata_service.common_value(release_mbids)
    group = metadata_service.common_value(group_mbids)
    artist_mbid = metadata_service.common_value(artist_mbids)
    album.release_mbid = release.lower() or None
    album.release_group_mbid = group.lower() or None
    album.artist_mbid = artist_mbid.lower() or None

    ordered: list[str] = []
    for genre in genres:
        cleaned = (genre or "").strip()
        if cleaned and cleaned not in ordered:
            ordered.append(cleaned)
    album.genres = ordered[:MAX_GENRES]

    album.formats = sorted({extension_of(Path(entry.path).name) for entry in entries} - {""})
    album.is_lossless = bool(album.formats) and all(
        item in LOSSLESS_EXTENSIONS for item in album.formats
    )
    album.bit_depth = _first(depths)
    album.sample_rate = _first(rates)
    album.newest_mtime = max(entry.mtime for entry in entries)

    entries.sort(key=lambda item: (item.disc or 1, item.track or 999, item.path.lower()))
    album.tracks = entries
    return album


def _write_album(session: Session, item_id: str, payload: _Album, existing: LibraryAlbum | None) -> LibraryAlbum:
    row = existing
    if row is None:
        row = LibraryAlbum(jellyfin_id=item_id)
        session.add(row)
        # Sorting by "recently added" needs a date, and the newest file of the
        # folder is the closest thing to one a filesystem offers. It is kept
        # from then on, so retagging an album does not move it back to the top.
        row.date_created = datetime.fromtimestamp(payload.newest_mtime)

    row.name = payload.name[:500]
    row.album_artist = payload.album_artist[:500]
    row.album_artist_id = artist_item_id(payload.album_artist) if payload.album_artist else None
    row.release_mbid = payload.release_mbid
    row.release_group_mbid = payload.release_group_mbid
    row.artist_mbid = payload.artist_mbid
    row.fuzzy_key = fuzzy_key(payload.album_artist, payload.name)[:600]
    row.year = payload.year
    row.path = payload.path
    row.track_count = len(payload.tracks)
    row.formats = payload.formats
    row.is_lossless = payload.is_lossless
    row.bit_depth = payload.bit_depth
    row.sample_rate = payload.sample_rate
    row.genres = payload.genres
    row.image_tag = None
    return row


def _write_tracks(session: Session, album_item_id_value: str, payload: _Album) -> None:
    session.execute(
        delete(LibraryTrack).where(LibraryTrack.album_item_id == album_item_id_value)
    )
    # A file moved from one folder to another still holds its old row, and the
    # path is unique. Clear it before inserting rather than letting the insert
    # fail on a library someone reorganised.
    paths = [entry.path for entry in payload.tracks]
    for start in range(0, len(paths), 400):
        session.execute(delete(LibraryTrack).where(LibraryTrack.path.in_(paths[start : start + 400])))

    for entry in payload.tracks:
        session.add(
            LibraryTrack(
                item_id=track_item_id(entry.path),
                album_item_id=album_item_id_value,
                path=entry.path[:1000],
                title=entry.title[:500],
                artist=entry.artist[:500],
                album=(entry.album or payload.name)[:500],
                track=entry.track,
                disc=entry.disc,
                duration=entry.duration,
                container=entry.container[:16],
                is_lossless=entry.is_lossless,
                recording_mbid=entry.recording_mbid,
                size=entry.size,
                mtime=entry.mtime,
            )
        )


def _rebuild_artists(session: Session) -> int:
    """Derive the artist list from the albums, rather than tracking it live.

    An album that changes hands or disappears would otherwise leave a stale
    artist behind, and recomputing the whole list is one query.
    """
    counts: dict[str, dict[str, object]] = {}
    for row in session.execute(
        select(LibraryAlbum.album_artist, LibraryAlbum.artist_mbid)
    ).all():
        name = (row.album_artist or "").strip()
        if not name:
            continue
        item_id = artist_item_id(name)
        entry = counts.setdefault(
            item_id, {"name": name, "mbid": row.artist_mbid, "count": 0}
        )
        entry["count"] = int(entry["count"]) + 1
        if row.artist_mbid and not entry["mbid"]:
            entry["mbid"] = row.artist_mbid

    existing = {row.jellyfin_id: row for row in session.execute(select(LibraryArtist)).scalars()}
    for item_id, entry in counts.items():
        row = existing.get(item_id)
        if row is None:
            row = LibraryArtist(jellyfin_id=item_id)
            session.add(row)
        name = str(entry["name"])
        row.name = name[:500]
        row.mbid = entry["mbid"]
        row.fuzzy_key = fuzzy_key(name, None)[:600]
        row.album_count = int(entry["count"])
        row.image_tag = None

    for item_id, row in existing.items():
        if item_id not in counts:
            session.delete(row)
    session.commit()
    return len(counts)


async def scan_library(session: Session) -> dict[str, int]:
    """Walk the music folder and refresh the local index."""
    naming = settings_service.load(session, "naming")
    config = settings_service.load(session, "metadata")

    root = Path(naming.music_dir)
    if not root.is_dir():
        logger.warning(
            'Library folder "%s" is not visible yet; skipping scan',
            root,
        )
        return {
            "albums": 0,
            "created": 0,
            "updated": 0,
            "unchanged": 0,
            "removed": 0,
            "skipped": 0,
            "tracks": 0,
            "artists": 0,
            "release_groups_backfilled": 0,
        }

    report = metadata_service.WalkReport()
    folders = await asyncio.to_thread(
        metadata_service.collect_folders,
        root,
        # One track in a folder is still one album someone owns. The higher
        # threshold of the metadata analysis exists to keep loose files out of
        # a report, which is a different question.
        min_tracks=1,
        max_albums=config.max_albums_per_scan,
        report=report,
    )
    logger.info(
        "Local library walk of %s: %s directories, %s audio files, %s album folders",
        root,
        report.directories,
        report.audio_files,
        report.grouped,
    )
    if report.unreadable:
        logger.warning("Local library walk skipped %s unreadable folder(s)", report.unreadable)

    albums = {row.jellyfin_id: row for row in session.execute(select(LibraryAlbum)).scalars()}
    known: dict[str, dict[str, tuple[int, float]]] = {}
    for row in session.execute(select(LibraryTrack)).scalars():
        known.setdefault(row.album_item_id, {})[row.path] = (
            int(row.size or 0),
            round(float(row.mtime or 0.0), 3),
        )
    # End the read snapshot before the mutagen pass. A long-lived
    # transaction here would sit on the file while thousands of tags are read.
    session.commit()

    seen: set[str] = set()
    created = updated = unchanged = skipped = 0

    for index, folder in enumerate(folders, start=1):
        item_id = album_item_id(folder.path)
        seen.add(item_id)
        existing = albums.get(item_id)
        fingerprint = known.get(item_id, {}) if existing is not None else {}

        try:
            payload = await asyncio.to_thread(_inspect, folder, fingerprint)
        except OSError as exc:
            skipped += 1
            logger.warning("Cannot index %s: %s", folder.path, exc)
            continue

        if payload is None:
            if existing is not None:
                unchanged += 1
            else:
                skipped += 1
            continue

        if existing is None:
            created += 1
        else:
            updated += 1
        _write_album(session, item_id, payload, existing)
        _write_tracks(session, item_id, payload)
        session.commit()
        if index % EXPIRE_EVERY == 0:
            session.expire_all()

    session.commit()

    removed = 0
    for item_id, row in albums.items():
        if item_id in seen:
            continue
        session.execute(delete(LibraryTrack).where(LibraryTrack.album_item_id == item_id))
        session.delete(row)
        removed += 1
    session.commit()

    artists = _rebuild_artists(session)
    tracks = track_count(session)
    backfilled = await backfill_release_groups(session)

    return {
        "albums": len(seen),
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "removed": removed,
        "skipped": skipped,
        "tracks": tracks,
        "artists": artists,
        "release_groups_backfilled": backfilled,
    }


def album_tracks(session: Session, album_item_id_value: str) -> list[LibraryTrack]:
    """The tracklist of one album, in disc then track order."""
    return list(
        session.execute(
            select(LibraryTrack)
            .where(LibraryTrack.album_item_id == album_item_id_value)
            .order_by(LibraryTrack.disc.asc(), LibraryTrack.track.asc(), LibraryTrack.title.asc())
        )
        .scalars()
        .all()
    )


def find_track(session: Session, item_id: str) -> LibraryTrack | None:
    return session.execute(
        select(LibraryTrack).where(LibraryTrack.item_id == item_id)
    ).scalar_one_or_none()


def search_tracks(session: Session, query: str, *, limit: int = 40) -> list[LibraryTrack]:
    pattern = f"%{query.strip()}%"
    return list(
        session.execute(
            select(LibraryTrack)
            .where(
                or_(
                    LibraryTrack.title.ilike(pattern),
                    LibraryTrack.artist.ilike(pattern),
                    LibraryTrack.album.ilike(pattern),
                )
            )
            .order_by(LibraryTrack.artist.asc(), LibraryTrack.title.asc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


def track_count(session: Session) -> int:
    return session.execute(select(func.count()).select_from(LibraryTrack)).scalar() or 0
