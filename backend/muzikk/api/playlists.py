"""Jellyfin playlists, seen and edited as the signed in listener.

Listing, editing and deleting run under the token Muzikk stored when the user
signed in: a playlist belongs to an account, and the server key would file
them all under whichever account owns it.

Importing into another account is the exception. An administrator may pick a
Jellyfin user; creation then uses the API key plus that ``UserId``, never the
target's password.

Playlists live in Jellyfin, so an installation without one has none. Every
route below refuses in local mode and the interface hides the section.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..matching.normalize import normalize_artist, normalize_title
from ..models import LibraryAlbum, User
from ..schemas import (
    PlaylistAccount,
    PlaylistAdd,
    PlaylistBackup,
    PlaylistBackupEntry,
    PlaylistBackupTrack,
    PlaylistChange,
    PlaylistCreate,
    PlaylistImportMissing,
    PlaylistImportReport,
    PlaylistImportRequest,
    PlaylistImportResult,
    PlaylistOut,
    PlaylistTrack,
)
from ..services import catalog, clients
from ..services import mode as mode_service
from ..services import users as users_service
from ..services.base import ServiceError
from ..services.jellyfin import JellyfinClient
from .deps import CurrentUser, SessionDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/playlists", tags=["playlists"])

BACKUP_VERSION = 1


def _client(session: Session) -> JellyfinClient:
    if mode_service.is_local(session):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This installation has no Jellyfin, and therefore no playlists",
        )
    client = clients.jellyfin(session)
    if not client.configured:
        raise HTTPException(status_code=400, detail="Jellyfin is not configured")
    return client


def _token(user: User) -> str:
    token = users_service.jellyfin_token(user)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No Jellyfin session for this account: sign out and sign in again",
        )
    return token


def _fail(exc: ServiceError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message)


def _albums_by_jellyfin_id(session: Session, ids: set[str]) -> dict[str, LibraryAlbum]:
    if not ids:
        return {}
    rows = (
        session.execute(select(LibraryAlbum).where(LibraryAlbum.jellyfin_id.in_(ids)))
        .scalars()
        .all()
    )
    return {row.jellyfin_id: row for row in rows}


async def _resolve_tracks(
    client: JellyfinClient, payload: PlaylistAdd | PlaylistCreate
) -> list[str]:
    """The tracks to add, an album standing for its own in track order."""
    ids = [item for item in payload.track_ids if item]
    if payload.album_id:
        items = await client.get_album_tracks(payload.album_id)
        items.sort(
            key=lambda item: (
                item.get("ParentIndexNumber") or 1,
                item.get("IndexNumber") or 999,
                item.get("Name") or "",
            )
        )
        ids.extend(item["Id"] for item in items if item.get("Id"))
    # Keep the order, drop the repeats.
    return list(dict.fromkeys(ids))


def _norm_path(value: str) -> str:
    return value.replace("\\", "/").casefold().rstrip("/")


def _mbids_of(item: dict[str, Any]) -> tuple[str, str]:
    providers = item.get("ProviderIds") or {}
    recording = (
        providers.get("MusicBrainzTrack") or providers.get("MusicBrainzRecording") or ""
    ).lower()
    release = (providers.get("MusicBrainzAlbum") or providers.get("MusicBrainzRelease") or "").lower()
    return recording, release


def track_matches_path(item: dict[str, Any], path: str) -> bool:
    """Whether a Jellyfin item is the file the backup remembers.

    Mount prefixes differ between machines, so a suffix match is accepted when
    the two paths share a file name.
    """
    wanted = _norm_path(path)
    have = _norm_path(item.get("Path") or "")
    if not wanted or not have:
        return False
    return have == wanted or have.endswith(wanted) or wanted.endswith(have)


def track_matches_tags(item: dict[str, Any], title: str, artist: str, album: str) -> bool:
    if not title or normalize_title(item.get("Name")) != normalize_title(title):
        return False
    if album and normalize_title(item.get("Album") or "") != normalize_title(album):
        return False
    if artist:
        artists = item.get("Artists") or []
        item_artist = (artists[0] if artists else "") or item.get("AlbumArtist") or ""
        if normalize_artist(item_artist) != normalize_artist(artist):
            return False
    return True


def _backup_track(item: dict[str, Any], album: LibraryAlbum | None) -> PlaylistBackupTrack:
    artists = item.get("Artists") or []
    recording, release = _mbids_of(item)
    if not release and album and album.release_mbid:
        release = album.release_mbid
    return PlaylistBackupTrack(
        jellyfin_id=item.get("Id") or "",
        path=item.get("Path") or (album.path if album else "") or "",
        title=item.get("Name") or "",
        artist=(artists[0] if artists else "") or item.get("AlbumArtist") or "",
        album=item.get("Album") or (album.name if album else "") or "",
        recording_mbid=recording or None,
        release_mbid=release or None,
    )


async def _lookup_exported_track(
    client: JellyfinClient, track: PlaylistBackupTrack
) -> str | None:
    """Find the current Jellyfin id of a backed-up track.

    Order: a still-valid id, then the recording MBID, then the path, then
    artist + album + title. Anything short of that is reported as missing.
    """
    if track.jellyfin_id:
        try:
            item = await client.get_item(track.jellyfin_id)
        except ServiceError:
            item = {}
        if item.get("Id"):
            return str(item["Id"])

    if track.recording_mbid:
        try:
            items = await client.find_audio_by_provider("MusicBrainzTrack", track.recording_mbid)
        except ServiceError:
            items = []
        if items and items[0].get("Id"):
            return str(items[0]["Id"])

    if track.path:
        leaf = Path(_norm_path(track.path)).name
        term = Path(leaf).stem or leaf
        if term:
            try:
                items = await client.search_audio(term, limit=40)
            except ServiceError:
                items = []
            for item in items:
                if item.get("Id") and track_matches_path(item, track.path):
                    return str(item["Id"])

    title = (track.title or "").strip()
    if title:
        try:
            items = await client.search_audio(title, limit=40)
        except ServiceError:
            items = []
        for item in items:
            if item.get("Id") and track_matches_tags(item, title, track.artist, track.album):
                return str(item["Id"])
    return None


def _missing_reason(track: PlaylistBackupTrack) -> str:
    if track.jellyfin_id or track.recording_mbid or track.path or track.title:
        return "not in the library"
    return "empty track"


@router.get("/accounts", response_model=list[PlaylistAccount])
async def list_accounts(session: SessionDep, user: CurrentUser) -> list[PlaylistAccount]:
    """Jellyfin accounts an administrator can import playlists into."""
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator only")
    _client(session)
    rows = (
        session.execute(
            select(User)
            .where(User.jellyfin_user_id.is_not(None), User.is_enabled.is_(True))
            .order_by(User.name.asc())
        )
        .scalars()
        .all()
    )
    return [
        PlaylistAccount(id=row.jellyfin_user_id or "", name=row.name)
        for row in rows
        if row.jellyfin_user_id
    ]


@router.get("/export", response_model=PlaylistBackup)
async def export_playlists(
    session: SessionDep,
    user: CurrentUser,
    ids: str | None = Query(default=None),
) -> PlaylistBackup:
    """Download the caller's playlists as JSON. Empty ``ids`` means all of them."""
    client = _client(session)
    token = _token(user)
    wanted = {item for item in (ids or "").split(",") if item}
    try:
        listed = await client.get_playlists(token=token, user_id=user.jellyfin_user_id)
    except ServiceError as exc:
        raise _fail(exc) from exc

    selected = [
        item
        for item in listed
        if item.get("Id") and (not wanted or item["Id"] in wanted)
    ]
    if wanted:
        missing = wanted - {item["Id"] for item in selected}
        if missing:
            raise HTTPException(
                status_code=404, detail="Unknown playlist or it does not belong to this account"
            )

    entries: list[PlaylistBackupEntry] = []
    for item in selected:
        playlist_id = item["Id"]
        try:
            tracks = await client.get_playlist_items(
                playlist_id, token=token, user_id=user.jellyfin_user_id
            )
        except ServiceError as exc:
            raise _fail(exc) from exc
        albums = _albums_by_jellyfin_id(
            session, {row.get("AlbumId") for row in tracks if row.get("AlbumId")}
        )
        entries.append(
            PlaylistBackupEntry(
                name=item.get("Name") or "",
                owner=user.name,
                tracks=[
                    _backup_track(row, albums.get(row.get("AlbumId") or ""))
                    for row in tracks
                    if row.get("Id")
                ],
            )
        )
    return PlaylistBackup(version=BACKUP_VERSION, playlists=entries)


@router.post("/import", response_model=PlaylistImportReport)
async def import_playlists(
    payload: PlaylistImportRequest, session: SessionDep, user: CurrentUser
) -> PlaylistImportReport:
    """Recreate playlists from a JSON backup, reporting tracks that could not be found."""
    if payload.version and payload.version != BACKUP_VERSION:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported playlist backup version {payload.version}",
        )
    if not payload.playlists:
        raise HTTPException(status_code=400, detail="The file holds no playlist")

    client = _client(session)
    target_id = (payload.target_user_id or "").strip()
    owner_id = user.jellyfin_user_id or ""
    token: str | None = _token(user)

    if target_id and target_id != owner_id:
        if not user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only an administrator can import into another account",
            )
        target = (
            session.execute(select(User).where(User.jellyfin_user_id == target_id))
            .scalars()
            .first()
        )
        if target is None:
            raise HTTPException(status_code=404, detail="Unknown Jellyfin account")
        if not client.api_key:
            raise HTTPException(
                status_code=400,
                detail="A Jellyfin API key is required to import into another account",
            )
        owner_id = target_id
        token = None

    if not owner_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No Jellyfin session for this account: sign out and sign in again",
        )

    report: list[PlaylistImportResult] = []
    for entry in payload.playlists:
        name = (entry.name or "").strip()
        if not name:
            report.append(
                PlaylistImportResult(
                    name="",
                    missing=[PlaylistImportMissing(reason="a playlist needs a name")],
                )
            )
            continue

        found: list[str] = []
        missing: list[PlaylistImportMissing] = []
        for track in entry.tracks:
            item_id = await _lookup_exported_track(client, track)
            if item_id:
                found.append(item_id)
            else:
                missing.append(
                    PlaylistImportMissing(
                        title=track.title,
                        artist=track.artist,
                        album=track.album,
                        reason=_missing_reason(track),
                    )
                )
        found = list(dict.fromkeys(found))

        try:
            playlist_id = await client.create_playlist(
                name, user_id=owner_id, item_ids=found, token=token
            )
        except ServiceError as exc:
            raise _fail(exc) from exc

        report.append(
            PlaylistImportResult(
                name=name, playlist_id=playlist_id, added=len(found), missing=missing
            )
        )
    return PlaylistImportReport(playlists=report)


@router.get("", response_model=list[PlaylistOut])
async def list_playlists(session: SessionDep, user: CurrentUser) -> list[PlaylistOut]:
    client = _client(session)
    try:
        items = await client.get_playlists(token=_token(user), user_id=user.jellyfin_user_id)
    except ServiceError as exc:
        raise _fail(exc) from exc

    return [
        PlaylistOut(
            id=item.get("Id") or "",
            name=item.get("Name") or "",
            track_count=int(item.get("ChildCount") or 0),
            can_delete=bool(item.get("CanDelete")),
            cover_url=catalog.cover_url(None, None, item.get("Id")),
        )
        for item in items
        if item.get("Id")
    ]


@router.get("/{playlist_id}", response_model=list[PlaylistTrack])
async def playlist_tracks(
    playlist_id: str, session: SessionDep, user: CurrentUser
) -> list[PlaylistTrack]:
    client = _client(session)
    try:
        items = await client.get_playlist_items(
            playlist_id, token=_token(user), user_id=user.jellyfin_user_id
        )
    except ServiceError as exc:
        raise _fail(exc) from exc

    albums = _albums_by_jellyfin_id(
        session, {item.get("AlbumId") for item in items if item.get("AlbumId")}
    )
    tracks: list[PlaylistTrack] = []
    for item in items:
        if not item.get("Id"):
            continue
        album = albums.get(item.get("AlbumId") or "")
        ticks = item.get("RunTimeTicks") or 0
        artists = item.get("Artists") or []
        tracks.append(
            PlaylistTrack(
                jellyfin_id=item["Id"],
                playlist_item_id=item.get("PlaylistItemId") or "",
                title=item.get("Name") or "",
                artist=(artists[0] if artists else "") or item.get("AlbumArtist") or "",
                album=item.get("Album") or (album.name if album else ""),
                album_id=item.get("AlbumId"),
                artist_mbid=album.artist_mbid if album else None,
                track=item.get("IndexNumber"),
                disc=item.get("ParentIndexNumber"),
                duration=round(ticks / 10_000_000, 3) if ticks else None,
                container=(item.get("Container") or "").lower(),
                cover_url=catalog.cover_url(
                    album.release_group_mbid if album else None,
                    album.release_mbid if album else None,
                    item.get("AlbumId"),
                ),
                stream_url=f"/api/play/track/{item['Id']}",
            )
        )
    return tracks


@router.post("", response_model=PlaylistChange, status_code=status.HTTP_201_CREATED)
async def create_playlist(
    payload: PlaylistCreate, session: SessionDep, user: CurrentUser
) -> PlaylistChange:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="A playlist needs a name")

    client = _client(session)
    token = _token(user)
    try:
        ids = await _resolve_tracks(client, payload)
        playlist_id = await client.create_playlist(
            name, token=token, user_id=user.jellyfin_user_id, item_ids=ids
        )
    except ServiceError as exc:
        raise _fail(exc) from exc

    return PlaylistChange(playlist_id=playlist_id, name=name, added=len(ids))


@router.post("/{playlist_id}/items", response_model=PlaylistChange)
async def add_items(
    playlist_id: str, payload: PlaylistAdd, session: SessionDep, user: CurrentUser
) -> PlaylistChange:
    """Add tracks, leaving behind the ones the playlist already holds.

    Jellyfin happily stores the same track twice, so the current contents are
    read first and the repeats are reported rather than filed again.
    """
    client = _client(session)
    token = _token(user)
    try:
        ids = await _resolve_tracks(client, payload)
        if not ids:
            raise HTTPException(status_code=400, detail="Nothing to add")
        current = await client.get_playlist_items(
            playlist_id, token=token, user_id=user.jellyfin_user_id
        )
        held = {item.get("Id") for item in current if item.get("Id")}
        fresh = [item for item in ids if item not in held]
        if fresh:
            await client.add_to_playlist(
                playlist_id, fresh, token=token, user_id=user.jellyfin_user_id
            )
    except ServiceError as exc:
        raise _fail(exc) from exc

    return PlaylistChange(
        playlist_id=playlist_id,
        name="",
        added=len(fresh),
        skipped=len(ids) - len(fresh),
    )


@router.delete("/{playlist_id}/items", status_code=status.HTTP_204_NO_CONTENT)
async def remove_items(
    playlist_id: str, entry_ids: str, session: SessionDep, user: CurrentUser
) -> None:
    entries = [item for item in entry_ids.split(",") if item]
    if not entries:
        raise HTTPException(status_code=400, detail="Nothing to remove")
    client = _client(session)
    try:
        await client.remove_from_playlist(playlist_id, entries, token=_token(user))
    except ServiceError as exc:
        raise _fail(exc) from exc


@router.delete("/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_playlist(playlist_id: str, session: SessionDep, user: CurrentUser) -> None:
    client = _client(session)
    try:
        await client.delete_playlist(playlist_id, token=_token(user))
    except ServiceError as exc:
        raise _fail(exc) from exc
