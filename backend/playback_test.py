"""Checks the pieces playback relies on: file location and Range parsing."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("MUZIKK_CONFIG_DIR", tempfile.mkdtemp(prefix="muzikk-playback-"))

from muzikk.api.play import review_file_path  # noqa: E402
from muzikk.services import localmedia  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, extra: object = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f" :: {extra}" if extra else ""))
    if not condition:
        failures.append(label)


root = Path(tempfile.mkdtemp(prefix="muzikk-music-"))
album = root / "Daft Punk" / "Discovery (2001)"
album.mkdir(parents=True)
track = album / "01 One More Time.flac"
track.write_bytes(bytes(range(256)) * 8)  # 2048 bytes

# ------------------------------------------------------------------- locating

check(
    "file found through a different mount point",
    localmedia.resolve(
        "/data/media/music/Daft Punk/Discovery (2001)/01 One More Time.flac", str(root)
    )
    == track,
)
check(
    "windows style path from jellyfin is understood",
    localmedia.resolve(
        r"D:\Media\Music\Daft Punk\Discovery (2001)\01 One More Time.flac", str(root)
    )
    == track,
)
check(
    "path already visible is used as is",
    localmedia.resolve(str(track), str(root)) == track,
)
check(
    "unknown file resolves to nothing",
    localmedia.resolve("/data/music/Nobody/Nothing/01 Ghost.flac", str(root)) is None,
)
check("empty path resolves to nothing", localmedia.resolve("", str(root)) is None)
check(
    "traversal is refused",
    localmedia.resolve("/music/../../etc/passwd", str(root)) is None,
)

check("flac plays in a browser", localmedia.is_browser_playable(track))
check("ape needs transcoding", not localmedia.is_browser_playable(Path("a.ape")))
check("flac content type", localmedia.content_type(track) == "audio/flac")

# --------------------------------------------------------------------- ranges

size = localmedia.file_size(track)
check("size read from disk", size == 2048, size)
check("no header means the whole file", localmedia.parse_range(None, size) is None)
check("open ended range", localmedia.parse_range("bytes=0-", size) == (0, 2047))
check("closed range", localmedia.parse_range("bytes=100-199", size) == (100, 199))
check("range clamped to the file", localmedia.parse_range("bytes=2000-9999", size) == (2000, 2047))
check("suffix range", localmedia.parse_range("bytes=-500", size) == (1548, 2047))
check("range past the end is ignored", localmedia.parse_range("bytes=5000-", size) is None)
check("reversed range is ignored", localmedia.parse_range("bytes=300-100", size) is None)
check("multi range is ignored", localmedia.parse_range("bytes=0-10,20-30", size) is None)

chunks = list(localmedia.read_range(track, 100, 199, 32))
body = b"".join(chunks)
check("range content", len(body) == 100 and body == track.read_bytes()[100:200], len(body))
check("range is chunked", len(chunks) == 4, len(chunks))

# ------------------------------------------------------- upgrade comparison

review = {
    "old_files": [{"path": str(track), "format": "flac"}],
    "new_files": [{"path": str(album / "01 One More Time.mp3"), "format": "mp3"}],
}
check("upgrade old file by index", review_file_path(review, "old", 0) == str(track))
check("upgrade new file by index", review_file_path(review, "new", 0) == str(album / "01 One More Time.mp3"))
check("upgrade unknown index is refused", review_file_path(review, "old", 1) is None)
check("upgrade unknown side is refused", review_file_path(review, "both", 0) is None)
check("upgrade empty review is refused", review_file_path(None, "old", 0) is None)
check("upgrade blank path is refused", review_file_path({"old_files": [{"path": "  "}]}, "old", 0) is None)

print()
if failures:
    print(f"{len(failures)} failure(s): " + ", ".join(failures))
    raise SystemExit(1)
print("playback checks passed")
