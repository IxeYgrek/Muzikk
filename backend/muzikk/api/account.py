"""The signed-in listener's own settings.

Administration owns what belongs to the installation; this router owns what
belongs to a person. A ListenBrainz handle or a Last.fm session is personal:
two accounts on one Muzikk have two different tastes and two different listening
histories, so an administrator has no business setting them for somebody else.

Tokens go in encrypted and never come back out. The API only ever reports
whether a service is connected.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, HTTPException, status

from ..schemas import LastfmAuthStart, ListeningAccounts, ListeningAccountsUpdate
from ..services import settings as settings_service
from ..services import users as users_service
from ..services.base import ServiceError, ServiceNotConfigured
from ..services.lastfm import LastfmClient
from ..services.listenbrainz import ListenBrainzClient
from .deps import CurrentUser, SessionDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/account", tags=["account"])


def _snapshot(session: SessionDep, user: CurrentUser) -> ListeningAccounts:
    listenbrainz = settings_service.load(session, "listenbrainz")
    lastfm = settings_service.load(session, "lastfm")
    return ListeningAccounts(
        listenbrainz_enabled=bool(listenbrainz.enabled),
        listenbrainz_user=user.listenbrainz_user,
        listenbrainz_connected=bool(user.listenbrainz_token),
        lastfm_enabled=bool(lastfm.enabled),
        lastfm_user=user.lastfm_user,
        lastfm_connected=bool(user.lastfm_session_key),
        lastfm_can_authorize=bool(lastfm.enabled and lastfm.api_key and lastfm.api_secret),
    )


@router.get("/services", response_model=ListeningAccounts)
async def listening_accounts(session: SessionDep, user: CurrentUser) -> ListeningAccounts:
    return _snapshot(session, user)


@router.put("/services", response_model=ListeningAccounts)
async def update_listening_accounts(
    session: SessionDep, user: CurrentUser, payload: ListeningAccountsUpdate
) -> ListeningAccounts:
    """Save the handles, and the ListenBrainz token when one is supplied.

    A supplied token is checked against ListenBrainz before being stored: a typo
    would otherwise fail silently on every listen from then on.
    """
    token = (payload.listenbrainz_token or "").strip()
    resolved_name: str | None = payload.listenbrainz_user

    if token:
        config = settings_service.load(session, "listenbrainz")
        if not config.enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="ListenBrainz is turned off for this installation",
            )
        client = ListenBrainzClient(config)
        try:
            details = await client.validate_token(token)
        except (ServiceError, ServiceNotConfigured) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            ) from exc
        if not details.get("valid"):
            raise HTTPException(status_code=422, detail="ListenBrainz refused this token")
        # The token knows its own account, which saves the listener typing it.
        resolved_name = details.get("user_name") or payload.listenbrainz_user

    users_service.set_listening_accounts(
        session,
        user,
        listenbrainz_user=resolved_name,
        listenbrainz_token_value=token if token else None,
        lastfm_user=payload.lastfm_user,
    )
    return _snapshot(session, user)


@router.delete("/services/{service}", response_model=ListeningAccounts)
async def disconnect(service: str, session: SessionDep, user: CurrentUser) -> ListeningAccounts:
    if service == "listenbrainz":
        users_service.set_listening_accounts(
            session, user, listenbrainz_user="", listenbrainz_token_value=""
        )
    elif service == "lastfm":
        users_service.set_listening_accounts(
            session, user, lastfm_user="", lastfm_session_key_value=""
        )
    else:
        raise HTTPException(status_code=404, detail="Unknown service")
    return _snapshot(session, user)


# ------------------------------------------------------- Last.fm approval flow


@router.post("/lastfm/authorize", response_model=LastfmAuthStart)
async def start_lastfm_authorization(session: SessionDep, user: CurrentUser) -> LastfmAuthStart:
    """Ask Last.fm for a token and return the page the listener must approve.

    This is the desktop flow rather than the web one on purpose: it needs no
    callback URL registered with Last.fm, which a self-hosted install cannot
    know in advance.
    """
    config = settings_service.load(session, "lastfm")
    if not config.enabled or not config.api_key or not config.api_secret:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An administrator has to register a Last.fm application first",
        )
    client = LastfmClient(config)
    try:
        token = await client.request_token()
    except (ServiceError, ServiceNotConfigured) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    if not token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Last.fm returned no token"
        )
    return LastfmAuthStart(token=token, url=client.authorize_url(token))


@router.post("/lastfm/finish", response_model=ListeningAccounts)
async def finish_lastfm_authorization(
    session: SessionDep, user: CurrentUser, token: str = Body(embed=True)
) -> ListeningAccounts:
    """Exchange the approved token for a session key, and keep it."""
    config = settings_service.load(session, "lastfm")
    if not config.enabled or not config.api_key or not config.api_secret:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An administrator has to register a Last.fm application first",
        )
    client = LastfmClient(config)
    try:
        found = await client.session_for_token(token.strip())
    except (ServiceError, ServiceNotConfigured) as exc:
        # The usual cause is the listener not having approved the page yet.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if not found.get("key"):
        raise HTTPException(status_code=422, detail="Last.fm returned no session")

    users_service.set_listening_accounts(
        session,
        user,
        lastfm_user=found.get("name") or user.lastfm_user or "",
        lastfm_session_key_value=found["key"],
    )
    return _snapshot(session, user)
