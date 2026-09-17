"""Drop an album folder onto the home page and land it in the library.

The browser cannot hand a Windows path to the container, so the files are
uploaded into a short-lived staging directory, identified (MusicBrainz list,
pasted MBID, or a manual form), then named and tagged the same way a download
would be.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import shutil
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..config import get_env_config
from ..jobs import queue
from ..matching.normalize import (
    AUDIO_EXTENSIONS,
    IMAGE_EXTENSIONS,
    extension_of,
    is_lossless_file,
)
from ..models import MetadataAlbum, utcnow
from ..pipeline.importer import (
    album_metadata_from_release,
    build_track_metadata,
    map_files_to_tracks,
    place_file,
    remove_replaced,
    tracks_from_release,
)
from ..pipeline.namer import TrackContext, render_relative_path
from ..pipeline.tagger import TrackMetadata, write_tags
from . import artwork, localmedia
from . import metadata as metadata_service
from . import settings as settings_service
from . import tags as tags_service
from .coverart import CoverArtClient
from .library_index import OwnershipIndex
from .musicbrainz import MusicBrainzClient

logger = logging.getLogger(__name__)

MBID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)

SESSION_TTL = timedelta(hours=24)
MAX_FILES = 200
MAX_FILE_BYTES = 250 * 1024 * 1024
ALLOWED_EXTENSIONS = AUDIO_EXTENSIONS | IMAGE_EXTENSIONS
COVER_NAME = "cover.jpg"

STATUS_UPLOADED = "uploaded"
STATUS_IDENTIFIED = "identified"
STATUS_COMMITTED = "committed"

MODE_MUSICBRAINZ = "musicbrainz"
MODE_MANUAL = "manual"


class LocalImportError(RuntimeError):
    def __init__(self, message: str, *, code: str = "error") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class ImportState:
    id: str
    user_id: int
    created_at: str
    status: str = STATUS_UPLOADED
    artist: str = ""
    album: str = ""
    year: str = ""
    mode: str = ""
    release_mbid: str = ""
    release_group_mbid: str = ""
    has_cover: bool = False
    is_lossless: bool = False
    tracks: list[dict[str, Any]] = field(default_factory=list)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    ownership: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    destination: str | None = None
    files: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------------ filesystem


def _root() -> Path:
    path = get_env_config().config_dir / "local-import"
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_dir(user_id: int, session_id: str) -> Path:
    return _root() / str(user_id) / session_id


def files_dir(user_id: int, session_id: str) -> Path:
    return session_dir(user_id, session_id) / "files"


def _state_path(directory: Path) -> Path:
    return directory / "state.json"


def _cover_path(directory: Path) -> Path:
    return directory / COVER_NAME


def load_session(user_id: int, session_id: str) -> ImportState:
    directory = session_dir(user_id, session_id)
    path = _state_path(directory)
    if not path.is_file():
        raise LocalImportError("this import session is gone", code="not_found")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalImportError("this import session is unreadable", code="not_found") from exc
    return ImportState(**payload)


def _save_state(state: ImportState) -> ImportState:
    directory = session_dir(state.user_id, state.id)
    directory.mkdir(parents=True, exist_ok=True)
    path = _state_path(directory)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return state


def prune_expired() -> None:
    """Drop staging folders that nobody came back to."""
    root = _root()
    cutoff = utcnow() - SESSION_TTL
    for state_file in root.glob("*/*/state.json"):
        try:
            payload = json.loads(state_file.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(payload.get("created_at") or "")
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=cutoff.tzinfo)
        if created > cutoff:
            continue
        shutil.rmtree(state_file.parent, ignore_errors=True)


def safe_relative(raw: str) -> Path:
    """A relative path the container is willing to write under the staging dir."""
    cleaned = (raw or "").replace("\\", "/").strip().lstrip("/")
    if not cleaned:
        raise LocalImportError("a relative path is required for each file", code="path_invalid")
    path = Path(cleaned)
    if path.is_absolute() or ".." in path.parts:
        raise LocalImportError("refusing a path that leaves the staging folder", code="path_invalid")
    suffix = extension_of(path.name)
    if suffix not in ALLOWED_EXTENSIONS:
        raise LocalImportError(f"unsupported file type: {path.name}", code="path_invalid")
    return path


def create_session(user_id: int) -> ImportState:
    prune_expired()
    state = ImportState(
        id=secrets.token_urlsafe(12),
        user_id=user_id,
        created_at=utcnow().isoformat(),
    )
    files_dir(user_id, state.id).mkdir(parents=True, exist_ok=True)
    return _save_state(state)


def delete_session(user_id: int, session_id: str) -> None:
    directory = session_dir(user_id, session_id)
    if directory.is_dir():
        shutil.rmtree(directory, ignore_errors=True)


def add_file(user_id: int, session_id: str, relative: str, data: bytes) -> None:
    state = load_session(user_id, session_id)
    if state.status == STATUS_COMMITTED:
        raise LocalImportError("this import has already been written", code="committed")
    if len(data) > MAX_FILE_BYTES:
        raise LocalImportError("a file is larger than 250 MB", code="too_large")

    dest = files_dir(user_id, session_id) / safe_relative(relative)
    existing = [
        item
        for item in files_dir(user_id, session_id).rglob("*")
        if item.is_file()
    ]
    if dest not in existing and len(existing) >= MAX_FILES:
        raise LocalImportError(f"at most {MAX_FILES} files per album", code="too_many")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def _audio_files(user_id: int, session_id: str) -> list[Path]:
    root = files_dir(user_id, session_id)
    if not root.is_dir():
        return []
    return sorted(
        item
        for item in root.rglob("*")
        if item.is_file() and extension_of(item.name) in AUDIO_EXTENSIONS
    )


def _relative_to_staging(user_id: int, session_id: str, path: Path) -> str:
    root = files_dir(user_id, session_id)
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _most_common(values: list[str]) -> str:
    cleaned = [item.strip() for item in values if item and item.strip()]
    if not cleaned:
        return ""
    return Counter(cleaned).most_common(1)[0][0]


def _store_cover(directory: Path, data: bytes | None) -> bool:
    if not data:
        return False
    jpeg = artwork.to_jpeg(data, 1200)
    try:
        _cover_path(directory).write_bytes(jpeg)
    except OSError as exc:
        logger.warning("Unable to store the staged cover: %s", exc)
        return False
    return True


def read_cover(user_id: int, session_id: str) -> bytes | None:
    path = _cover_path(session_dir(user_id, session_id))
    if not path.is_file():
        return None
    return path.read_bytes() or None


def set_cover(user_id: int, session_id: str, data: bytes) -> ImportState:
    state = load_session(user_id, session_id)
    if state.status == STATUS_COMMITTED:
        raise LocalImportError("this import has already been written", code="committed")
    if not _store_cover(session_dir(user_id, session_id), data):
        raise LocalImportError("this image could not be read as a cover", code="missing_cover")
    state.has_cover = True
    return _save_state(state)


# ---------------------------------------------------------------- identification


def _hint(state: ImportState) -> MetadataAlbum:
    year = int(state.year[:4]) if state.year[:4].isdigit() else None
    return MetadataAlbum(
        path=str(files_dir(state.user_id, state.id)),
        album_artist=state.artist,
        album_title=state.album,
        year=year,
        track_count=len(state.tracks),
    )


def _proposal_payload(proposal: metadata_service.Proposal) -> dict[str, Any]:
    cover = (
        f"/api/images/cover/release-group/{proposal.release_group_mbid}"
        if proposal.release_group_mbid
        else None
    )
    if proposal.release_mbid:
        cover = f"/api/images/cover/release/{proposal.release_mbid}"
    return {
        "release_group_mbid": proposal.release_group_mbid,
        "release_mbid": proposal.release_mbid,
        "artist": proposal.artist,
        "title": proposal.title,
        "year": proposal.year,
        "track_count": proposal.track_count,
        "score": proposal.score,
        "source": proposal.source,
        "details": proposal.details,
        "cover_url": cover,
    }


def assess_ownership(
    session: Session,
    *,
    artist: str,
    album: str,
    release_mbid: str = "",
    release_group_mbid: str = "",
    incoming_lossless: bool,
) -> dict[str, Any] | None:
    match = OwnershipIndex(session).lookup(
        release_group_mbid=release_group_mbid or None,
        release_mbids=[release_mbid] if release_mbid else None,
        artist=artist,
        album=album,
    )
    if match is None:
        return None

    better = incoming_lossless and not match.is_lossless
    if better:
        reason = "upgrade"
        blocked = False
    elif match.is_lossless:
        reason = "already_lossless"
        blocked = True
    else:
        reason = "already_owned"
        blocked = True

    return {
        "status": match.status,
        "upgradable": better,
        "blocked": blocked,
        "reason": reason,
        "path": match.path,
        "is_lossless": match.is_lossless,
        "formats": match.formats,
        "jellyfin_id": match.jellyfin_id,
    }


def _refresh_ownership(session: Session, state: ImportState) -> ImportState:
    state.ownership = assess_ownership(
        session,
        artist=state.artist,
        album=state.album,
        release_mbid=state.release_mbid,
        release_group_mbid=state.release_group_mbid,
        incoming_lossless=state.is_lossless,
    )
    return state


async def _search_proposals(
    session: Session, state: ImportState, query: str = ""
) -> list[dict[str, Any]]:
    hint = _hint(state)
    if query.strip():
        # The search box is a single MusicBrainz query, not two separate fields.
        hint.album_artist = ""
        hint.album_title = query.strip()

    try:
        proposals = await metadata_service.propose_from_text(session, hint)
    except metadata_service.MetadataError as exc:
        logger.info("MusicBrainz search skipped: %s", exc)
        return []
    return [_proposal_payload(item) for item in proposals]


def analyze(session: Session, user_id: int, session_id: str) -> ImportState:
    state = load_session(user_id, session_id)
    if state.status == STATUS_COMMITTED:
        return state

    audio = _audio_files(user_id, session_id)
    if not audio:
        raise LocalImportError("no audio file in this folder", code="no_audio")

    directory = session_dir(user_id, session_id)
    tags = [tags_service.read_file(path) for path in audio]
    state.tracks = [
        {
            "name": path.name,
            "relative": _relative_to_staging(user_id, session_id, path),
            "title": info.title,
            "artist": info.artist or info.albumartist,
            "album": info.album,
            "track": info.track,
            "disc": info.disc,
            "extension": info.extension or extension_of(path.name),
        }
        for path, info in zip(audio, tags, strict=False)
    ]
    state.artist = _most_common([info.albumartist or info.artist for info in tags])
    state.album = _most_common([info.album for info in tags])
    years = [info.date[:4] for info in tags if info.date[:4].isdigit()]
    state.year = _most_common(years)
    state.is_lossless = bool(audio) and all(is_lossless_file(path.name) for path in audio)
    state.warnings = []
    state.mode = ""
    state.release_mbid = _most_common([info.release_mbid for info in tags])
    state.release_group_mbid = _most_common([info.release_group_mbid for info in tags])

    if not state.has_cover:
        state.has_cover = _store_cover(directory, artwork.from_disk(str(files_dir(user_id, session_id))))

    state.status = STATUS_UPLOADED
    _refresh_ownership(session, state)
    return _save_state(state)


async def search(session: Session, user_id: int, session_id: str, query: str = "") -> ImportState:
    state = analyze(session, user_id, session_id)
    state.proposals = await _search_proposals(session, state, query)
    if not state.proposals:
        state.warnings = [
            warning
            for warning in state.warnings
            if warning != "no MusicBrainz candidate matched these tags"
        ]
        state.warnings.append("no MusicBrainz candidate matched these tags")
    return _save_state(state)


def _read_reference(text: str) -> tuple[str, str, bool]:
    found = MBID_RE.search(text or "")
    if not found:
        raise LocalImportError("No MusicBrainz identifier found in this text", code="bad_mbid")
    mbid = found.group(0)
    if "/release-group/" in text:
        return mbid, "", False
    if "/release/" in text:
        return "", mbid, False
    return mbid, "", True


async def _resolve(
    session: Session, hint: MetadataAlbum, group_mbid: str, release_mbid: str
) -> metadata_service.Proposal:
    return await metadata_service.resolve_release(
        session, hint, release_group_mbid=group_mbid, release_mbid=release_mbid
    )


async def choose(
    session: Session,
    user_id: int,
    session_id: str,
    *,
    release_group_mbid: str = "",
    release_mbid: str = "",
    reference: str = "",
) -> ImportState:
    state = load_session(user_id, session_id)
    if state.status == STATUS_COMMITTED:
        raise LocalImportError("this import has already been written", code="committed")
    if not state.tracks:
        state = analyze(session, user_id, session_id)

    group = release_group_mbid.strip()
    release = release_mbid.strip()
    ambiguous = False
    if reference and not (group or release):
        group, release, ambiguous = _read_reference(reference)
    if not (group or release):
        raise LocalImportError("A release or release group is required", code="bad_mbid")

    hint = _hint(state)

    async def resolve(group_id: str, release_id: str) -> metadata_service.Proposal:
        return await _resolve(session, hint, group_id, release_id)

    try:
        try:
            proposal = await resolve(group, release)
        except metadata_service.MetadataError:
            if not ambiguous:
                raise
            proposal = await resolve("", group)
    except metadata_service.MetadataError as exc:
        raise LocalImportError(str(exc), code="musicbrainz_unresolved") from exc

    state.mode = MODE_MUSICBRAINZ
    state.release_mbid = proposal.release_mbid
    state.release_group_mbid = proposal.release_group_mbid
    state.artist = proposal.artist or state.artist
    state.album = proposal.title or state.album
    if proposal.year:
        state.year = str(proposal.year)
    state.status = STATUS_IDENTIFIED
    state.warnings = [item for item in state.warnings if "MusicBrainz" not in item]

    directory = session_dir(user_id, session_id)
    coverart = CoverArtClient(settings_service.load(session, "coverart"))
    remote = await coverart.get_front_with_fallback(proposal.release_mbid, proposal.release_group_mbid)
    if remote:
        state.has_cover = _store_cover(directory, remote)
    elif not state.has_cover:
        state.has_cover = _store_cover(directory, artwork.from_disk(str(files_dir(user_id, session_id))))

    _refresh_ownership(session, state)
    return _save_state(state)


def set_manual(
    session: Session,
    user_id: int,
    session_id: str,
    *,
    artist: str,
    album: str,
    year: str = "",
) -> ImportState:
    state = load_session(user_id, session_id)
    if state.status == STATUS_COMMITTED:
        raise LocalImportError("this import has already been written", code="committed")
    if not state.tracks:
        state = analyze(session, user_id, session_id)

    artist = artist.strip()
    album = album.strip()
    if not artist:
        raise LocalImportError("an artist name is required", code="missing_artist")
    if not album:
        raise LocalImportError("an album name is required", code="missing_album")
    if not state.has_cover:
        raise LocalImportError("an album cover is required", code="missing_cover")

    state.mode = MODE_MANUAL
    state.artist = artist
    state.album = album
    state.year = year.strip()[:4]
    state.release_mbid = ""
    state.release_group_mbid = ""
    state.status = STATUS_IDENTIFIED
    _refresh_ownership(session, state)
    return _save_state(state)


# -------------------------------------------------------------------- commit


def _place_mode() -> str:
    return "move"


def _write_folder_covers(directories: set[Path], cover: bytes, warnings: list[str]) -> None:
    for directory in directories:
        for name in ("cover.jpg", "folder.jpg"):
            try:
                (directory / name).write_bytes(cover)
            except OSError as exc:
                warnings.append(f"unable to write {name}: {exc}")


def _manual_pairs(files: list[Path], state: ImportState) -> list[tuple[Path, TrackMetadata]]:
    by_relative = {item["relative"]: item for item in state.tracks}
    numbered = []
    for index, path in enumerate(files, start=1):
        snapshot = by_relative.get(_relative_to_staging(state.user_id, state.id, path), {})
        track_no = snapshot.get("track") or index
        disc_no = snapshot.get("disc") or 1
        numbered.append((path, int(track_no or index), int(disc_no or 1), snapshot))
    numbered.sort(key=lambda item: (item[2], item[1], item[0].name.lower()))

    total = len(numbered)
    discs = {item[2] for item in numbered} or {1}
    pairs: list[tuple[Path, TrackMetadata]] = []
    for position, (path, track_no, disc_no, snapshot) in enumerate(numbered, start=1):
        title = str(snapshot.get("title") or "").strip() or path.stem
        artist = str(snapshot.get("artist") or "").strip() or state.artist
        pairs.append(
            (
                path,
                TrackMetadata(
                    title=title,
                    artist=artist,
                    artists=[artist] if artist else [],
                    album=state.album,
                    albumartist=state.artist,
                    date=state.year,
                    track=track_no or position,
                    total_tracks=total,
                    disc=disc_no,
                    total_discs=len(discs),
                ),
            )
        )
    return pairs


def _mb_pairs(
    files: list[Path], release: dict[str, Any], group_mbid: str
) -> tuple[list[tuple[Path, TrackMetadata]], list[str]]:
    album = album_metadata_from_release(release, group_mbid)
    tracks = tracks_from_release(release)
    if not tracks:
        raise LocalImportError("the MusicBrainz release has no track list", code="musicbrainz_unresolved")
    mapped, warnings = map_files_to_tracks(files, tracks)
    if not mapped:
        raise LocalImportError(
            "unable to pair the files with the MusicBrainz track list",
            code="musicbrainz_unresolved",
        )
    pairs = [
        (path, build_track_metadata(album, track, total_tracks=len(tracks)))
        for path, track in mapped
    ]
    return pairs, warnings


def _context_from_meta(meta: TrackMetadata, path: Path, *, is_multiartist: bool) -> TrackContext:
    return TrackContext(
        albumartist=meta.albumartist or meta.artist,
        album=meta.album,
        title=meta.title,
        artist=meta.artist,
        track=meta.track,
        totaltracks=meta.total_tracks,
        disc=meta.disc,
        totaldiscs=meta.total_discs,
        year=(meta.date or "")[:4],
        date=meta.date,
        genre=meta.genres[0] if meta.genres else "",
        label=meta.label,
        extension=path.suffix.lower().lstrip(".") or "flac",
        is_multiartist=is_multiartist,
    )


def _old_audio(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return [
        item
        for item in folder.rglob("*")
        if item.is_file() and extension_of(item.name) in AUDIO_EXTENSIONS
    ]


async def commit(
    session: Session,
    user_id: int,
    session_id: str,
    *,
    confirm_upgrade: bool = False,
) -> ImportState:
    state = load_session(user_id, session_id)
    if state.status == STATUS_COMMITTED:
        return state
    if state.status != STATUS_IDENTIFIED or not state.mode:
        raise LocalImportError("identify the album before writing it", code="not_identified")
    if not state.artist or not state.album:
        raise LocalImportError("an artist name and an album name are required", code="missing_artist")

    cover = read_cover(user_id, session_id)
    if not cover:
        raise LocalImportError("an album cover is required", code="missing_cover")

    files = _audio_files(user_id, session_id)
    if not files:
        raise LocalImportError("no audio file in this folder", code="no_audio")

    state.is_lossless = all(is_lossless_file(path.name) for path in files)
    _refresh_ownership(session, state)
    ownership = state.ownership
    if ownership and ownership.get("blocked"):
        raise LocalImportError(
            "this album is already in the library at the same or a better quality",
            code=str(ownership.get("reason") or "already_owned"),
        )
    if ownership and ownership.get("upgradable") and not confirm_upgrade:
        raise LocalImportError(
            "this album is already owned; confirm the upgrade to replace the lossy copy",
            code="upgrade_required",
        )

    naming = settings_service.load(session, "naming")
    coverart_settings = settings_service.load(session, "coverart")
    music_dir = Path(naming.music_dir)
    try:
        music_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise LocalImportError(f"the library folder {music_dir} is not writable: {exc}") from exc

    warnings = list(state.warnings)
    if state.mode == MODE_MUSICBRAINZ:
        client = MusicBrainzClient(settings_service.load(session, "musicbrainz"))
        if not client.configured:
            raise LocalImportError("MusicBrainz is not configured", code="musicbrainz_unresolved")
        if not state.release_mbid:
            raise LocalImportError("choose a MusicBrainz release first", code="bad_mbid")
        release = await client.get_release(state.release_mbid)
        pairs, pair_warnings = _mb_pairs(files, release, state.release_group_mbid)
        warnings.extend(pair_warnings)
    else:
        pairs = _manual_pairs(files, state)

    is_multiartist = any(
        meta.artist and meta.artist.strip().lower() != (meta.albumartist or state.artist).strip().lower()
        for _, meta in pairs
    )

    album_dirs: set[Path] = set()
    written: list[str] = []
    for path, meta in pairs:
        context = _context_from_meta(meta, path, is_multiartist=is_multiartist)
        try:
            relative = render_relative_path(context, naming)
        except ValueError as exc:
            raise LocalImportError(str(exc), code="naming") from exc
        destination = music_dir / Path(str(relative))
        try:
            place_file(path, destination, mode=_place_mode())
        except OSError as exc:
            raise LocalImportError(f"unable to write {destination}: {exc}") from exc
        try:
            write_tags(destination, meta, cover if coverart_settings.embed_in_files else None)
        except Exception as exc:  # noqa: BLE001 - keep the file, report the problem
            warnings.append(f"tagging failed for {destination.name}: {exc}")
        written.append(str(destination))
        album_dirs.add(destination.parent)

    _write_folder_covers(album_dirs, cover, warnings)

    if ownership and ownership.get("upgradable") and confirm_upgrade:
        remote = ownership.get("path")
        old_folder = localmedia.resolve_folder(remote, naming.music_dir)
        if old_folder is None and remote:
            warnings.append(f"could not find the previous copy at {remote}")
        elif old_folder is not None:
            kept = {path.resolve() for path in (Path(item) for item in written)}
            doomed = [path for path in _old_audio(old_folder) if path.resolve() not in kept]
            try:
                removed = remove_replaced(old_folder, doomed, album_dirs, music_dir)
                if removed:
                    warnings.append(f"replaced {len(removed)} previous file(s)")
            except OSError as exc:
                warnings.append(f"unable to remove the previous copy: {exc}")

    state.status = STATUS_COMMITTED
    state.destination = str(sorted(album_dirs)[0]) if album_dirs else None
    state.files = written
    state.warnings = warnings
    _save_state(state)

    queue.enqueue(session, queue.LIBRARY_SYNC)

    # Staging audio has been moved; drop the leftover images.
    staging = files_dir(user_id, session_id)
    if staging.is_dir():
        shutil.rmtree(staging, ignore_errors=True)
        files_dir(user_id, session_id).mkdir(parents=True, exist_ok=True)

    return state


def session_out(state: ImportState) -> dict[str, Any]:
    cover_url = (
        f"/api/local-import/sessions/{state.id}/cover" if state.has_cover else None
    )
    return {
        **state.as_dict(),
        "track_count": len(state.tracks),
        "cover_url": cover_url,
    }

