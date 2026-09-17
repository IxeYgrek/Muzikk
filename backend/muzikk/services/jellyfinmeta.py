"""Making Jellyfin agree with the tags written on disk.

Jellyfin reads the tags of a file when it first sees it and then trusts its own
database. A refresh in the default mode only fills in what is missing, so an
album it once named from a broken tag keeps that name for ever: correcting the
files changes nothing on screen. A library that saves NFO files makes it worse,
since the wrong name sitting in ``album.nfo`` is read back before the tags.

Two passes, like the cover repair:

1. every album whose title, artist, year or track titles disagree with the disk
   is asked for a full metadata refresh, the only mode that makes Jellyfin read
   the tags again;
2. whatever still disagrees is written straight into Jellyfin through the same
   endpoint as *Edit metadata*, which asks no provider and reads no NFO.

The disagreement is looked for twice on purpose. The stored analysis is the
cheap filter — it already holds what every folder declares, so no file is read
to find the suspects. The files themselves are then read again, and they have
the final word: an analysis older than the last correction would otherwise push
outdated values into Jellyfin.

Images are never touched: replacing those on a music library deletes the cover
files sitting in the folders (jellyfin#12629).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..matching.normalize import is_audio_file
from ..models import AppSetting, MetadataAlbum, utcnow
from . import settings as settings_service
from . import tags as tags_service
from .base import ServiceError
from .jellyfin import JellyfinClient
from .metadata import MetadataError, common_value

logger = logging.getLogger(__name__)

REPORT_KEY = "jellyfin_metadata_report"

# Albums detailed on screen; the rest stays in the log.
FAILURE_SAMPLES = 5
STALE_SAMPLES = 10

# Correcting one album costs a few calls per item written, so a library where
# hundreds of albums disagree is handled over several passes. A pass that leaves
# albums behind queues the next one itself, up to that many times: the whole
# library ends up aligned without anyone having to click again.
MAX_ALBUMS = 400
MAX_CHAINED_PASSES = 8

# Asking a server to reread hundreds of albums is expensive and, on a library
# where something else overrides the tags, completely useless. A handful is
# tried first; the rest is only asked if that handful proved it was worth it.
PROBE_ALBUMS = 8

# Jellyfin queues a refresh and answers immediately, so the check has to wait
# for the queue to drain.
SETTLE_BASE_SECONDS = 20.0
SETTLE_PER_ALBUM_SECONDS = 0.6
SETTLE_MAX_SECONDS = 420.0

CALL_INTERVAL_SECONDS = 0.05


@dataclass(slots=True)
class DiskAlbum:
    """What the files of one folder declare about themselves."""

    title: str = ""
    artist: str = ""
    year: int | None = None
    # By file name in lower case: the two sides hold the very same files, so
    # their names match even when the library is mounted elsewhere.
    tracks: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(slots=True)
class Stale:
    """One album Jellyfin disagrees with, and what it takes to fix it."""

    album: dict[str, Any]
    disk: DiskAlbum
    fields: list[str]
    tracks: list[dict[str, Any]]
    # Whether Jellyfin holds a value written twice rather than merely a
    # different one. Those albums are served first: it is the fault that shows.
    doubled: bool = False

    @property
    def label(self) -> str:
        return str(self.album.get("Name") or self.album.get("Id") or "?")


@dataclass(slots=True)
class AlignReport:
    started_at: datetime | None = None
    finished_at: datetime | None = None
    albums: int = 0
    compared: int = 0
    stale: int = 0
    refreshed: int = 0
    fixed_by_refresh: int = 0
    albums_written: int = 0
    tracks_written: int = 0
    unreadable: int = 0
    left: int = 0
    # The server was asked to reread the files and changed nothing, so the rest
    # of the pass did not bother asking again.
    refresh_ignored: bool = False
    failed: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)
    samples: list[dict[str, str]] = field(default_factory=list)

    def note_failure(self, label: str, error: str) -> None:
        self.failed += 1
        if len(self.failures) < FAILURE_SAMPLES:
            self.failures.append({"path": label, "error": error[:300]})

    def note_stale(self, item: Stale) -> None:
        self.stale += 1
        if len(self.samples) < STALE_SAMPLES:
            parts = list(item.fields)
            if item.tracks:
                parts.append(f"{len(item.tracks)} piste(s)")
            self.samples.append({"path": item.label, "error": ", ".join(parts)})

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "albums": self.albums,
            "compared": self.compared,
            "stale": self.stale,
            "refreshed": self.refreshed,
            "fixed_by_refresh": self.fixed_by_refresh,
            "albums_written": self.albums_written,
            "tracks_written": self.tracks_written,
            "unreadable": self.unreadable,
            "left": self.left,
            "refresh_ignored": self.refresh_ignored,
            "failed": self.failed,
            "failures": self.failures,
            "samples": self.samples,
        }


def read_report(session: Session) -> dict[str, Any]:
    row = session.get(AppSetting, REPORT_KEY)
    return dict(row.data or {}) if row else {}


def _write_report(session: Session, payload: dict[str, Any]) -> None:
    row = session.get(AppSetting, REPORT_KEY)
    if row is None:
        session.add(AppSetting(section=REPORT_KEY, data=payload))
    else:
        row.data = payload
    session.commit()


# --------------------------------------------------------------- the two sides


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _album_artist(album: dict[str, Any]) -> str:
    credited = album.get("AlbumArtists") or []
    if credited:
        return _clean(credited[0].get("Name"))
    return _clean(album.get("AlbumArtist"))


def _read_folder(folder: Path) -> DiskAlbum | None:
    """The truth, read from the files themselves."""
    if not folder.is_dir():
        return None
    files = [
        item
        for item in sorted(folder.rglob("*"))
        if item.is_file() and is_audio_file(item.name)
    ]
    entries = [entry for entry in tags_service.read_album(files) if entry.readable]
    if not entries:
        return None

    years = [entry.year for entry in entries if entry.year]
    return DiskAlbum(
        title=common_value([entry.album for entry in entries]),
        artist=common_value([entry.albumartist for entry in entries])
        or common_value([entry.artist for entry in entries]),
        year=years[0] if years else None,
        tracks={
            Path(entry.path).name.lower(): {
                "title": entry.title,
                "track": entry.track,
                "disc": entry.disc,
            }
            for entry in entries
        },
    )


def _from_row(row: MetadataAlbum) -> DiskAlbum:
    """The same view, taken from the last analysis instead of the disk."""
    tracks: dict[str, dict[str, Any]] = {}
    for track in row.tracks or []:
        name = str(track.get("name") or Path(str(track.get("path") or "")).name)
        if not name or not track.get("readable", True):
            continue
        tracks[name.lower()] = {
            "title": _clean(track.get("title")),
            "track": track.get("track"),
            "disc": track.get("disc"),
        }
    return DiskAlbum(
        title=_clean(row.album_title),
        artist=_clean(row.album_artist),
        year=row.year,
        tracks=tracks,
    )


def _album_differences(album: dict[str, Any], disk: DiskAlbum) -> list[str]:
    """Album wide fields Jellyfin holds differently. Blanks prove nothing."""
    found: list[str] = []
    if disk.title and _clean(album.get("Name")) != disk.title:
        found.append("title")
    if disk.artist and _album_artist(album) != disk.artist:
        found.append("artist")
    if disk.year and album.get("ProductionYear") != disk.year:
        found.append("year")
    return found


def _looks_doubled(current: str, expected: str) -> bool:
    """Whether Jellyfin holds that value written twice.

    That is the fault an album shows on screen — "Aloha!Aloha!" — as opposed to
    a year or a title that simply disagrees, which nobody notices.
    """
    current = current.strip()
    if not current or not expected or current == expected:
        return False
    return any(
        current == f"{expected}{separator}{expected}"
        for separator in ("", " ", "; ", ";", " / ", "/", ", ")
    )


def _is_doubling(album: dict[str, Any], changes: list[dict[str, Any]], disk: DiskAlbum) -> bool:
    if _looks_doubled(_clean(album.get("Name")), disk.title):
        return True
    return any(
        _looks_doubled(_clean(change["item"].get("Name")), str(change["changes"]["Name"]))
        for change in changes
        if "Name" in change["changes"]
    )


def _track_differences(items: list[dict[str, Any]], disk: DiskAlbum) -> list[dict[str, Any]]:
    """Tracks whose title or numbering Jellyfin holds differently."""
    stale: list[dict[str, Any]] = []
    for item in items:
        name = Path(_clean(item.get("Path"))).name.lower()
        expected = disk.tracks.get(name)
        if not expected:
            continue
        changes: dict[str, Any] = {}
        if expected["title"] and _clean(item.get("Name")) != expected["title"]:
            changes["Name"] = expected["title"]
        if expected["track"] and item.get("IndexNumber") != expected["track"]:
            changes["IndexNumber"] = expected["track"]
        if changes:
            stale.append({"item": item, "changes": changes})
    return stale


# ------------------------------------------------------------------- the passes


def _rows(session: Session, album_id: int | None) -> dict[str, MetadataAlbum]:
    statement = select(MetadataAlbum).where(MetadataAlbum.jellyfin_id.is_not(None))
    if album_id is not None:
        statement = statement.where(MetadataAlbum.id == album_id)
    return {
        row.jellyfin_id: row
        for row in session.execute(statement).scalars()
        if row.jellyfin_id and row.path
    }


def _group_tracks(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        album_id = item.get("AlbumId") or item.get("ParentId")
        if album_id:
            grouped.setdefault(str(album_id), []).append(item)
    return grouped


async def _collect(
    client: JellyfinClient, rows: dict[str, MetadataAlbum], library_ids: list[str], single: bool
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """The Jellyfin side: the albums and their tracks as the server sees them."""
    if not single:
        albums = await client.get_albums(library_ids or None)
        tracks = _group_tracks(await client.get_audio_items(library_ids or None))
        return albums, tracks

    # The editing view rather than a listing: it carries the whole item, so the
    # album artist is there without having to guess which field holds it.
    item_id = next(iter(rows))
    album = await client.get_item_for_edit(item_id)
    if not album:
        return [], {}
    return [album], {item_id: await client.get_album_tracks(item_id)}


async def _recheck(
    client: JellyfinClient, item: Stale
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    """The album as Jellyfin holds it right now, and what is still wrong with it.

    Asked album by album rather than by sweeping the library again: the answer
    is then as fresh as it can be, and it is the very item the write posts back.
    """
    item_id = str(item.album["Id"])
    album = await client.get_item_for_edit(item_id) or item.album
    tracks = await client.get_album_tracks(item_id)
    return album, _album_differences(album, item.disk), _track_differences(tracks, item.disk)


async def _write_album(
    client: JellyfinClient, album: dict[str, Any], disk: DiskAlbum, fields: list[str]
) -> None:
    payload = dict(album)
    if "title" in fields:
        payload["Name"] = disk.title
    if "artist" in fields:
        # Only the names are read back, the identifiers are resolved server side.
        payload["AlbumArtists"] = [{"Name": disk.artist}]
        payload["AlbumArtist"] = disk.artist
    if "year" in fields:
        payload["ProductionYear"] = disk.year
    await client.update_item(str(album["Id"]), payload)


async def _write_track(client: JellyfinClient, track: dict[str, Any]) -> None:
    item_id = str(track["item"]["Id"])
    payload = await client.get_item_for_edit(item_id)
    payload.update(track["changes"])
    await client.update_item(item_id, payload)


async def _ask_refresh(
    client: JellyfinClient, items: list[Stale], report: AlignReport
) -> None:
    """Ask for a full reread, then wait for the queue Jellyfin answers from."""
    if not items:
        return
    for item in items:
        try:
            await client.refresh_item_metadata(str(item.album["Id"]))
            report.refreshed += 1
        except ServiceError as exc:
            report.note_failure(item.label, f"refresh: {exc}")
        await asyncio.sleep(CALL_INTERVAL_SECONDS)

    settle = min(
        SETTLE_BASE_SECONDS + SETTLE_PER_ALBUM_SECONDS * len(items), SETTLE_MAX_SECONDS
    )
    logger.info(
        "Jellyfin metadata: reread asked for %s albums, waiting %.0fs", len(items), settle
    )
    await asyncio.sleep(settle)


async def align_metadata(session: Session, *, album_id: int | None = None) -> dict[str, Any]:
    """Make Jellyfin show what the tags on disk actually say.

    With ``album_id`` set, only that album is handled and no report is stored:
    that is the pass queued right after a correction, and it has no business
    overwriting the report of a library wide run.
    """
    jellyfin_settings = settings_service.load(session, "jellyfin")
    client = JellyfinClient(jellyfin_settings)
    if not client.configured or not client.api_key:
        raise MetadataError(
            "Jellyfin needs a URL and an API key before its metadata can be aligned"
        )

    library_ids = list(jellyfin_settings.music_library_ids or [])
    single = album_id is not None
    report = AlignReport(started_at=utcnow())

    rows = _rows(session, album_id)
    if not rows:
        return _finish(session, report, store=not single)

    albums, tracks_by_album = await _collect(client, rows, library_ids, single)
    report.albums = len(albums)

    # ------------------------------------------------------- find the stragglers
    found: list[Stale] = []
    for album in albums:
        item_id = str(album.get("Id") or "")
        row = rows.get(item_id)
        if row is None:
            continue
        report.compared += 1

        items = tracks_by_album.get(item_id, [])
        stored = _from_row(row)
        if not (_album_differences(album, stored) or _track_differences(items, stored)):
            continue

        disk = await asyncio.to_thread(_read_folder, Path(row.path))
        if disk is None:
            report.unreadable += 1
            continue
        fields = _album_differences(album, disk)
        changes = _track_differences(items, disk)
        if not (fields or changes):
            continue  # the analysis was simply out of date, Jellyfin is right

        found.append(
            Stale(
                album=album,
                disk=disk,
                fields=fields,
                tracks=changes,
                doubled=_is_doubling(album, changes, disk),
            )
        )

    # Doubled values first. The pass is capped, and the albums are swept in
    # alphabetical order: without this a library whose fault sits under the
    # letter T would spend its whole budget on years that merely disagree.
    found.sort(key=lambda item: (not item.doubled, item.label.casefold()))
    report.left = max(0, len(found) - MAX_ALBUMS)
    stale = {str(item.album["Id"]): item for item in found[:MAX_ALBUMS]}
    for item in stale.values():
        report.note_stale(item)

    if not stale:
        logger.info("Jellyfin metadata: %s albums compared, nothing to align", report.compared)
        return _finish(session, report, store=not single)

    # ------------------------------------------------- ask Jellyfin first, a little
    # A refresh that works spares a write; one that is ignored costs nothing but
    # the wait, and it can even undo a write that lands while it is still
    # running. So it is tried on a handful of albums and only kept if it worked.
    queued = list(stale.values())
    probe = queued[:PROBE_ALBUMS]
    await _ask_refresh(client, probe, report)
    fixed = 0
    for item in probe:
        album, fields, changes = await _recheck(client, item)
        item.album = album
        if not (fields or changes):
            fixed += 1

    if fixed:
        await _ask_refresh(client, queued[PROBE_ALBUMS:], report)
    else:
        report.refresh_ignored = True
        logger.info(
            "Jellyfin metadata: rereading the files changed none of the %s albums tried, "
            "writing the values in directly",
            len(probe),
        )

    # --------------------------------------------- then write what is still wrong
    for item in queued:
        try:
            album, fields, changes = await _recheck(client, item)
            if not (fields or changes):
                report.fixed_by_refresh += 1
                continue
            if fields:
                await _write_album(client, album, item.disk, fields)
                report.albums_written += 1
            for track in changes:
                await _write_track(client, track)
                report.tracks_written += 1
                await asyncio.sleep(CALL_INTERVAL_SECONDS)
        except ServiceError as exc:
            report.note_failure(item.label, f"write: {exc}")
        except Exception as exc:  # noqa: BLE001 - one bad album must not stop the pass
            report.note_failure(item.label, f"{type(exc).__name__}: {exc}")
            logger.exception("Metadata alignment failed on %s", item.label)
        await asyncio.sleep(CALL_INTERVAL_SECONDS)

    logger.info(
        "Jellyfin metadata over %s albums: %s compared, %s stale, %s fixed by refresh, "
        "%s albums and %s tracks written, %s failed, %s left for the next pass",
        report.albums,
        report.compared,
        report.stale,
        report.fixed_by_refresh,
        report.albums_written,
        report.tracks_written,
        report.failed,
        report.left,
    )
    return _finish(session, report, store=not single)


def _finish(session: Session, report: AlignReport, *, store: bool) -> dict[str, Any]:
    report.finished_at = utcnow()
    payload = report.as_dict()
    if store:
        _write_report(session, payload)
    return payload
