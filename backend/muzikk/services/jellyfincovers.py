"""Giving Jellyfin the album covers its own providers refuse to find.

Jellyfin reads ``folder.jpg`` and ``cover.jpg`` next to the tracks and falls
back on the picture embedded in the first track, but that chain breaks often
enough — a disabled image fetcher, a regression in the embedded image reader, a
cover file written after the last scan — to leave a library full of grey
squares. Adding the image by hand through *Edit images* always works, because
that path uploads straight into the Jellyfin metadata folder without asking any
provider. This module does the same thing in bulk.

Two passes, in that order:

1. every album with no primary image is asked to refresh, which is enough when
   the picture is on disk and Jellyfin simply had not looked since;
2. whatever is still missing gets its cover uploaded, taken from the folder,
   the tags, and finally Cover Art Archive.

The refresh is never asked to replace existing images: on a music library that
is known to delete the cover files sitting in the folders (jellyfin#12629).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..matching.normalize import is_audio_file
from ..models import AppSetting, LibraryAlbum, utcnow
from . import artwork
from . import settings as settings_service
from .base import ServiceError
from .coverart import CoverArtClient
from .jellyfin import JellyfinClient
from .metadata import MetadataError

logger = logging.getLogger(__name__)

REPORT_KEY = "jellyfin_cover_report"

# Folders detailed on screen; the rest stays in the log.
FAILURE_SAMPLES = 5

# Jellyfin queues a refresh and answers immediately, so the second pass has to
# wait for the queue to drain. The wait grows with the number of albums asked
# for, up to seven minutes: past that, an upload is a better use of the time.
SETTLE_BASE_SECONDS = 20.0
SETTLE_PER_ALBUM_SECONDS = 0.4
SETTLE_MAX_SECONDS = 420.0

# Spacing between calls, so a big library does not look like an attack.
REFRESH_INTERVAL_SECONDS = 0.05
UPLOAD_INTERVAL_SECONDS = 0.1


@dataclass(slots=True)
class CoverReport:
    """What the pass found in Jellyfin and what it changed."""

    started_at: datetime | None = None
    finished_at: datetime | None = None
    albums: int = 0
    without_cover: int = 0
    refreshed: int = 0
    fixed_by_refresh: int = 0
    uploaded: int = 0
    no_source: int = 0
    failed: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)

    def note_failure(self, label: str, error: str) -> None:
        self.failed += 1
        if len(self.failures) < FAILURE_SAMPLES:
            self.failures.append({"path": label, "error": error[:300]})

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "albums": self.albums,
            "without_cover": self.without_cover,
            "refreshed": self.refreshed,
            "fixed_by_refresh": self.fixed_by_refresh,
            "uploaded": self.uploaded,
            "no_source": self.no_source,
            "failed": self.failed,
            "failures": self.failures,
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


def _has_cover(album: dict[str, Any]) -> bool:
    return bool((album.get("ImageTags") or {}).get("Primary"))


def _local_folder(raw: str | None, music_dir: Path) -> Path | None:
    """The album folder as Muzikk sees it, from the path Jellyfin reported.

    Both containers rarely mount the library under the same prefix, so when the
    path Jellyfin gave is not readable here, the ``Artist/Album`` tail is looked
    up under the configured music folder instead.
    """
    if not raw:
        return None

    candidate = Path(raw)
    # Jellyfin reports the album folder, or a track path when the album has no
    # folder of its own. Only an audio name is stripped: plenty of albums are
    # called "Vol. 2" and a plain suffix test would climb one level too far.
    if is_audio_file(candidate.name):
        candidate = candidate.parent
    if candidate.is_dir():
        return candidate

    parts = [part for part in re.split(r"[\\/]+", str(candidate)) if part not in ("", ".", "..")]
    for depth in (2, 1):
        if len(parts) >= depth:
            guess = music_dir.joinpath(*parts[-depth:])
            if guess.is_dir():
                return guess
    return None


async def _artwork_for(
    album: dict[str, Any],
    folder: Path | None,
    covers: CoverArtClient,
    *,
    size: int,
) -> bytes | None:
    """A picture for this album: the folder first, Cover Art Archive last."""
    if folder is not None:
        data = await asyncio.to_thread(artwork.from_disk, str(folder))
        if data:
            return artwork.to_jpeg(data, size)

    providers = album.get("ProviderIds") or {}
    release = providers.get("MusicBrainzAlbum") or providers.get("MusicBrainzRelease") or ""
    group = providers.get("MusicBrainzReleaseGroup") or ""
    if not (release or group):
        return None
    try:
        remote = await covers.get_front_with_fallback(release, group)
    except ServiceError as exc:
        logger.debug("Cover Art Archive refused %s: %s", album.get("Name"), exc)
        return None
    return artwork.to_jpeg(remote, size) if remote else None


async def repair_covers(session: Session) -> dict[str, Any]:
    """Fill in the album covers Jellyfin is missing."""
    jellyfin_settings = settings_service.load(session, "jellyfin")
    coverart_settings = settings_service.load(session, "coverart")
    naming = settings_service.load(session, "naming")

    client = JellyfinClient(jellyfin_settings)
    if not client.configured or not client.api_key:
        raise MetadataError("Jellyfin needs a URL and an API key before its covers can be repaired")

    library_ids = list(jellyfin_settings.music_library_ids or [])
    report = CoverReport(started_at=utcnow())

    albums = await client.get_albums(library_ids or None)
    report.albums = len(albums)
    missing = {album["Id"]: album for album in albums if album.get("Id") and not _has_cover(album)}
    report.without_cover = len(missing)

    if not missing:
        report.finished_at = utcnow()
        payload = report.as_dict()
        _write_report(session, payload)
        logger.info("Jellyfin cover repair: %s albums, none missing a cover", report.albums)
        return payload

    # ------------------------------------------------------- ask Jellyfin first
    for item_id, album in missing.items():
        try:
            await client.refresh_item(item_id)
            report.refreshed += 1
        except ServiceError as exc:
            report.note_failure(str(album.get("Name") or item_id), f"refresh: {exc}")
        await asyncio.sleep(REFRESH_INTERVAL_SECONDS)

    settle = min(
        SETTLE_BASE_SECONDS + SETTLE_PER_ALBUM_SECONDS * report.refreshed, SETTLE_MAX_SECONDS
    )
    logger.info(
        "Jellyfin cover repair: %s albums without a cover, refresh asked for %s, waiting %.0fs",
        report.without_cover,
        report.refreshed,
        settle,
    )
    await asyncio.sleep(settle)

    reread = await client.get_albums(library_ids or None)
    still: dict[str, dict[str, Any]] = {}
    for album in reread:
        item_id = album.get("Id")
        if item_id in missing:
            if _has_cover(album):
                report.fixed_by_refresh += 1
            else:
                still[item_id] = album

    # ------------------------------------------------- then upload what is left
    music_dir = Path(naming.music_dir)
    known_paths = {
        row.jellyfin_id: row.path
        for row in session.execute(select(LibraryAlbum)).scalars()
        if row.path
    }
    covers = CoverArtClient(coverart_settings)

    for item_id, album in still.items():
        label = str(album.get("Name") or item_id)
        folder = _local_folder(album.get("Path") or known_paths.get(item_id), music_dir)
        try:
            data = await _artwork_for(
                album, folder, covers, size=coverart_settings.preferred_size
            )
            if not data:
                report.no_source += 1
                logger.info("No artwork anywhere for %s (%s)", label, folder or "no folder")
                continue
            await client.upload_primary_image(item_id, data)
            report.uploaded += 1
        except ServiceError as exc:
            report.note_failure(label, f"upload: {exc}")
        except Exception as exc:  # noqa: BLE001 - one bad album must not stop the pass
            report.note_failure(label, f"{type(exc).__name__}: {exc}")
            logger.exception("Cover repair failed on %s", label)
        await asyncio.sleep(UPLOAD_INTERVAL_SECONDS)

    report.finished_at = utcnow()
    logger.info(
        "Jellyfin cover repair over %s albums: %s without a cover, %s fixed by refresh, "
        "%s uploaded, %s with no artwork anywhere, %s failed",
        report.albums,
        report.without_cover,
        report.fixed_by_refresh,
        report.uploaded,
        report.no_source,
        report.failed,
    )
    payload = report.as_dict()
    _write_report(session, payload)
    return payload
