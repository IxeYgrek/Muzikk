"""Turning the containers a browser cannot decode into ones it can.

In Jellyfin mode this never runs: anything exotic is relayed to Jellyfin,
which transcodes it. In local mode nobody else will, so Muzikk asks ffmpeg,
already in the image for audio fingerprinting.

The result is a pipe, so it carries neither a length nor a byte index and the
browser cannot seek inside it. Playback restarts the stream at the wanted
second instead, which is what ``start`` is for.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

CHUNK_SIZE = 64 * 1024

# How much of ffmpeg's complaint is worth keeping when it refuses a file.
ERROR_TAIL = 400

FORMATS: dict[str, tuple[list[str], str, str]] = {
    # V0 from a lossless source is transparent, and every browser plays it.
    "mp3": (["-c:a", "libmp3lame", "-q:a", "0"], "mp3", "audio/mpeg"),
    # Lighter and better, but Safari is unreliable with Ogg.
    "opus": (["-c:a", "libopus", "-b:a", "192k", "-vbr", "on"], "ogg", "audio/ogg"),
}

DEFAULT_FORMAT = "mp3"


class TranscodeError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def binary() -> str | None:
    return shutil.which("ffmpeg")


def available() -> bool:
    return binary() is not None


def content_type(fmt: str) -> str:
    return FORMATS.get(fmt, FORMATS[DEFAULT_FORMAT])[2]


def _command(path: Path, fmt: str, start: float) -> list[str]:
    codec, container, _ = FORMATS.get(fmt, FORMATS[DEFAULT_FORMAT])
    executable = binary()
    if executable is None:
        raise TranscodeError("ffmpeg is not installed in this container")

    args = [executable, "-hide_banner", "-loglevel", "error", "-nostdin"]
    # Before the input, so ffmpeg jumps in the file instead of decoding up to
    # the mark. Accurate enough for a seek bar, and orders of magnitude faster.
    if start > 0:
        args += ["-ss", f"{start:.3f}"]
    args += [
        "-i",
        str(path),
        "-vn",
        "-sn",
        "-dn",
        # Cover art travels as a video stream and would be re-encoded.
        "-map_metadata",
        "-1",
        # LAME knows stereo and mono only, and a browser wants nothing else.
        "-ac",
        "2",
        *codec,
        "-f",
        container,
        "pipe:1",
    ]
    return args


async def stream(path: Path, *, fmt: str = DEFAULT_FORMAT, start: float = 0.0) -> AsyncIterator[bytes]:
    """Yield the file re-encoded on the fly, from ``start`` seconds in."""
    command = _command(path, fmt, start)
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    assert process.stdout is not None

    finished = False
    try:
        while True:
            chunk = await process.stdout.read(CHUNK_SIZE)
            if not chunk:
                finished = True
                break
            yield chunk
    finally:
        # The listener skipping to the next track closes the generator, and an
        # ffmpeg left running would hold a file handle and a CPU for nothing.
        if not finished and process.returncode is None:
            process.kill()
        try:
            _, errors = await process.communicate()
        except ProcessLookupError:
            errors = b""
        if process.returncode not in (0, None) and errors:
            logger.warning(
                "ffmpeg failed on %s: %s",
                path.name,
                errors.decode("utf-8", "replace").strip()[-ERROR_TAIL:],
            )
