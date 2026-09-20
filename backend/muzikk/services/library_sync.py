"""Refreshing the library index, whichever scanner this install uses.

The two scanners write the same tables, so everything downstream stays the
same; only the source of the rows differs.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from . import library_index, local_library
from . import mode as mode_service


async def sync(session: Session) -> dict[str, Any]:
    if mode_service.is_local(session):
        return await local_library.scan_library(session)
    return await library_index.sync_library(session)
