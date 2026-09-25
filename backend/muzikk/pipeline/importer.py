"""Import pipeline: place the downloaded files in the library and tag them.

Two placement strategies are used on purpose:

* Soulseek downloads are hardlinked (or moved) and tagged in place, because the
  source is deleted right after.
* Torrent downloads are copied, because tagging rewrites the file and a
  hardlink would change the very bytes the torrent is still seeding.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from ..matching.normalize import leading_track_number, normalize_title, strip_track_number
from ..services.settings import CoverArtSettings, NamingSettings
from ..services.tags import read_file
from . import cleanup
from .namer import TrackContext, render_relative_path
from .tagger import TrackMetadata, write_tags

logger = logging.getLogger(__name__)

VARIOUS_ARTISTS_MBID = "89ad4ac3-39f7-470e-963a-56509c546377"


@dataclass(slots=True)
class MbTrack:
    disc: int
    position: int
    title: str
    recording_mbid: str = ""
    release_track_mbid: str = ""
    artist: str = ""
    artist_mbid: str = ""
    length_ms: int | None = None
    isrc: str = ""


@dataclass(slots=True)
class AlbumMetadata:
    album: str
    albumartist: str
    albumartist_mbid: str = ""
    albumartist_sort: str = ""
    date: str = ""
    original_date: str = ""
    label: str = ""
    catalog_number: str = ""
    media: str = ""
    country: str = ""
    status: str = ""
    release_type: str = ""
    barcode: str = ""
    genres: list[str] = field(default_factory=list)
    release_mbid: str = ""
    release_group_mbid: str = ""
    total_discs: int = 1
    total_tracks: int = 0

    @property
    def is_compilation(self) -> bool:
        return self.albumartist_mbid == VARIOUS_ARTISTS_MBID or "compilation" in (
            self.release_type or ""
        ).lower()


@dataclass(slots=True)
class ImportRequest:
    source_path: Path
    release: dict[str, Any]
    release_group_mbid: str
    naming: NamingSettings
    coverart: CoverArtSettings
    cover: bytes | None = None
    keep_source: bool = False
    is_upgrade: bool = False
    replaces_path: str | None = None
    confirm_replace: bool = False
    # Set when one track was asked for rather than the record: the file is then
    # paired with that recording instead of being run through the tracklist,
    # which would otherwise tag it as track one of the album.
    only_recording_mbid: str | None = None


@dataclass(slots=True)
class ImportResult:
    ok: bool = False
    destination: str | None = None
    files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    error: str = ""
    # Both sides of an upgrade left undecided, for whoever has to compare them.
    review: dict[str, Any] | None = None


def _credit_name(credits: list[dict[str, Any]] | None) -> str:
    if not credits:
        return ""
    parts: list[str] = []
    for credit in credits:
        parts.append(credit.get("name") or (credit.get("artist") or {}).get("name") or "")
        parts.append(credit.get("joinphrase") or "")
    return "".join(parts).strip()


def _credit_mbid(credits: list[dict[str, Any]] | None) -> str:
    for credit in credits or []:
        artist = credit.get("artist") or {}
        if artist.get("id"):
            return artist["id"]
    return ""


def _credit_sort(credits: list[dict[str, Any]] | None) -> str:
    for credit in credits or []:
        artist = credit.get("artist") or {}
        if artist.get("sort-name"):
            return artist["sort-name"]
    return ""


def album_metadata_from_release(release: dict[str, Any], release_group_mbid: str) -> AlbumMetadata:
    group = release.get("release-group") or {}
    credits = release.get("artist-credit")
    label_info = release.get("label-info") or []
    label_name = ""
    catalog_number = ""
    for entry in label_info:
        label = entry.get("label") or {}
        label_name = label_name or (label.get("name") or "")
        catalog_number = catalog_number or (entry.get("catalog-number") or "")

    media = release.get("media") or []
    formats = [medium.get("format") for medium in media if medium.get("format")]
    total_tracks = sum(
        medium.get("track-count") or len(medium.get("tracks") or []) for medium in media
    )

    types = [group.get("primary-type")] + list(group.get("secondary-types") or [])
    release_type = "; ".join([item for item in types if item])

    genres = sorted(
        {
            (item.get("name") or "").strip()
            for item in (release.get("genres") or []) + (group.get("genres") or [])
            if item.get("name")
        }
    )

    return AlbumMetadata(
        album=release.get("title") or group.get("title") or "",
        albumartist=_credit_name(credits) or "Unknown Artist",
        albumartist_mbid=_credit_mbid(credits),
        albumartist_sort=_credit_sort(credits),
        date=release.get("date") or "",
        original_date=group.get("first-release-date") or "",
        label=label_name,
        catalog_number=catalog_number,
        media=formats[0] if formats else "",
        country=release.get("country") or "",
        status=release.get("status") or "",
        release_type=release_type,
        barcode=release.get("barcode") or "",
        genres=genres[:8],
        release_mbid=release.get("id") or "",
        release_group_mbid=group.get("id") or release_group_mbid,
        total_discs=max(1, len(media)),
        total_tracks=total_tracks,
    )


def tracks_from_release(release: dict[str, Any]) -> list[MbTrack]:
    tracks: list[MbTrack] = []
    for index, medium in enumerate(release.get("media") or [], start=1):
        disc = medium.get("position") or index
        for entry in medium.get("tracks") or []:
            recording = entry.get("recording") or {}
            credits = entry.get("artist-credit") or recording.get("artist-credit")
            length = entry.get("length") or recording.get("length")
            isrcs = recording.get("isrcs") or []
            tracks.append(
                MbTrack(
                    disc=disc,
                    position=entry.get("position") or len(tracks) + 1,
                    title=entry.get("title") or recording.get("title") or "",
                    recording_mbid=recording.get("id") or "",
                    release_track_mbid=entry.get("id") or "",
                    artist=_credit_name(credits),
                    artist_mbid=_credit_mbid(credits),
                    length_ms=int(length) if length else None,
                    isrc=isrcs[0] if isrcs else "",
                )
            )
    return tracks


def build_track_metadata(
    album: AlbumMetadata, track: MbTrack, *, total_tracks: int = 0
) -> TrackMetadata:
    """Merge album level and track level MusicBrainz data into a tag set.

    Shared by the import pipeline and by the metadata repair screen, so a
    retagged album ends up indistinguishable from a freshly imported one.
    """
    return TrackMetadata(
        title=track.title,
        artist=track.artist or album.albumartist,
        artists=[track.artist] if track.artist else [],
        album=album.album,
        albumartist=album.albumartist,
        albumartist_sort=album.albumartist_sort,
        date=album.date or album.original_date,
        original_date=album.original_date,
        track=track.position,
        total_tracks=album.total_tracks or total_tracks,
        disc=track.disc,
        total_discs=album.total_discs,
        genres=album.genres,
        label=album.label,
        catalog_number=album.catalog_number,
        media=album.media,
        release_country=album.country,
        release_status=album.status,
        release_type=album.release_type,
        barcode=album.barcode,
        isrc=track.isrc,
        is_compilation=album.is_compilation,
        release_mbid=album.release_mbid,
        release_group_mbid=album.release_group_mbid,
        recording_mbid=track.recording_mbid,
        release_track_mbid=track.release_track_mbid,
        artist_mbid=track.artist_mbid,
        albumartist_mbid=album.albumartist_mbid,
    )


def _existing_track_number(path: Path) -> int | None:
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(str(path))
    except Exception:  # noqa: BLE001
        return None
    if audio is None or not audio.tags:
        return None
    for key in ("tracknumber", "TRACKNUMBER", "TRCK", "trkn"):
        try:
            value = audio.tags.get(key)
        except (AttributeError, KeyError, TypeError, ValueError):
            value = None
        if not value:
            continue
        raw = value[0] if isinstance(value, list) else value
        if isinstance(raw, tuple):
            raw = raw[0]
        text = str(raw).split("/")[0].strip()
        if text.isdigit():
            return int(text)
    return None


def _order_files(files: list[Path], tracks: list[MbTrack]) -> tuple[list[Path], str]:
    """Order files so that position N in the list is track N of the disc."""
    if len(files) <= 1:
        return files, "single file"

    tagged = {path: _existing_track_number(path) for path in files}
    numbers = [value for value in tagged.values() if value]
    if len(numbers) == len(files) and len(set(numbers)) == len(files):
        return sorted(files, key=lambda path: tagged[path] or 0), "existing track numbers"

    from_names = {path: leading_track_number(path.name) for path in files}
    name_numbers = [value for value in from_names.values() if value]
    if len(name_numbers) == len(files) and len(set(name_numbers)) == len(files):
        return sorted(files, key=lambda path: from_names[path] or 0), "file name numbering"

    # Greedy title matching, best pairs first.
    scores: list[tuple[float, Path, int]] = []
    for path in files:
        stem = normalize_title(strip_track_number(path.name)) or normalize_title(path.stem)
        for index, track in enumerate(tracks):
            target = normalize_title(track.title)
            if not target or not stem:
                continue
            scores.append((fuzz.token_set_ratio(target, stem), path, index))

    if scores:
        scores.sort(reverse=True)
        assigned: dict[int, Path] = {}
        used: set[Path] = set()
        for score, path, index in scores:
            if score < 70 or path in used or index in assigned:
                continue
            assigned[index] = path
            used.add(path)
        if len(assigned) == len(files) == len(tracks):
            return [assigned[index] for index in sorted(assigned)], "title matching"

    return sorted(files, key=lambda path: path.name.lower()), "alphabetical order"


def map_files_to_tracks(
    files: list[Path], tracks: list[MbTrack]
) -> tuple[list[tuple[Path, MbTrack]], list[str]]:
    """Pair each audio file with the MusicBrainz track it represents."""
    warnings: list[str] = []
    if not files or not tracks:
        return [], ["nothing to map"]

    discs = sorted({track.disc for track in tracks})
    by_parent: dict[Path, list[Path]] = {}
    for path in files:
        by_parent.setdefault(path.parent, []).append(path)
    parents = sorted(by_parent, key=lambda path: str(path).lower())

    pairs: list[tuple[Path, MbTrack]] = []

    if len(discs) > 1 and len(parents) == len(discs):
        # One folder per disc.
        for parent, disc in zip(parents, discs, strict=False):
            disc_tracks = [track for track in tracks if track.disc == disc]
            disc_files, method = _order_files(sorted(by_parent[parent]), disc_tracks)
            warnings.append(f"disc {disc}: {method}")
            for path, track in zip(disc_files, disc_tracks, strict=False):
                pairs.append((path, track))
            if len(disc_files) != len(disc_tracks):
                warnings.append(
                    f"disc {disc}: {len(disc_files)} files for {len(disc_tracks)} tracks"
                )
        return pairs, warnings

    ordered, method = _order_files(files, tracks)
    warnings.append(f"mapping by {method}")
    if len(ordered) > len(tracks):
        warnings.append(f"{len(ordered) - len(tracks)} extra files ignored")
    for path, track in zip(ordered, tracks, strict=False):
        pairs.append((path, track))
    return pairs, warnings


def _place_file(source: Path, destination: Path, *, mode: str) -> str:
    """Put ``source`` at ``destination`` and report the strategy used."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()

    if mode == "hardlink":
        try:
            os.link(source, destination)
            return "hardlink"
        except OSError:
            shutil.copy2(source, destination)
            return "copy"
    if mode == "move":
        shutil.move(str(source), str(destination))
        return "move"
    shutil.copy2(source, destination)
    return "copy"


# The home-page folder import places files the same way.
place_file = _place_file


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def describe_files(files: list[Path]) -> list[dict[str, Any]]:
    """Each file as the upgrade comparison has to show it."""
    described: list[dict[str, Any]] = []
    for path in files:
        info = read_file(path)
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        described.append(
            {
                "path": str(path),
                "name": path.name,
                "format": info.extension or path.suffix.lower().lstrip("."),
                "title": info.title,
                "track": info.track,
                "duration": info.duration,
                "bitrate": info.bitrate,
                "bit_depth": info.bit_depth,
                "sample_rate": info.sample_rate,
                "size": size,
            }
        )
    described.sort(key=lambda item: (item["track"] or 0, str(item["name"]).lower()))
    return described


def _inside(path: Path, root: Path) -> bool:
    try:
        _resolved(path).relative_to(_resolved(root))
    except ValueError:
        return False
    return True


def shares_folder(old_path: Path, new_dirs: set[Path]) -> bool:
    """Whether an upgrade landed in the folder it improves."""
    resolved = _resolved(old_path)
    for directory in new_dirs:
        target = _resolved(directory)
        if target == resolved or resolved in target.parents or target in resolved.parents:
            return True
    return False


def _remove_files(paths: list[Path], music_dir: Path) -> list[str]:
    removed: list[str] = []
    for path in paths:
        if not _inside(path, music_dir):
            logger.warning("Refusing to delete %s: outside the library folder", path)
            continue
        try:
            if path.is_file():
                path.unlink()
                removed.append(str(path))
        except OSError as exc:
            logger.warning("Unable to delete %s: %s", path, exc)
    return removed


def remove_replaced(
    old_path: Path, doomed: list[Path], new_dirs: set[Path], music_dir: Path
) -> list[str]:
    """Delete the copy an upgrade replaces, whichever shape it takes.

    Two shapes happen. When the naming template sends the new files somewhere
    else, the old folder goes whole. But an upgrade normally lands in the very
    folder it improves, and there only the old audio files may go: the artwork
    and the tracks just written have to stay.
    """
    if not _inside(old_path, music_dir):
        logger.warning("Refusing to delete %s: outside the library folder", old_path)
        return []

    if old_path.is_dir() and not shares_folder(old_path, new_dirs):
        if not cleanup.remove_tree(old_path, guard=music_dir):
            return []
        cleanup.prune_empty_parents(old_path.parent, music_dir)
        return [str(old_path)]

    removed = _remove_files(doomed, music_dir)
    if removed and old_path.is_dir():
        cleanup.remove_empty_dirs(old_path)
        cleanup.prune_empty_parents(old_path, music_dir)
    return removed


def commit_upgrade(review: dict[str, Any], music_dir: Path) -> list[str]:
    """Delete what a validated upgrade replaces."""
    old_path = Path(str(review.get("old_path") or ""))
    if not old_path.name:
        return []
    doomed = [Path(str(item)) for item in review.get("remove") or []]
    new_dirs = {Path(str(item)) for item in review.get("new_dirs") or []}
    return remove_replaced(old_path, doomed, new_dirs, music_dir)


def revert_upgrade(review: dict[str, Any], music_dir: Path) -> list[str]:
    """Take back a refused upgrade and leave the older copy alone.

    The folder artwork was overwritten on import and cannot be brought back,
    but the tracks themselves are untouched: only the files we added go away.
    """
    removed: list[str] = []
    new_dirs = sorted({Path(str(item)) for item in review.get("new_dirs") or []})
    if review.get("same_folder"):
        paths = [Path(str(item.get("path") or "")) for item in review.get("new_files") or []]
        removed.extend(_remove_files([path for path in paths if path.name], music_dir))
    else:
        for directory in new_dirs:
            if directory.is_dir() and cleanup.remove_tree(directory, guard=music_dir):
                removed.append(str(directory))
    for directory in new_dirs:
        cleanup.prune_empty_parents(directory, music_dir)
    return removed


def _run_import(request: ImportRequest) -> ImportResult:
    result = ImportResult()
    source = request.source_path
    if not source.exists():
        result.error = f"the downloaded files are not readable at {source}"
        return result

    audio_files = cleanup.collect_audio_files(source)
    if not audio_files:
        result.error = f"no audio file found in {source}"
        return result

    album = album_metadata_from_release(request.release, request.release_group_mbid)
    tracks = tracks_from_release(request.release)
    if not tracks:
        result.error = "the MusicBrainz release has no track list"
        return result

    if request.only_recording_mbid:
        wanted = next(
            (track for track in tracks if track.recording_mbid == request.only_recording_mbid),
            None,
        )
        if wanted is None:
            result.error = "the requested track is not on this release"
            return result
        if len(audio_files) != 1:
            result.error = f"a track import expects one file, found {len(audio_files)}"
            return result
        # Paired by identifier, never by position: the one file downloaded is
        # this recording, whatever its name or its place in the folder.
        pairs = [(audio_files[0], wanted)]
        result.warnings.append(f"single track import: {wanted.title}")
    else:
        pairs, warnings = map_files_to_tracks(audio_files, tracks)
        result.warnings.extend(warnings)
    if not pairs:
        result.error = "unable to match the files with the track list"
        return result

    music_dir = Path(request.naming.music_dir)
    try:
        music_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.error = f"the library folder {music_dir} is not writable: {exc}"
        return result

    old_files: list[Path] = []
    old_snapshot: list[dict[str, Any]] = []
    if request.is_upgrade and request.replaces_path:
        old_root = Path(request.replaces_path)
        if old_root.is_dir():
            # Read now: a file whose name the new release reuses is overwritten
            # a few lines below, and with it the proof of what it used to be.
            old_files = cleanup.collect_audio_files(old_root)
            old_snapshot = describe_files(old_files)

    # Tagging rewrites the file, so a seeding torrent must never be hardlinked.
    mode = "copy"
    if not request.keep_source:
        mode = "hardlink" if request.naming.use_hardlinks else "copy"

    is_multiartist = album.is_compilation or any(
        track.artist and normalize_title(track.artist) != normalize_title(album.albumartist)
        for _, track in pairs
    )

    album_dirs: set[Path] = set()
    for path, track in pairs:
        context = TrackContext(
            albumartist=album.albumartist,
            album=album.album,
            title=track.title,
            artist=track.artist or album.albumartist,
            track=track.position,
            totaltracks=album.total_tracks or len(tracks),
            disc=track.disc,
            totaldiscs=album.total_discs,
            year=(album.date or album.original_date or "")[:4],
            date=album.date or album.original_date,
            genre=album.genres[0] if album.genres else "",
            label=album.label,
            catalognumber=album.catalog_number,
            media=album.media,
            releasetype=album.release_type,
            extension=path.suffix.lower().lstrip(".") or "flac",
            is_multiartist=is_multiartist,
        )
        try:
            relative = render_relative_path(context, request.naming)
        except ValueError as exc:
            result.error = str(exc)
            return result

        destination = music_dir / Path(str(relative))
        try:
            strategy = _place_file(path, destination, mode=mode)
        except OSError as exc:
            result.error = f"unable to write {destination}: {exc}"
            return result

        metadata = build_track_metadata(album, track, total_tracks=len(tracks))
        try:
            write_tags(
                destination,
                metadata,
                request.cover if request.coverart.embed_in_files else None,
            )
        except Exception as exc:  # noqa: BLE001 - keep the file, report the problem
            result.warnings.append(f"tagging failed for {destination.name}: {exc}")

        result.files.append(str(destination))
        album_dirs.add(destination.parent)
        if strategy != mode:
            result.warnings.append(f"{destination.name}: {strategy} instead of {mode}")

    if request.cover:
        # Players do not agree on the name: Plex reads cover.jpg, others folder.jpg.
        names = [
            name
            for name, wanted in (
                ("cover.jpg", request.coverart.save_folder_cover),
                ("folder.jpg", request.coverart.save_folder_jpg),
            )
            if wanted
        ]
        for directory in album_dirs:
            for name in names:
                try:
                    (directory / name).write_bytes(request.cover)
                except OSError as exc:
                    result.warnings.append(f"unable to write {name}: {exc}")

    result.destination = str(sorted(album_dirs)[0]) if album_dirs else None

    if request.is_upgrade and request.replaces_path and request.naming.overwrite_on_upgrade:
        old_root = Path(request.replaces_path)
        kept = {_resolved(Path(item)) for item in result.files}
        doomed = [path for path in old_files if _resolved(path) not in kept]
        if request.confirm_replace and doomed:
            result.review = {
                "old_path": str(old_root),
                "new_path": result.destination,
                "same_folder": shares_folder(old_root, album_dirs),
                "old_files": old_snapshot,
                "new_files": describe_files([Path(item) for item in result.files]),
                "remove": [str(path) for path in doomed],
                "new_dirs": [str(path) for path in sorted(album_dirs)],
            }
        else:
            result.removed.extend(remove_replaced(old_root, doomed, album_dirs, music_dir))

    if not request.keep_source:
        removed = cleanup.remove_tree(source) if source.is_dir() else False
        if removed:
            result.removed.append(str(source))

    result.ok = True
    return result


async def import_album(request: ImportRequest) -> ImportResult:
    """Run the blocking import work in a worker thread."""
    return await asyncio.to_thread(_run_import, request)
