"""Album requests: creation, moderation and follow-up."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Request, RequestStatus, User
from ..schemas import (
    DownloadAttemptOut,
    DownloadOut,
    RequestCreate,
    RequestDetail,
    RequestEventOut,
    RequestListResponse,
    RequestOut,
)
from ..services import catalog, clients
from ..services import requests as requests_service
from ..services import settings as settings_service
from ..services.base import ServiceError
from .deps import AdminUser, CurrentUser, SessionDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/requests", tags=["requests"])


def _to_out(session: Session, request: Request) -> RequestOut:
    payload = RequestOut.model_validate(request)
    payload.cover_url = catalog.cover_url(request.release_group_mbid, request.release_mbid)
    user = session.get(User, request.user_id)
    payload.user_name = user.name if user else None
    return payload


def _load(session: Session, request_id: int, user: User) -> Request:
    request = session.get(Request, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if not user.is_admin and request.user_id != user.id:
        raise HTTPException(status_code=403, detail="This request belongs to another user")
    return request


@router.post("", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
async def create(payload: RequestCreate, session: SessionDep, user: CurrentUser) -> RequestOut:
    try:
        request = await requests_service.create_request(
            session,
            user,
            payload.release_group_mbid,
            release_mbid=payload.release_mbid,
            is_upgrade=payload.is_upgrade,
        )
    except requests_service.RequestError as exc:
        code = status.HTTP_400_BAD_REQUEST
        if exc.code == "forbidden":
            code = status.HTTP_403_FORBIDDEN
        elif exc.code == "quota_exceeded":
            code = status.HTTP_429_TOO_MANY_REQUESTS
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    return _to_out(session, request)


@router.get("", response_model=RequestListResponse)
async def list_requests(
    session: SessionDep,
    user: CurrentUser,
    status_filter: str | None = Query(default=None, alias="status"),
    mine: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> RequestListResponse:
    statement = select(Request)
    count_statement = select(func.count()).select_from(Request)
    conditions = []

    if mine or not user.is_admin:
        conditions.append(Request.user_id == user.id)
    if status_filter:
        if status_filter == "active":
            conditions.append(Request.status.in_(RequestStatus.ACTIVE))
        elif status_filter == "open":
            conditions.append(
                Request.status.in_(
                    (RequestStatus.PENDING, RequestStatus.APPROVED, *RequestStatus.ACTIVE)
                )
            )
        else:
            conditions.append(Request.status == status_filter)

    for condition in conditions:
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)

    total = session.execute(count_statement).scalar() or 0
    rows = (
        session.execute(statement.order_by(Request.id.desc()).limit(limit).offset(offset))
        .scalars()
        .all()
    )
    return RequestListResponse(
        count=total, offset=offset, items=[_to_out(session, row) for row in rows]
    )


def _own_or_all(statement, user: User):
    """Restrict a bulk action to the caller unless they administer Muzikk."""
    return statement if user.is_admin else statement.where(Request.user_id == user.id)


@router.delete("/imported")
async def clear_imported(session: SessionDep, user: CurrentUser) -> dict[str, int]:
    """Drop the requests that reached the library.

    Declared before the ``/{request_id}`` routes, otherwise the path parameter
    would try to read "imported" as an identifier.
    """
    statement = _own_or_all(select(Request).where(Request.status == RequestStatus.IMPORTED), user)
    rows = session.execute(statement).scalars().all()
    for request in rows:
        session.delete(request)
    session.commit()
    return {"removed": len(rows)}


@router.delete("/failed")
async def clear_failed(session: SessionDep, user: CurrentUser) -> dict[str, int]:
    """Drop the requests nothing could be found for."""
    statement = _own_or_all(select(Request).where(Request.status == RequestStatus.FAILED), user)
    rows = session.execute(statement).scalars().all()
    for request in rows:
        session.delete(request)
    session.commit()
    return {"removed": len(rows)}


@router.post("/retry-failed")
async def retry_failed(session: SessionDep, user: CurrentUser) -> dict[str, int]:
    """Queue a new attempt for every request nothing could be found for.

    The retry delay is ignored here: someone asked for it by hand. The worker
    picks them up one after the other, so nothing runs in parallel.
    """
    statement = _own_or_all(select(Request).where(Request.status == RequestStatus.FAILED), user)
    rows = session.execute(statement.order_by(Request.id.asc())).scalars().all()
    for request in rows:
        requests_service.retry_request(session, request)
    return {"requeued": len(rows)}


@router.post("/cancel-active")
async def cancel_active(session: SessionDep, user: CurrentUser) -> dict[str, int]:
    """Close everything still on its way.

    A transfer already running is not killed here: the pipeline notices the
    cancellation at its next progress check and aborts it then.
    """
    statement = _own_or_all(
        select(Request).where(
            Request.status.in_(
                (RequestStatus.PENDING, RequestStatus.APPROVED, *RequestStatus.ACTIVE)
            )
        ),
        user,
    )
    rows = session.execute(statement).scalars().all()
    for request in rows:
        requests_service.cancel_request(session, request)
    return {"cancelled": len(rows)}


@router.get("/{request_id}", response_model=RequestDetail)
async def detail(request_id: int, session: SessionDep, user: CurrentUser) -> RequestDetail:
    request = _load(session, request_id, user)
    payload = RequestDetail.model_validate(_to_out(session, request).model_dump())
    payload.events = [RequestEventOut.model_validate(event) for event in request.events]
    payload.attempts_log = [
        DownloadAttemptOut.model_validate(attempt) for attempt in request.attempts_log
    ]
    payload.downloads = [DownloadOut.model_validate(download) for download in request.downloads]
    payload.upgrade_review = request.upgrade_review
    return payload


@router.post("/{request_id}/approve", response_model=RequestOut)
async def approve(request_id: int, session: SessionDep, admin: AdminUser) -> RequestOut:
    request = session.get(Request, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    try:
        requests_service.approve_request(session, request, admin)
    except requests_service.RequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(session, request)


@router.post("/{request_id}/reject", response_model=RequestOut)
async def reject(
    request_id: int,
    session: SessionDep,
    admin: AdminUser,
    reason: str = Query(default="", max_length=500),
) -> RequestOut:
    request = session.get(Request, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    try:
        requests_service.reject_request(session, request, admin, reason)
    except requests_service.RequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(session, request)


@router.post("/{request_id}/retry", response_model=RequestOut)
async def retry(request_id: int, session: SessionDep, user: CurrentUser) -> RequestOut:
    request = _load(session, request_id, user)
    if request.status in RequestStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="This request is already running")
    requests_service.retry_request(session, request)
    return _to_out(session, request)


@router.post("/{request_id}/cancel", response_model=RequestOut)
async def cancel(request_id: int, session: SessionDep, user: CurrentUser) -> RequestOut:
    request = _load(session, request_id, user)
    if request.status in RequestStatus.TERMINAL:
        raise HTTPException(status_code=400, detail="This request is already closed")
    requests_service.cancel_request(session, request)
    return _to_out(session, request)


async def _rescan_library(session: Session) -> None:
    """Tell Jellyfin the folder changed, without making the caller wait on it."""
    jellyfin_settings = settings_service.load(session, "jellyfin")
    client = clients.jellyfin(session)
    if not jellyfin_settings.trigger_scan_on_import or not client.api_key:
        return
    try:
        await client.refresh_library()
    except ServiceError as exc:
        logger.warning("Unable to trigger the Jellyfin scan: %s", exc.message)


@router.post("/{request_id}/upgrade/confirm", response_model=RequestOut)
async def confirm_upgrade(request_id: int, session: SessionDep, user: CurrentUser) -> RequestOut:
    """Accept the new release and delete the copy it replaces."""
    request = _load(session, request_id, user)
    try:
        requests_service.resolve_upgrade(session, request, accept=True)
    except requests_service.RequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _rescan_library(session)
    return _to_out(session, request)


@router.post("/{request_id}/upgrade/refuse", response_model=RequestOut)
async def refuse_upgrade(request_id: int, session: SessionDep, user: CurrentUser) -> RequestOut:
    """Refuse the new release and delete it instead of the older copy."""
    request = _load(session, request_id, user)
    try:
        requests_service.resolve_upgrade(session, request, accept=False)
    except requests_service.RequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _rescan_library(session)
    return _to_out(session, request)


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(request_id: int, session: SessionDep, admin: AdminUser) -> None:
    request = session.get(Request, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    session.delete(request)
    session.commit()
