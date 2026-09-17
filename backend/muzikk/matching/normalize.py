"""Text normalisation shared by the matcher and the library index.

Release titles are written in a hundred different ways across Soulseek and
torrent trackers. Everything is folded down to a comparable form before any
similarity is computed.
"""

from __future__ import annotations

import re
import unicodedata

AUDIO_EXTENSIONS = {
    "flac", "mp3", "m4a", "alac", "aac", "ogg", "opus", "wav", "aiff", "aif",
    "ape", "wv", "wma", "dsf", "dff", "mpc", "shn",
}

LOSSLESS_EXTENSIONS = {"flac", "alac", "wav", "aiff", "aif", "ape", "wv", "dsf", "dff", "shn"}

JUNK_EXTENSIONS = {
    "nfo", "url", "txt", "m3u", "m3u8", "sfv", "log", "cue", "md5", "torrent",
    "db", "ini", "lnk", "html", "htm", "pdf", "doc", "docx",
}

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "tif", "tiff"}

# Edition noise that must not penalise the title similarity.
_EDITION_NOISE = [
    r"\bdeluxe(\s+edition)?\b",
    r"\bsuper\s+deluxe\b",
    r"\bexpanded(\s+edition)?\b",
    r"\bspecial\s+edition\b",
    r"\blimited(\s+edition)?\b",
    r"\banniversary(\s+edition)?\b",
    r"\bcollector'?s?(\s+edition)?\b",
    r"\bremaster(ed)?\b",
    r"\bre[\s\-]?issue\b",
    r"\bbonus(\s+track(s)?)?\b",
    r"\bdisc\s*\d+\b",
    r"\bcd\s*\d+\b",
    r"\b\d{2,3}\s*(bit|khz)\b",
    r"\bhi[\s\-]?res\b",
    r"\bexplicit\b",
    r"\bclean\b",
    r"\bmono\b",
    r"\bstereo\b",
    r"\bjapan(ese)?(\s+edition)?\b",
    r"\bus(\s+edition)?\b",
    r"\buk(\s+edition)?\b",
    r"\bweb\b",
    r"\bvinyl\b",
    r"\bsacd\b",
    r"\bdsd\b",
    r"\b(24|16)\s*[\-/]?\s*(44|48|88|96|176|192)(\.\d)?\b",
]

_EDITION_RE = re.compile("|".join(_EDITION_NOISE), re.IGNORECASE)
_BRACKETS_RE = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_YEAR_RE = re.compile(r"(19|20)\d{2}")

_ARTICLES = ("the ", "a ", "an ", "le ", "la ", "les ", "l'", "der ", "die ", "das ")

_REPLACEMENTS = {
    "&": " and ",
    "+": " and ",
    "@": " at ",
    "ø": "o",
    "æ": "ae",
    "œ": "oe",
    "ß": "ss",
    "ð": "d",
    "þ": "th",
    "ł": "l",
    "đ": "d",
}


def strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize(value: str | None, *, drop_brackets: bool = False, drop_articles: bool = False) -> str:
    """Fold a string to a lowercase alphanumeric form."""
    if not value:
        return ""
    text = value.lower()
    for source, target in _REPLACEMENTS.items():
        text = text.replace(source, target)
    text = strip_accents(text)
    if drop_brackets:
        text = _BRACKETS_RE.sub(" ", text)
    text = _EDITION_RE.sub(" ", text)
    text = _NON_ALNUM_RE.sub(" ", text).strip()
    if drop_articles:
        for article in _ARTICLES:
            if text.startswith(article):
                text = text[len(article) :]
                break
    return " ".join(text.split())


def normalize_title(value: str | None) -> str:
    """Album or track title, with edition noise and brackets removed."""
    return normalize(value, drop_brackets=True)


def normalize_artist(value: str | None) -> str:
    return normalize(value, drop_brackets=True, drop_articles=True)


def fuzzy_key(artist: str | None, album: str | None) -> str:
    """Stable key used to match a library album without any MBID."""
    artist_part = normalize_artist(artist)
    album_part = normalize_title(album)
    if not artist_part and not album_part:
        return ""
    return f"{artist_part}|{album_part}"


def extension_of(name: str) -> str:
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower().strip()


def is_audio_file(name: str) -> bool:
    return extension_of(name) in AUDIO_EXTENSIONS


def is_lossless_file(name: str) -> bool:
    return extension_of(name) in LOSSLESS_EXTENSIONS


def guess_year(text: str) -> int | None:
    match = _YEAR_RE.search(text or "")
    return int(match.group(0)) if match else None


def basename(path: str) -> str:
    """Last component of a path using either separator."""
    return re.split(r"[\\/]", path or "")[-1]


def parent_dir(path: str) -> str:
    parts = re.split(r"[\\/]", path or "")
    return "\\".join(parts[:-1]) if len(parts) > 1 else ""


def strip_track_number(name: str) -> str:
    """Remove a leading track number from a filename.

    The caller compares both the raw and the stripped form, because a title can
    legitimately start with a number ("99 Problems").
    """
    stem = name.rsplit(".", 1)[0] if "." in name else name
    stem = re.sub(r"^\s*[\(\[]?(?:[a-d]|cd\s*\d)?\s*\d{1,3}[\)\]]?\s*[\-\._\s]+", " ", stem, flags=re.I)
    return stem.strip()


_LEADING_NUMBER_RE = re.compile(r"^\s*[\(\[]?(?:[a-d]|cd\s*\d)?[\s\-\._]*(\d{1,3})[\)\]]?\s*[\-\._\s]+", re.I)


def leading_track_number(name: str) -> int | None:
    """Track number read from the beginning of a filename, when present."""
    match = _LEADING_NUMBER_RE.match(name or "")
    if not match:
        return None
    value = int(match.group(1))
    return value if 0 < value <= 200 else None
