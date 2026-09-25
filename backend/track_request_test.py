"""Asking for one track, without loosening what protects album requests.

The rules that reject a lone file — a two file minimum on Soulseek, a track
count that has to match, a tracklist that has to be covered — are what stop an
isolated track being mistaken for the record it came from. They are asserted
here alongside the track path, because the point is that both hold at once.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MUZIKK_CONFIG_DIR", tempfile.mkdtemp(prefix="muzikk-track-"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from muzikk.matching.scorer import score_candidate  # noqa: E402
from muzikk.providers import slskd  # noqa: E402
from muzikk.providers.base import AlbumQuery, Candidate, CandidateFile  # noqa: E402
from muzikk.providers.slskd import SlskdProvider  # noqa: E402
from muzikk.services.settings import QualitySettings, SlskdSettings  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, extra: object = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f" :: {extra}" if extra != "" else ""))
    if not condition:
        failures.append(label)


ALBUM = AlbumQuery(
    release_group_mbid="rg",
    release_mbid="rel",
    album="Discovery",
    artist="Daft Punk",
    track_count=14,
    track_titles=["One More Time", "Aerodynamic", "Digital Love"],
)
TRACK = AlbumQuery(
    release_group_mbid="rg",
    release_mbid="rel",
    album="Discovery",
    artist="Daft Punk",
    track_count=14,
    track_titles=["One More Time", "Aerodynamic", "Digital Love"],
    recording_mbid="rec-1",
    track_title="Digital Love",
    track_position=3,
    track_duration_ms=301_000,
)

check("an album query is not a track query", not ALBUM.is_track)
check("a track query says so", TRACK.is_track)

# ------------------------------------------------------------- search terms

terms = TRACK.search_terms()
check("the track title is asked first", terms[0] == "Daft Punk Digital Love", terms)
check("the album is still asked once", "Daft Punk Discovery" in terms, terms)
check(
    "the title is never asked without its artist",
    all("daft punk" in term.lower() for term in terms),
    terms,
)
check(
    "an album request is unchanged",
    ALBUM.search_terms() == ["Daft Punk Discovery"],
    ALBUM.search_terms(),
)

# ------------------------------------------------------- how many files slskd asks

check("a track request accepts a lone file", slskd._minimum_files(TRACK) == 1)
check("an album request still demands two", slskd._minimum_files(ALBUM) == 2)
check(
    "a genuine single still accepts one",
    slskd._minimum_files(
        AlbumQuery(release_group_mbid="rg", album="Bang It", artist="Eekoz", track_count=1)
    )
    == 1,
)


def one_file(name: str, *, seconds: int | None = 301, size: int = 30_000_000) -> Candidate:
    return Candidate(
        provider_key="slskd",
        provider_label="Soulseek",
        kind="soulseek",
        title=name,
        directory="shared\\Daft Punk - Discovery",
        files=[CandidateFile(filename=name, size=size, length_seconds=seconds)],
        files_inspected=True,
        size=size,
        extra={"has_free_upload_slot": True},
    )


quality = QualitySettings()

# ------------------------------------------------------------- the right file

good = one_file("Daft Punk - Discovery\\03 Digital Love.flac")
result = score_candidate(good, TRACK, quality)
check("the requested track is accepted", result.accepted, f"{result.score} {result.reason}")

# ------------------------------------------------------- the neighbouring track

neighbour = one_file("Daft Punk - Discovery\\02 Aerodynamic.flac", seconds=212)
result = score_candidate(neighbour, TRACK, quality)
check("another track of the same album is refused", not result.accepted, result.reason)
check("and says why", "not this track" in result.reason, result.reason)

# ------------------------------------------------- same title, different version

live = one_file("Daft Punk - Alive\\Digital Love (live).flac", seconds=520)
result = score_candidate(live, TRACK, quality)
check("a much longer take is refused", not result.accepted, result.reason)
check("on its length", "length differs" in result.reason, result.reason)

# A rip a few seconds apart is the same recording.
close = one_file("Daft Punk - Discovery\\03 Digital Love.flac", seconds=305)
check("a few seconds of drift is fine", score_candidate(close, TRACK, quality).accepted)

# ------------------------------------------------------------ the wrong artist

impostor = Candidate(
    provider_key="slskd",
    provider_label="Soulseek",
    kind="soulseek",
    title="Digital Love.flac",
    directory="shared\\Covers Band\\Tribute",
    files=[CandidateFile(filename="Covers Band\\Digital Love.flac", size=30_000_000, length_seconds=301)],
    files_inspected=True,
    size=30_000_000,
)
result = score_candidate(impostor, TRACK, quality)
check("a cover by somebody else is refused", not result.accepted, result.reason)

# ------------------------------------------------- a folder is not a track

folder = Candidate(
    provider_key="slskd",
    provider_label="Soulseek",
    kind="soulseek",
    title="Daft Punk - Discovery",
    directory="shared\\Daft Punk - Discovery",
    files=[
        CandidateFile(filename="01 One More Time.flac", size=40_000_000, length_seconds=320),
        CandidateFile(filename="03 Digital Love.flac", size=30_000_000, length_seconds=301),
    ],
    files_inspected=True,
    size=70_000_000,
)
result = score_candidate(folder, TRACK, quality)
check("a whole folder is refused for a track request", not result.accepted, result.reason)

# ------------------------------- and the album path keeps its own protections

result = score_candidate(good, ALBUM, quality)
check(
    "one file is still not an album",
    not result.accepted,
    result.reason,
)
check("on its track count", "track count mismatch" in result.reason, result.reason)

# The bug that made these rules necessary, re-checked on the album path.
bootleg = Candidate(
    provider_key="slskd",
    provider_label="Soulseek",
    kind="soulseek",
    title="Dan Lampinski Early Years Volume 14 Johnny Winter 1974",
    directory="shared\\bootlegs\\Dan Lampinski Early Years Volume 14 Johnny Winter 1974",
    files=[CandidateFile(filename="concert.flac", size=209_400_000)],
    files_inspected=True,
    size=209_400_000,
    extra={"has_free_upload_slot": True},
)
cross_country = AlbumQuery(
    release_group_mbid="rg",
    album="Cross Country",
    artist="Pete & Bas",
    track_count=1,
    track_titles=["Cross Country"],
)
check(
    "the unrelated bootleg is still refused",
    not score_candidate(bootleg, cross_country, quality).accepted,
)

# ------------------------------------------------- one candidate per file

RESPONSES = [
    {
        "username": "peer",
        "uploadSpeed": 900_000,
        "queueLength": 0,
        "hasFreeUploadSlot": True,
        "files": [
            {"filename": "music\\Daft Punk - Discovery\\01 One More Time.flac", "size": 40_000_000, "length": 320},
            {"filename": "music\\Daft Punk - Discovery\\03 Digital Love.flac", "size": 30_000_000, "length": 301},
            {"filename": "music\\Daft Punk - Discovery\\cover.jpg", "size": 500_000},
        ],
    }
]

asked: list[dict[str, object]] = []


async def fake_request(method: str, path: str, **kwargs: object) -> object:
    if method == "POST" and path.endswith("/searches"):
        asked.append(dict(kwargs.get("json") or {}))
        return {}
    if method == "DELETE":
        return b""
    if method == "GET" and path.endswith("/searches"):
        return []
    if path.endswith("/responses"):
        return RESPONSES
    return {"state": "Completed"}


slskd.SEARCH_POLL_INTERVAL = 0.01
provider = SlskdProvider(SlskdSettings(downloads_dir="/tmp", api_key="x"))
provider.http.request = fake_request  # type: ignore[assignment]

found = asyncio.run(provider.search(TRACK))
check("each audio file is its own candidate", len(found) == 2, [item.title for item in found])
check("the artwork is not a candidate", all(".jpg" not in item.title for item in found), found)
check("each candidate holds one file", all(len(item.files) == 1 for item in found))

# The same peer, searched for the album, yields one candidate for the folder.
album_found = asyncio.run(provider.search(ALBUM))
check("an album search still groups per folder", len(album_found) == 1, len(album_found))
check("and keeps every file", len(album_found[0].files) == 3, len(album_found[0].files))

print()
print("FAILURES: " + (", ".join(failures) if failures else "none"))
sys.exit(1 if failures else 0)
