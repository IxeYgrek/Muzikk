"""Checks the album artwork chain: cover file, embedded picture, resizing."""

from __future__ import annotations

import asyncio
import base64
import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("MUZIKK_CONFIG_DIR", tempfile.mkdtemp(prefix="muzikk-artwork-"))

from PIL import Image  # noqa: E402

from muzikk.services import artwork, coverfiles, jellyfincovers  # noqa: E402
from muzikk.services.jellyfin import JellyfinClient  # noqa: E402
from muzikk.services.localmedia import resolve_folder  # noqa: E402
from muzikk.services.settings import JellyfinSettings  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, extra: object = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f" :: {extra}" if extra else ""))
    if not condition:
        failures.append(label)


def make_image(width: int, height: int, colour: str = "purple") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="JPEG")
    return buffer.getvalue()


root = Path(tempfile.mkdtemp(prefix="muzikk-album-"))

# ------------------------------------------------------------- cover on disk

album = root / "OutKast" / "Stankonia (2000)"
album.mkdir(parents=True)
(album / "1-01 Intro.flac").write_bytes(b"not really a flac")
(album / "back.jpg").write_bytes(make_image(600, 600, "red"))
(album / "cover.jpg").write_bytes(make_image(500, 447, "blue"))

data = artwork.from_disk(str(album))
check("cover.jpg found", data is not None)
with Image.open(io.BytesIO(data or b"")) as image:
    check("cover.jpg preferred over back.jpg", image.size == (500, 447), image.size)

# The folder name should not matter, only the file names.
(album / "cover.jpg").unlink()
data = artwork.from_disk(str(album))
check("falls back to another image", data is not None)

for junk in album.glob("*.jpg"):
    junk.unlink()
check("no image left means nothing found", artwork.from_disk(str(album)) is None)

# A track path must resolve to its folder.
(album / "folder.png").write_bytes(make_image(300, 300, "green"))
check("track path resolves to the folder", artwork.from_disk(str(album / "1-01 Intro.flac")))

# ---------------------------------------------------------- multi disc album

boxset = root / "Pink Floyd" / "The Wall (1979)"
(boxset / "CD1").mkdir(parents=True)
(boxset / "CD1" / "cover.jpg").write_bytes(make_image(800, 800, "orange"))
check("artwork found one level down", artwork.from_disk(str(boxset)) is not None)

# ------------------------------------------------------------ embedded cover

try:
    from mutagen.flac import FLAC, Picture, StreamInfo  # noqa: F401

    has_mutagen = True
except ImportError:
    has_mutagen = False

if has_mutagen:
    from mutagen.id3 import APIC, ID3, TIT2

    mp3_album = root / "Test" / "Tagged (2020)"
    mp3_album.mkdir(parents=True)
    # MPEG-1 layer 3, 128 kbps, 44.1 kHz: 417 byte frames, repeated so that
    # mutagen can sync on the stream.
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    mp3 = mp3_album / "01 track.mp3"
    mp3.write_bytes(frame * 12)
    tags = ID3()
    tags.add(TIT2(encoding=3, text="Track"))
    tags.add(
        APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=make_image(400, 400, "cyan"))
    )
    tags.save(str(mp3))

    data = artwork.from_disk(str(mp3_album))
    check("embedded picture extracted", data is not None)
    if data:
        with Image.open(io.BytesIO(data)) as image:
            check("embedded picture readable", image.size == (400, 400), image.size)

    # A truncated file still has readable tags, and its artwork must be used.
    broken_album = root / "Test" / "Broken (2021)"
    broken_album.mkdir(parents=True)
    broken = broken_album / "01 track.mp3"
    broken.write_bytes(b"\x00" * 64)
    broken_tags = ID3()
    broken_tags.add(
        APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=make_image(360, 360, "pink"))
    )
    broken_tags.save(str(broken))
    check("artwork read from an unplayable file", artwork.from_disk(str(broken_album)) is not None)
else:
    print("SKIP  embedded picture (mutagen missing)")

# ------------------------------------------------------------------ resizing

big = make_image(2000, 2000)
small = artwork.to_jpeg(big, 500)
with Image.open(io.BytesIO(small)) as image:
    check("oversized artwork shrunk", max(image.size) == 500, image.size)
check("shrinking actually saves bytes", len(small) < len(big), f"{len(small)} < {len(big)}")

already_small = make_image(300, 300)
check("small jpeg left untouched", artwork.to_jpeg(already_small, 500) == already_small)

png = io.BytesIO()
Image.new("RGB", (320, 320), "black").save(png, format="PNG")
converted = artwork.to_jpeg(png.getvalue(), 500)
with Image.open(io.BytesIO(converted)) as image:
    check("png converted to jpeg", image.format == "JPEG", image.format)

check("garbage passed through untouched", artwork.to_jpeg(b"nope", 500) == b"nope")

# --------------------------------------------------------------------- cache

check("nothing cached yet", artwork.read_cached("album-1", 500) is None)
artwork.remember("album-1", 500, make_image(200, 200))
check("cached value returned", artwork.read_cached("album-1", 500) is not None)
check("other size not cached", artwork.read_cached("album-1", 250) is None)

artwork.remember("album-2", 500, None)
check("missing marker remembered", artwork.is_known_missing("album-2", 500))
check("marker is per album", not artwork.is_known_missing("album-3", 500))
artwork.remember("album-2", 500, make_image(120, 120))
check("marker cleared once found", not artwork.is_known_missing("album-2", 500))

# ------------------------------------------------- pairing cover and folder

pairs = Path(tempfile.mkdtemp(prefix="muzikk-pairs-"))


def make_album(name: str) -> Path:
    directory = pairs / name
    directory.mkdir(parents=True)
    return directory


both = make_album("both")
(both / "cover.jpg").write_bytes(make_image(200, 200, "red"))
(both / "folder.png").write_bytes(make_image(200, 200, "blue"))
check(
    "a folder holding both names is left alone",
    coverfiles.normalise_folder(both, size=1200) == "already",
)
check("the existing files are untouched", not (both / "folder.jpg").exists())

only_folder = make_album("only folder")
(only_folder / "folder.jpg").write_bytes(make_image(300, 300, "green"))
check(
    "a lone folder.jpg is copied",
    coverfiles.normalise_folder(only_folder, size=1200) == "copied",
)
check(
    "the copy carries the other name and the same bytes",
    (only_folder / "cover.jpg").read_bytes() == (only_folder / "folder.jpg").read_bytes(),
)

only_cover = make_album("only cover")
(only_cover / "cover.png").write_bytes(make_image(300, 300, "purple"))
coverfiles.normalise_folder(only_cover, size=1200)
check("a png cover is copied as png", (only_cover / "folder.png").is_file())

capitals = make_album("capitals")
(capitals / "Folder.JPG").write_bytes(make_image(240, 240, "brown"))
check(
    "a file named Folder.JPG is recognised",
    coverfiles.normalise_folder(capitals, size=1200) == "copied",
)
check("the copy uses lower case", (capitals / "cover.jpg").is_file())

empty_cover = make_album("empty cover")
(empty_cover / "cover.jpg").write_bytes(b"")
check(
    "a zero byte cover does not count as artwork",
    coverfiles.normalise_folder(empty_cover, size=1200) == "without_art",
)

nothing = make_album("nothing")
(nothing / "01 track.mp3").write_bytes(b"\x00" * 32)
check(
    "a folder with no artwork at all is reported",
    coverfiles.normalise_folder(nothing, size=1200) == "without_art",
)

if has_mutagen:
    from mutagen.id3 import APIC as APIC2
    from mutagen.id3 import ID3 as ID32

    tagged = make_album("tagged")
    track = tagged / "01 track.mp3"
    track.write_bytes(frame * 12)
    frames = ID32()
    frames.add(
        APIC2(
            encoding=3, mime="image/jpeg", type=3, desc="Cover", data=make_image(700, 700, "teal")
        )
    )
    frames.save(str(track))

    check(
        "artwork extracted from the tags",
        coverfiles.normalise_folder(tagged, size=1200) == "extracted",
    )
    check(
        "both names written",
        (tagged / "cover.jpg").is_file() and (tagged / "folder.jpg").is_file(),
    )
    check(
        "both names hold the same picture",
        (tagged / "cover.jpg").read_bytes() == (tagged / "folder.jpg").read_bytes(),
    )
    check(
        "a second pass has nothing left to do",
        coverfiles.normalise_folder(tagged, size=1200) == "already",
    )

    # A multi disc album keeps its tracks one level down, so the walk hands the
    # known files over rather than letting the folder be listed again.
    boxed = make_album("boxed")
    (boxed / "CD1").mkdir()
    disc_track = boxed / "CD1" / "01 track.mp3"
    disc_track.write_bytes(frame * 12)
    frames = ID32()
    frames.add(
        APIC2(
            encoding=3, mime="image/jpeg", type=3, desc="Cover", data=make_image(500, 500, "gold")
        )
    )
    frames.save(str(disc_track))

    check(
        "artwork found through the disc subfolder",
        coverfiles.normalise_folder(boxed, size=1200, tracks=[disc_track]) == "extracted",
    )
    check("the album folder gets both files", (boxed / "cover.jpg").is_file())
else:
    print("SKIP  artwork extracted from the tags (mutagen missing)")

# -------------------------------------------------- jellyfin cover repair

# Jellyfin and Muzikk almost never see the library under the same prefix, so the
# path in the API answer has to be matched on its Artist/Album tail.
check(
    "a readable path is used as is",
    jellyfincovers._local_folder(str(album), root) == album,
)
check(
    "a foreign prefix is mapped onto the music folder",
    jellyfincovers._local_folder("/data/media/OutKast/Stankonia (2000)", root) == album,
)
check(
    "resolve_folder remaps a Jellyfin prefix onto the music folder",
    resolve_folder("/media/xvogrek/WDOREDI/Music/OutKast/Stankonia (2000)", str(root)) == album,
)
check(
    "resolve_folder climbs a track path",
    resolve_folder("/media/host/OutKast/Stankonia (2000)/1-01 Intro.flac", str(root)) == album,
)

artwork.remember("jf-sib", 500, None)
artwork.remember("jf-sib", 1200, make_image(200, 200, "navy"))
check("a cover found at 1200 px is visible to the 500 px tile", artwork.read_any_cached("jf-sib") is not None)
check("finding a cover clears the recorded miss", not artwork.is_known_missing("jf-sib", 500))
check(
    "a track path resolves to its album folder",
    jellyfincovers._local_folder("/data/media/OutKast/Stankonia (2000)/1-01 Intro.flac", root)
    == album,
)
check(
    "windows separators are understood too",
    jellyfincovers._local_folder(
        "C:\\muzikk-not-here\\OutKast\\Stankonia (2000)\\1-01 Intro.flac", root
    )
    == album,
)
check(
    "an album whose name looks like a file is not climbed",
    jellyfincovers._local_folder("/data/media/OutKast/Vol. 2", root) is None,
)
check("an unknown album maps to nothing", jellyfincovers._local_folder("/nope/at/all", root) is None)
check("no path maps to nothing", jellyfincovers._local_folder(None, root) is None)

primary = {"ImageTags": {"Primary": "abc"}}
check("an album with a primary tag is left alone", jellyfincovers._has_cover(primary))
check("an empty tag set means no cover", not jellyfincovers._has_cover({"ImageTags": {}}))
check("a missing tag set means no cover", not jellyfincovers._has_cover({"Name": "U"}))

# The upload endpoint decodes base64 from the body and rejects image/*, so the
# exact shape of that request is worth pinning down.
sent: dict[str, object] = {}


class RecordingClient(JellyfinClient):
    async def request(self, method, path, **kwargs):  # type: ignore[override]
        sent.update(method=method, path=path, **kwargs)
        return None


recorder = RecordingClient(JellyfinSettings(url="http://jellyfin:8096", api_key="key"))
asyncio.run(recorder.upload_primary_image("album-42", b"picture bytes"))

check("upload posts to the primary image", sent.get("path") == "/Items/album-42/Images/Primary")
check("upload sends base64", sent.get("content") == base64.b64encode(b"picture bytes"))
check(
    "upload names the exact mime type",
    (sent.get("headers") or {}).get("Content-Type") == "image/jpeg",
)

# ------------------------------------------ group cover falls back to a release

from muzikk.api.images import _release_cover_order  # noqa: E402
from muzikk.services.coverart import CoverArtClient  # noqa: E402
from muzikk.services.settings import CoverArtSettings  # noqa: E402

editions = _release_cover_order(
    [
        {"id": "promo", "status": "Promotion", "date": "2026-01-01"},
        {"id": "old", "status": "Official", "date": "2001-05-13"},
        {"id": "new", "status": "Official", "date": "2026-08-01"},
        {"id": "nodate", "status": "Official", "date": ""},
        {"title": "no id"},
    ]
)
check(
    "official dated editions come first, oldest first",
    [item["id"] for item in editions] == ["old", "new", "nodate", "promo"],
    [item["id"] for item in editions],
)

cover_client = CoverArtClient(CoverArtSettings())
sample = make_image(250, 250, "navy")
cover_client.remember("rg-1", entity="release-group", size=500, data=sample)
check(
    "a release cover stored under the group is served next time",
    asyncio.run(cover_client.get_front("rg-1", entity="release-group", size=500)) == sample,
)
check(
    "a group not yet walked is not exhausted",
    not cover_client.is_exhausted("rg-1", entity="release-group", size=500),
)
cover_client.mark_exhausted("rg-miss", entity="release-group", size=500)
check(
    "a walked group is remembered as empty",
    cover_client.is_exhausted("rg-miss", entity="release-group", size=500),
)

from muzikk.services.catalog import attach_releases, cover_url  # noqa: E402

check(
    "an owned album uses the Jellyfin sleeve",
    cover_url("rg", "rel", "jf-1") == "/api/images/jellyfin/jf-1",
)
check(
    "an unowned album asks for the edition, not only the group",
    cover_url("rg", "rel", None) == "/api/images/cover/release/rel?group=rg",
)

groups = [{"id": "rg-a", "title": "A", "releases": []}, {"id": "rg-b", "title": "B"}]
attach_releases(
    groups,
    [
        {"id": "rel-a", "release-group": {"id": "rg-a"}},
        {"id": "rel-b", "release-group": "rg-b"},
        {"id": "orphan", "release-group": None},
    ],
)
check("editions land on the matching group", groups[0]["releases"] == [{"id": "rel-a"}])
check("a string release-group is accepted", groups[1]["releases"] == [{"id": "rel-b"}])

print()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
