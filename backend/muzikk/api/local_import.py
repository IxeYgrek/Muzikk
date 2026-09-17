"""Upload a local album folder and write it into the library."""

from __future__ import annotations

import logging
from typing import NoReturn

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from ..schemas import (
    LocalImportCommitRequest,
    LocalImportManualRequest,
    LocalImportMatchRequest,
    LocalImportSearchRequest,
    LocalImportSessionOut,
)
from ..services import clients, local_import
from ..services import settings as settings_service
from ..services.base import ServiceError
from .deps import ImportUser, SessionDep, authorize_media

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/local-import", tags=["local-import"])


def _out(state: local_import.ImportState) -> LocalImportSessionOut:
    return LocalImportSessionOut.model_validate(local_import.session_out(state))


def _raise(exc: local_import.LocalImportError) -> NoReturn:
    status = 404 if exc.code == "not_found" else 403 if exc.code == "forbidden" else 400
    raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post("/sessions", response_model=LocalImportSessionOut)
async def create_session(user: ImportUser) -> LocalImportSessionOut:
    return _out(local_import.create_session(user.id))


@router.get("/sessions/{session_id}", response_model=LocalImportSessionOut)
async def get_session(session_id: str, user: ImportUser) -> LocalImportSessionOut:
    try:
        return _out(local_import.load_session(user.id, session_id))
    except local_import.LocalImportError as exc:
        _raise(exc)


@router.delete("/sessions/{session_id}", status_code=204)
async def drop_session(session_id: str, user: ImportUser) -> None:
    local_import.delete_session(user.id, session_id)


@router.post("/sessions/{session_id}/files", response_model=LocalImportSessionOut)
async def upload_files(
    session_id: str,
    user: ImportUser,
    files: list[UploadFile] = File(),
    paths: list[str] | None = Form(default=None),
) -> LocalImportSessionOut:
    """Receive one batch of files; ``paths`` keeps the original folder layout."""
    names = paths or []
    try:
        for index, uploaded in enumerate(files):
            relative = names[index] if index < len(names) else (uploaded.filename or f"track-{index}")
            data = await uploaded.read()
            local_import.add_file(user.id, session_id, relative, data)
        return _out(local_import.load_session(user.id, session_id))
    except local_import.LocalImportError as exc:
        _raise(exc)


@router.post("/sessions/{session_id}/analyze", response_model=LocalImportSessionOut)
async def analyze_session(
    session_id: str, payload: LocalImportSearchRequest, session: SessionDep, user: ImportUser
) -> LocalImportSessionOut:
    try:
        return _out(await local_import.search(session, user.id, session_id, payload.query))
    except local_import.LocalImportError as exc:
        _raise(exc)


@router.post("/sessions/{session_id}/search", response_model=LocalImportSessionOut)
async def search_session(
    session_id: str, payload: LocalImportSearchRequest, session: SessionDep, user: ImportUser
) -> LocalImportSessionOut:
    try:
        return _out(await local_import.search(session, user.id, session_id, payload.query))
    except local_import.LocalImportError as exc:
        _raise(exc)


@router.post("/sessions/{session_id}/match", response_model=LocalImportSessionOut)
async def match_session(
    session_id: str, payload: LocalImportMatchRequest, session: SessionDep, user: ImportUser
) -> LocalImportSessionOut:
    try:
        return _out(
            await local_import.choose(
                session,
                user.id,
                session_id,
                release_group_mbid=payload.release_group_mbid,
                release_mbid=payload.release_mbid,
                reference=payload.reference,
            )
        )
    except local_import.LocalImportError as exc:
        _raise(exc)


@router.post("/sessions/{session_id}/manual", response_model=LocalImportSessionOut)
async def manual_session(
    session_id: str, payload: LocalImportManualRequest, session: SessionDep, user: ImportUser
) -> LocalImportSessionOut:
    try:
        return _out(
            local_import.set_manual(
                session,
                user.id,
                session_id,
                artist=payload.artist,
                album=payload.album,
                year=payload.year,
            )
        )
    except local_import.LocalImportError as exc:
        _raise(exc)


@router.post("/sessions/{session_id}/cover", response_model=LocalImportSessionOut)
async def upload_cover(
    session_id: str, user: ImportUser, file: UploadFile = File()
) -> LocalImportSessionOut:
    data = await file.read()
    try:
        return _out(local_import.set_cover(user.id, session_id, data))
    except local_import.LocalImportError as exc:
        _raise(exc)


@router.get("/sessions/{session_id}/cover")
async def session_cover(
    session_id: str,
    request: Request,
    session: SessionDep,
    token: str | None = Query(default=None),
) -> Response:
    user = authorize_media(request, session, token)
    if not user.can_import:
        raise HTTPException(status_code=403, detail="Local import is not allowed for this account")
    data = local_import.read_cover(user.id, session_id)
    if not data:
        raise HTTPException(status_code=404, detail="No cover yet")
    return Response(content=data, media_type="image/jpeg")


@router.post("/sessions/{session_id}/commit", response_model=LocalImportSessionOut)
async def commit_session(
    session_id: str, payload: LocalImportCommitRequest, session: SessionDep, user: ImportUser
) -> LocalImportSessionOut:
    try:
        state = await local_import.commit(
            session, user.id, session_id, confirm_upgrade=payload.confirm_upgrade
        )
    except local_import.LocalImportError as exc:
        _raise(exc)

    jellyfin_settings = settings_service.load(session, "jellyfin")
    client = clients.jellyfin(session)
    if jellyfin_settings.trigger_scan_on_import and client.api_key:
        try:
            await client.refresh_library()
        except ServiceError as exc:
            logger.warning("Unable to trigger the Jellyfin scan: %s", exc.message)
    return _out(state)
