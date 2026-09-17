"""Quick end to end smoke test of the HTTP surface, run outside Docker."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

workdir = tempfile.mkdtemp(prefix="muzikk-smoke-")
os.environ["MUZIKK_CONFIG_DIR"] = workdir
os.environ["MUZIKK_STATIC_DIR"] = os.path.join(workdir, "static")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from muzikk.main import app  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}{f' :: {extra}' if extra else ''}")
    if not condition:
        failures.append(label)


with TestClient(app) as client:
    health = client.get("/api/health")
    check("health 200", health.status_code == 200, health.text[:120])
    check("setup required", health.json().get("setup_required") is True)

    status = client.get("/api/setup/status")
    check("setup status", status.status_code == 200, status.text[:120])

    libraries = client.get("/api/setup/libraries")
    check("libraries need jellyfin", libraries.status_code == 400, libraries.text[:120])

    protected = client.get("/api/albums/search?q=daft")
    check("search requires auth", protected.status_code == 401, protected.text[:120])

    admin = client.get("/api/admin/settings")
    check("admin requires auth", admin.status_code == 401, admin.text[:120])

    login = client.post("/api/auth/login", json={"username": "x", "password": "y"})
    check("login without jellyfin", login.status_code == 503, login.text[:160])

    spa = client.get("/")
    check("spa placeholder", spa.status_code == 503, spa.text[:120])

    schema = client.get("/api/openapi.json")
    paths = schema.json().get("paths", {})
    check("openapi paths", len(paths) > 30, f"{len(paths)} paths")
    for required in (
        "/api/auth/login",
        "/api/albums/search",
        "/api/library/albums",
        "/api/requests",
        "/api/activity/stream",
        "/api/discover/new-releases",
        "/api/watchlist",
        "/api/admin/settings/{section}",
        "/api/admin/test/{service}",
        "/api/images/cover/{entity}/{mbid}",
        "/api/tracks/search",
        "/api/labels/search",
        "/api/labels/{label_mbid}",
        "/api/play/track/{item_id}",
        "/api/play/album/{album_id}",
        "/api/play/preview",
        "/api/play/preview/stream",
        "/api/play/upgrade/{request_id}/{side}/{index}",
        "/api/metadata/summary",
        "/api/metadata/albums",
        "/api/metadata/albums/{album_id}/plan",
        "/api/metadata/albums/{album_id}/apply",
        "/api/metadata/artwork-sync",
        "/api/metadata/jellyfin-covers",
        "/api/requests/imported",
        "/api/requests/failed",
        "/api/requests/cancel-active",
        "/api/requests/retry-failed",
        "/api/requests/{request_id}/upgrade/confirm",
        "/api/requests/{request_id}/upgrade/refuse",
        "/api/playlists",
        "/api/playlists/{playlist_id}",
        "/api/playlists/{playlist_id}/items",
        "/api/watchlist/{watch_id}",
        "/api/watchlist/releases",
        "/api/watchlist/releases/{release_id}",
        "/api/wishlist/refresh",
        "/api/local-import/sessions",
        "/api/local-import/sessions/{session_id}",
        "/api/local-import/sessions/{session_id}/files",
        "/api/local-import/sessions/{session_id}/analyze",
        "/api/local-import/sessions/{session_id}/match",
        "/api/local-import/sessions/{session_id}/manual",
        "/api/local-import/sessions/{session_id}/commit",
    ):
        check(f"route {required}", required in paths)

    labels = client.get("/api/labels/search?q=otodayo")
    check("label search requires auth", labels.status_code == 401, labels.text[:120])

    pairing = client.post("/api/metadata/artwork-sync")
    check("artwork sync requires auth", pairing.status_code == 401, pairing.text[:120])

    local_import = client.post("/api/local-import/sessions")
    check("local import requires auth", local_import.status_code == 401, local_import.text[:120])

# ------------------------------------------------- editions folded into albums

from muzikk.services.catalog import groups_from_releases  # noqa: E402

pressings = [
    {
        "id": "rel-1",
        "artist-credit": [{"name": "Foo"}],
        "release-group": {"id": "rg-1", "title": "First", "first-release-date": "2019-04-01"},
    },
    {
        "id": "rel-2",
        "artist-credit": [{"name": "Foo"}],
        "release-group": {"id": "rg-1", "title": "First", "first-release-date": "2019-04-01"},
    },
    {"id": "rel-3", "artist-credit": [{"name": "Bar"}], "release-group": {"id": "rg-2"}},
    {"id": "rel-4", "artist-credit": [{"name": "Nobody"}]},
]
folded = groups_from_releases(pressings)
check("one card per album", len(folded) == 2, [item.get("id") for item in folded])
check("every pressing kept", len(folded[0]["releases"]) == 2, folded[0]["releases"])
check("artist borrowed from the pressing", folded[0]["artist-credit"][0]["name"] == "Foo")
check("release without an album ignored", all(item.get("id") for item in folded))

# --------------------------------------------- an album added to a playlist

import asyncio  # noqa: E402

from muzikk.api.playlists import _resolve_tracks  # noqa: E402
from muzikk.schemas import PlaylistAdd  # noqa: E402


class ShuffledAlbum:
    """A Jellyfin client returning an album's tracks in no useful order."""

    async def get_album_tracks(self, album_id: str) -> list[dict]:
        return [
            {"Id": "b", "ParentIndexNumber": 1, "IndexNumber": 2},
            {"Id": "c", "ParentIndexNumber": 2, "IndexNumber": 1},
            {"Id": "a", "ParentIndexNumber": 1, "IndexNumber": 1},
        ]


added = asyncio.run(
    _resolve_tracks(ShuffledAlbum(), PlaylistAdd(album_id="album-1", track_ids=["a"]))
)
check("album added disc then track", added == ["a", "b", "c"], added)

# ------------------------------------------- what a follow puts on the list

from muzikk.models import WatchedArtist, WatchScope  # noqa: E402
from muzikk.services.watchlist import _wanted  # noqa: E402

discography = [
    {"id": "rg-new", "title": "Latest", "first-release-date": "2026-06-01", "primary-type": "Album"},
    {"id": "rg-old", "title": "Debut", "first-release-date": "2003-02-11", "primary-type": "Album"},
    {
        "id": "rg-live",
        "title": "Live in Paris",
        "first-release-date": "2026-05-01",
        "primary-type": "Album",
        "secondary-types": ["Live"],
    },
    {"id": "rg-single", "title": "A Single", "first-release-date": "2026-04-02", "primary-type": "Single"},
    {"id": "rg-video", "title": "A Video", "first-release-date": "2026-04-02", "primary-type": "Other"},
    {"id": "rg-nodate", "title": "Undated", "first-release-date": "", "primary-type": "Album"},
]
follow = WatchedArtist(artist_mbid="a", artist_name="Foo")

follow.scope = WatchScope.NEW
recent = _wanted(discography, follow, "2025-08-01")
check(
    "new releases only, single included",
    [group["id"] for group, _ in recent] == ["rg-new", "rg-single"],
    [group["id"] for group, _ in recent],
)

follow.scope = WatchScope.MISSING
everything = _wanted(discography, follow, "2025-08-01")
check(
    "whole discography, live album and video aside",
    [group["id"] for group, _ in everything] == ["rg-new", "rg-old", "rg-single", "rg-nodate"],
    [group["id"] for group, _ in everything],
)
check(
    "only the recent ones count as new",
    [is_new for _, is_new in everything] == [True, False, True, False],
)

shutil.rmtree(workdir, ignore_errors=True)

print()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
