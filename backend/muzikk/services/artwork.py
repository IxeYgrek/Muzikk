"""Album artwork resolution for the albums we already own.

Jellyfin is not always able to give us a picture: it only exposes one once it
has extracted or downloaded it. The files on disk are a far more reliable
source, so we walk the whole chain — Jellyfin, then a cover file sitting next to
the tracks, then the picture embedded in the tags, then Cover Art Archive — and
cache whatever we find.
"""

from __future__ import annotations

import io
import logging
import time
from collections.abc import Iterable
from pathlib import Path

from ..config import get_env_config

logger = logging.getLogger(__name__)

# Ordered by how likely each name is to be the real front cover.
COVER_STEMS = (
    "cover",
    "folder",
    "front",
    "album",
    "albumart",
    "albumartsmall",
    "thumb",
    "poster",
)
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
AUDIO_SUFFIXES = (".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wv", ".ape", ".aiff", ".wav")
MISSING_TTL_SECONDS = 24 * 3600


def _cache_paths(key: str, size: int) -> tuple[Path, Path]:
    cache_dir = get_env_config().cache_dir / "covers"
    cache_dir.mkdir(parents=True, exist_ok=True)
    stem = f"library_{key}_{size}"
    return cache_dir / f"{stem}.jpg", cache_dir / f"{stem}.missing"


def read_cached(key: str, size: int) -> bytes | None:
    image_path, _ = _cache_paths(key, size)
    if image_path.exists() and image_path.stat().st_size > 0:
        return image_path.read_bytes()
    return None


def read_any_cached(key: str) -> bytes | None:
    """A cover already found for this album, at any size.

    The grid asks for 500 px and the album page for 1200 px. A miss at one
    size must not hide a hit at the other.
    """
    cache_dir = get_env_config().cache_dir / "covers"
    if not cache_dir.is_dir():
        return None
    matches = [
        path
        for path in cache_dir.glob(f"library_{key}_*.jpg")
        if path.stat().st_size > 0
    ]
    if not matches:
        return None
    matches.sort(key=lambda path: path.stat().st_size, reverse=True)
    return matches[0].read_bytes()


def is_known_missing(key: str, size: int) -> bool:
    _, missing_path = _cache_paths(key, size)
    if not missing_path.exists():
        return False
    if time.time() - missing_path.stat().st_mtime > MISSING_TTL_SECONDS:
        missing_path.unlink(missing_ok=True)
        return False
    return True


def remember(key: str, size: int, data: bytes | None) -> None:
    image_path, missing_path = _cache_paths(key, size)
    if data:
        image_path.write_bytes(data)
        missing_path.unlink(missing_ok=True)
        # A hit at 1200 px must unlock the 500 px tile that failed earlier.
        for leftover in image_path.parent.glob(f"library_{key}_*.missing"):
            leftover.unlink(missing_ok=True)
    else:
        missing_path.write_bytes(b"")


def to_jpeg(data: bytes, size: int) -> bytes:
    """Normalise to JPEG and shrink oversized artwork.

    Album folders often hold 3000 px scans; sending those to a grid of tiles
    would be wasteful.
    """
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            if image.width <= size and image.height <= size and image.format == "JPEG":
                return data
            image = image.convert("RGB")
            image.thumbnail((size, size), Image.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=88, optimize=True)
            return buffer.getvalue()
    except Exception as exc:  # noqa: BLE001 - a bad image must not break the page
        logger.debug("Could not normalise artwork: %s", exc)
        return data


def folder_cover(directory: Path) -> bytes | None:
    """Return the cover file stored next to the tracks."""
    try:
        entries = [item for item in directory.iterdir() if item.is_file()]
    except OSError:
        return None

    images = [item for item in entries if item.suffix.lower() in IMAGE_SUFFIXES]
    if not images:
        return None

    def rank(path: Path) -> tuple[int, int]:
        stem = path.stem.lower()
        for index, candidate in enumerate(COVER_STEMS):
            if stem == candidate:
                return (index, 0)
        for index, candidate in enumerate(COVER_STEMS):
            if stem.startswith(candidate):
                return (len(COVER_STEMS) + index, 0)
        # Unknown names come last, biggest first: scans beat thumbnails.
        return (len(COVER_STEMS) * 2, -path.stat().st_size)

    for path in sorted(images, key=rank):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if data:
            return data
    return None


def _tags_only(path: Path):
    """Read tags of a file whose audio stream cannot be parsed.

    Real libraries always hold a few damaged or truncated files, and their
    artwork is usually still perfectly readable.
    """
    suffix = path.suffix.lower()
    try:
        if suffix == ".mp3":
            from mutagen.id3 import ID3

            return ID3(str(path))
        if suffix == ".flac":
            from mutagen.flac import FLAC

            return FLAC(str(path))
    except Exception:  # noqa: BLE001
        return None
    return None


def _picture_from_audio(path: Path) -> bytes | None:
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(str(path))
    except Exception:  # noqa: BLE001 - unreadable files are simply skipped
        audio = _tags_only(path)
    if audio is None:
        return None

    pictures = getattr(audio, "pictures", None)
    if pictures:
        return bytes(pictures[0].data)

    # _tags_only returns the tag object itself rather than a container.
    tags = getattr(audio, "tags", None) or audio
    if tags is None:
        return None

    getall = getattr(tags, "getall", None)
    if callable(getall):
        frames = getall("APIC")
        if frames:
            return bytes(frames[0].data)

    try:
        covers = tags.get("covr")
    except (AttributeError, KeyError, TypeError, ValueError):
        covers = None
    if covers:
        return bytes(covers[0])

    try:
        block = tags.get("metadata_block_picture")
    except (AttributeError, KeyError, TypeError, ValueError):
        block = None
    if block:
        import base64

        from mutagen.flac import Picture

        try:
            return bytes(Picture(base64.b64decode(block[0])).data)
        except Exception:  # noqa: BLE001
            return None
    return None


def picture_from_tracks(tracks: Iterable[Path], *, limit: int = 4) -> bytes | None:
    """Return the first picture embedded in these tracks.

    Callers that already know the files of an album — a multi disc release keeps
    them in subfolders — should use this rather than walking the folder again.
    """
    for index, track in enumerate(tracks):
        if index >= limit:
            break
        data = _picture_from_audio(track)
        if data:
            return data
    return None


def embedded_cover(directory: Path) -> bytes | None:
    """Return the picture embedded in the first tagged track of the folder."""
    try:
        tracks = sorted(
            item
            for item in directory.iterdir()
            if item.is_file() and item.suffix.lower() in AUDIO_SUFFIXES
        )
    except OSError:
        return None

    # A handful of files is enough; whole discographies must not be scanned.
    return picture_from_tracks(tracks)


def has_cover(directory: Path) -> bool:
    """Whether artwork is available, without loading full scans in memory.

    File names are checked first because that costs nothing; only then is one
    track opened to look for an embedded picture.
    """
    try:
        entries = list(directory.iterdir())
    except OSError:
        return False

    tracks: list[Path] = []
    for item in entries:
        if not item.is_file():
            continue
        suffix = item.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            try:
                if item.stat().st_size > 0:
                    return True
            except OSError:
                continue
        elif suffix in AUDIO_SUFFIXES:
            tracks.append(item)

    for track in sorted(tracks)[:2]:
        if _picture_from_audio(track):
            return True
    return False


def from_disk(album_path: str | None) -> bytes | None:
    """Look for artwork around an album folder, going one level up if needed."""
    if not album_path:
        return None
    directory = Path(album_path)
    if directory.is_file():
        directory = directory.parent
    if not directory.is_dir():
        logger.debug("Album folder %s is not visible from the container", album_path)
        return None

    data = folder_cover(directory) or embedded_cover(directory)
    if data:
        return data

    # Multi-disc albums keep the artwork in the parent folder.
    for child in sorted(directory.iterdir()) if directory.is_dir() else []:
        if child.is_dir():
            data = folder_cover(child) or embedded_cover(child)
            if data:
                return data
            break
    return None
