"""Local folder import: staging, ownership rules, manual tagging and naming."""

from __future__ import annotations

import asyncio
import io
import os
import struct
import sys
import tempfile
from pathlib import Path

workdir = tempfile.mkdtemp(prefix="muzikk-local-import-")
os.environ["MUZIKK_CONFIG_DIR"] = workdir
sys.path.insert(0, str(Path(__file__).parent))

from mutagen.flac import FLAC  # noqa: E402
from mutagen.id3 import ID3, TALB, TIT2, TPE1, TPE2, TRCK  # noqa: E402
from PIL import Image  # noqa: E402

from muzikk.db import SessionLocal, init_db  # noqa: E402
from muzikk.matching.normalize import fuzzy_key  # noqa: E402
from muzikk.models import LibraryAlbum  # noqa: E402
from muzikk.services import local_import  # noqa: E402
from muzikk.services import settings as settings_service  # noqa: E402
from muzikk.services import tags as tags_service  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, extra: object = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f" :: {extra}" if extra else ""))
    if not condition:
        failures.append(label)


def make_image(size: int = 240) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), "teal").save(buffer, format="JPEG")
    return buffer.getvalue()


MP3_FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 413


def write_mp3(path: Path, **fields: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(MP3_FRAME * 12)
    frames = ID3()
    if fields.get("title"):
        frames.add(TIT2(encoding=3, text=str(fields["title"])))
    if fields.get("artist"):
        frames.add(TPE1(encoding=3, text=str(fields["artist"])))
    if fields.get("albumartist"):
        frames.add(TPE2(encoding=3, text=str(fields["albumartist"])))
    if fields.get("album"):
        frames.add(TALB(encoding=3, text=str(fields["album"])))
    if fields.get("track"):
        frames.add(TRCK(encoding=3, text=str(fields["track"])))
    frames.save(str(path))


def _flac_header() -> bytes:
    bits = (44100 << 44) | (1 << 41) | (15 << 36) | 44100
    info = struct.pack(">HH", 4096, 4096) + b"\x00" * 6 + struct.pack(">Q", bits) + b"\x00" * 16
    return b"fLaC" + b"\x80\x00\x00\x22" + info


def write_flac(path: Path, **fields: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_flac_header())
    audio = FLAC(str(path))
    audio.add_tags()
    for key, value in fields.items():
        if value:
            audio[key] = [str(value)]
    audio.save()


def add_owned(
    session,
    *,
    artist: str,
    album: str,
    lossless: bool,
    path: str,
    jellyfin_id: str,
) -> None:
    session.add(
        LibraryAlbum(
            jellyfin_id=jellyfin_id,
            name=album,
            album_artist=artist,
            path=path,
            fuzzy_key=fuzzy_key(artist, album),
            is_lossless=lossless,
            formats=["flac"] if lossless else ["mp3"],
            track_count=1,
        )
    )
    session.commit()


init_db()
session = SessionLocal()
music = Path(workdir) / "music"
music.mkdir()
settings_service.save(session, "naming", {"music_dir": str(music), "use_hardlinks": False})

# ------------------------------------------------------------------ paths

try:
    local_import.safe_relative("../escape.mp3")
    check("path traversal rejected", False)
except local_import.LocalImportError:
    check("path traversal rejected", True)

try:
    local_import.safe_relative("notes.txt")
    check("non-audio rejected", False)
except local_import.LocalImportError:
    check("non-audio rejected", True)

relative = local_import.safe_relative("Album/01 Track.mp3")
check("audio path accepted", relative.as_posix() == "Album/01 Track.mp3")

# ------------------------------------------------------------------ analyze

state = local_import.create_session(1)
source = Path(tempfile.mkdtemp(prefix="muzikk-drop-")) / "Loose"
write_mp3(
    source / "01 Hello.mp3",
    title="Hello",
    artist="Adele",
    albumartist="Adele",
    album="25",
    track="1",
)
local_import.add_file(1, state.id, "25/01 Hello.mp3", (source / "01 Hello.mp3").read_bytes())
state = local_import.analyze(session, 1, state.id)
check("analyze reads the artist", state.artist == "Adele", state.artist)
check("analyze reads the album", state.album == "25", state.album)
check("analyze counts the track", len(state.tracks) == 1, state.tracks)
check("mp3 is not lossless", state.is_lossless is False)

# ------------------------------------------------------------------ ownership

add_owned(
    session,
    artist="Adele",
    album="25",
    lossless=True,
    path=str(music / "Adele" / "25"),
    jellyfin_id="jf-25",
)
owned = local_import.assess_ownership(
    session, artist="Adele", album="25", incoming_lossless=False
)
check("lossy against lossless is blocked", bool(owned and owned["blocked"]), owned)
check("lossy against lossless is not an upgrade", bool(owned and not owned["upgradable"]), owned)

add_owned(
    session,
    artist="Eekoz",
    album="Pharaoh",
    lossless=False,
    path=str(music / "Eekoz" / "Pharaoh (2014)"),
    jellyfin_id="jf-pharaoh",
)
upgrade = local_import.assess_ownership(
    session, artist="Eekoz", album="Pharaoh", incoming_lossless=True
)
check("lossless against lossy is an upgrade", bool(upgrade and upgrade["upgradable"]), upgrade)
check("lossless against lossy is not blocked", bool(upgrade and not upgrade["blocked"]), upgrade)

# ------------------------------------------------------------------ manual commit

cover = make_image()
manual = local_import.create_session(2)
write_flac(
    source / "01 Pharaoh.flac",
    title="Pharaoh",
    artist="Eekoz",
    albumartist="Eekoz",
    album="Pharaoh",
    tracknumber="1",
)
local_import.add_file(
    2, manual.id, "Pharaoh/01 Pharaoh.flac", (source / "01 Pharaoh.flac").read_bytes()
)
manual = local_import.analyze(session, 2, manual.id)
local_import.set_cover(2, manual.id, cover)
try:
    local_import.set_manual(session, 2, manual.id, artist="", album="Pharaoh")
    check("manual requires the artist", False)
except local_import.LocalImportError as exc:
    check("manual requires the artist", exc.code == "missing_artist", exc)

manual = local_import.set_manual(session, 2, manual.id, artist="Eekoz", album="Pharaoh", year="2014")
check("manual marks the session identified", manual.status == "identified", manual.status)
check("manual sees the upgrade offer", bool(manual.ownership and manual.ownership["upgradable"]))

try:
    asyncio.run(local_import.commit(session, 2, manual.id, confirm_upgrade=False))
    check("upgrade without confirmation refused", False)
except local_import.LocalImportError as exc:
    check("upgrade without confirmation refused", exc.code == "upgrade_required", exc)

# A lossy copy already sitting where the namer will write the new one.
old_dir = music / "Eekoz" / "Pharaoh (2014)"
old_dir.mkdir(parents=True)
old_mp3 = old_dir / "01 Pharaoh.mp3"
write_mp3(old_mp3, title="Pharaoh", artist="Eekoz", album="Pharaoh", track="1")

committed = asyncio.run(local_import.commit(session, 2, manual.id, confirm_upgrade=True))
expected = music / "Eekoz" / "Pharaoh (2014)" / "01 Pharaoh.flac"
check("manual commit writes the track", expected.is_file(), committed.destination)
check("cover.jpg is written", (expected.parent / "cover.jpg").is_file())
check("folder.jpg is written", (expected.parent / "folder.jpg").is_file())
written = tags_service.read_file(expected)
check("id3 album artist", written.albumartist == "Eekoz", written.albumartist)
check("id3 album", written.album == "Pharaoh", written.album)
check("id3 title", written.title == "Pharaoh", written.title)
check("session is committed", committed.status == "committed", committed.status)
check("old lossy file removed", not old_mp3.exists())

# ------------------------------------------------------------------ refuse a worse copy

worse = local_import.create_session(3)
local_import.add_file(3, worse.id, "25/01 Hello.mp3", (source / "01 Hello.mp3").read_bytes())
worse = local_import.analyze(session, 3, worse.id)
local_import.set_cover(3, worse.id, cover)
worse = local_import.set_manual(session, 3, worse.id, artist="Adele", album="25", year="2015")
try:
    asyncio.run(local_import.commit(session, 3, worse.id))
    check("already lossless refused", False)
except local_import.LocalImportError as exc:
    check("already lossless refused", exc.code == "already_lossless", exc.code)

# ------------------------------------------------------------------ lossless landing without a previous copy

fresh = local_import.create_session(4)
write_flac(
    source / "01 New.flac",
    title="New",
    artist="Nobody",
    albumartist="Nobody",
    album="Blank",
    tracknumber="1",
)
local_import.add_file(4, fresh.id, "Blank/01 New.flac", (source / "01 New.flac").read_bytes())
fresh = local_import.analyze(session, 4, fresh.id)
check("flac is lossless", fresh.is_lossless is True)
local_import.set_cover(4, fresh.id, cover)
fresh = local_import.set_manual(session, 4, fresh.id, artist="Nobody", album="Blank", year="2024")
landed = asyncio.run(local_import.commit(session, 4, fresh.id))
flac_dest = music / "Nobody" / "Blank (2024)" / "01 New.flac"
check("fresh lossless lands in the library", flac_dest.is_file(), landed.destination)
check("fresh lossless has no ownership block", landed.ownership is None, landed.ownership)

print()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
