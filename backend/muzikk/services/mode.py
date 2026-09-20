"""Which user and library backend this installation was built on.

Muzikk runs either against Jellyfin, which owns the accounts and the music
library, or entirely on its own, with local passwords and a library it scans
itself. The choice belongs to the first run wizard and is never revisited: a
Jellyfin account carries no password Muzikk could keep, and a local account
carries no Jellyfin identity, so converting one install into the other would
quietly lock everybody out.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from . import settings as settings_service

JELLYFIN = "jellyfin"
LOCAL = "local"
MODES = (JELLYFIN, LOCAL)


def current(session: Session) -> str:
    """The active mode.

    Installations created before the local mode existed have nothing stored
    and were necessarily built on Jellyfin, hence the default. An unknown
    value is treated the same way rather than raising: locking an
    administrator out of their own server over a typo in the database would be
    a poor trade.
    """
    value = getattr(settings_service.load(session, "general"), "mode", JELLYFIN)
    return value if value in MODES else JELLYFIN


def is_local(session: Session) -> bool:
    return current(session) == LOCAL


def is_jellyfin(session: Session) -> bool:
    return current(session) == JELLYFIN
