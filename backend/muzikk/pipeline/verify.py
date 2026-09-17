"""Audio integrity checks.

A truncated or corrupted FLAC plays for thirty seconds and then dies, which is
exactly the kind of release that must be rejected before it reaches the
library rather than after.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

PROCESS_TIMEOUT = 300


@dataclass(slots=True)
class VerificationResult:
    ok: bool
    checked: int = 0
    skipped: int = 0
    failures: list[str] = field(default_factory=list)
    message: str = ""


async def _run(command: list[str]) -> tuple[int, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, NotImplementedError, OSError) as exc:
        return -1, str(exc)

    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=PROCESS_TIMEOUT)
    except TimeoutError:
        process.kill()
        return -2, "verification timed out"
    return process.returncode or 0, (stderr or b"").decode("utf-8", errors="replace")[-400:]


async def verify_file(path: Path) -> tuple[bool, str]:
    """Decode a file to check it is complete and not corrupted."""
    extension = path.suffix.lower().lstrip(".")

    if extension == "flac" and shutil.which("flac"):
        code, output = await _run(["flac", "-t", "--silent", str(path)])
        if code == 0:
            return True, ""
        if code < 0:
            return True, f"skipped ({output})"
        return False, output.strip() or "flac reported a decoding error"

    if shutil.which("ffmpeg"):
        code, output = await _run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"]
        )
        if code == 0:
            return True, ""
        if code < 0:
            return True, f"skipped ({output})"
        return False, output.strip() or "ffmpeg reported a decoding error"

    return True, "skipped (no verification tool available)"


async def verify_files(paths: list[Path], *, enabled: bool = True) -> VerificationResult:
    if not enabled:
        return VerificationResult(ok=True, skipped=len(paths), message="verification disabled")

    result = VerificationResult(ok=True)
    for path in paths:
        ok, message = await verify_file(path)
        if message.startswith("skipped"):
            result.skipped += 1
            continue
        result.checked += 1
        if not ok:
            result.ok = False
            result.failures.append(f"{path.name}: {message}")

    if not result.ok:
        result.message = "; ".join(result.failures[:3])
    elif result.skipped and not result.checked:
        result.message = "no integrity check performed (flac and ffmpeg unavailable)"
    return result
