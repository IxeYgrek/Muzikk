"""Library analysis and metadata repair.

Muzikk walks the music folder itself instead of asking Jellyfin, because the
albums worth reporting are precisely the ones Jellyfin could not index. Each
album folder is compared with the tags it carries, with the Jellyfin index and
with MusicBrainz, and anything missing is recorded for an administrator to
review. Nothing is ever written without an explicit confirmation.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..matching.normalize import (
    AUDIO_EXTENSIONS,
    LOSSLESS_EXTENSIONS,
    extension_of,
    fuzzy_key,
    guess_year,
    normalize_artist,
    normalize_title,
)
from ..matching.release_picker import pick_release
from ..models import (
    AppSetting,
    LibraryAlbum,
    MetadataAlbum,
    MetadataIssue,
    MetadataState,
    utcnow,
)
from ..pipeline.importer import (
    album_metadata_from_release,
    build_track_metadata,
    map_files_to_tracks,
    tracks_from_release,
)
from ..pipeline.tagger import TaggingError, write_tags
from . import artwork
from . import mode as mode_service
from . import settings as settings_service
from . import tags as tags_service
from .coverart import CoverArtClient
from .musicbrainz import MusicBrainzClient

logger = logging.getLogger(__name__)

# "CD1", "Disc 2", "Disque 3": the album lives one level up.
DISC_DIR_RE = re.compile(r"^(cd|disc|disk|disque)\s*[-_]?\s*\d{1,2}$", re.IGNORECASE)

SKIP_DIRECTORIES = {"@eadir", ".@__thumb", "lost+found", ".stfolder", ".trash-1000"}

# Tags an album is expected to carry once it has been through Picard or Muzikk.
REQUIRED_TAGS = ("albumartist", "album", "date", "genre", "track")

# Reported when absent, but never enough on their own to call an album
# incomplete: Picard leaves them empty unless asked, and flagging a whole
# library for them buries the albums that really need attention.
OPTIONAL_TAGS = ("genre",)

MATCH_SEARCH_LIMIT = 8

# Failing folders reported on screen; the rest stays in the log.
FAILURE_SAMPLES = 5


class MetadataError(RuntimeError):
    pass


# --------------------------------------------------------------- disk walking


@dataclass(slots=True)
class FolderInfo:
    """An album as it exists on disk."""

    path: Path
    files: list[Path] = field(default_factory=list)

    @property
    def formats(self) -> list[str]:
        return sorted({extension_of(item.name) for item in self.files} - {""})

    @property
    def is_lossless(self) -> bool:
        formats = self.formats
        return bool(formats) and all(item in LOSSLESS_EXTENSIONS for item in formats)


@dataclass(slots=True)
class WalkReport:
    """What the walk actually saw, to explain an empty result."""

    directories: int = 0
    audio_files: int = 0
    grouped: int = 0
    below_min_tracks: int = 0
    failed: int = 0
    unreadable: int = 0
    # A few examples of what went wrong, shown on the administration screen so
    # a failing scan can be diagnosed without opening a shell.
    failures: list[dict[str, str]] = field(default_factory=list)


def collect_folders(
    root: Path,
    *,
    min_tracks: int = 2,
    max_albums: int = 20000,
    report: WalkReport | None = None,
) -> list[FolderInfo]:
    """Group the audio files of the library by album folder.

    Symbolic links are followed: a library exposed to the container as a tree of
    linked artist folders is common enough that skipping them would silently
    return nothing. Already visited directories are remembered so a link
    pointing back up cannot loop.
    """
    grouped: dict[Path, list[Path]] = {}
    seen_directories: set[str] = set()
    notes = report if report is not None else WalkReport()

    def unreadable(error: OSError) -> None:
        # os.walk swallows these by default, which turns a permission problem
        # into a silently shorter library.
        notes.unreadable += 1
        logger.warning("Cannot read %s: %s", error.filename, error)

    for current, directories, filenames in os.walk(root, onerror=unreadable, followlinks=True):
        notes.directories += 1
        # os.path.realpath rather than Path.resolve: no exception on a dangling
        # link, which a media library tends to accumulate.
        directories[:] = [
            name
            for name in directories
            if name.lower() not in SKIP_DIRECTORIES
            and os.path.realpath(os.path.join(current, name)) not in seen_directories
        ]
        seen_directories.update(
            os.path.realpath(os.path.join(current, name)) for name in directories
        )

        audio = [name for name in filenames if extension_of(name) in AUDIO_EXTENSIONS]
        if not audio:
            continue
        notes.audio_files += len(audio)

        directory = Path(current)
        # Multi disc albums are one album, not one per disc.
        target = directory.parent if DISC_DIR_RE.match(directory.name) else directory
        grouped.setdefault(target, []).extend(directory / name for name in audio)

        if len(grouped) > max_albums:
            logger.warning("Metadata scan stopped at %s folders", max_albums)
            break

    notes.grouped = len(grouped)
    threshold = max(1, min_tracks)
    notes.below_min_tracks = sum(1 for files in grouped.values() if len(files) < threshold)

    folders = [
        FolderInfo(path=path, files=sorted(files))
        for path, files in grouped.items()
        if len(files) >= threshold
    ]
    folders.sort(key=lambda item: str(item.path).lower())
    return folders


def common_value(values: list[str]) -> str:
    """Most frequent non-empty value, favouring the first one on a tie.

    Positions are recorded while counting rather than looked up afterwards:
    values are trimmed, and a tag padded with spaces would then not be found
    in the original list.
    """
    counts: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for index, value in enumerate(values):
        cleaned = (value or "").strip()
        if not cleaned:
            continue
        counts[cleaned] = counts.get(cleaned, 0) + 1
        first_seen.setdefault(cleaned, index)
    if not counts:
        return ""
    return max(counts.items(), key=lambda item: (item[1], -first_seen[item[0]]))[0]


def titles_from_path(folder: FolderInfo) -> tuple[str, str, int | None]:
    """Guess artist, album and year from the folder layout.

    Libraries are almost always laid out as ``Artist/Album (Year)``, which is
    the only clue left when a folder carries no tags at all.
    """
    name = folder.path.name
    year = guess_year(name)
    title = re.sub(r"[\(\[]\s*(19|20)\d{2}\s*[\)\]]", " ", name).strip(" -_")
    artist = folder.path.parent.name if folder.path.parent != folder.path else ""
    return artist, " ".join(title.split()), year


# ------------------------------------------------------------ jellyfin lookup


@dataclass(slots=True)
class LibraryRow:
    jellyfin_id: str
    path: str
    fuzzy_key: str
    release_mbid: str | None
    release_group_mbid: str | None


def _path_tail(path: str, depth: int = 2) -> str:
    """Last components of a path, used to compare two different mount points.

    Jellyfin and Muzikk rarely see the library under the same prefix, but they
    always agree on the ``Artist/Album`` tail.
    """
    parts = [part for part in re.split(r"[\\/]+", (path or "").strip()) if part]
    return "/".join(part.lower() for part in parts[-depth:])


class LibraryLocator:
    """Matches a folder on disk with the album Jellyfin indexed for it."""

    def __init__(self, session: Session) -> None:
        rows = session.execute(
            select(
                LibraryAlbum.jellyfin_id,
                LibraryAlbum.path,
                LibraryAlbum.fuzzy_key,
                LibraryAlbum.release_mbid,
                LibraryAlbum.release_group_mbid,
            )
        ).all()

        self._by_path: dict[str, LibraryRow] = {}
        self._by_tail: dict[str, LibraryRow] = {}
        self._by_fuzzy: dict[str, LibraryRow] = {}
        self._by_mbid: dict[str, LibraryRow] = {}

        for row in rows:
            entry = LibraryRow(
                jellyfin_id=row.jellyfin_id,
                path=row.path or "",
                fuzzy_key=row.fuzzy_key or "",
                release_mbid=row.release_mbid,
                release_group_mbid=row.release_group_mbid,
            )
            if entry.path:
                # Jellyfin stores an album path, or a track path when the album
                # itself has none.
                folder = entry.path
                if extension_of(folder):
                    folder = str(Path(folder).parent)
                self._by_path.setdefault(folder.rstrip("/\\").lower(), entry)
                self._by_tail.setdefault(_path_tail(folder), entry)
            if entry.fuzzy_key:
                self._by_fuzzy.setdefault(entry.fuzzy_key, entry)
            for mbid in (entry.release_mbid, entry.release_group_mbid):
                if mbid:
                    self._by_mbid.setdefault(mbid.lower(), entry)

    def find(
        self,
        folder: Path,
        key: str,
        *,
        release_mbid: str = "",
        release_group_mbid: str = "",
    ) -> LibraryRow | None:
        exact = self._by_path.get(str(folder).rstrip("/\\").lower())
        if exact is not None:
            return exact
        tail = self._by_tail.get(_path_tail(str(folder)))
        if tail is not None:
            return tail
        # Identifiers beat names: Jellyfin often titles an album differently
        # from its folder, but it reads the same tags we do.
        for mbid in (release_mbid, release_group_mbid):
            if mbid:
                found = self._by_mbid.get(mbid.lower())
                if found is not None:
                    return found
        return self._by_fuzzy.get(key) if key.strip("|") else None


# -------------------------------------------------------------------- scanning


@dataclass(slots=True)
class Finding:
    """Everything the analysis learned about one album folder."""

    path: str
    album_artist: str
    album_title: str
    year: int | None
    track_count: int
    formats: list[str]
    fuzzy_key: str
    has_cover: bool
    release_mbid: str
    release_group_mbid: str
    issues: list[str] = field(default_factory=list)
    tracks: list[dict[str, Any]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    jellyfin_id: str | None = None


# Files detailed in the report of an album whose tags are doubled. A folder
# where every track is affected says everything it has to say in a few lines.
DUPLICATE_SAMPLES = 12


def _duplicated_tags(entries: list[tags_service.FileTags]) -> dict[str, Any]:
    """Which tags of an album hold the same value twice, and where.

    Kept as a summary rather than the full list: the screen needs to name the
    affected fields and show a few examples, the repair rewrites every file
    anyway.
    """
    fields: list[str] = []
    files: list[dict[str, Any]] = []
    for entry in entries:
        if not entry.repeated:
            continue
        if len(files) < DUPLICATE_SAMPLES:
            files.append({"name": entry.name, "tags": entry.repeated})
        for name in entry.repeated:
            if name not in fields:
                fields.append(name)

    if not files:
        return {}
    return {
        "fields": fields,
        "files": files,
        "file_count": sum(1 for entry in entries if entry.repeated),
    }


def _missing_tags(entries: list[tags_service.FileTags]) -> list[str]:
    missing: list[str] = []
    if not any(entry.albumartist for entry in entries):
        missing.append("albumartist")
    if not any(entry.album for entry in entries):
        missing.append("album")
    if not any(entry.date for entry in entries):
        missing.append("date")
    if not any(entry.genres for entry in entries):
        missing.append("genre")
    if any(entry.track is None for entry in entries):
        missing.append("track")
    if not any(entry.title for entry in entries):
        missing.append("title")
    return missing


def _examine(folder: FolderInfo, locator: LibraryLocator) -> Finding:
    entries = tags_service.read_album(folder.files)
    readable = [entry for entry in entries if entry.readable]

    album_title = common_value([entry.album for entry in readable])
    album_artist = common_value([entry.albumartist for entry in readable]) or common_value(
        [entry.artist for entry in readable]
    )
    guessed_artist, guessed_title, guessed_year = titles_from_path(folder)
    album_title = album_title or guessed_title
    album_artist = album_artist or guessed_artist

    years = [entry.year for entry in readable if entry.year]
    year = years[0] if years else guessed_year

    release_mbid = common_value([entry.release_mbid for entry in readable])
    group_mbid = common_value([entry.release_group_mbid for entry in readable])
    key = fuzzy_key(album_artist, album_title)

    finding = Finding(
        path=str(folder.path),
        album_artist=album_artist,
        album_title=album_title,
        year=year,
        track_count=len(folder.files),
        formats=folder.formats,
        fuzzy_key=key,
        has_cover=artwork.has_cover(folder.path),
        release_mbid=release_mbid,
        release_group_mbid=group_mbid,
        tracks=[
            {
                "name": entry.name,
                "path": entry.path,
                "readable": entry.readable,
                "extension": entry.extension,
                "duration": entry.duration,
                "has_picture": entry.has_picture,
                "repeated": entry.repeated,
                **entry.as_dict(),
            }
            for entry in entries
        ],
    )

    if not (release_mbid or group_mbid):
        finding.issues.append(MetadataIssue.MISSING_MBID)
    if not finding.has_cover:
        finding.issues.append(MetadataIssue.MISSING_COVER)

    missing = _missing_tags(readable) if readable else list(REQUIRED_TAGS)
    if missing:
        finding.details["missing_tags"] = missing
    if any(tag not in OPTIONAL_TAGS for tag in missing):
        finding.issues.append(MetadataIssue.INCOMPLETE_TAGS)
    if len(readable) != len(entries):
        finding.details["unreadable_files"] = [
            entry.name for entry in entries if not entry.readable
        ]

    doubled = _duplicated_tags(entries)
    if doubled:
        finding.issues.append(MetadataIssue.DUPLICATE_TAGS)
        finding.details["duplicated_tags"] = doubled

    match = locator.find(
        folder.path, key, release_mbid=release_mbid, release_group_mbid=group_mbid
    )
    if match is None:
        finding.issues.append(MetadataIssue.NOT_IN_JELLYFIN)
    else:
        finding.jellyfin_id = match.jellyfin_id
        if not match.release_group_mbid and not match.release_mbid:
            finding.issues.append(MetadataIssue.PROBABLE_MATCH)
    return finding


def _from_path_only(folder: FolderInfo, locator: LibraryLocator, reason: str) -> Finding:
    """Last resort entry for a folder whose files could not be read.

    Losing the album would be worse than listing it with what the folder name
    says: it stays visible, flagged, and an administrator can act on it.
    """
    artist, title, year = titles_from_path(folder)
    key = fuzzy_key(artist, title)
    finding = Finding(
        path=str(folder.path),
        album_artist=artist,
        album_title=title,
        year=year,
        track_count=len(folder.files),
        formats=folder.formats,
        fuzzy_key=key,
        has_cover=False,
        release_mbid="",
        release_group_mbid="",
        issues=[MetadataIssue.MISSING_MBID, MetadataIssue.INCOMPLETE_TAGS],
        details={"scan_error": reason},
    )
    match = locator.find(folder.path, key)
    if match is None:
        finding.issues.append(MetadataIssue.NOT_IN_JELLYFIN)
    else:
        finding.jellyfin_id = match.jellyfin_id
    return finding


def _flag_duplicates(findings: list[Finding]) -> None:
    by_key: dict[str, list[Finding]] = {}
    for finding in findings:
        if finding.fuzzy_key.strip("|"):
            by_key.setdefault(finding.fuzzy_key, []).append(finding)

    for group in by_key.values():
        if len(group) < 2:
            continue
        for finding in group:
            finding.issues.append(MetadataIssue.DUPLICATE)
            finding.details["duplicate_of"] = [
                other.path for other in group if other.path != finding.path
            ]


def _scan_disk(
    root: Path,
    *,
    min_tracks: int,
    max_albums: int,
    locator: LibraryLocator,
    report: WalkReport,
) -> list[Finding]:
    folders = collect_folders(
        root, min_tracks=min_tracks, max_albums=max_albums, report=report
    )
    findings: list[Finding] = []
    for folder in folders:
        try:
            findings.append(_examine(folder, locator))
        except Exception as exc:  # noqa: BLE001 - one broken folder must not lose the scan
            reason = f"{type(exc).__name__}: {exc}"[:300]
            report.failed += 1
            if len(report.failures) < FAILURE_SAMPLES:
                report.failures.append({"path": str(folder.path), "error": reason})
            logger.exception("Metadata analysis failed on %s", folder.path)
            try:
                findings.append(_from_path_only(folder, locator, reason))
            except Exception:  # noqa: BLE001
                logger.exception("Cannot even list %s", folder.path)
    _flag_duplicates(findings)
    return findings


def _empty_scan_reason(root: Path, min_tracks: int, report: WalkReport) -> str:
    """Turn an empty walk into something an administrator can act on."""
    if report.directories <= 1 and not report.audio_files:
        return (
            f'nothing readable under "{root}": the folder is empty for Muzikk. Check that '
            "the volume is mounted and that PUID/PGID can read it."
        )
    if not report.audio_files:
        return (
            f'no audio file found under "{root}" after visiting {report.directories} folders. '
            "Check that the library folder of the Naming section really points at the music."
        )
    if report.below_min_tracks:
        return (
            f"{report.grouped} folder(s) found under \"{root}\" but all of them hold fewer than "
            f"{min_tracks} tracks. Lower the minimum in the Metadata section to include them."
        )
    return (
        f'{report.audio_files} audio file(s) seen under "{root}" but no album could be built '
        "from them. The muzikk.log file holds the details."
    )


# Where the last walk is remembered. Not a settings section: it is written by
# the worker and only read back to explain the numbers on screen.
SCAN_REPORT_KEY = "metadata_scan_report"


def read_scan_report(session: Session) -> dict[str, Any]:
    row = session.get(AppSetting, SCAN_REPORT_KEY)
    return dict(row.data or {}) if row else {}


def _write_scan_report(session: Session, payload: dict[str, Any]) -> None:
    row = session.get(AppSetting, SCAN_REPORT_KEY)
    if row is None:
        session.add(AppSetting(section=SCAN_REPORT_KEY, data=payload))
    else:
        row.data = payload
    session.commit()


async def scan_library(session: Session) -> dict[str, int]:
    """Walk the library and refresh the list of albums needing attention."""
    naming = settings_service.load(session, "naming")
    config = settings_service.load(session, "metadata")

    root = Path(naming.music_dir)
    if not root.is_dir():
        raise MetadataError(
            f'the library folder "{root}" is not visible from Muzikk: check the volume mount'
        )

    started = utcnow()
    locator = LibraryLocator(session)
    report = WalkReport()
    findings = await asyncio.to_thread(
        _scan_disk,
        root,
        min_tracks=config.min_tracks_per_album,
        max_albums=config.max_albums_per_scan,
        locator=locator,
        report=report,
    )
    if mode_service.is_local(session):
        # The local scanner is the index: "not in Jellyfin" has no meaning.
        for finding in findings:
            finding.issues = [
                issue for issue in finding.issues if issue != MetadataIssue.NOT_IN_JELLYFIN
            ]
    logger.info(
        "Metadata walk of %s: %s directories, %s audio files, %s album folders",
        root,
        report.directories,
        report.audio_files,
        report.grouped,
    )
    if report.failed or report.unreadable:
        logger.warning(
            "Metadata scan skipped %s unreadable folder(s) and failed on %s album(s)",
            report.unreadable,
            report.failed,
        )

    summary = {
        "root": str(root),
        "started_at": started.isoformat(),
        "finished_at": utcnow().isoformat(),
        "min_tracks": config.min_tracks_per_album,
        "directories": report.directories,
        "audio_files": report.audio_files,
        "folders": report.grouped,
        "analysed": len(findings),
        "below_min_tracks": report.below_min_tracks,
        "unreadable": report.unreadable,
        "failed": report.failed,
        "failures": report.failures,
    }
    _write_scan_report(session, summary)

    # An empty result is always a configuration problem, and the job row is the
    # only place the interface can read an explanation from.
    if not findings:
        raise MetadataError(_empty_scan_reason(root, config.min_tracks_per_album, report))

    existing = {row.path: row for row in session.execute(select(MetadataAlbum)).scalars()}
    seen: set[str] = set()
    created = 0
    now = utcnow()

    for finding in findings:
        seen.add(finding.path)
        row = existing.get(finding.path)
        if row is None:
            row = MetadataAlbum(path=finding.path)
            session.add(row)
            created += 1

        row.jellyfin_id = finding.jellyfin_id
        row.album_artist = finding.album_artist[:500]
        row.album_title = finding.album_title[:500]
        row.year = finding.year
        row.track_count = finding.track_count
        row.formats = finding.formats
        row.fuzzy_key = finding.fuzzy_key[:600]
        row.has_cover = finding.has_cover
        row.release_mbid = finding.release_mbid or None
        row.release_group_mbid = finding.release_group_mbid or None
        row.issues = finding.issues
        row.tracks = finding.tracks
        row.details = finding.details
        row.scanned_at = now
        # A folder that came back with problems is worth reviewing again, but a
        # folder an administrator chose to ignore stays ignored.
        if row.state == MetadataState.RESOLVED and finding.issues:
            row.state = MetadataState.OPEN
        elif not finding.issues and row.state == MetadataState.OPEN:
            row.state = MetadataState.RESOLVED
            row.resolved_at = now

    removed = 0
    for path, row in existing.items():
        if path not in seen:
            session.delete(row)
            removed += 1

    session.commit()

    counts = {kind: 0 for kind in MetadataIssue.ALL}
    for finding in findings:
        for kind in finding.issues:
            counts[kind] = counts.get(kind, 0) + 1

    return {
        "albums": len(findings),
        "created": created,
        "removed": removed,
        "folders": report.grouped,
        "skipped": report.below_min_tracks,
        "failed": report.failed,
        "unreadable": report.unreadable,
        "with_issues": sum(1 for item in findings if item.issues),
        **counts,
    }


# -------------------------------------------------------------- identification


@dataclass(slots=True)
class Proposal:
    release_group_mbid: str
    release_mbid: str
    artist: str
    title: str
    year: int | None
    track_count: int
    score: float
    source: str
    details: dict[str, Any] = field(default_factory=dict)


def _score_candidate(
    row: MetadataAlbum, artist: str, title: str, track_count: int | None
) -> float:
    """How well a MusicBrainz candidate matches what is on disk."""
    title_score = fuzz.token_set_ratio(normalize_title(row.album_title), normalize_title(title))
    artist_score = fuzz.token_set_ratio(
        normalize_artist(row.album_artist), normalize_artist(artist)
    )
    # An album with no artist tag can only be judged on its title.
    score = title_score * 0.6 + artist_score * 0.4 if row.album_artist else title_score

    if track_count and row.track_count:
        difference = abs(track_count - row.track_count)
        if difference == 0:
            score += 8
        elif difference <= 2:
            score += 2
        else:
            score -= min(20, difference * 3)
    return round(max(0.0, min(100.0, score)), 1)


async def _release_for_group(
    client: MusicBrainzClient, group_mbid: str, wanted_tracks: int
) -> tuple[dict[str, Any] | None, int]:
    """Pick the edition of a release group that fits the folder.

    Track count is the strongest signal available, so an edition matching it
    beats the one the acquisition pipeline would otherwise prefer.
    """
    payload = await client.browse_releases_for_group(group_mbid)
    releases = (payload or {}).get("releases") or []
    if not releases:
        return None, 0

    best, candidates = pick_release(releases)
    if wanted_tracks:
        exact = [item for item in candidates if item.track_count == wanted_tracks]
        if exact:
            best = exact[0]
    if best is None:
        return None, 0
    return best.raw, best.track_count


async def propose_from_text(
    session: Session, row: MetadataAlbum, *, limit: int = MATCH_SEARCH_LIMIT
) -> list[Proposal]:
    """Search MusicBrainz with whatever the folder already knows about itself."""
    client = MusicBrainzClient(settings_service.load(session, "musicbrainz"))
    if not client.configured:
        raise MetadataError("MusicBrainz is not configured")

    query = " ".join(part for part in (row.album_artist, row.album_title) if part).strip()
    if not query:
        raise MetadataError("this folder carries neither an artist nor an album name")

    payload = await client.search_release_groups(query, limit=limit)
    groups = (payload or {}).get("release-groups") or []

    proposals: list[Proposal] = []
    for group in groups:
        credits = group.get("artist-credit") or []
        artist = (credits[0].get("name") if credits else "") or ""
        title = group.get("title") or ""
        date = group.get("first-release-date") or ""
        proposals.append(
            Proposal(
                release_group_mbid=group.get("id") or "",
                release_mbid="",
                artist=artist,
                title=title,
                year=int(date[:4]) if date[:4].isdigit() else None,
                track_count=0,
                score=_score_candidate(row, artist, title, None),
                source="musicbrainz",
                details={"primary_type": group.get("primary-type")},
            )
        )

    proposals.sort(key=lambda item: -item.score)
    return proposals[:limit]


async def propose_from_acoustid(session: Session, row: MetadataAlbum) -> list[Proposal]:
    """Identify the album by listening to it rather than by reading its tags."""
    from . import acoustid

    config = settings_service.load(session, "metadata")
    if not config.acoustid_enabled:
        raise MetadataError("fingerprinting is disabled in the metadata settings")
    if not config.acoustid_api_key:
        raise MetadataError("no AcoustID API key configured")

    files = [
        Path(entry["path"])
        for entry in row.tracks
        if isinstance(entry, dict) and entry.get("path")
    ]
    if not files:
        files = sorted(
            item
            for item in Path(row.path).rglob("*")
            if item.is_file() and extension_of(item.name) in AUDIO_EXTENSIONS
        )
    if not files:
        raise MetadataError(f"no audio file left in {row.path}")

    try:
        votes = await acoustid.identify(
            files, config.acoustid_api_key, sample=config.acoustid_sample_tracks
        )
    except acoustid.AcoustidError as exc:
        raise MetadataError(str(exc)) from exc

    proposals: list[Proposal] = []
    for vote in votes[:MATCH_SEARCH_LIMIT]:
        # Agreement across the sampled tracks matters more than the raw score.
        confidence = min(100.0, 60.0 + vote.votes * 12 + vote.best_score * 20)
        proposals.append(
            Proposal(
                release_group_mbid=vote.release_group_mbid,
                release_mbid="",
                artist=vote.artist,
                title=vote.title,
                year=None,
                track_count=0,
                score=round(confidence, 1),
                source="acoustid",
                details={"votes": vote.votes, "fingerprint_score": round(vote.best_score, 3)},
            )
        )
    return proposals


async def resolve_release(
    session: Session, row: MetadataAlbum, *, release_group_mbid: str, release_mbid: str = ""
) -> Proposal:
    """Turn a chosen release group into a concrete edition to write."""
    client = MusicBrainzClient(settings_service.load(session, "musicbrainz"))
    if not client.configured:
        raise MetadataError("MusicBrainz is not configured")

    if release_mbid:
        release = await client.get_release(release_mbid)
        group = (release or {}).get("release-group") or {}
        group_mbid = group.get("id") or release_group_mbid
        track_count = sum(
            medium.get("track-count") or len(medium.get("tracks") or [])
            for medium in (release.get("media") or [])
        )
    else:
        group_mbid = release_group_mbid
        release, track_count = await _release_for_group(client, group_mbid, row.track_count)
        if release is None:
            raise MetadataError("this release group has no usable edition in MusicBrainz")
        release = await client.get_release(release["id"])

    album = album_metadata_from_release(release, group_mbid)
    return Proposal(
        release_group_mbid=group_mbid,
        release_mbid=release.get("id") or "",
        artist=album.albumartist,
        title=album.album,
        year=int(album.date[:4]) if album.date[:4].isdigit() else None,
        track_count=track_count or album.total_tracks,
        score=_score_candidate(row, album.albumartist, album.album, track_count),
        source="musicbrainz",
        details={"release_title": release.get("title"), "country": release.get("country")},
    )


def store_proposal(session: Session, row: MetadataAlbum, proposal: Proposal) -> MetadataAlbum:
    row.match_release_group_mbid = proposal.release_group_mbid or None
    row.match_release_mbid = proposal.release_mbid or None
    row.match_artist = proposal.artist[:500]
    row.match_title = proposal.title[:500]
    row.match_year = proposal.year
    row.match_track_count = proposal.track_count or None
    row.match_score = proposal.score
    row.match_source = proposal.source
    row.match_details = proposal.details
    session.commit()
    return row


# ------------------------------------------------------------- plan and apply


@dataclass(slots=True)
class FileChange:
    name: str
    path: str
    before: dict[str, Any]
    after: dict[str, Any]
    changed: list[str] = field(default_factory=list)
    # Values the file holds twice, so the before column can show them as they
    # are: ``before`` only ever carries the first one.
    repeated: dict[str, list[str]] = field(default_factory=dict)


@dataclass(slots=True)
class Plan:
    """What writing the chosen release would change, file by file."""

    release_mbid: str
    release_group_mbid: str
    artist: str
    album: str
    year: int | None
    track_count: int
    files: list[FileChange] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cover_source: str = ""
    unmatched: list[str] = field(default_factory=list)


COMPARED_FIELDS = (
    "title",
    "artist",
    "album",
    "albumartist",
    "date",
    "track",
    "disc",
    "genres",
    "release_mbid",
    "release_group_mbid",
    "recording_mbid",
)


def _audio_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise MetadataError(f'the folder "{directory}" is no longer readable')
    files = sorted(
        item
        for item in directory.rglob("*")
        if item.is_file() and extension_of(item.name) in AUDIO_EXTENSIONS
    )
    if not files:
        raise MetadataError(f'no audio file left in "{directory}"')
    return files


def _prepare(row: MetadataAlbum, release: dict[str, Any], group_mbid: str):
    """Pair the files on disk with the MusicBrainz track list.

    Shared by the simulation and by the write, so what an administrator
    validates is exactly what gets written.
    """
    files = _audio_files(Path(row.path))
    album = album_metadata_from_release(release, group_mbid)
    tracks = tracks_from_release(release)
    if not tracks:
        raise MetadataError("the MusicBrainz release has no track list")

    pairs, warnings = map_files_to_tracks(files, tracks)
    if not pairs:
        raise MetadataError("unable to pair the files with the MusicBrainz track list")
    return files, album, tracks, pairs, warnings


def _build_plan(row: MetadataAlbum, release: dict[str, Any], group_mbid: str) -> Plan:
    files, album, tracks, pairs, warnings = _prepare(row, release, group_mbid)

    plan = Plan(
        release_mbid=album.release_mbid,
        release_group_mbid=album.release_group_mbid,
        artist=album.albumartist,
        album=album.album,
        year=int(album.date[:4]) if album.date[:4].isdigit() else None,
        track_count=album.total_tracks or len(tracks),
        warnings=warnings,
    )

    matched = {path for path, _ in pairs}
    plan.unmatched = [path.name for path in files if path not in matched]

    for path, track in pairs:
        current = tags_service.read_file(path)
        target = build_track_metadata(album, track, total_tracks=len(tracks))
        after = {
            "title": target.title,
            "artist": target.artist,
            "album": target.album,
            "albumartist": target.albumartist,
            "date": target.date,
            "track": target.track,
            "disc": target.disc,
            "genres": target.genres,
            "release_mbid": target.release_mbid,
            "release_group_mbid": target.release_group_mbid,
            "recording_mbid": target.recording_mbid,
        }
        before = current.as_dict()
        # A value written twice counts as a change even when its text already
        # matches: the rewrite deletes the tags first, so the repeat goes away.
        changed = [
            field_name
            for field_name in COMPARED_FIELDS
            if before.get(field_name) != after.get(field_name) or field_name in current.repeated
        ]
        plan.files.append(
            FileChange(
                name=path.name,
                path=str(path),
                before=before,
                after=after,
                changed=changed,
                repeated=current.repeated,
            )
        )
    return plan


async def build_plan(session: Session, row: MetadataAlbum) -> Plan:
    """Compute the before/after view, without touching a single file."""
    group_mbid = row.match_release_group_mbid or row.release_group_mbid
    release_mbid = row.match_release_mbid or row.release_mbid
    if not (group_mbid or release_mbid):
        raise MetadataError("choose a MusicBrainz release first")

    client = MusicBrainzClient(settings_service.load(session, "musicbrainz"))
    if not client.configured:
        raise MetadataError("MusicBrainz is not configured")

    if not release_mbid:
        release, _ = await _release_for_group(client, group_mbid, row.track_count)
        if release is None:
            raise MetadataError("this release group has no usable edition in MusicBrainz")
        release_mbid = release["id"]

    release = await client.get_release(release_mbid)
    plan = await asyncio.to_thread(
        _build_plan, row, release, group_mbid or (release.get("release-group") or {}).get("id", "")
    )

    coverart_settings = settings_service.load(session, "coverart")
    config = settings_service.load(session, "metadata")
    if config.embed_cover or config.write_folder_cover or config.write_folder_jpg:
        cover = await CoverArtClient(coverart_settings).get_front_with_fallback(
            plan.release_mbid, plan.release_group_mbid
        )
        plan.cover_source = "coverartarchive" if cover else ""
    return plan


@dataclass(slots=True)
class ApplyResult:
    written: int = 0
    cover_written: bool = False
    warnings: list[str] = field(default_factory=list)


def _apply_plan(
    row: MetadataAlbum,
    release: dict[str, Any],
    group_mbid: str,
    cover: bytes | None,
    *,
    embed: bool,
    folder_cover: bool,
    folder_jpg: bool,
) -> ApplyResult:
    """Write the full Picard style tag set on every paired file."""
    _, album, tracks, pairs, _ = _prepare(row, release, group_mbid)

    result = ApplyResult()
    directories: set[Path] = set()

    for path, track in pairs:
        metadata = build_track_metadata(album, track, total_tracks=len(tracks))
        try:
            write_tags(path, metadata, cover if embed else None)
            result.written += 1
            directories.add(path.parent)
        except TaggingError as exc:
            result.warnings.append(str(exc))
        except Exception as exc:  # noqa: BLE001 - mutagen raises many unrelated types
            result.warnings.append(f"{path.name}: {exc}")

    if cover:
        # Players do not agree on the name: Plex reads cover.jpg, others folder.jpg.
        names = [
            name
            for name, wanted in (("cover.jpg", folder_cover), ("folder.jpg", folder_jpg))
            if wanted
        ]
        for directory in directories:
            for name in names:
                try:
                    (directory / name).write_bytes(cover)
                    result.cover_written = True
                except OSError as exc:
                    result.warnings.append(f"unable to write {name}: {exc}")
    return result


async def apply_plan(session: Session, row: MetadataAlbum) -> ApplyResult:
    """Write the chosen MusicBrainz release into the files of one album."""
    group_mbid = row.match_release_group_mbid or row.release_group_mbid or ""
    release_mbid = row.match_release_mbid or row.release_mbid or ""

    client = MusicBrainzClient(settings_service.load(session, "musicbrainz"))
    if not client.configured:
        raise MetadataError("MusicBrainz is not configured")
    if not (group_mbid or release_mbid):
        raise MetadataError("choose a MusicBrainz release first")

    if not release_mbid:
        picked, _ = await _release_for_group(client, group_mbid, row.track_count)
        if picked is None:
            raise MetadataError("this release group has no usable edition in MusicBrainz")
        release_mbid = picked["id"]

    release = await client.get_release(release_mbid)
    group_mbid = group_mbid or (release.get("release-group") or {}).get("id") or ""

    config = settings_service.load(session, "metadata")
    cover = None
    if config.embed_cover or config.write_folder_cover or config.write_folder_jpg:
        cover = await CoverArtClient(
            settings_service.load(session, "coverart")
        ).get_front_with_fallback(release_mbid, group_mbid)

    result = await asyncio.to_thread(
        _apply_plan,
        row,
        release,
        group_mbid,
        cover,
        embed=config.embed_cover,
        folder_cover=config.write_folder_cover,
        folder_jpg=config.write_folder_jpg,
    )

    if result.written:
        row.release_mbid = release_mbid
        row.release_group_mbid = group_mbid or None
        row.match_release_mbid = release_mbid
        row.match_release_group_mbid = group_mbid or None
        row.state = MetadataState.RESOLVED
        row.resolved_at = utcnow()
        row.note = ""
        remaining = [
            issue
            for issue in (row.issues or [])
            if issue not in (MetadataIssue.MISSING_MBID, MetadataIssue.PROBABLE_MATCH)
        ]
        if result.cover_written or cover:
            remaining = [item for item in remaining if item != MetadataIssue.MISSING_COVER]
            row.has_cover = True
        # Every tag was deleted then written again from MusicBrainz, so a value
        # that used to be there twice is now there once.
        row.issues = [
            item
            for item in remaining
            if item not in (MetadataIssue.INCOMPLETE_TAGS, MetadataIssue.DUPLICATE_TAGS)
        ]
        details = dict(row.details or {})
        if details.pop("duplicated_tags", None) is not None:
            row.details = details
        session.commit()
    return result
