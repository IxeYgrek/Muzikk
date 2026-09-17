"""Factories building service clients from the stored settings."""

from __future__ import annotations

from sqlalchemy.orm import Session

from . import settings as settings_service
from .coverart import CoverArtClient
from .jellyfin import JellyfinClient
from .musicbrainz import MusicBrainzClient


def jellyfin(session: Session) -> JellyfinClient:
    return JellyfinClient(settings_service.load(session, "jellyfin"))


def musicbrainz(session: Session) -> MusicBrainzClient:
    return MusicBrainzClient(settings_service.load(session, "musicbrainz"))


def coverart(session: Session) -> CoverArtClient:
    return CoverArtClient(settings_service.load(session, "coverart"))
