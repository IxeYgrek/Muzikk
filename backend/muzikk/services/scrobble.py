"""Sending what is being played to the listening services.

Both services get the same listen, independently: one being down, misconfigured
or simply not set up by this listener must never stop the other, and neither may
ever break playback. Every failure here is logged and swallowed.

What counts as a listen is Last.fm's rule, applied to both so that the two
histories agree: the track has to be at least thirty seconds long, and has to
have played past half its length, or four minutes, whichever comes first.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..models import User
from . import settings as settings_service
from . import users as users_service
from .lastfm import MIN_SCROBBLE_SECONDS, LastfmClient
from .listenbrainz import ListenBrainzClient

logger = logging.getLogger(__name__)

# Past this, a long track has been listened to whatever its length.
LISTEN_CEILING_SECONDS = 4 * 60


@dataclass(slots=True)
class Listen:
    """One track, described the way both services want to receive it."""

    artist: str
    title: str
    album: str = ""
    duration: float | None = None
    recording_mbid: str | None = None
    release_mbid: str | None = None
    artist_mbid: str | None = None

    @property
    def playable(self) -> bool:
        return bool(self.artist.strip() and self.title.strip())


def counts_as_listen(listen: Listen, position_ms: int) -> bool:
    """Whether enough of the track played for the services to accept it."""
    duration = listen.duration or 0
    if duration and duration < MIN_SCROBBLE_SECONDS:
        return False
    played = position_ms / 1000
    if not duration:
        # An unknown length still deserves a listen once it has clearly played.
        return played >= MIN_SCROBBLE_SECONDS
    return played >= min(duration / 2, LISTEN_CEILING_SECONDS)


def _targets(session: Session, user: User) -> tuple[str, str]:
    """The listener's credentials, empty when they have not connected a service."""
    return users_service.listenbrainz_token(user), users_service.lastfm_session_key(user)


async def announce(session: Session, user: User, listen: Listen) -> dict[str, bool]:
    """Tell both services what is playing right now."""
    if not listen.playable:
        return {"listenbrainz": False, "lastfm": False}

    token, session_key = _targets(session, user)
    sent = {"listenbrainz": False, "lastfm": False}

    if token:
        config = settings_service.load(session, "listenbrainz")
        if config.enabled and config.submit_listens:
            client = ListenBrainzClient(config)
            try:
                await client.submit_listen(
                    token,
                    artist=listen.artist,
                    title=listen.title,
                    album=listen.album,
                    recording_mbid=listen.recording_mbid,
                    release_mbid=listen.release_mbid,
                    artist_mbid=listen.artist_mbid,
                    duration=listen.duration,
                    playing_now=True,
                )
                sent["listenbrainz"] = True
            except Exception as exc:  # noqa: BLE001 - playback must not care
                logger.debug("ListenBrainz now-playing failed: %s", exc)

    if session_key:
        config = settings_service.load(session, "lastfm")
        if config.enabled and config.submit_listens:
            client = LastfmClient(config)
            try:
                await client.now_playing(
                    session_key,
                    artist=listen.artist,
                    title=listen.title,
                    album=listen.album,
                    duration=listen.duration,
                )
                sent["lastfm"] = True
            except Exception as exc:  # noqa: BLE001
                logger.debug("Last.fm now-playing failed: %s", exc)

    return sent


async def submit(
    session: Session, user: User, listen: Listen, *, position_ms: int
) -> dict[str, bool]:
    """Record a finished listen, if enough of the track actually played."""
    sent = {"listenbrainz": False, "lastfm": False}
    if not listen.playable or not counts_as_listen(listen, position_ms):
        return sent

    token, session_key = _targets(session, user)
    # Both services timestamp the listen, so they have to agree on when it was.
    listened_at = int(time.time())
    tasks: list[asyncio.Future[None]] = []
    names: list[str] = []

    if token:
        config = settings_service.load(session, "listenbrainz")
        if config.enabled and config.submit_listens:
            client = ListenBrainzClient(config)
            tasks.append(
                asyncio.ensure_future(
                    client.submit_listen(
                        token,
                        artist=listen.artist,
                        title=listen.title,
                        album=listen.album,
                        recording_mbid=listen.recording_mbid,
                        release_mbid=listen.release_mbid,
                        artist_mbid=listen.artist_mbid,
                        duration=listen.duration,
                        listened_at=listened_at,
                    )
                )
            )
            names.append("listenbrainz")

    if session_key:
        config = settings_service.load(session, "lastfm")
        if config.enabled and config.submit_listens:
            client = LastfmClient(config)
            tasks.append(
                asyncio.ensure_future(
                    client.scrobble(
                        session_key,
                        artist=listen.artist,
                        title=listen.title,
                        album=listen.album,
                        duration=listen.duration,
                        mbid=listen.recording_mbid,
                        listened_at=listened_at,
                    )
                )
            )
            names.append("lastfm")

    if not tasks:
        return sent

    # Sent side by side: the slower service must not delay the other.
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for name, result in zip(names, results, strict=True):
        if isinstance(result, BaseException):
            logger.debug("%s scrobble failed: %s", name, result)
        else:
            sent[name] = True
    return sent
