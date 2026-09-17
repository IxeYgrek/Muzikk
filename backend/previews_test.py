"""Checks the thirty second previews: which hit wins, and which is refused."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("MUZIKK_CONFIG_DIR", tempfile.mkdtemp(prefix="muzikk-preview-"))

import httpx  # noqa: E402

from muzikk.services import previews  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, extra: object = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f" :: {extra}" if extra else ""))
    if not condition:
        failures.append(label)


def deezer_track(title: str, artist: str, *, preview: str = "https://cdnt-preview.dzcdn.net/x.mp3"):
    return {
        "title": title,
        "preview": preview,
        "artist": {"name": artist},
        "album": {"title": "Discovery", "cover_medium": "https://e-cdns.dzcdn.net/cover.jpg"},
    }


def itunes_track(title: str, artist: str, *, url: str = "https://audio-ssl.itunes.apple.com/x.m4a"):
    return {
        "trackName": title,
        "artistName": artist,
        "collectionName": "Discovery",
        "previewUrl": url,
        "artworkUrl100": "https://is1-ssl.mzstatic.com/image.jpg",
    }


calls: list[str] = []


def transport(*, deezer: dict, itunes: dict) -> httpx.MockTransport:
    """Answer both search APIs without leaving the machine."""

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url.host))
        payload = deezer if "deezer" in request.url.host else itunes
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


def run(artist: str, title: str, *, deezer: dict, itunes: dict) -> previews.Preview | None:
    """One lookup against the fake services, with a cold cache."""
    previews.forget_all()
    calls.clear()
    original = httpx.AsyncClient

    class Patched(original):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport(deezer=deezer, itunes=itunes)
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = Patched  # type: ignore[misc]
    try:
        return asyncio.run(previews.find(artist, title))
    finally:
        httpx.AsyncClient = original  # type: ignore[misc]


# ------------------------------------------------------------------- scoring

exact = previews.score_hit(
    wanted_artist="Daft Punk", wanted_title="Digital Love", artist="Daft Punk", title="Digital Love"
)
check("an exact hit scores full marks", exact == 100, exact)

accents = previews.score_hit(
    wanted_artist="Étienne Daho", wanted_title="Week-end à Rome",
    artist="Etienne Daho", title="Week End a Rome",
)
check("accents and dashes do not matter", accents >= previews.MATCH_THRESHOLD, accents)

karaoke = previews.score_hit(
    wanted_artist="Daft Punk", wanted_title="Digital Love",
    artist="Karaoke All Stars", title="Digital Love (Karaoke Version)",
)
check("a karaoke cover is refused outright", karaoke == 0, karaoke)

featuring = previews.score_hit(
    wanted_artist="Kanye West", wanted_title="Otis",
    artist="JAY-Z & Kanye West feat. Otis Redding", title="Otis",
)
check("a featuring credit still matches", featuring >= previews.MATCH_THRESHOLD, featuring)

other = previews.score_hit(
    wanted_artist="Daft Punk", wanted_title="Digital Love",
    artist="Daft Punk", title="Aerodynamic",
)
check("another track of the same artist is refused", other < previews.MATCH_THRESHOLD, other)

# --------------------------------------------------------------- the lookup

found = run(
    "Daft Punk",
    "Digital Love",
    deezer={"data": [deezer_track("Aerodynamic", "Daft Punk"),
                     deezer_track("Digital Love", "Daft Punk")]},
    itunes={"results": []},
)
check("deezer answers first", found is not None and found.source == "deezer", found)
check("the right track is picked", found is not None and found.title == "Digital Love", found)
check("iTunes is left alone", all("deezer" in host for host in calls), calls)
check(
    "the extract is an mp3",
    found is not None and found.content_type == "audio/mpeg",
    found.content_type if found else "",
)

found = run(
    "Daft Punk",
    "Digital Love",
    deezer={"data": [deezer_track("Digital Love", "Daft Punk", preview="")]},
    itunes={"results": [itunes_track("Digital Love", "Daft Punk")]},
)
check("a hit without an extract does not count", found is not None and found.source == "itunes")
check("iTunes was asked", any("apple" in host for host in calls), calls)

found = run(
    "Daft Punk",
    "Digital Love",
    deezer={"data": [deezer_track("Digital Love (Karaoke)", "Karaoke All Stars")]},
    itunes={"results": [itunes_track("Digital Love", "Daft Punk")]},
)
check("a karaoke hit hands over to iTunes", found is not None and found.source == "itunes", found)

found = run(
    "Daft Punk",
    "Digital Love",
    deezer={"data": []},
    itunes={"results": [itunes_track("Something Else", "Someone Else")]},
)
check("nothing convincing means no extract", found is None, found)

# ----------------------------------------------------------------- caching

previews.forget_all()
answered: list[int] = []


def counting(request: httpx.Request) -> httpx.Response:
    answered.append(1)
    return httpx.Response(200, json={"data": [deezer_track("Digital Love", "Daft Punk")]})


original_client = httpx.AsyncClient


class Counted(original_client):  # type: ignore[misc, valid-type]
    def __init__(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(counting)
        super().__init__(*args, **kwargs)


httpx.AsyncClient = Counted  # type: ignore[misc]
try:
    first = asyncio.run(previews.find("Daft Punk", "Digital Love"))
    second = asyncio.run(previews.find("daft punk", "Digital  Love"))
finally:
    httpx.AsyncClient = original_client  # type: ignore[misc]

check("the second lookup is served from memory", len(answered) == 1, answered)
check(
    "and gives the same extract",
    first is not None and second is not None and first.url == second.url,
)

# -------------------------------------------------------------- stream hosts

check("a deezer host is allowed", previews.host_allowed("https://cdnt-preview.dzcdn.net/x.mp3"))
check("an apple host is allowed", previews.host_allowed("https://audio-ssl.itunes.apple.com/x.m4a"))
check("a lookalike host is refused", not previews.host_allowed("https://dzcdn.net.evil.com/x.mp3"))
check("anything else is refused", not previews.host_allowed("http://127.0.0.1:8080/secret"))

print()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
