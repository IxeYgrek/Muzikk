"""Mirror of the Prowlarr indexer list with Muzikk specific settings."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Indexer, utcnow
from ..providers.prowlarr import ProwlarrClient, group_for_privacy
from . import settings as settings_service

logger = logging.getLogger(__name__)


def _music_capable(indexer: dict[str, Any]) -> bool:
    capabilities = indexer.get("capabilities") or {}
    if capabilities.get("musicSearchParams"):
        return True
    for category in capabilities.get("categories") or []:
        if int(category.get("id") or 0) // 1000 == 3:
            return True
        for sub in category.get("subCategories") or []:
            if int(sub.get("id") or 0) // 1000 == 3:
                return True
    return False


def _music_categories(indexer: dict[str, Any]) -> list[int]:
    found: set[int] = set()
    capabilities = indexer.get("capabilities") or {}
    for category in capabilities.get("categories") or []:
        for candidate in [category, *(category.get("subCategories") or [])]:
            value = int(candidate.get("id") or 0)
            if value // 1000 == 3:
                found.add(value)
    return sorted(found)


def _initial_priority(prowlarr_priority: Any) -> int:
    """Prowlarr uses 1 as the best priority; Muzikk sorts by descending value."""
    try:
        value = int(prowlarr_priority)
    except (TypeError, ValueError):
        return 50
    return max(1, min(100, 51 - value))


async def sync_indexers(session: Session) -> dict[str, int]:
    prowlarr_settings = settings_service.load(session, "prowlarr")
    client = ProwlarrClient(prowlarr_settings)
    if not client.configured:
        raise RuntimeError("Prowlarr URL and API key are required")

    remote = await client.list_indexers()
    existing = {row.prowlarr_id: row for row in session.execute(select(Indexer)).scalars()}
    seen: set[int] = set()
    created = updated = skipped = 0

    for item in remote:
        prowlarr_id = item.get("id")
        if prowlarr_id is None:
            continue
        if (item.get("protocol") or "torrent").lower() != "torrent":
            skipped += 1
            continue
        if not _music_capable(item):
            skipped += 1
            continue

        seen.add(prowlarr_id)
        row = existing.get(prowlarr_id)
        if row is None:
            row = Indexer(
                prowlarr_id=prowlarr_id,
                enabled=bool(item.get("enable", True)),
                priority=_initial_priority(item.get("priority")),
                min_seeders=1,
            )
            session.add(row)
            created += 1
        else:
            updated += 1

        row.name = item.get("name") or f"Indexer {prowlarr_id}"
        row.protocol = (item.get("protocol") or "torrent").lower()
        row.privacy = (item.get("privacy") or "public").lower()
        row.supports_music_search = _music_capable(item)
        row.categories = _music_categories(item)
        row.last_synced_at = utcnow()
        if not item.get("enable", True):
            row.enabled = False

    removed = 0
    for prowlarr_id, row in existing.items():
        if prowlarr_id not in seen:
            session.delete(row)
            removed += 1

    session.commit()
    return {
        "total": len(remote),
        "created": created,
        "updated": updated,
        "removed": removed,
        "skipped": skipped,
    }


def grouped_indexers(session: Session) -> dict[str, list[Indexer]]:
    result: dict[str, list[Indexer]] = {"torrent_public": [], "torrent_private": []}
    for row in session.execute(select(Indexer)).scalars():
        result.setdefault(group_for_privacy(row.privacy), []).append(row)
    for rows in result.values():
        rows.sort(key=lambda item: (-item.priority, item.name.lower()))
    return result
