"""Playback of the albums already in the library.

Audio never reaches the browser straight from Jellyfin: no Jellyfin token
leaves the server, and a media server only reachable inside the Docker network
keeps working. Sources answer a track in this order: the file itself when the
library folder is mounted here, then Jellyfin for anything a browser cannot
decode. Both honour Range requests, so seeking behaves normally.

In local mode there is no Jellyfin to fall back on, so a container the browser
refuses goes through ffmpeg instead. That stream has no byte index, so seeking
restarts it at the wanted second rather than jumping inside it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LibraryAlbum, LibraryTrack, User
from ..models import Request as AlbumRequest
from ..schemas import PlayableTrack
from ..services import catalog, clients, local_library, localmedia, previews
from ..services import mode as mode_service
from ..services import scrobble as scrobble_service
from ..services import settings as settings_service
from ..services import transcode as transcode_service
from ..services import users as users_service
from ..services.base import ServiceError
from ..services.jellyfin import JellyfinClient
from .deps import CurrentUser, SessionDep, authorize_media

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/play", tags=["play"])

CHUNK_SIZE = 128 * 1024
# Only the headers a media element actually needs.
FORWARDED_HEADERS = (
    "content-type",
    "content-length",
    "content-range",
    "accept-ranges",
    "cache-control",
)
TICKS_PER_MS = 10_000


def _client(session: Session) -> JellyfinClient:
    client = clients.jellyfin(session)
    if not client.configured:
        raise HTTPException(status_code=400, detail="Jellyfin is not configured")
    return client


def _require_enabled(session: Session) -> Any:
    config = settings_service.load(session, "player")
    if not config.enabled:
        raise HTTPException(status_code=403, detail="Playback is disabled")
    return config


def _playback_tokens(user: User, client: JellyfinClient) -> list[str]:
    """Credentials to try, best first.

    The listener's own token comes first so Jellyfin credits the play to the
    right account. The server API key follows: a user who signed in before
    playback existed has no stored token, and a stored token can have been
    revoked since.
    """
    tokens: list[str] = []
    for candidate in (users_service.jellyfin_token(user), client.api_key):
        if candidate and candidate not in tokens:
            tokens.append(candidate)
    if not tokens:
        raise HTTPException(
            status_code=400, detail="No Jellyfin credentials available for playback"
        )
    return tokens


def _to_playable(item: dict[str, Any], album: LibraryAlbum | None) -> PlayableTrack:
    ticks = item.get("RunTimeTicks") or 0
    artists = item.get("Artists") or []
    album_id = item.get("AlbumId")
    return PlayableTrack(
        jellyfin_id=item.get("Id") or "",
        title=item.get("Name") or "",
        artist=(artists[0] if artists else "") or item.get("AlbumArtist") or "",
        album=item.get("Album") or (album.name if album else ""),
        album_id=album_id,
        artist_mbid=album.artist_mbid if album else None,
        track=item.get("IndexNumber"),
        disc=item.get("ParentIndexNumber"),
        duration=round(ticks / 10_000_000, 3) if ticks else None,
        container=(item.get("Container") or "").lower(),
        cover_url=catalog.cover_url(
            album.release_group_mbid if album else None,
            album.release_mbid if album else None,
            album_id,
        ),
        stream_url=f"/api/play/track/{item.get('Id')}",
    )


def _local_file(session: Session, row: LibraryTrack) -> Path | None:
    """The file behind an indexed track, if it is still where the scan saw it."""
    naming = settings_service.load(session, "naming")
    path = localmedia.resolve(row.path, naming.music_dir)
    if path is None or localmedia.file_size(path) <= 0:
        return None
    return path


def _local_playable(session: Session, row: LibraryTrack, album: LibraryAlbum | None) -> PlayableTrack:
    config = settings_service.load(session, "player")
    path = Path(row.path)
    native = localmedia.is_browser_playable(path)
    return PlayableTrack(
        jellyfin_id=row.item_id,
        title=row.title,
        artist=row.artist or (album.album_artist if album else ""),
        album=row.album or (album.name if album else ""),
        album_id=row.album_item_id,
        artist_mbid=album.artist_mbid if album else None,
        track=row.track,
        disc=row.disc,
        duration=row.duration,
        container=row.container,
        cover_url=catalog.cover_url(
            album.release_group_mbid if album else None,
            album.release_mbid if album else None,
            row.album_item_id,
        ),
        # The browser cannot seek inside a re-encoded stream, so it has to be
        # told which tracks are one before it draws a seek bar it can trust.
        transcoded=not native and config.transcode and transcode_service.available(),
        playable=native or (config.transcode and transcode_service.available()),
        stream_url=f"/api/play/track/{row.item_id}",
    )


@router.get("/album/{album_id}", response_model=list[PlayableTrack])
async def album_queue(
    album_id: str, session: SessionDep, user: CurrentUser
) -> list[PlayableTrack]:
    """The play queue of one library album, in track order."""
    _require_enabled(session)

    if mode_service.is_local(session):
        album = (
            session.execute(select(LibraryAlbum).where(LibraryAlbum.jellyfin_id == album_id))
            .scalars()
            .first()
        )
        return [
            _local_playable(session, row, album)
            for row in local_library.album_tracks(session, album_id)
        ]

    client = _client(session)
    try:
        items = await client.get_album_tracks(album_id)
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    album = (
        session.execute(select(LibraryAlbum).where(LibraryAlbum.jellyfin_id == album_id))
        .scalars()
        .first()
    )
    tracks = [_to_playable(item, album) for item in items if item.get("Id")]
    tracks.sort(key=lambda item: (item.disc or 1, item.track or 999, item.title))
    return tracks


@router.get("/track/{item_id}/info", response_model=PlayableTrack)
async def track_info(item_id: str, session: SessionDep, user: CurrentUser) -> PlayableTrack:
    _require_enabled(session)

    if mode_service.is_local(session):
        row = local_library.find_track(session, item_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Unknown track")
        album = (
            session.execute(
                select(LibraryAlbum).where(LibraryAlbum.jellyfin_id == row.album_item_id)
            )
            .scalars()
            .first()
        )
        return _local_playable(session, row, album)

    client = _client(session)
    try:
        item = await client.get_item(item_id)
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc
    if not item:
        raise HTTPException(status_code=404, detail="Unknown track")

    album_id = item.get("AlbumId")
    album = (
        session.execute(select(LibraryAlbum).where(LibraryAlbum.jellyfin_id == album_id))
        .scalars()
        .first()
        if album_id
        else None
    )
    return _to_playable(item, album)


def _local_track(session: Session, item: dict[str, Any]) -> Path | None:
    """The file behind a Jellyfin track, if Muzikk can read it too."""
    naming = settings_service.load(session, "naming")
    path = localmedia.resolve(item.get("Path"), naming.music_dir)
    if path is None or not localmedia.is_browser_playable(path):
        return None
    # A zero byte file is a failed copy: let Jellyfin answer instead.
    return path if localmedia.file_size(path) > 0 else None


def _serve_local(path: Path, request: Request) -> StreamingResponse:
    """Send the file straight from disk, honouring Range so seeking works."""
    size = localmedia.file_size(path)
    window = localmedia.parse_range(request.headers.get("range"), size)
    start, end = window if window else (0, max(size - 1, 0))

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Cache-Control": "private, max-age=3600",
    }
    if window:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"

    return StreamingResponse(
        localmedia.read_range(path, start, end, CHUNK_SIZE),
        status_code=status.HTTP_206_PARTIAL_CONTENT if window else status.HTTP_200_OK,
        headers=headers,
        media_type=localmedia.content_type(path),
    )


def review_file_path(review: dict[str, Any] | None, side: str, index: int) -> str | None:
    """The stored path of one file in an upgrade comparison.

    The browser only sends a side and an index: the filesystem path never
    leaves the review JSON the pipeline already wrote.
    """
    if not isinstance(review, dict) or side not in {"old", "new"}:
        return None
    files = review.get("old_files" if side == "old" else "new_files") or []
    if not isinstance(files, list) or index < 0 or index >= len(files):
        return None
    entry = files[index]
    if not isinstance(entry, dict):
        return None
    path = entry.get("path")
    return path.strip() if isinstance(path, str) and path.strip() else None


def _owned_request(session: Session, request_id: int, user: User) -> AlbumRequest:
    request = session.get(AlbumRequest, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if not user.is_admin and request.user_id != user.id:
        raise HTTPException(status_code=403, detail="This request belongs to another user")
    return request


def _upgrade_audio(session: Session, request: AlbumRequest, side: str, index: int) -> Path:
    stored = review_file_path(request.upgrade_review, side, index)
    if stored is None:
        raise HTTPException(status_code=404, detail="Unknown file in this comparison")
    naming = settings_service.load(session, "naming")
    path = localmedia.resolve(stored, naming.music_dir)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="File is no longer available")
    if not localmedia.is_browser_playable(path):
        raise HTTPException(status_code=415, detail="This format cannot be played in the browser")
    return path


@router.get("/upgrade/{request_id}/{side}/{index}")
async def stream_upgrade(
    request_id: int,
    side: Literal["old", "new"],
    index: int,
    request: Request,
    session: SessionDep,
    token: str | None = Query(default=None),
) -> StreamingResponse:
    """Stream one file of an upgrade comparison, old or new.

    Only the paths already stored on the request can be read: the client
    never chooses a filesystem location.
    """
    user = authorize_media(request, session, token)
    _require_enabled(session)
    album_request = _owned_request(session, request_id, user)
    return _serve_local(_upgrade_audio(session, album_request, side, index), request)


async def _describe_refusal(response: httpx.Response, item_id: str) -> str:
    """Read and close a failed upstream response, keeping its explanation."""
    code = response.status_code
    try:
        body = (await response.aread()).decode("utf-8", "replace").strip()
    except httpx.HTTPError:
        body = ""
    await response.aclose()

    hint = f": {body[:200]}" if body else ""
    if code in (401, 403) and not hint:
        hint = ": the Jellyfin credentials were refused, sign out and sign in again"
    logger.warning("Jellyfin refused to stream %s (HTTP %s)%s", item_id, code, hint)
    return f"Jellyfin refused the stream (HTTP {code}){hint}"


def _serve_transcoded(path: Path, config: Any, start: float) -> StreamingResponse:
    """Re-encode on the fly for a container the browser will not take.

    The response is deliberately not byte addressable: the length is unknown
    until the file has gone through ffmpeg, so a Range request could not be
    answered honestly. The player restarts the stream at an offset instead.
    """
    fmt = config.transcode_format if config.transcode_format in transcode_service.FORMATS else "mp3"
    return StreamingResponse(
        transcode_service.stream(path, fmt=fmt, start=start),
        media_type=transcode_service.content_type(fmt),
        headers={"Accept-Ranges": "none", "Cache-Control": "no-store"},
    )


def _stream_local_track(
    session: Session, item_id: str, request: Request, config: Any, start: float
) -> StreamingResponse:
    row = local_library.find_track(session, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown track")

    path = _local_file(session, row)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail="This file is no longer where the last scan saw it; run a library scan",
        )

    if localmedia.is_browser_playable(path):
        return _serve_local(path, request)
    if not config.transcode:
        raise HTTPException(
            status_code=415,
            detail=f"A {path.suffix.lstrip('.').upper()} file cannot be played in a browser, "
            "and transcoding is switched off",
        )
    if not transcode_service.available():
        raise HTTPException(
            status_code=503, detail="ffmpeg is missing, this format cannot be transcoded"
        )
    return _serve_transcoded(path, config, start)


@router.get("/track/{item_id}")
async def stream_track(
    item_id: str,
    request: Request,
    session: SessionDep,
    token: str | None = Query(default=None),
    start: float = Query(default=0.0, ge=0, description="Seconds to skip in a transcoded stream"),
) -> StreamingResponse:
    """Stream one track, from disk when possible and through Jellyfin otherwise.

    Reading the file directly avoids a round trip and every Jellyfin playback
    quirk (session policy, transcoding profile, expired token); the proxy stays
    for the containers a browser cannot decode and for a library Muzikk only
    sees through Jellyfin. Without Jellyfin, ffmpeg takes that last role.
    """
    user = authorize_media(request, session, token)
    config = _require_enabled(session)

    if mode_service.is_local(session):
        return _stream_local_track(session, item_id, request, config, start)

    client = _client(session)

    item: dict[str, Any] = {}
    try:
        item = await client.get_item(item_id)
    except ServiceError as exc:
        # A metadata hiccup must not make the track unplayable: the proxy below
        # only needs the identifier.
        logger.debug("Jellyfin did not describe track %s: %s", item_id, exc.message)
    else:
        if not item:
            raise HTTPException(status_code=404, detail="Unknown track")

    if config.direct_file_access:
        local = _local_track(session, item)
        if local is not None:
            return _serve_local(local, request)

    headers = {}
    if request.headers.get("range"):
        headers["Range"] = request.headers["range"]

    http = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=15.0), follow_redirects=True)
    response: httpx.Response | None = None
    refusal = ""

    for candidate in _playback_tokens(user, client):
        upstream = client.stream_url(item_id, token=candidate, max_bitrate=config.max_bitrate)
        try:
            attempt = await http.send(
                http.build_request("GET", upstream, headers=headers), stream=True
            )
        except httpx.HTTPError as exc:
            await http.aclose()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Jellyfin unreachable: {exc}"
            ) from exc

        if attempt.status_code < 400:
            response = attempt
            break

        refusal = await _describe_refusal(attempt, item_id)
        # An expired personal token is worth retrying with the server key.
        if attempt.status_code not in (401, 403):
            break

    if response is None:
        await http.aclose()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=refusal)

    async def body():
        try:
            async for chunk in response.aiter_bytes(CHUNK_SIZE):
                yield chunk
        finally:
            await response.aclose()
            await http.aclose()

    passthrough = {
        key: value
        for key, value in response.headers.items()
        if key.lower() in FORWARDED_HEADERS
    }
    passthrough.setdefault("Accept-Ranges", "bytes")
    return StreamingResponse(
        body(),
        status_code=response.status_code,
        headers=passthrough,
        media_type=response.headers.get("content-type", "audio/mpeg"),
    )


def _preview_country(session: Session) -> str:
    """Which iTunes store to ask, guessed from the interface language."""
    language = (settings_service.load(session, "general").default_language or "en").strip()
    return (language[:2] or "fr").upper()


async def _find_preview(session: Session, artist: str, title: str, album: str) -> previews.Preview:
    config = _require_enabled(session)
    if not config.previews:
        raise HTTPException(status_code=403, detail="Previews are disabled")
    found = await previews.find(
        artist, title, album=album or None, country=_preview_country(session)
    )
    if found is None:
        raise HTTPException(status_code=404, detail="No preview found for this track")
    return found


@router.get("/preview", response_model=PlayableTrack)
async def preview_track(
    session: SessionDep,
    user: CurrentUser,
    title: str = Query(min_length=1, max_length=300),
    artist: str = Query(default="", max_length=300),
    album: str = Query(default="", max_length=300),
    cover_url: str = Query(default="", max_length=500),
) -> PlayableTrack:
    """A thirty second extract of a track nobody owns yet.

    The queue entry carries no Jellyfin identifier, which is what tells the
    player it is listening to an extract: nothing to report, nothing to seek in
    a library that does not hold this album.

    The sleeve is the one the caller was already showing. Deezer hands out one
    too, but displaying it would have the browser fetch an image from Deezer,
    which is exactly what relaying the audio avoids.
    """
    found = await _find_preview(session, artist, title, album)
    query = urlencode({"artist": artist, "title": title, "album": album})
    return PlayableTrack(
        jellyfin_id="",
        title=found.title or title,
        artist=found.artist or artist,
        album=found.album or album,
        duration=previews.PREVIEW_SECONDS,
        container="mp3" if found.source == "deezer" else "m4a",
        cover_url=cover_url if cover_url.startswith("/api/") else None,
        preview=found.source,
        stream_url=f"/api/play/preview/stream?{query}",
    )


@router.get("/preview/stream")
async def stream_preview(
    request: Request,
    session: SessionDep,
    title: str = Query(min_length=1, max_length=300),
    artist: str = Query(default="", max_length=300),
    album: str = Query(default="", max_length=300),
    token: str | None = Query(default=None),
) -> StreamingResponse:
    """Relay the extract, so the browser never talks to Deezer or Apple itself.

    The lookup is repeated rather than trusted from the caller: an audio
    element can only pass a query string, and a server that fetches whatever
    URL it is handed is a server that can be pointed at anything.
    """
    authorize_media(request, session, token)
    found = await _find_preview(session, artist, title, album)
    if not previews.host_allowed(found.url):
        logger.warning("Preview host refused: %s", found.url)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Unexpected host")

    headers = {}
    if request.headers.get("range"):
        headers["Range"] = request.headers["range"]

    http = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=15.0), follow_redirects=True)
    try:
        upstream = await http.send(
            http.build_request("GET", found.url, headers=headers), stream=True
        )
    except httpx.HTTPError as exc:
        await http.aclose()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"{found.source} unreachable: {exc}"
        ) from exc

    if upstream.status_code >= 400:
        code = upstream.status_code
        await upstream.aclose()
        await http.aclose()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{found.source} refused the extract (HTTP {code})",
        )

    async def body():
        try:
            async for chunk in upstream.aiter_bytes(CHUNK_SIZE):
                yield chunk
        finally:
            await upstream.aclose()
            await http.aclose()

    passthrough = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() in FORWARDED_HEADERS
    }
    passthrough.setdefault("Accept-Ranges", "bytes")
    # The extract changes as rarely as the track does, but its URL is signed:
    # let the browser keep it for the length of a listening session, no more.
    passthrough["Cache-Control"] = "private, max-age=600"
    return StreamingResponse(
        body(),
        status_code=upstream.status_code,
        headers=passthrough,
        media_type=upstream.headers.get("content-type", found.content_type),
    )


async def _listen_for(session: Session, item_id: str) -> scrobble_service.Listen | None:
    """Describe a track well enough to scrobble it.

    Resolved from whichever index this install has, and only on the stages that
    need it: doing it on every progress tick would query Jellyfin once every few
    seconds for a name that has not changed.
    """
    if mode_service.is_local(session):
        row = local_library.find_track(session, item_id)
        if row is None:
            return None
        album = (
            session.execute(
                select(LibraryAlbum).where(LibraryAlbum.jellyfin_id == row.album_item_id)
            )
            .scalars()
            .first()
        )
        return scrobble_service.Listen(
            artist=row.artist or (album.album_artist if album else ""),
            title=row.title,
            album=row.album or (album.name if album else ""),
            duration=row.duration,
            recording_mbid=row.recording_mbid,
            release_mbid=album.release_mbid if album else None,
            artist_mbid=album.artist_mbid if album else None,
        )

    client = clients.jellyfin(session)
    if not client.configured:
        return None
    try:
        item = await client.get_item(item_id)
    except ServiceError:
        return None
    if not item:
        return None

    album_id = item.get("AlbumId")
    album = (
        session.execute(select(LibraryAlbum).where(LibraryAlbum.jellyfin_id == album_id))
        .scalars()
        .first()
        if album_id
        else None
    )
    artists = item.get("Artists") or []
    ticks = item.get("RunTimeTicks") or 0
    providers = item.get("ProviderIds") or {}
    return scrobble_service.Listen(
        artist=(artists[0] if artists else "") or item.get("AlbumArtist") or "",
        title=item.get("Name") or "",
        album=item.get("Album") or (album.name if album else ""),
        duration=round(ticks / 10_000_000, 3) if ticks else None,
        recording_mbid=(providers.get("MusicBrainzTrack") or providers.get("MusicBrainzRecording") or "").lower()
        or None,
        release_mbid=album.release_mbid if album else None,
        artist_mbid=album.artist_mbid if album else None,
    )


@router.post("/report")
async def report(
    session: SessionDep,
    user: CurrentUser,
    item_id: str = Query(min_length=1),
    stage: str = Query(pattern="^(start|progress|stop)$"),
    position_ms: int = Query(default=0, ge=0),
    paused: bool = Query(default=False),
) -> dict[str, Any]:
    """Mirror the playback state into Jellyfin, and scrobble the listen.

    The two are independent. Jellyfin only hears about a play when this install
    runs on it; the listening services hear about it in either mode, because
    they belong to the listener rather than to the library.
    """
    config = _require_enabled(session)
    result: dict[str, Any] = {"reported": False, "listenbrainz": False, "lastfm": False}

    if config.report_playback and not mode_service.is_local(session):
        token = users_service.jellyfin_token(user)
        # Reporting under the server API key would credit the wrong account.
        if token:
            payload = {
                "ItemId": item_id,
                "PositionTicks": position_ms * TICKS_PER_MS,
                "PlayMethod": "DirectStream",
                "IsPaused": paused,
                "CanSeek": True,
            }
            try:
                await _client(session).report_playback(stage, payload, token=token)
                result["reported"] = True
            except ServiceError as exc:
                logger.debug("Playback reporting failed: %s", exc.message)

    if stage == "progress" or not (user.listenbrainz_token or user.lastfm_session_key):
        return result

    listen = await _listen_for(session, item_id)
    if listen is None:
        return result

    if stage == "start":
        result.update(await scrobble_service.announce(session, user, listen))
    else:
        result.update(await scrobble_service.submit(session, user, listen, position_ms=position_ms))
    return result
