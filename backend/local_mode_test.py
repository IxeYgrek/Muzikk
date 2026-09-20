"""Local mode: passwords, accounts, the first run wizard and the disk scanner.

Runs outside Docker against a throwaway config directory, like the other
checks in this folder.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import struct
import sys
import tempfile
from pathlib import Path

workdir = tempfile.mkdtemp(prefix="muzikk-local-mode-")
os.environ["MUZIKK_CONFIG_DIR"] = workdir
os.environ["MUZIKK_STATIC_DIR"] = os.path.join(workdir, "static")
sys.path.insert(0, str(Path(__file__).parent))

from fastapi.testclient import TestClient  # noqa: E402
from mutagen.flac import FLAC  # noqa: E402
from mutagen.id3 import ID3, TALB, TIT2, TPE1, TPE2, TRCK  # noqa: E402

from muzikk.db import SessionLocal  # noqa: E402
from muzikk.main import app  # noqa: E402
from muzikk.models import LibraryAlbum, LibraryArtist, LibraryTrack  # noqa: E402
from muzikk.security import hash_password, verify_password  # noqa: E402
from muzikk.services import local_library  # noqa: E402
from muzikk.services import mode as mode_service  # noqa: E402
from muzikk.services import settings as settings_service  # noqa: E402
from muzikk.services import users as users_service  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, extra: object = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f" :: {extra}" if extra else ""))
    if not condition:
        failures.append(label)


MP3_FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 413


def write_mp3(path: Path, **fields: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(MP3_FRAME * 12)
    frames = ID3()
    for key, frame in (
        ("title", TIT2),
        ("artist", TPE1),
        ("albumartist", TPE2),
        ("album", TALB),
        ("track", TRCK),
    ):
        if fields.get(key):
            frames.add(frame(encoding=3, text=str(fields[key])))
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


# ------------------------------------------------------------------ passwords

stored = hash_password("correct horse battery")
check("a password verifies", verify_password("correct horse battery", stored))
check("a wrong password does not", not verify_password("correct horse", stored))
check("two hashes of the same password differ", stored != hash_password("correct horse battery"))
check("an account without a hash never authenticates", not verify_password("x", None))
check("a hash from nowhere is refused", not verify_password("x", "plaintext"))


# ----------------------------------------------------------------- the wizard

music = Path(workdir) / "music"
write_flac(
    music / "Daft Punk" / "Discovery (2001)" / "01 One More Time.flac",
    title="One More Time",
    artist="Daft Punk",
    albumartist="Daft Punk",
    album="Discovery",
    date="2001",
    genre="House",
    tracknumber="1",
    musicbrainz_albumid="8f5d1d18-1d05-4b61-9e0d-2a9a8f8f1b4f",
)
write_flac(
    music / "Daft Punk" / "Discovery (2001)" / "02 Aerodynamic.flac",
    title="Aerodynamic",
    artist="Daft Punk",
    albumartist="Daft Punk",
    album="Discovery",
    date="2001",
    genre="House",
    tracknumber="2",
)
write_mp3(
    music / "Eekoz" / "Pharaoh (2014)" / "01 Pharaoh.mp3",
    title="Pharaoh",
    artist="Eekoz",
    albumartist="Eekoz",
    album="Pharaoh",
    track="1",
)

with TestClient(app) as client:
    health = client.get("/api/health").json()
    check("a fresh install asks for the wizard", health.get("setup_required") is True)
    check("and defaults to jellyfin", health.get("mode") == "jellyfin", health.get("mode"))

    chosen = client.post("/api/setup/mode", json={"mode": "local"})
    check("the local mode is accepted", chosen.status_code == 200, chosen.text[:120])
    check("an unknown mode is not", client.post("/api/setup/mode", json={"mode": "plex"}).status_code == 422)

    refused = client.post("/api/setup/jellyfin", json={"url": "http://x", "api_key": "y"})
    check("jellyfin setup is closed in local mode", refused.status_code == 409, refused.text[:120])

    missing = client.post(
        "/api/setup/finish",
        json={"username": "ada", "password": "longenough1", "music_dir": str(music / "nope")},
    )
    check("an invisible music folder is refused", missing.status_code == 422, missing.text[:160])

    short = client.post(
        "/api/setup/finish",
        json={"username": "ada", "password": "short", "music_dir": str(music)},
    )
    check("a short password is refused", short.status_code == 422, short.text[:160])

    done = client.post(
        "/api/setup/finish",
        json={
            "username": "ada",
            "password": "longenough1",
            "name": "Ada",
            "music_dir": str(music),
        },
    )
    check("the wizard completes", done.status_code == 200, done.text[:200])

    again = client.post("/api/setup/mode", json={"mode": "jellyfin"})
    check("the mode cannot be revisited", again.status_code == 409, again.text[:120])

    health = client.get("/api/health").json()
    check("health reports the local mode", health.get("mode") == "local", health.get("mode"))
    check("and drops the jellyfin service", "jellyfin" not in health.get("services", {}))

    server = client.get("/api/auth/server").json()
    check("the login screen knows the mode", server.get("mode") == "local", server)
    check("and shows no jellyfin server", server.get("jellyfin_configured") is False)

    bad = client.post("/api/auth/login", json={"username": "ada", "password": "wrong"})
    check("a wrong password is a 401", bad.status_code == 401, bad.text[:120])

    login = client.post("/api/auth/login", json={"username": "ada", "password": "longenough1"})
    check("the administrator can sign in", login.status_code == 200, login.text[:200])
    body = login.json() if login.status_code == 200 else {}
    check("and is an administrator", (body.get("user") or {}).get("is_admin") is True)
    check("with a username, not a jellyfin id", (body.get("user") or {}).get("username") == "ada")

    check(
        "playlists are gone",
        client.get("/api/playlists").status_code == 409,
        client.get("/api/playlists").text[:120],
    )
    check(
        "the jellyfin settings are read only",
        client.put("/api/admin/settings/jellyfin", json={"url": "http://x"}).status_code == 409,
    )
    check("importing jellyfin users fails", client.post("/api/admin/users/sync").status_code == 400)
    check(
        "so does the jellyfin metadata pass",
        client.post("/api/metadata/jellyfin-metadata").status_code == 409,
    )
    check(
        "the users job is not offered",
        client.post("/api/admin/jobs/users_sync").status_code == 400,
    )

    created = client.post(
        "/api/admin/users",
        json={"username": "grace", "password": "anotherlongone", "name": "Grace"},
    )
    check("an account can be added", created.status_code == 201, created.text[:200])
    duplicate = client.post(
        "/api/admin/users", json={"username": "grace", "password": "anotherlongone"}
    )
    check("but not twice", duplicate.status_code == 422, duplicate.text[:160])

    grace_id = created.json().get("id") if created.status_code == 201 else 0
    reset = client.post(f"/api/admin/users/{grace_id}/password", json={"password": "freshpassword"})
    check("its password can be reset", reset.status_code == 200, reset.text[:160])

    me = client.get("/api/auth/me").json()
    own = client.delete(f"/api/admin/users/{me['user']['id']}")
    check("an administrator cannot delete itself", own.status_code == 400, own.text[:120])
    check("but can delete someone else", client.delete(f"/api/admin/users/{grace_id}").status_code == 200)


# ------------------------------------------------------------------- accounts

session = SessionLocal()
check("the mode is stored", mode_service.is_local(session))

ada = users_service.find_by_username(session, "ADA")
check("a username is matched regardless of case", ada is not None)

ada.is_enabled = False
session.commit()
try:
    users_service.authenticate_local(session, "ada", "longenough1")
    check("a disabled account cannot sign in", False)
except users_service.AuthError as exc:
    check("a disabled account cannot sign in", exc.code == "disabled", exc.code)
ada.is_enabled = True
session.commit()

try:
    users_service.create_local_user(session, username="a b", password="longenough1")
    check("a username with a space is refused", False)
except users_service.AccountError:
    check("a username with a space is refused", True)


# -------------------------------------------------------------------- scanner

result = asyncio.run(local_library.scan_library(session))
check("both albums are indexed", result["albums"] == 2, result)
check("and created", result["created"] == 2, result)
check("three tracks in all", result["tracks"] == 3, result)
check("two artists", result["artists"] == 2, result)

albums = {row.name: row for row in session.query(LibraryAlbum).all()}
check("the flac album is there", "Discovery" in albums, sorted(albums))
discovery = albums.get("Discovery")
check("its identifier is local", discovery is not None and discovery.jellyfin_id.startswith("local:"))
check("it is lossless", discovery is not None and discovery.is_lossless)
check("its artist came from the tags", discovery is not None and discovery.album_artist == "Daft Punk")
check("its year too", discovery is not None and discovery.year == 2001)
check("its release mbid too", discovery is not None and bool(discovery.release_mbid))
check("its genre too", discovery is not None and discovery.genres == ["House"], discovery.genres)
check("it counts two tracks", discovery is not None and discovery.track_count == 2)

pharaoh = albums.get("Pharaoh")
check("the mp3 album is not lossless", pharaoh is not None and not pharaoh.is_lossless)

tracks = local_library.album_tracks(session, discovery.jellyfin_id)
check("the tracklist is ordered", [row.title for row in tracks] == ["One More Time", "Aerodynamic"], [row.title for row in tracks])
check("a track identifier is local", tracks[0].item_id.startswith("local:t:"))
check("and resolves back", local_library.find_track(session, tracks[0].item_id) is not None)

found = local_library.search_tracks(session, "aero")
check("a track search finds it", [row.title for row in found] == ["Aerodynamic"], found)

again = asyncio.run(local_library.scan_library(session))
check("a second walk changes nothing", again["unchanged"] == 2 and again["updated"] == 0, again)
check("and creates nothing", again["created"] == 0, again)

shutil.rmtree(music / "Eekoz")
after = asyncio.run(local_library.scan_library(session))
check("a deleted folder leaves the index", after["removed"] == 1, after)
check("one album is left", session.query(LibraryAlbum).count() == 1)
check("and one artist", session.query(LibraryArtist).count() == 1)
check(
    "its tracks went with it",
    session.query(LibraryTrack).count() == 2,
    session.query(LibraryTrack).count(),
)

write_flac(
    music / "Daft Punk" / "Discovery (2001)" / "03 Digital Love.flac",
    title="Digital Love",
    artist="Daft Punk",
    albumartist="Daft Punk",
    album="Discovery",
    date="2001",
    tracknumber="3",
)
grown = asyncio.run(local_library.scan_library(session))
check("a new file is picked up", grown["updated"] == 1, grown)
check("and counted", session.query(LibraryTrack).count() == 3)

settings_service.invalidate_cache()
session.close()

print()
print("FAILURES: " + (", ".join(failures) if failures else "none"))
sys.exit(1 if failures else 0)
