"""Exercise the pure logic: naming, normalisation, release picking and scoring."""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("MUZIKK_CONFIG_DIR", tempfile.mkdtemp(prefix="muzikk-pipeline-"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from muzikk.matching.normalize import fuzzy_key, normalize_title, strip_track_number  # noqa: E402
from muzikk.matching.release_picker import pick_release  # noqa: E402
from muzikk.matching.scorer import rank_candidates, score_candidate  # noqa: E402
from muzikk.pipeline import namer  # noqa: E402
from muzikk.providers.base import AlbumQuery, Candidate, CandidateFile  # noqa: E402
from muzikk.services.settings import NamingSettings, QualitySettings  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, extra: object = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}{f' :: {extra}' if extra != '' else ''}")
    if not condition:
        failures.append(label)


# ------------------------------------------------------------------ naming

naming = NamingSettings()
examples = namer.preview(naming)
check("naming preview", len(examples) == 3, examples[0])
check(
    "picard layout",
    examples[0] == "Daft Punk/Discovery (2001)/03 Digital Love.flac",
    examples[0],
)
check("multi disc prefix", "/2-06 " in examples[1], examples[1])
check("multi artist prefix", "09 Underworld - Born Slippy" in examples[2], examples[2])

try:
    namer.preview(naming, "{albumartist}/{nope}")
    check("unknown variable rejected", False, "no error raised")
except ValueError as exc:
    check("unknown variable rejected", "nope" in str(exc), str(exc))

# ------------------------------------------------------------- normalising

check("edition noise", normalize_title("Discovery (Deluxe Remaster)") == "discovery")
check("accents", normalize_title("Émile") == "emile")
check("track number", strip_track_number("03 - Digital Love.flac") == "Digital Love")
check("fuzzy key", fuzzy_key("The Beatles", "Abbey Road") == fuzzy_key("Beatles", "abbey road"))

# ------------------------------------------------------------ search terms

# Soulseek answers only when every word of the query is in the path, so a
# release catalogued as "Pharaoh EP" has to be asked for without its type too:
# the folder shared by the peer is plainly named "Eekoz - Pharaoh".
pharaoh = AlbumQuery(release_group_mbid="rg", album="Pharaoh Ep", artist="Eekoz").search_terms()
check("the release type is dropped from a term", "Eekoz Pharaoh" in pharaoh, pharaoh)
check("the full title is still asked first", pharaoh[0] == "Eekoz Pharaoh Ep", pharaoh)
check(
    "the naked album comes after the terms naming the artist",
    pharaoh.index("Pharaoh Ep") > pharaoh.index("Eekoz Pharaoh"),
    pharaoh,
)

bracketed = AlbumQuery(
    release_group_mbid="rg", album="Bang It (Single)", artist="Eekoz"
).search_terms()
check("no empty brackets left behind", "Eekoz Bang It" in bracketed, bracketed)

only_type = AlbumQuery(release_group_mbid="rg", album="EP", artist="Tycho").search_terms()
check("a record really called EP keeps its name", only_type[0] == "Tycho EP", only_type)

plain = AlbumQuery(release_group_mbid="rg", album="Discovery", artist="Daft Punk").search_terms()
check("a plain title asks twice, not four times", plain == ["Daft Punk Discovery", "Discovery"], plain)

# --------------------------------------------------------- release picking

releases = [
    {
        "id": "bootleg",
        "title": "Discovery (Live Bootleg)",
        "status": "Bootleg",
        "date": "2001-03-12",
        "country": "US",
        "media": [{"format": "CD", "track-count": 14}],
    },
    {
        "id": "official",
        "title": "Discovery",
        "status": "Official",
        "date": "2001-03-12",
        "country": "FR",
        "media": [{"format": "CD", "track-count": 14}],
    },
    {
        "id": "deluxe",
        "title": "Discovery (Deluxe Edition)",
        "status": "Official",
        "date": "2014-05-01",
        "country": "US",
        "media": [{"format": "Digital Media", "track-count": 22}],
    },
]
best, ranked = pick_release(releases, group_first_date="2001-03-12")
check("official edition wins", best is not None and best.mbid == "official", best.mbid if best else None)
check("all editions ranked", len(ranked) == 3, len(ranked))

# -------------------------------------------------------------- scoring

query = AlbumQuery(
    release_group_mbid="rg",
    release_mbid="rel",
    artist="Daft Punk",
    album="Discovery",
    year=2001,
    track_count=3,
    track_titles=["One More Time", "Aerodynamic", "Digital Love"],
)
quality = QualitySettings()


def candidate(name: str, files: list[tuple[str, int]], **kwargs) -> Candidate:
    return Candidate(
        provider_key="slskd",
        provider_label="Soulseek",
        kind="soulseek",
        title=name,
        directory=name,
        files=[CandidateFile(filename=filename, size=size) for filename, size in files],
        files_inspected=True,
        size=sum(size for _, size in files),
        **kwargs,
    )


good = candidate(
    "Daft Punk - Discovery (2001) [FLAC]",
    [
        ("Daft Punk - Discovery/01 One More Time.flac", 40_000_000),
        ("Daft Punk - Discovery/02 Aerodynamic.flac", 30_000_000),
        ("Daft Punk - Discovery/03 Digital Love.flac", 35_000_000),
    ],
)
result = score_candidate(good, query, quality)
check("complete flac accepted", result.accepted, f"score={result.score} {result.reason}")

mp3 = candidate(
    "Daft Punk - Discovery [MP3 320]",
    [
        ("Discovery/01 One More Time.mp3", 9_000_000),
        ("Discovery/02 Aerodynamic.mp3", 8_000_000),
        ("Discovery/03 Digital Love.mp3", 8_500_000),
    ],
)
result = score_candidate(mp3, query, quality)
check("lossy refused by default", not result.accepted, result.reason)

partial = candidate(
    "Daft Punk - Discovery [FLAC]",
    [("Discovery/01 One More Time.flac", 40_000_000)],
)
result = score_candidate(partial, query, quality)
check("incomplete album refused", not result.accepted, result.reason)

wrong = candidate(
    "Random Artist - Some Other Album [FLAC]",
    [
        ("Some Other Album/01 A.flac", 40_000_000),
        ("Some Other Album/02 B.flac", 30_000_000),
        ("Some Other Album/03 C.flac", 35_000_000),
    ],
)
result = score_candidate(wrong, query, quality)
check("unrelated album refused", not result.accepted, f"score={result.score}")

# The right album name by the wrong artist: it used to pass, since the artist is
# only worth 20 points out of 100 and everything else matched.
impostor = Candidate(
    provider_key="slskd",
    provider_label="Soulseek (slskd)",
    kind="soulseek",
    title="LP029_Pharaoh_K-Bora_EP_2016_",
    directory="shared\\Labels\\K\\LP029_Pharaoh_K-Bora_EP_2016_",
    files=[
        CandidateFile(filename="A1 Pharaoh.flac", size=30_000_000),
        CandidateFile(filename="B1 Child Story.flac", size=31_900_000),
    ],
    files_inspected=True,
    extra={"has_free_upload_slot": True},
)
pharaoh_query = AlbumQuery(
    release_group_mbid="rg",
    album="Pharaoh Ep",
    artist="Eekoz",
    track_count=2,
    track_titles=["Pharaoh", "Child Story"],
)
result = score_candidate(impostor, pharaoh_query, QualitySettings())
check("another artist's album refused", not result.accepted, result.reason)
check("the reason names the artist", "artist" in result.reason, result.reason)

# The real folder, which names the artist, stays welcome.
genuine = Candidate(
    provider_key="slskd",
    provider_label="Soulseek (slskd)",
    kind="soulseek",
    title="[2014-01-13] Eekoz - Pharaoh",
    directory="shared\\Labels\\O\\Otodayo Records\\[2014-01-13] Eekoz - Pharaoh",
    files=[
        CandidateFile(filename="01 Eekoz - Pharaoh.flac", size=28_800_000),
        CandidateFile(filename="02 Eekoz - Child Story.flac", size=26_900_000),
    ],
    files_inspected=True,
    extra={"has_free_upload_slot": True},
)
result = score_candidate(genuine, pharaoh_query, QualitySettings())
check("the right folder is accepted", result.accepted, f"score={result.score} {result.reason}")

slow_peer = Candidate(
    provider_key="slskd",
    provider_label="Soulseek (slskd)",
    kind="soulseek",
    title="[2014-01-13] Eekoz - Pharaoh",
    directory="shared\\slow\\[2014-01-13] Eekoz - Pharaoh",
    username="slow-user",
    upload_speed=80_000,
    queue_length=12,
    files=list(genuine.files),
    files_inspected=True,
    extra={"has_free_upload_slot": False},
)
fast_peer = Candidate(
    provider_key="slskd",
    provider_label="Soulseek (slskd)",
    kind="soulseek",
    title="[2014-01-13] Eekoz - Pharaoh",
    directory="shared\\fast\\[2014-01-13] Eekoz - Pharaoh",
    username="fast-user",
    upload_speed=14_000_000,
    queue_length=0,
    files=list(genuine.files),
    files_inspected=True,
    extra={"has_free_upload_slot": True},
)
ranked_peers = rank_candidates([slow_peer, fast_peer], pharaoh_query, QualitySettings())
check("faster soulseek peer is tried first", ranked_peers[0][0].username == "fast-user")

# Turning the rule off brings the old behaviour back, for a library where the
# shares are named after the album alone.
result = score_candidate(impostor, pharaoh_query, QualitySettings(require_artist_match=False))
check("the rule can be switched off", result.accepted, f"score={result.score} {result.reason}")

tiny = candidate(
    "Daft Punk - Discovery [FLAC]",
    [
        ("Discovery/01 One More Time.flac", 200_000),
        ("Discovery/02 Aerodynamic.flac", 200_000),
        ("Discovery/03 Digital Love.flac", 200_000),
    ],
)
result = score_candidate(tiny, query, quality)
check("fake flac refused on size", not result.accepted, result.reason)

# ------------------------------------------------------------- file mapping

from pathlib import PurePath  # noqa: E402

from muzikk.pipeline.importer import (  # noqa: E402
    album_metadata_from_release,
    map_files_to_tracks,
    tracks_from_release,
)

release = {
    "id": "rel",
    "title": "Discovery",
    "date": "2001-03-12",
    "country": "FR",
    "artist-credit": [{"name": "Daft Punk", "artist": {"id": "artist-mbid", "name": "Daft Punk"}}],
    "label-info": [{"label": {"name": "Virgin"}, "catalog-number": "7243 8 49606 1 4"}],
    "media": [
        {
            "position": 1,
            "format": "CD",
            "tracks": [
                {"id": "t1", "position": 1, "title": "One More Time", "length": 320000,
                 "recording": {"id": "r1"}},
                {"id": "t2", "position": 2, "title": "Aerodynamic", "length": 212000,
                 "recording": {"id": "r2"}},
                {"id": "t3", "position": 3, "title": "Digital Love", "length": 301000,
                 "recording": {"id": "r3"}},
            ],
        }
    ],
}

metadata = album_metadata_from_release(release, "rg")
check("album metadata", metadata.album == "Discovery" and metadata.albumartist == "Daft Punk")
check("label read", metadata.label == "Virgin", metadata.label)

tracks = tracks_from_release(release)
check("tracks parsed", len(tracks) == 3 and tracks[2].title == "Digital Love")

from pathlib import Path as _Path  # noqa: E402

shuffled = [
    _Path("/downloads/Discovery/03 Digital Love.flac"),
    _Path("/downloads/Discovery/01 One More Time.flac"),
    _Path("/downloads/Discovery/02 Aerodynamic.flac"),
]
pairs, notes = map_files_to_tracks(shuffled, tracks)
check(
    "numbered files mapped in order",
    [PurePath(path).name for path, _ in pairs]
    == ["01 One More Time.flac", "02 Aerodynamic.flac", "03 Digital Love.flac"],
    notes,
)
check("mapping targets right tracks", [track.title for _, track in pairs] == [
    "One More Time",
    "Aerodynamic",
    "Digital Love",
])

unnumbered = [
    _Path("/downloads/Discovery/Digital Love.flac"),
    _Path("/downloads/Discovery/Aerodynamic.flac"),
    _Path("/downloads/Discovery/One More Time.flac"),
]
pairs, notes = map_files_to_tracks(unnumbered, tracks)
check(
    "titles matched without numbers",
    all(
        PurePath(path).stem.lower() == track.title.lower() for path, track in pairs
    ),
    notes,
)

two_disc_release = {
    **release,
    "media": [
        {"position": 1, "format": "CD", "tracks": [
            {"id": "a1", "position": 1, "title": "In the Flesh?", "recording": {"id": "ra1"}},
            {"id": "a2", "position": 2, "title": "The Thin Ice", "recording": {"id": "ra2"}},
        ]},
        {"position": 2, "format": "CD", "tracks": [
            {"id": "b1", "position": 1, "title": "Hey You", "recording": {"id": "rb1"}},
            {"id": "b2", "position": 2, "title": "Comfortably Numb", "recording": {"id": "rb2"}},
        ]},
    ],
}
two_disc_tracks = tracks_from_release(two_disc_release)
files = [
    _Path("/downloads/Wall/CD1/01 In the Flesh.flac"),
    _Path("/downloads/Wall/CD1/02 The Thin Ice.flac"),
    _Path("/downloads/Wall/CD2/01 Hey You.flac"),
    _Path("/downloads/Wall/CD2/02 Comfortably Numb.flac"),
]
pairs, notes = map_files_to_tracks(files, two_disc_tracks)
check(
    "one folder per disc",
    [track.disc for _, track in pairs] == [1, 1, 2, 2]
    and [track.title for _, track in pairs][-1] == "Comfortably Numb",
    notes,
)

# ----------------------------------------------------------------- upgrades
#
# An upgrade almost always lands in the very folder it improves, since the
# naming template gives the same artist, album and year. The old MP3 files then
# sit next to the new FLAC ones, and deleting the folder is out of the question.

import asyncio  # noqa: E402

from muzikk.pipeline.importer import (  # noqa: E402
    ImportRequest,
    commit_upgrade,
    import_album,
    revert_upgrade,
)
from muzikk.services.settings import CoverArtSettings  # noqa: E402

pharaoh_release = {
    "id": "rel-pharaoh",
    "title": "Pharaoh",
    "date": "2014-01-13",
    "artist-credit": [{"name": "Eekoz", "artist": {"id": "eekoz", "name": "Eekoz"}}],
    "media": [
        {
            "position": 1,
            "format": "Digital Media",
            "tracks": [
                {"id": "p1", "position": 1, "title": "Pharaoh", "recording": {"id": "rp1"}},
                {"id": "p2", "position": 2, "title": "Child Story", "recording": {"id": "rp2"}},
            ],
        }
    ],
}


def build_upgrade(template: str | None = None) -> tuple[NamingSettings, _Path, _Path]:
    """A library holding the album in MP3, and a FLAC copy freshly downloaded."""
    root = _Path(tempfile.mkdtemp(prefix="muzikk-upgrade-"))
    music = root / "music"
    old = music / "Eekoz" / "Pharaoh (2014)"
    old.mkdir(parents=True)
    for name in ("01 Pharaoh.mp3", "02 Child Story.mp3"):
        (old / name).write_bytes(b"old audio" * 64)
    (old / "cover.jpg").write_bytes(b"jpeg bytes")

    download = root / "downloads" / "Eekoz - Pharaoh"
    download.mkdir(parents=True)
    for name in ("01 Pharaoh.flac", "02 Child Story.flac"):
        (download / name).write_bytes(b"new audio" * 128)

    settings = NamingSettings(music_dir=str(music), use_hardlinks=False)
    if template:
        settings = NamingSettings(music_dir=str(music), use_hardlinks=False, album_template=template)
    return settings, old, download


def run_upgrade(settings: NamingSettings, old: _Path, download: _Path, *, confirm: bool):
    return asyncio.run(
        import_album(
            ImportRequest(
                source_path=download,
                release=pharaoh_release,
                release_group_mbid="rg-pharaoh",
                naming=settings,
                coverart=CoverArtSettings(),
                is_upgrade=True,
                replaces_path=str(old),
                confirm_replace=confirm,
            )
        )
    )


settings, old_album, download_dir = build_upgrade()
outcome = run_upgrade(settings, old_album, download_dir, confirm=True)
review = outcome.review or {}
check("upgrade imported", outcome.ok, outcome.error)
check("the upgrade waits for a decision", bool(review), outcome.removed)
check("both copies share one folder", review.get("same_folder") is True, review.get("old_path"))
check("nothing is deleted before the decision", (old_album / "01 Pharaoh.mp3").exists())
check(
    "only the superseded files are listed",
    sorted(_Path(item).name for item in review.get("remove") or [])
    == ["01 Pharaoh.mp3", "02 Child Story.mp3"],
    review.get("remove"),
)
check("the new files are already in place", (old_album / "01 Pharaoh.flac").exists())
check(
    "both sides are described",
    len(review.get("old_files") or []) == 2 and len(review.get("new_files") or []) == 2,
    review.get("new_files"),
)

removed = commit_upgrade(review, _Path(settings.music_dir))
check("validating deletes the old files", len(removed) == 2, removed)
check("the old files are gone", not (old_album / "01 Pharaoh.mp3").exists())
check("the new files stay", (old_album / "02 Child Story.flac").exists())
check("the artwork survives", (old_album / "cover.jpg").exists())

# Refusing does the opposite: the download goes, the library is left as it was.
settings, old_album, download_dir = build_upgrade()
outcome = run_upgrade(settings, old_album, download_dir, confirm=True)
removed = revert_upgrade(outcome.review or {}, _Path(settings.music_dir))
check("refusing deletes what was just imported", len(removed) == 2, removed)
check("the refused files are gone", not (old_album / "01 Pharaoh.flac").exists())
check("the previous copy is untouched", (old_album / "02 Child Story.mp3").exists())

# Without the confirmation step the old files go straight away. They used to
# survive: deleting the folder was refused, and nothing else was ever tried.
settings, old_album, download_dir = build_upgrade()
outcome = run_upgrade(settings, old_album, download_dir, confirm=False)
check("the automatic mode deletes the old files", len(outcome.removed) >= 2, outcome.removed)
check("no decision is asked for", outcome.review is None, outcome.review)
check("the old copy is gone", not (old_album / "01 Pharaoh.mp3").exists())
check("the new copy remains", (old_album / "01 Pharaoh.flac").exists())

# And when the template sends the album somewhere else, the folder left behind
# goes whole, artwork included.
settings, old_album, download_dir = build_upgrade("{albumartist}/{album}/{track:02} {title}")
outcome = run_upgrade(settings, old_album, download_dir, confirm=False)
check("a folder left behind is removed whole", not old_album.exists(), outcome.removed)
check(
    "the album moved to the new layout",
    (_Path(settings.music_dir) / "Eekoz" / "Pharaoh" / "01 Pharaoh.flac").exists(),
    outcome.destination,
)

print()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
