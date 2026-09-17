"""Giving every album folder both a cover.jpg and a folder.jpg.

Media players disagree on which file name holds the front cover: Jellyfin and
Kodi read both, Plex and older Sonos builds only look at one of them. Keeping
the two names side by side costs a few kilobytes per album and removes the
question entirely.

Nothing is downloaded here. Either the folder already holds a picture under one
of the two names and the other name is a copy of it, or the picture embedded in
the tags is written out. A folder with no artwork at all is reported, not
invented.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..models import AppSetting, utcnow
from . import artwork
from . import settings as settings_service
from .metadata import MetadataError, WalkReport, collect_folders

logger = logging.getLogger(__name__)

# The two names to keep in sync, in the order they are trusted.
COVER_NAME = "cover"
FOLDER_NAME = "folder"

# Extensions worth copying, best first: a copy keeps the extension of the file
# it comes from, so the list only decides which source wins.
SOURCE_SUFFIXES = (".jpg", ".jpeg", ".png")

REPORT_KEY = "artwork_sync_report"

# Folders detailed on screen; the rest stays in the log.
FAILURE_SAMPLES = 5


@dataclass(slots=True)
class SyncReport:
    """What the pass did, folder by folder."""

    root: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    folders: int = 0
    already: int = 0
    copied: int = 0
    extracted: int = 0
    without_art: int = 0
    failed: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "folders": self.folders,
            "already": self.already,
            "copied": self.copied,
            "extracted": self.extracted,
            "without_art": self.without_art,
            "failed": self.failed,
            "failures": self.failures,
        }


def _usable(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _existing(directory: Path) -> dict[str, Path]:
    """The cover and folder pictures already there, whatever their case.

    Windows Media Player writes ``Folder.jpg`` and ripping tools have their own
    habits, so the listing is matched case insensitively rather than guessed
    name by name. An empty file counts as missing: it is what a failed copy
    leaves behind.
    """
    found: dict[str, list[Path]] = {}
    for entry in directory.iterdir():
        stem = entry.stem.lower()
        if stem in (COVER_NAME, FOLDER_NAME) and entry.suffix.lower() in SOURCE_SUFFIXES:
            if _usable(entry):
                found.setdefault(stem, []).append(entry)

    rank = {suffix: index for index, suffix in enumerate(SOURCE_SUFFIXES)}
    return {
        stem: min(entries, key=lambda path: (rank[path.suffix.lower()], path.name))
        for stem, entries in found.items()
    }


def normalise_folder(directory: Path, *, size: int, tracks: Sequence[Path] = ()) -> str:
    """Make both names exist in one album folder.

    Returns what happened: ``already``, ``copied``, ``extracted`` or
    ``without_art``. Raises :class:`OSError` when the folder cannot be read or
    written.
    """
    existing = _existing(directory)
    cover = existing.get(COVER_NAME)
    folder = existing.get(FOLDER_NAME)

    if cover and folder:
        return "already"

    source = cover or folder
    if source is not None:
        target = directory / f"{FOLDER_NAME if cover else COVER_NAME}{source.suffix.lower()}"
        target.write_bytes(source.read_bytes())
        return "copied"

    embedded = (
        artwork.picture_from_tracks(tracks) if tracks else artwork.embedded_cover(directory)
    )
    if not embedded:
        return "without_art"

    data = artwork.to_jpeg(embedded, size)
    for stem in (COVER_NAME, FOLDER_NAME):
        (directory / f"{stem}.jpg").write_bytes(data)
    return "extracted"


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


def _walk(root: Path, *, size: int, max_albums: int) -> SyncReport:
    """The disk half of the pass, kept out of the event loop."""
    report = SyncReport(root=str(root), started_at=utcnow())
    walk = WalkReport()
    # One track is enough here: even a folder holding a single song deserves
    # its artwork, which is not true of the analysis that looks for albums.
    folders = collect_folders(root, min_tracks=1, max_albums=max_albums, report=walk)
    report.folders = len(folders)

    for folder in folders:
        try:
            outcome = normalise_folder(folder.path, size=size, tracks=folder.files)
        except Exception as exc:  # noqa: BLE001 - a locked folder must not stop the pass
            report.failed += 1
            if len(report.failures) < FAILURE_SAMPLES:
                report.failures.append(
                    {"path": str(folder.path), "error": f"{type(exc).__name__}: {exc}"[:300]}
                )
            logger.exception("Artwork sync failed on %s", folder.path)
            continue
        setattr(report, outcome, getattr(report, outcome) + 1)

    report.finished_at = utcnow()
    logger.info(
        "Artwork sync over %s: %s folders, %s already paired, %s copied, "
        "%s extracted from tags, %s without artwork, %s failed",
        root,
        report.folders,
        report.already,
        report.copied,
        report.extracted,
        report.without_art,
        report.failed,
    )
    return report


async def sync_library(session: Session) -> dict[str, Any]:
    """Walk every album folder of the library and give each one both names."""
    naming = settings_service.load(session, "naming")
    config = settings_service.load(session, "metadata")
    coverart = settings_service.load(session, "coverart")

    root = Path(naming.music_dir)
    if not root.is_dir():
        raise MetadataError(
            f'the library folder "{root}" is not visible from Muzikk: check the volume mount'
        )

    report = await asyncio.to_thread(
        _walk,
        root,
        size=coverart.preferred_size,
        max_albums=config.max_albums_per_scan,
    )
    payload = report.as_dict()
    _write_report(session, payload)
    return payload
