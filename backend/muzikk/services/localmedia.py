"""Finding on disk the file Jellyfin describes.

Jellyfin and Muzikk almost never see the library under the same prefix: the
same album can be ``/data/media/music/...`` for one container and ``/music/...``
for the other. Playback still wants the real file, because reading it directly
is both faster and far more reliable than asking Jellyfin to stream it back.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from ..matching.normalize import is_audio_file

logger = logging.getLogger(__name__)

# Containers every current browser decodes natively. Anything else has to go
# through Jellyfin so it can be transcoded.
BROWSER_EXTENSIONS = {"flac", "mp3", "m4a", "aac", "ogg", "opus", "wav", "webm", "weba"}

CONTENT_TYPES = {
    "flac": "audio/flac",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "aac": "audio/aac",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
    "wav": "audio/wav",
    "webm": "audio/webm",
    "weba": "audio/webm",
}


def content_type(path: Path) -> str:
    return CONTENT_TYPES.get(path.suffix.lower().lstrip("."), "application/octet-stream")


def is_browser_playable(path: Path) -> bool:
    return path.suffix.lower().lstrip(".") in BROWSER_EXTENSIONS


def _parts(path: str) -> list[str]:
    return [part for part in re.split(r"[\\/]+", path.strip()) if part not in ("", ".")]


def resolve(remote_path: str | None, music_dir: str) -> Path | None:
    """The local file matching a path as Jellyfin reported it.

    The path is tried as is, then re-rooted under the library folder by
    dropping its leading components one at a time. The longest tail wins, so a
    file is never confused with a namesake sitting higher in the tree.
    """
    parts = _parts(remote_path or "")
    if not parts or ".." in parts:
        return None

    direct = Path(remote_path or "")
    try:
        if direct.is_file():
            return direct
    except OSError:
        pass

    root = Path(music_dir)
    if not music_dir or not root.is_dir():
        return None

    for depth in range(len(parts), 0, -1):
        candidate = root.joinpath(*parts[-depth:])
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue

    logger.debug("No local file for %s under %s", remote_path, music_dir)
    return None


def resolve_folder(remote_path: str | None, music_dir: str) -> Path | None:
    """The album folder matching a path as Jellyfin reported it.

    Same idea as ``resolve``, for a directory: the raw path first, then the
    longest tail that exists under the configured music folder. A track path is
    climbed to its parent; an album named like a file (``Vol. 2``) is left
    alone.
    """
    if not remote_path:
        return None

    candidate = Path(remote_path)
    if is_audio_file(candidate.name):
        candidate = candidate.parent
    try:
        if candidate.is_dir():
            return candidate
    except OSError:
        pass

    parts = _parts(str(candidate))
    if not parts or ".." in parts:
        return None

    root = Path(music_dir)
    if not music_dir or not root.is_dir():
        return None

    for depth in range(len(parts), 0, -1):
        guess = root.joinpath(*parts[-depth:])
        try:
            if guess.is_dir():
                return guess
        except OSError:
            continue
    return None


def read_range(path: Path, start: int, end: int, chunk_size: int):
    """Yield ``[start, end]`` of a file, inclusive on both ends."""

    def stream():
        remaining = end - start + 1
        with open(path, "rb") as handle:
            handle.seek(start)
            while remaining > 0:
                chunk = handle.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return stream()


_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """First byte range of a ``Range`` header, clamped to the file size.

    ``None`` means "send the whole file": either no range was asked for, or the
    header is one of the exotic forms a media element never produces.
    """
    match = _RANGE_RE.match((header or "").strip().lower())
    if not match or size <= 0:
        return None

    first, last = match.group(1), match.group(2)
    if not first and not last:
        return None
    if not first:
        # "bytes=-500": the trailing 500 bytes.
        length = min(int(last), size)
        return size - length, size - 1

    start = int(first)
    if start >= size:
        return None
    end = min(int(last), size - 1) if last else size - 1
    if end < start:
        return None
    return start, end


def file_size(path: Path) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0
