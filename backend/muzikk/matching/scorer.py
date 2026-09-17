"""Candidate scoring.

A release title lies: it says "FLAC" when it is a 320 kbps rip, it says
"Discovery" when it is a live bootleg. Scoring therefore leans on the file list
whenever it is available (always for Soulseek, and for torrents once the
.torrent has been inspected) and only falls back to the title otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from ..providers.base import AlbumQuery, Candidate
from ..services.settings import QualitySettings
from .normalize import (
    normalize_artist,
    normalize_title,
    parent_dir,
    strip_track_number,
)

WEIGHT_ALBUM = 30.0
WEIGHT_ARTIST = 20.0
WEIGHT_TRACK_COUNT = 20.0
WEIGHT_TRACK_TITLES = 20.0
WEIGHT_FORMAT = 10.0

TITLE_HIT_THRESHOLD = 76.0

# Below this, the artist asked for is simply not in the path. Measured on real
# shares, the two cases sit far apart: a folder naming the artist scores 0.6 at
# worst — "Jarre - Oxygene" against "Jean-Michel Jarre" — while an unrelated
# release lands between 0.2 and 0.45. Without this an album of the right name by
# the wrong artist passes the threshold, since the artist is only worth 20 points.
MIN_ARTIST_SIMILARITY = 0.55
MB_PER_BYTE = 1 / (1024 * 1024)

LOSSLESS_TOKENS = ("flac", "lossless", "alac", "ape", "wavpack", "wv", "aiff", "24bit", "24 bit", "hi-res")
LOSSY_TOKENS = ("mp3", "320", "v0", "v2", "aac", "m4a", "ogg", "opus", "vbr", "cbr", "128", "192", "256")


@dataclass(slots=True)
class MatchResult:
    score: float = 0.0
    accepted: bool = False
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def _haystack(candidate: Candidate) -> str:
    """Text describing the candidate, used when the file list is unavailable."""
    parts = [candidate.title]
    if candidate.directory:
        parts.append(candidate.directory.replace("\\", " ").replace("/", " "))
    if candidate.extra.get("torrent_name"):
        parts.append(str(candidate.extra["torrent_name"]))
    return " ".join(parts)


def _album_similarity(candidate: Candidate, query: AlbumQuery) -> float:
    target = query.normalized_album
    if not target:
        return 0.0
    haystack = normalize_title(_haystack(candidate))
    if not haystack:
        return 0.0
    direct = fuzz.token_set_ratio(target, haystack)
    partial = fuzz.partial_ratio(target, haystack)
    return max(direct, partial) / 100.0


def _artist_similarity(candidate: Candidate, query: AlbumQuery) -> float:
    if query.is_various:
        return 1.0
    target = query.normalized_artist
    if not target:
        return 0.5
    haystack = normalize_artist(_haystack(candidate))
    if candidate.directory:
        haystack = f"{haystack} {normalize_artist(parent_dir(candidate.directory))}"
    if not haystack.strip():
        return 0.0
    return max(fuzz.token_set_ratio(target, haystack), fuzz.partial_ratio(target, haystack)) / 100.0


def _track_count_score(audio_count: int, query: AlbumQuery, tolerance: int) -> tuple[float, int]:
    expected = query.track_count
    if expected <= 0:
        return 0.7, audio_count
    delta = abs(audio_count - expected)
    if delta == 0:
        return 1.0, delta
    if delta <= tolerance:
        return 0.85, delta
    # A few extra tracks usually means bonus tracks, which is acceptable.
    if audio_count > expected and delta <= max(2, expected // 8):
        return 0.6, delta
    return 0.0, delta


def _track_title_coverage(candidate: Candidate, query: AlbumQuery) -> float:
    expected = [normalize_title(title) for title in query.track_titles if title]
    if not expected:
        return 0.6
    stems: list[str] = []
    for item in candidate.audio_files:
        name = Path(item.filename.replace("\\", "/")).name
        stems.append(normalize_title(name))
        stripped = normalize_title(strip_track_number(name))
        if stripped and stripped not in stems:
            stems.append(stripped)
    if not stems:
        return 0.0

    hits = 0
    for title in expected:
        best = max((fuzz.token_set_ratio(title, stem) for stem in stems), default=0)
        if best >= TITLE_HIT_THRESHOLD:
            hits += 1
    return hits / len(expected)


def _format_assessment(
    candidate: Candidate, quality: QualitySettings
) -> tuple[bool, bool, float, str]:
    """Return ``(acceptable, is_lossless, bonus, description)``."""
    lossless = {item.lower() for item in quality.lossless_formats}
    lossy = {item.lower() for item in quality.lossy_formats}

    audio = candidate.audio_files
    if audio:
        extensions = {item.extension for item in audio}
        if extensions and extensions <= lossless:
            # Formats are configured best first, so a later entry scores lower.
            best = next(
                (fmt for fmt in quality.lossless_formats if fmt.lower() in extensions), "lossless"
            )
            rank = quality.lossless_formats.index(best) if best in quality.lossless_formats else 0
            listed = "/".join(sorted(extensions))
            return True, True, max(0.5, 1.0 - rank * 0.1), f"lossless ({listed})"

        if not quality.allow_lossy_fallback:
            return False, False, 0.0, f"unwanted format ({'/'.join(sorted(extensions)) or 'unknown'})"

        if extensions <= (lossless | lossy):
            bitrates = [item.bitrate for item in audio if item.bitrate]
            if bitrates and max(bitrates) < quality.min_lossy_bitrate:
                return False, False, 0.0, f"bitrate too low ({max(bitrates)} kbps)"
            return True, False, 0.25, f"lossy accepted ({'/'.join(sorted(extensions))})"

        return False, False, 0.0, f"unwanted format ({'/'.join(sorted(extensions))})"

    # No file list: fall back on the tokens present in the title.
    text = _haystack(candidate).lower()
    has_lossless = any(token in text for token in LOSSLESS_TOKENS)
    has_lossy = any(token in text for token in LOSSY_TOKENS)
    if has_lossless and not has_lossy:
        return True, True, 0.7, "lossless announced in the title"
    if has_lossless and has_lossy:
        return True, True, 0.4, "mixed format announced in the title"
    if quality.allow_lossy_fallback and has_lossy:
        return True, False, 0.2, "lossy announced in the title"
    return False, False, 0.0, "no lossless format announced"


def _size_sanity(candidate: Candidate, query: AlbumQuery, quality: QualitySettings) -> str | None:
    audio_count = len(candidate.audio_files) or query.track_count
    if not candidate.size or audio_count <= 0:
        return None
    per_track_mb = candidate.size * MB_PER_BYTE / audio_count
    if per_track_mb < quality.min_size_per_track_mb:
        return f"suspiciously small ({per_track_mb:.1f} MB per track)"
    if per_track_mb > quality.max_size_per_track_mb:
        return f"suspiciously large ({per_track_mb:.1f} MB per track)"
    return None


def score_candidate(
    candidate: Candidate, query: AlbumQuery, quality: QualitySettings
) -> MatchResult:
    details: dict[str, Any] = {}

    audio_files = candidate.audio_files
    if candidate.files_inspected and not audio_files:
        return MatchResult(reason="no audio file in the release", details=details)

    if candidate.kind == "torrent":
        minimum = int(candidate.extra.get("min_seeders") or quality.min_seeders)
        seeders = candidate.seeders
        if seeders is not None and seeders < max(minimum, quality.min_seeders):
            return MatchResult(
                reason=f"not enough seeders ({seeders} < {max(minimum, quality.min_seeders)})",
                details={"seeders": seeders},
            )

    acceptable, is_lossless, format_bonus, format_reason = _format_assessment(candidate, quality)
    details["format"] = format_reason
    details["lossless"] = is_lossless
    if not acceptable:
        return MatchResult(reason=format_reason, details=details)

    size_problem = _size_sanity(candidate, query, quality)
    if size_problem:
        details["size"] = size_problem
        return MatchResult(reason=size_problem, details=details)

    album_similarity = _album_similarity(candidate, query)
    artist_similarity = _artist_similarity(candidate, query)
    details["album_similarity"] = round(album_similarity * 100, 1)
    details["artist_similarity"] = round(artist_similarity * 100, 1)

    if (
        quality.require_artist_match
        and query.normalized_artist
        and not query.is_various
        and artist_similarity < MIN_ARTIST_SIMILARITY
    ):
        return MatchResult(
            reason=f"artist not in the release ({details['artist_similarity']}% match)",
            details=details,
        )

    if candidate.files_inspected:
        count_score, delta = _track_count_score(
            len(audio_files), query, quality.track_count_tolerance
        )
        details["audio_files"] = len(audio_files)
        details["expected_tracks"] = query.track_count
        details["track_count_delta"] = delta
        if count_score == 0.0 and quality.reject_incomplete_albums:
            return MatchResult(
                score=0.0,
                reason=f"track count mismatch ({len(audio_files)} instead of {query.track_count})",
                details=details,
            )
        coverage = _track_title_coverage(candidate, query)
        details["track_title_coverage"] = round(coverage * 100, 1)
    else:
        count_score = 0.6
        coverage = 0.5
        details["content_verified"] = False

    score = (
        WEIGHT_ALBUM * album_similarity
        + WEIGHT_ARTIST * artist_similarity
        + WEIGHT_TRACK_COUNT * count_score
        + WEIGHT_TRACK_TITLES * coverage
        + WEIGHT_FORMAT * format_bonus
    )

    if query.year:
        text = _haystack(candidate)
        if str(query.year) in text:
            score += 4
            details["year_match"] = True

    if candidate.kind == "torrent" and candidate.seeders:
        score += min(6.0, candidate.seeders / 10.0)
    if candidate.kind == "soulseek":
        if candidate.extra.get("has_free_upload_slot"):
            score += 3
        if candidate.queue_length is not None and candidate.queue_length == 0:
            score += 2
        if candidate.upload_speed:
            score += min(3.0, candidate.upload_speed / 500_000)

    if quality.prefer_24bit and any((item.bit_depth or 0) >= 24 for item in audio_files):
        score += 3
        details["high_resolution"] = True

    score = round(max(0.0, min(score, 120.0)), 2)
    accepted = score >= quality.min_score
    return MatchResult(
        score=score,
        accepted=accepted,
        reason="" if accepted else f"score {score} below the {quality.min_score} threshold",
        details=details,
    )


def rank_candidates(
    candidates: list[Candidate], query: AlbumQuery, quality: QualitySettings
) -> list[tuple[Candidate, MatchResult]]:
    """Score every candidate and return them best first."""
    scored: list[tuple[Candidate, MatchResult]] = []
    for candidate in candidates:
        result = score_candidate(candidate, query, quality)
        candidate.score = result.score
        scored.append((candidate, result))
    scored.sort(
        key=lambda item: (
            item[1].accepted,
            item[1].score,
            item[0].extra.get("indexer_priority", 50) * -1,
            # Among equal scores, start with the peer most likely to accept.
            1 if item[0].extra.get("has_free_upload_slot") else 0,
            item[0].upload_speed or 0,
            -(item[0].queue_length if item[0].queue_length is not None else 10**9),
        ),
        reverse=True,
    )
    return scored
