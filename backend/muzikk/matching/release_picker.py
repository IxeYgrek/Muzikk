"""Pick the edition of an album that should be acquired.

A MusicBrainz release group holds every edition of the same album: original,
remaster, japanese pressing, vinyl, deluxe... They do not share the same track
list, and the track count drives the matching, so one release has to be chosen.
The default preference is the plain original edition, which is what most
Soulseek shares and torrents actually contain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PREFERRED_COUNTRIES = ("XW", "XE", "FR", "GB", "US", "DE", "JP")
PREFERRED_FORMATS = ("CD", "Digital Media", "Vinyl", "Cassette")

_DELUXE_MARKERS = (
    "deluxe", "expanded", "special edition", "anniversary", "collector",
    "super deluxe", "limited", "box", "reissue", "bonus",
)


@dataclass(slots=True)
class ReleaseInfo:
    mbid: str
    title: str
    date: str | None
    country: str | None
    status: str | None
    formats: list[str] = field(default_factory=list)
    track_count: int = 0
    disc_count: int = 1
    label: str | None = None
    score: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def year(self) -> int | None:
        if self.date and len(self.date) >= 4 and self.date[:4].isdigit():
            return int(self.date[:4])
        return None


def parse_release(payload: dict[str, Any]) -> ReleaseInfo:
    media = payload.get("media") or []
    formats: list[str] = []
    track_count = 0
    for medium in media:
        if medium.get("format"):
            formats.append(medium["format"])
        track_count += medium.get("track-count") or len(medium.get("tracks") or [])

    labels = payload.get("label-info") or []
    label_name = None
    for entry in labels:
        label = entry.get("label") or {}
        if label.get("name"):
            label_name = label["name"]
            break

    return ReleaseInfo(
        mbid=payload.get("id") or "",
        title=payload.get("title") or "",
        date=payload.get("date") or None,
        country=payload.get("country") or None,
        status=payload.get("status") or None,
        formats=formats,
        track_count=track_count,
        disc_count=max(1, len(media)),
        label=label_name,
        raw=payload,
    )


def score_release(
    release: ReleaseInfo, *, group_first_date: str | None = None, typical_tracks: int = 0
) -> float:
    """Higher is better. Favours the plain original official edition."""
    score = 0.0

    status = (release.status or "").lower()
    if status == "official":
        score += 40
    elif status in ("promotion", "bootleg", "pseudo-release"):
        score -= 40
    elif not status:
        score += 5

    for index, fmt in enumerate(PREFERRED_FORMATS):
        if any(fmt.lower() == item.lower() for item in release.formats):
            score += 20 - index * 4
            break
    else:
        if release.formats:
            score += 2

    country = (release.country or "").upper()
    if country in PREFERRED_COUNTRIES:
        score += 14 - PREFERRED_COUNTRIES.index(country) * 1.5
    elif country:
        score += 2

    title = (release.title or "").lower()
    if any(marker in title for marker in _DELUXE_MARKERS):
        score -= 18

    if release.disc_count > 1:
        score -= 6 * (release.disc_count - 1)

    if release.track_count <= 0:
        score -= 25
    # A 1-track "file" edition of a 12-track album must not win: Soulseek then
    # treats every lone FLAC as a complete match.
    if typical_tracks >= 6 and 0 < release.track_count <= 2 and release.track_count * 3 < typical_tracks:
        score -= 35

    if group_first_date and release.date:
        if release.date[:4] == group_first_date[:4]:
            score += 16
        elif release.date[:4] < group_first_date[:4]:
            score += 4
    if release.date:
        score += 3

    return score


def pick_release(
    releases: list[dict[str, Any]], *, group_first_date: str | None = None
) -> tuple[ReleaseInfo | None, list[ReleaseInfo]]:
    """Return the recommended release and every candidate, best first."""
    parsed = [parse_release(item) for item in releases or []]
    typical_tracks = max((item.track_count for item in parsed if item.track_count >= 4), default=0)
    for release in parsed:
        release.score = score_release(
            release, group_first_date=group_first_date, typical_tracks=typical_tracks
        )
    parsed.sort(key=lambda item: (-item.score, item.date or "9999", item.title))
    return (parsed[0] if parsed else None), parsed
