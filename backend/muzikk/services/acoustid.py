"""Audio fingerprinting through AcoustID, the way Picard identifies a disc.

Only used as a last resort: it needs the ``fpcalc`` binary from Chromaprint, an
API key, and one network round trip per sampled track. When the tags or the
folder name say enough, the text search is both faster and more accurate.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .. import __version__

logger = logging.getLogger(__name__)

LOOKUP_URL = "https://api.acoustid.org/v2/lookup"
FPCALC = "fpcalc"
FPCALC_TIMEOUT = 60.0
# AcoustID asks for no more than three requests per second.
REQUEST_INTERVAL = 0.4


class AcoustidError(RuntimeError):
    pass


@dataclass(slots=True)
class GroupVote:
    """A release group proposed by AcoustID, with how convinced it is."""

    release_group_mbid: str
    title: str = ""
    artist: str = ""
    votes: int = 0
    best_score: float = 0.0
    recordings: list[str] = field(default_factory=list)


def available() -> bool:
    """Whether Chromaprint is installed in this image."""
    return shutil.which(FPCALC) is not None


async def fingerprint(path: Path) -> tuple[int, str]:
    """Duration in seconds and Chromaprint fingerprint of one file."""
    binary = shutil.which(FPCALC)
    if binary is None:
        raise AcoustidError(
            "fpcalc is not installed: rebuild the Muzikk image to enable fingerprinting"
        )

    process = await asyncio.create_subprocess_exec(
        binary,
        "-json",
        "-length",
        "120",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=FPCALC_TIMEOUT)
    except TimeoutError as exc:
        process.kill()
        raise AcoustidError(f"fingerprinting timed out on {path.name}") from exc

    if process.returncode != 0:
        detail = (stderr or b"").decode("utf-8", "replace").strip()[:200]
        raise AcoustidError(f"fpcalc failed on {path.name}: {detail or 'unknown error'}")

    try:
        payload = json.loads(stdout.decode("utf-8", "replace"))
        return int(payload["duration"]), str(payload["fingerprint"])
    except (ValueError, KeyError) as exc:
        raise AcoustidError(f"unreadable fpcalc output for {path.name}") from exc


async def _lookup(
    client: httpx.AsyncClient, api_key: str, duration: int, value: str
) -> list[dict]:
    response = await client.post(
        LOOKUP_URL,
        data={
            "client": api_key,
            "duration": str(duration),
            "fingerprint": value,
            "meta": "recordings+releasegroups+compress",
        },
        headers={"User-Agent": f"Muzikk/{__version__}"},
    )
    if response.status_code == 400:
        raise AcoustidError("AcoustID refused the request: check the API key")
    if response.status_code >= 400:
        raise AcoustidError(f"AcoustID answered HTTP {response.status_code}")

    payload = response.json()
    if payload.get("status") != "ok":
        raise AcoustidError(payload.get("error", {}).get("message") or "AcoustID error")
    return payload.get("results") or []


async def identify(files: list[Path], api_key: str, *, sample: int = 3) -> list[GroupVote]:
    """Fingerprint a few tracks and rank the release groups they point at.

    Individual tracks are often shared by a studio album, a compilation and a
    live record, so the release group appearing across the sample wins.
    """
    if not api_key:
        raise AcoustidError("no AcoustID API key configured")

    # Spread the sample over the album: the first tracks are the most reused.
    chosen = files[:sample] if len(files) <= sample else [
        files[index * len(files) // sample] for index in range(sample)
    ]

    votes: dict[str, GroupVote] = {}
    counter: Counter[str] = Counter()

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        for index, path in enumerate(chosen):
            if index:
                await asyncio.sleep(REQUEST_INTERVAL)
            try:
                duration, value = await fingerprint(path)
                results = await _lookup(client, api_key, duration, value)
            except AcoustidError as exc:
                logger.debug("AcoustID lookup failed for %s: %s", path.name, exc)
                continue

            seen_here: set[str] = set()
            for result in results:
                score = float(result.get("score") or 0.0)
                for recording in result.get("recordings") or []:
                    for group in recording.get("releasegroups") or []:
                        group_id = group.get("id")
                        if not group_id:
                            continue
                        entry = votes.get(group_id)
                        if entry is None:
                            artists = group.get("artists") or []
                            entry = GroupVote(
                                release_group_mbid=group_id,
                                title=group.get("title") or "",
                                artist=(artists[0].get("name") if artists else "") or "",
                            )
                            votes[group_id] = entry
                        entry.best_score = max(entry.best_score, score)
                        if recording.get("id") and recording["id"] not in entry.recordings:
                            entry.recordings.append(recording["id"])
                        if group_id not in seen_here:
                            seen_here.add(group_id)
                            counter[group_id] += 1

    for group_id, count in counter.items():
        votes[group_id].votes = count

    return sorted(
        votes.values(), key=lambda item: (-item.votes, -item.best_score, item.title)
    )
