"""Checks how a finished slskd transfer is found back on disk."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("MUZIKK_CONFIG_DIR", tempfile.mkdtemp(prefix="muzikk-slskd-"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from muzikk.matching.scorer import score_candidate  # noqa: E402
from muzikk.providers import slskd  # noqa: E402
from muzikk.providers.base import AlbumQuery, DownloadHandle  # noqa: E402
from muzikk.providers.slskd import SlskdProvider  # noqa: E402
from muzikk.services.settings import QualitySettings, SlskdSettings  # noqa: E402

failures: list[str] = []

TRACKS = [
    "LiSA - LACE UP - 01 - OPENiNG -LACE UP.flac",
    "LiSA - LACE UP - 02 - DECOTORA15.flac",
    "LiSA - LACE UP - 05 - 小豆あらい.flac",
]


def check(label: str, condition: bool, extra: object = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}{f' :: {extra}' if extra != '' else ''}")
    if not condition:
        failures.append(label)


def provider_for(downloads_dir: Path | str) -> SlskdProvider:
    return SlskdProvider(SlskdSettings(downloads_dir=str(downloads_dir), api_key="x"))


def handle_for(names: list[str]) -> DownloadHandle:
    return DownloadHandle(
        client="slskd",
        external_id="1",
        username="peer",
        # Soulseek sends Windows-style paths; only the leaf is kept.
        payload={"expected_audio": names},
    )


with tempfile.TemporaryDirectory(prefix="muzikk-dl-") as tmp:
    root = Path(tmp)

    # ------------------------------------------- the folder is not mounted
    missing = provider_for(root / "nope")._locate_content(handle_for(TRACKS))
    check("missing folder reports no path", missing.path is None)
    check("missing folder names itself", "nope" in missing.problem, missing.problem)
    check("missing folder is not worth retrying", missing.worth_retrying is False)

    # ------------------------------------------ nothing matches yet on disk
    empty = provider_for(root)._locate_content(handle_for(TRACKS))
    check("empty folder reports no path", empty.path is None)
    check("empty folder counts the tracks", "3 downloaded track" in empty.problem, empty.problem)
    check("empty folder is worth retrying", empty.worth_retrying is True)

    # ---------------------------------------------- the usual slskd layout
    album = root / "LACE UP (2026)"
    album.mkdir()
    for name in TRACKS:
        (album / name).write_bytes(b"x")
    (album / "cover.jpg").write_bytes(b"x")

    found = provider_for(root)._locate_content(handle_for(TRACKS))
    check("album folder found", found.path == str(album), found.path)
    check("no problem reported", found.problem == "")

    # A decoy folder holding a single track must not win over the real one.
    decoy = root / "singles"
    decoy.mkdir()
    (decoy / TRACKS[0]).write_bytes(b"x")
    best = provider_for(root)._locate_content(handle_for(TRACKS))
    check("richest folder wins", best.path == str(album), best.path)

    # slskd may nest the peer's own subfolders under the download root.
    nested_root = root / "nested"
    nested = nested_root / "peer" / "music" / "LACE UP (2026)"
    nested.mkdir(parents=True)
    for name in TRACKS:
        (nested / name).write_bytes(b"x")
    deep = provider_for(nested_root)._locate_content(handle_for(TRACKS))
    check("nested folder found", deep.path == str(nested), deep.path)

    # -------------------------------------- an unmounted folder fails fast
    start = time.monotonic()
    waited = asyncio.run(provider_for(root / "nope")._await_content(handle_for(TRACKS)))
    check("unmounted folder does not sleep", time.monotonic() - start < 1.0)
    check("unmounted folder still reports the problem", waited.path is None)

    # A folder that could still be filling up gets a few more chances, and the
    # files landing late are picked up without failing the request.
    late = root / "late"
    late.mkdir()
    slskd.LOCATE_DELAY_SECONDS = 0.05
    calls = {"count": 0}
    original = SlskdProvider._locate_content

    def fill_on_third(self, handle):
        calls["count"] += 1
        if calls["count"] == 3:
            for name in TRACKS:
                (late / name).write_bytes(b"x")
        return original(self, handle)

    SlskdProvider._locate_content = fill_on_third
    try:
        recovered = asyncio.run(provider_for(late)._await_content(handle_for(TRACKS)))
    finally:
        SlskdProvider._locate_content = original
    check("late files are picked up", recovered.path == str(late), recovered.path)
    check("retries stay bounded", calls["count"] <= 4, calls["count"])

# ------------------------------------------------- how many files a folder needs

# A single is one file. Asking two of it, as an album search rightly does, threw
# the release away before it could be scored.
single = AlbumQuery(
    release_group_mbid="rg-1", album="Bang It", artist="Eekoz", track_count=1,
    track_titles=["Bang It"],
)
album_query = AlbumQuery(
    release_group_mbid="rg-2", album="Discovery", artist="Daft Punk", track_count=14,
    track_titles=["One More Time"],
)
unknown = AlbumQuery(release_group_mbid="rg-3", album="Nothing", artist="Nobody")

check("a single asks for one file", slskd._minimum_files(single) == 1)
check("an album still asks for two", slskd._minimum_files(album_query) == 2)
check("an unknown track count asks for two", slskd._minimum_files(unknown) == 2)

# The folder the manual search found: one FLAC next to its cover.
RESPONSES = [
    {
        "username": "sommlid",
        "uploadSpeed": 845_330,
        "queueLength": 69,
        "hasFreeUploadSlot": True,
        "files": [
            {
                "filename": "shared\\Labels\\O\\Otodayo Records\\"
                "[2015-01-28] Eekoz - Bang It\\01 Eekoz - Bang It.flac",
                "size": 42_046_000,
                "length": 294,
                "bitRate": 1146,
                "bitDepth": 16,
                "sampleRate": 44100,
            },
            {
                "filename": "shared\\Labels\\O\\Otodayo Records\\"
                "[2015-01-28] Eekoz - Bang It\\cover.jpg",
                "size": 1_600_000,
            },
        ],
    }
]

asked: list[dict[str, object]] = []


async def fake_request(method: str, path: str, **kwargs: object) -> object:
    if method == "POST" and path.endswith("/searches"):
        asked.append(dict(kwargs.get("json") or {}))
        return {}
    if path.endswith("/responses"):
        return RESPONSES
    return {"state": "Completed"}


probe = provider_for("/tmp")
probe.http.request = fake_request  # type: ignore[assignment]
slskd.SEARCH_POLL_INTERVAL = 0.01

single_found = asyncio.run(probe.search(single))
check("the single is now a candidate", len(single_found) == 1, len(single_found))
check("the folder is kept whole",
      single_found and len(single_found[0].files) == 2, single_found[0].files if single_found else "")
check("slskd is asked for one file too",
      asked and asked[0]["minimumResponseFileCount"] == 1, asked[:1])

scored = score_candidate(single_found[0], single, QualitySettings())
check("the single passes the scorer", scored.accepted, f"{scored.score} {scored.reason}")

asked.clear()
album_found = asyncio.run(probe.search(album_query))
check("a lone track is still no album for an album search", album_found == [], album_found)
check("slskd keeps its two file minimum for albums",
      asked and asked[0]["minimumResponseFileCount"] == 2, asked[:1])

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("All slskd location checks passed.")
