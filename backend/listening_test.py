"""ListenBrainz and Last.fm: what counts as a listen, and how tastes are merged.

Runs outside Docker against a throwaway config directory, like the other checks
in this folder. No network: every client has its HTTP call replaced.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

workdir = tempfile.mkdtemp(prefix="muzikk-listening-")
os.environ["MUZIKK_CONFIG_DIR"] = workdir
os.environ["MUZIKK_STATIC_DIR"] = os.path.join(workdir, "static")
sys.path.insert(0, str(Path(__file__).parent))

from muzikk.db import SessionLocal, init_db  # noqa: E402
from muzikk.models import LibraryArtist, User  # noqa: E402
from muzikk.services import recommend, scrobble  # noqa: E402
from muzikk.services import settings as settings_service  # noqa: E402
from muzikk.services import users as users_service  # noqa: E402
from muzikk.services.lastfm import LastfmClient  # noqa: E402
from muzikk.services.listenbrainz import ListenBrainzClient  # noqa: E402
from muzikk.services.settings import LastfmSettings, ListenBrainzSettings  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, extra: object = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f" :: {extra}" if extra != "" else ""))
    if not condition:
        failures.append(label)


init_db()

# --------------------------------------------------------- what is a listen

short = scrobble.Listen(artist="Eekoz", title="Bang It", duration=20)
check("a track under 30 seconds is never a listen", not scrobble.counts_as_listen(short, 20_000))

song = scrobble.Listen(artist="Daft Punk", title="Digital Love", duration=300)
check("a third of the way through is too early", not scrobble.counts_as_listen(song, 100_000))
check("half way through counts", scrobble.counts_as_listen(song, 150_000))

epic = scrobble.Listen(artist="Godspeed", title="Storm", duration=1200)
check(
    "four minutes is enough however long the track",
    scrobble.counts_as_listen(epic, 240_000),
    "20 minute track",
)
check("but not three", not scrobble.counts_as_listen(epic, 179_000))

unknown = scrobble.Listen(artist="Nobody", title="Untitled")
check("an unknown length falls back on 30 seconds", scrobble.counts_as_listen(unknown, 31_000))
check("and refuses less", not scrobble.counts_as_listen(unknown, 10_000))

check(
    "a track without an artist is never submitted",
    not scrobble.Listen(artist="", title="Ghost").playable,
)

# ------------------------------------------------------------ last.fm signing

import hashlib  # noqa: E402

signing = LastfmClient(LastfmSettings(enabled=True, api_key="key", api_secret="secret"))
# Last.fm's rule: every parameter but the format, sorted by name, concatenated
# as name then value with no separator, then the shared secret appended.
expected = hashlib.md5(b"api_keykeymethodauth.getSessiontokenabcsecret").hexdigest()  # noqa: S324
signature = signing._signature({"method": "auth.getSession", "api_key": "key", "token": "abc"})
check("the signature follows the documented concatenation", signature == expected, signature)
check(
    "the signature ignores the format parameter",
    signature
    == signing._signature(
        {"method": "auth.getSession", "api_key": "key", "token": "abc", "format": "json"}
    ),
    signature,
)

# ------------------------------------------------- listenbrainz similar artists

SEED = "83d91898-7763-47d7-b03b-b92132375c47"
LABS_ANSWER = [
    [
        {"artist_mbid": SEED, "artist_credit_name": "Radiohead", "score": 999},
        {"artist_mbid": "b7ffd2af-418f-4be2-bdd1-22f8b48613da", "artist_credit_name": "Beatles", "score": 10},
        {"artist_mbid": "aaaaaaaa-0000-0000-0000-000000000001", "artist_credit_name": "Blur", "score": 40},
        {"artist_mbid": "", "artist_credit_name": "Nameless", "score": 80},
    ]
]

lb = ListenBrainzClient(ListenBrainzSettings(enabled=True))


async def fake_labs(method: str, path: str, **kwargs: object) -> object:
    return LABS_ANSWER


lb.request = fake_labs  # type: ignore[assignment]
similar = asyncio.run(lb.similar_artists(SEED))
check("the nested list is flattened", len(similar) == 2, similar)
check("the seed artist is dropped", all(row["artist_mbid"] != SEED for row in similar))
check("an entry without an mbid is dropped", all(row["artist_mbid"] for row in similar))
check("the best score comes first", similar[0]["name"] == "Blur", similar[0])

# ----------------------------------------------------- last.fm similar artists

FM_ANSWER = {
    "similarartists": {
        "artist": [
            {"name": "Blur", "mbid": "aaaaaaaa-0000-0000-0000-000000000001", "match": "0.9"},
            # Last.fm often answers with a name and no identifier, which cannot
            # be resolved without risking a namesake.
            {"name": "Some Cover Band", "mbid": "", "match": "0.8"},
            {"name": "Pulp", "mbid": "cccccccc-0000-0000-0000-000000000003", "match": "0.5"},
        ]
    }
}

fm = LastfmClient(LastfmSettings(enabled=True, api_key="key", api_secret="secret"))


async def fake_fm(method: str, path: str, **kwargs: object) -> object:
    return FM_ANSWER


fm.request = fake_fm  # type: ignore[assignment]
fm_similar = asyncio.run(fm.similar_artists(name="Oasis"))
check("only identified artists are kept", len(fm_similar) == 2, fm_similar)
check(
    "the unidentified one is the one dropped",
    all(row["name"] != "Some Cover Band" for row in fm_similar),
    fm_similar,
)

# an error inside a 200 response is still an error
async def fake_error(method: str, path: str, **kwargs: object) -> object:
    return {"error": 10, "message": "Invalid API key"}


fm.request = fake_error  # type: ignore[assignment]
check("a refusal inside a 200 body is caught", asyncio.run(fm.similar_artists(name="Oasis")) == [])

# ------------------------------------------------------------------ merging

session = SessionLocal()
settings_service.save(session, "listenbrainz", {"enabled": True})
settings_service.save(session, "lastfm", {"enabled": True, "api_key": "key", "api_secret": "s"})

original_lb = ListenBrainzClient.similar_artists
original_fm = LastfmClient.similar_artists


async def lb_similar(self, artist_mbid, *, limit=20):  # type: ignore[no-untyped-def]
    return [
        {"artist_mbid": "aaaaaaaa-0000-0000-0000-000000000001", "name": "Blur", "score": 20.0},
        {"artist_mbid": "bbbbbbbb-0000-0000-0000-000000000002", "name": "Suede", "score": 40.0},
    ]


async def fm_similar(self, *, name="", mbid=None, limit=20):  # type: ignore[no-untyped-def]
    return [
        {"artist_mbid": "aaaaaaaa-0000-0000-0000-000000000001", "name": "Blur", "score": 0.5},
        {"artist_mbid": "cccccccc-0000-0000-0000-000000000003", "name": "Pulp", "score": 1.0},
    ]


ListenBrainzClient.similar_artists = lb_similar  # type: ignore[assignment]
LastfmClient.similar_artists = fm_similar  # type: ignore[assignment]
try:
    merged = asyncio.run(recommend.similar_to(session, [recommend.Seed(artist_mbid=SEED, name="Oasis")]))
finally:
    ListenBrainzClient.similar_artists = original_lb  # type: ignore[assignment]
    LastfmClient.similar_artists = original_fm  # type: ignore[assignment]

check("both services are merged", len(merged) == 3, [row.name for row in merged])
check(
    "the artist both services agree on ranks first",
    merged[0].name == "Blur" and merged[0].sources == {"listenbrainz", "lastfm"},
    merged[0],
)
check(
    "a service is not allowed to win on its own scale",
    # Suede scores 40 at ListenBrainz and Pulp 1.0 at Last.fm: normalised, both
    # are a perfect 1.0, so neither may outrank the agreed-on artist.
    merged[0].score >= merged[1].score,
    [(row.name, round(row.score, 2)) for row in merged],
)

# ---------------------------------------------------------------- seeding

check("no account and no library means no seed", asyncio.run(recommend.seeds_for(session, User(name="x"))) == ([], []))

session.add(LibraryArtist(jellyfin_id="a1", name="Daft Punk", mbid=SEED, album_count=4))
session.add(
    LibraryArtist(
        jellyfin_id="a2", name="Air", mbid="dddddddd-0000-0000-0000-000000000004", album_count=9
    )
)
session.commit()

seeds, sources = asyncio.run(recommend.seeds_for(session, User(name="x")))
check("the library stands in when nothing is connected", sources == ["library"], sources)
check("the best represented artist seeds first", seeds and seeds[0].name == "Air", seeds)

# ------------------------------------------------------- artists as suggestions

cards = recommend._as_artist_cards(
    session,
    User(id=1, name="x"),
    [
        recommend.Suggestion(artist_mbid=SEED, name="Daft Punk", sources={"lastfm"}),
        recommend.Suggestion(
            artist_mbid="eeeeeeee-0000-0000-0000-000000000005",
            name="Justice",
            sources={"lastfm", "listenbrainz"},
        ),
        # No name: nothing to show on a card.
        recommend.Suggestion(artist_mbid="ffffffff-0000-0000-0000-000000000006", name=""),
    ],
    limit=10,
)
check("a nameless suggestion is not shown", len(cards) == 2, [card.name for card in cards])
check(
    "an artist already in the library is flagged",
    next(card.in_library for card in cards if card.name == "Daft Punk"),
    cards[0],
)
check(
    "agreement between services is spelled out",
    next(card.disambiguation for card in cards if card.name == "Justice") == "lastfm · listenbrainz",
    cards[1],
)
check(
    "a single source says nothing",
    next(card.disambiguation for card in cards if card.name == "Daft Punk") is None,
)

# -------------------------------------------------------- nothing connected

listener = User(name="Ada", username="ada", password_hash="x")
session.add(listener)
session.commit()
sent = asyncio.run(
    scrobble.submit(session, listener, scrobble.Listen(artist="A", title="B", duration=300), position_ms=200_000)
)
check("a listener without accounts scrobbles nowhere", sent == {"listenbrainz": False, "lastfm": False}, sent)

users_service.set_listening_accounts(session, listener, listenbrainz_user="ada", listenbrainz_token_value="tok")
check("the token is not stored in clear", (listener.listenbrainz_token or "").startswith("enc:"), listener.listenbrainz_token)
check("but reads back", users_service.listenbrainz_token(listener) == "tok")
users_service.set_listening_accounts(session, listener, listenbrainz_token_value="")
check("and can be disconnected", listener.listenbrainz_token is None)

settings_service.invalidate_cache()
session.close()

print()
print("FAILURES: " + (", ".join(failures) if failures else "none"))
sys.exit(1 if failures else 0)
