"""Checks the reuse of an album already present in the download folder."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MUZIKK_CONFIG_DIR", tempfile.mkdtemp(prefix="muzikk-salvage-"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from muzikk.pipeline import salvage  # noqa: E402
from muzikk.providers.base import AlbumQuery  # noqa: E402
from muzikk.services.settings import QualitySettings  # noqa: E402

failures: list[str] = []

TITLES = ["OPENiNG", "DECOTORA15", "QUEEN", "REALiZE", "Shouted Serenade"]
MB = 1024 * 1024


def check(label: str, condition: bool, extra: object = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}{f' :: {extra}' if extra != '' else ''}")
    if not condition:
        failures.append(label)


def query_for() -> AlbumQuery:
    return AlbumQuery(
        release_group_mbid="rg-1",
        album="LACE UP",
        artist="LiSA",
        year=2026,
        track_count=len(TITLES),
        track_titles=list(TITLES),
    )


def make_album(
    directory: Path, titles: list[str], *, extension: str = "flac", size: int = 6 * MB
) -> Path:
    """Write plausible track files, sparsely so the test stays fast."""
    directory.mkdir(parents=True, exist_ok=True)
    for index, title in enumerate(titles, 1):
        path = directory / f"LiSA - LACE UP - {index:02} - {title}.{extension}"
        with path.open("wb") as handle:
            if size > 0:
                handle.seek(size - 1)
                handle.write(b"\0")
    return directory


quality = QualitySettings()

with tempfile.TemporaryDirectory(prefix="muzikk-dl-") as tmp:
    root = Path(tmp)

    # ------------------------------------------------ the complete album wins
    album = make_album(root / "LACE UP (2026)", TITLES)
    found = salvage.find_local_album([root], query_for(), quality)
    check("complete album accepted", found is not None)
    if found:
        candidate, result = found
        check("right folder returned", candidate.directory == str(album), candidate.directory)
        check("every track listed", len(candidate.audio_files) == 5, len(candidate.audio_files))
        check("score above the threshold", result.score >= quality.min_score, result.score)

    # -------------------------------------------- a partial copy is refused
    with tempfile.TemporaryDirectory(prefix="muzikk-partial-") as other:
        partial_root = Path(other)
        make_album(partial_root / "LACE UP (2026)", TITLES[:2])
        check(
            "partial album refused",
            salvage.find_local_album([partial_root], query_for(), quality) is None,
        )

    # ------------------------------------- empty shells count as missing tracks
    with tempfile.TemporaryDirectory(prefix="muzikk-empty-") as other:
        empty_root = Path(other)
        make_album(empty_root / "LACE UP (2026)", TITLES, size=0)
        check(
            "zero byte files refused",
            salvage.find_local_album([empty_root], query_for(), quality) is None,
        )

    # ------------------------------------------ a lossy copy is refused by default
    with tempfile.TemporaryDirectory(prefix="muzikk-mp3-") as other:
        mp3_root = Path(other)
        make_album(mp3_root / "LACE UP (2026)", TITLES, extension="mp3")
        check(
            "mp3 refused when lossless is required",
            salvage.find_local_album([mp3_root], query_for(), quality) is None,
        )
        lossy_ok = QualitySettings(allow_lossy_fallback=True)
        check(
            "mp3 accepted when lossy is allowed",
            salvage.find_local_album([mp3_root], query_for(), lossy_ok) is not None,
        )

    # ---------------------------------------- suspiciously small files are refused
    with tempfile.TemporaryDirectory(prefix="muzikk-small-") as other:
        small_root = Path(other)
        make_album(small_root / "LACE UP (2026)", TITLES, size=2048)
        check(
            "tiny files refused",
            salvage.find_local_album([small_root], query_for(), quality) is None,
        )

    # ----------------------------------------- another album is not confused for it
    with tempfile.TemporaryDirectory(prefix="muzikk-other-") as other:
        wrong_root = Path(other)
        wrong = wrong_root / "LiSA - LEO-NiNE (2020)"
        wrong.mkdir(parents=True)
        for index, title in enumerate(["Akai Wana", "Catch the Moment", "Gurenge"], 1):
            path = wrong / f"LiSA - LEO-NiNE - {index:02} - {title}.flac"
            with path.open("wb") as handle:
                handle.seek(6 * MB - 1)
                handle.write(b"\0")
        check(
            "different album refused",
            salvage.find_local_album([wrong_root], query_for(), quality) is None,
        )

    # -------------------------------------- in-progress folders are skipped
    with tempfile.TemporaryDirectory(prefix="muzikk-inc-") as other:
        inc_root = Path(other)
        make_album(inc_root / "incomplete" / "LACE UP (2026)", TITLES)
        check(
            "incomplete folder skipped",
            salvage.find_local_album([inc_root], query_for(), quality) is None,
        )

    # ------------------------------------------ a missing root is not an error
    check(
        "missing root ignored",
        salvage.find_local_album([root / "nope"], query_for(), quality) is None,
    )

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("All salvage checks passed.")
