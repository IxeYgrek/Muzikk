"""Image proxies.

Covers are served by Muzikk so the browser never talks to the Cover Art
Archive, and Jellyfin artwork is proxied so the API key never reaches the
frontend. Every route walks a fallback chain, because no single source has
artwork for every album.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from ..models import LibraryAlbum, MetadataAlbum
from ..services import artwork, clients, localmedia
from ..services import mode as mode_service
from ..services import settings as settings_service
from ..services.base import ServiceError
from ..services.coverart import CoverArtClient
from .deps import SessionDep, authorize_media

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/images", tags=["images"])

CACHE_HEADERS = {"Cache-Control": "public, max-age=604800"}
PLACEHOLDER_STATUS = status.HTTP_404_NOT_FOUND
# One or two editions is enough: a grid of tiles cannot wait for a discography.
RELEASE_COVER_TRIES = 2

_authorize = authorize_media


def _release_cover_order(releases: list[dict]) -> list[dict]:
    """Official dated editions first: those are the ones CAA usually illustrates."""

    def key(item: dict) -> tuple:
        official = (item.get("status") or "").lower() == "official"
        date = item.get("date") or ""
        return (0 if official else 1, 0 if date else 1, date)

    return sorted((item for item in releases if item.get("id")), key=key)


async def _cover_from_group_releases(
    session: SessionDep, client: CoverArtClient, group_mbid: str, size: int
) -> bytes | None:
    """A release-group front is often missing for a few days after a new album.

    Cover Art Archive only answers `/release-group/…/front` once a picture is
    attached to the group. The first official edition usually already has one,
    which is why the album page (that asks for a release) shows a sleeve the
    search grid (that asks for the group) does not.
    """
    if client.is_exhausted(group_mbid, entity="release-group", size=size):
        return None

    musicbrainz = clients.musicbrainz(session)
    try:
        payload = await musicbrainz.browse_releases_for_group(group_mbid, limit=RELEASE_COVER_TRIES)
    except ServiceError as exc:
        logger.debug("Release list for cover of %s failed: %s", group_mbid, exc.message)
        return None

    for release in _release_cover_order((payload or {}).get("releases") or []):
        data = await client.get_front(release["id"], entity="release", size=size)
        if data:
            client.remember(group_mbid, entity="release-group", size=size, data=data)
            return data

    client.mark_exhausted(group_mbid, entity="release-group", size=size)
    return None


async def _jellyfin_bytes(session: SessionDep, item_id: str, height: int) -> bytes | None:
    client = clients.jellyfin(session)
    if not client.configured or not client.api_key:
        return None

    album = session.execute(
        select(LibraryAlbum).where(LibraryAlbum.jellyfin_id == item_id)
    ).scalars().first()
    url = client.image_url(item_id, album.image_tag if album else None, max_height=height)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), follow_redirects=True) as http:
            response = await http.get(url, headers={"X-Emby-Token": client.api_key})
    except httpx.HTTPError:
        return None

    if response.status_code >= 400 or not response.content:
        return None
    return response.content


async def _library_cover(session: SessionDep, item_id: str, size: int) -> bytes | None:
    """Resolve the artwork of an album we own, from the best source available.

    The files come first — a ``cover.jpg`` or an ID3 picture — then Jellyfin,
    then Cover Art Archive. The path Jellyfin stored is remapped onto the
    music folder, because the two containers almost never share a prefix.
    Without Jellyfin the chain is simply one link shorter.
    """
    cached = artwork.read_cached(item_id, size)
    if cached:
        return cached

    sibling = artwork.read_any_cached(item_id)
    if sibling:
        data = artwork.to_jpeg(sibling, size)
        artwork.remember(item_id, size, data)
        return data

    album = session.execute(
        select(LibraryAlbum).where(LibraryAlbum.jellyfin_id == item_id)
    ).scalars().first()

    folder = None
    if album is not None:
        music_dir = settings_service.load(session, "naming").music_dir
        folder = localmedia.resolve_folder(album.path, music_dir)

    data = None
    if folder is not None:
        data = await asyncio.to_thread(artwork.from_disk, str(folder))

    # A miss recorded while Jellyfin was slow must not hide a folder we can
    # now read. Only skip the remote calls.
    if not data and artwork.is_known_missing(item_id, size):
        return None

    if not data and not mode_service.is_local(session):
        data = await _jellyfin_bytes(session, item_id, size)

    if not data and album is not None:
        client = clients.coverart(session)
        data = await client.get_front_with_fallback(
            album.release_mbid, album.release_group_mbid, size=size
        )

    data = artwork.to_jpeg(data, size) if data else None
    # A folder we could not see is not "no artwork": the mount may appear later.
    if data or folder is not None or album is None:
        artwork.remember(item_id, size, data)
    return data


async def _library_cover_for_group(session: SessionDep, group_mbid: str, size: int) -> bytes | None:
    """The sleeve the library already holds for this release group, if we own it."""
    album = (
        session.execute(select(LibraryAlbum).where(LibraryAlbum.release_group_mbid == group_mbid))
        .scalars()
        .first()
    )
    if album is None:
        return None
    return await _library_cover(session, album.jellyfin_id, size)


@router.get("/cover/{entity}/{mbid}")
async def cover(
    entity: str,
    mbid: str,
    request: Request,
    session: SessionDep,
    size: int = Query(default=500, ge=64, le=1200),
    group: str | None = Query(default=None, description="Release-group MBID to fall back on"),
    jf: str | None = Query(default=None, description="Jellyfin item to fall back on"),
    token: str | None = Query(default=None),
) -> Response:
    _authorize(request, session, token)
    if entity not in ("release", "release-group"):
        raise HTTPException(status_code=400, detail="Unknown cover entity")

    # A given edition often has no artwork of its own while the release group
    # does, and an album we already own always has something on disk.
    client = clients.coverart(session)
    data = await client.get_front(mbid, entity=entity, size=size)
    if not data and entity == "release-group":
        data = await _library_cover_for_group(session, mbid, size)
        if not data:
            data = await _cover_from_group_releases(session, client, mbid, size)
    if not data and group and group != mbid:
        data = await client.get_front(group, entity="release-group", size=size)
        if not data:
            data = await _library_cover_for_group(session, group, size)
        if not data:
            data = await _cover_from_group_releases(session, client, group, size)
    if not data and jf:
        data = await _library_cover(session, jf, size)

    if not data:
        raise HTTPException(
            status_code=PLACEHOLDER_STATUS,
            detail="No cover art",
            headers={"Cache-Control": "no-store"},
        )
    return Response(content=data, media_type="image/jpeg", headers=CACHE_HEADERS)


@router.get("/folder/{album_id}")
async def folder_image(
    album_id: int,
    request: Request,
    session: SessionDep,
    size: int = Query(default=300, ge=64, le=1200),
    token: str | None = Query(default=None),
) -> Response:
    """Artwork of a folder found by the metadata analysis.

    Those albums often have no MusicBrainz identifier and no Jellyfin entry
    yet, so the files on disk are the only source available.
    """
    _authorize(request, session, token)
    row = session.get(MetadataAlbum, album_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown album")

    key = f"folder{album_id}"
    data = artwork.read_cached(key, size)
    if not data:
        if artwork.is_known_missing(key, size):
            raise HTTPException(status_code=PLACEHOLDER_STATUS, detail="No cover art")
        found = await asyncio.to_thread(artwork.from_disk, row.path)
        data = artwork.to_jpeg(found, size) if found else None
        artwork.remember(key, size, data)

    if not data:
        raise HTTPException(status_code=PLACEHOLDER_STATUS, detail="No cover art")
    return Response(content=data, media_type="image/jpeg", headers=CACHE_HEADERS)


@router.get("/jellyfin/{item_id}")
async def jellyfin_image(
    item_id: str,
    request: Request,
    session: SessionDep,
    height: int = Query(default=500, ge=64, le=1600),
    token: str | None = Query(default=None),
) -> Response:
    _authorize(request, session, token)
    data = await _library_cover(session, item_id, height)
    if not data:
        raise HTTPException(status_code=PLACEHOLDER_STATUS, detail="No image")
    return Response(content=data, media_type="image/jpeg", headers=CACHE_HEADERS)
