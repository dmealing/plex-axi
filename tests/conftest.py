"""A Plex Media Server double that answers like Plex, not like the client.

**There is no Plex server in these tests and there must never be one.** Every
test runs the real client library against this double, which speaks HTTP-shaped
XML over a fake ``requests`` session. That is the point: the claims worth testing
here -- that a filter is applied server-side, that the URL carries the operator
Plex actually defines, that a count is exact -- are claims about the *request the
client library builds*, and a double that only agreed with the client could not
test any of them.

Two rules make it a second opinion rather than an echo, both learned from the
sibling AXI project:

* **It models the refusals.** :data:`KNOWN_PARAMS` is an explicit allow-list of
  query parameters. Anything else is a ``400``, so a filter that reached the URL
  untranslated -- the exact failure this tool exists to prevent -- fails the test
  instead of passing through as a no-op. A new parameter is refused here until it
  is added to the table, and adding it is how the parameter gets *confirmed*
  rather than assumed. The table is deliberately not imported from ``plex_axi``.
* **It applies the filters for real.** A request for tracks rated four stars and
  up returns only those tracks, from this module's own predicate code. A double
  that returned the same rows whatever was asked would let a filter that does
  nothing pass every test.

There is a third rule, and it was paid for by a live audit rather than learned
from a sibling project:

* **Anything describing what the server *answers* is transcribed, never
  authored.** Operator tables, field lists, element attributes, the shape of a
  value: these are copied from a real ``?includeMeta=1`` capture and from real
  responses. Everything the tool *asks* may be invented; nothing the server
  *answers* may be. Two of the worst bugs this suite ever missed were a guessed
  operator and a guessed attribute, and both passed every test here while
  failing on every real server. See AGENTS.md, "The double-fidelity rule".

Every name, path and identifier in the fixture is invented. Nothing here came
from a real library: the *shapes* are transcribed, the *content* never is.
"""

from __future__ import annotations

import copy
import re
import time
import urllib.parse
from xml.sax.saxutils import quoteattr

import pytest

# --------------------------------------------------------------------- fixture data

TOKEN = "example-token-0000000001"

#: The access token plex.tv hands back for the one account this server is shared
#: with. Built from the same obviously-synthetic shape as the owner's, and never
#: printed by anything: `--user` registers it as a secret the moment it arrives.
USER_TOKEN = "example-token-0000000002"
SHARED_USERNAME = "example-friend"
SHARED_EMAIL = "example-friend@example.com"
SHARED_USER_ID = "770077"

MACHINE_ID = "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f"
SERVER_NAME = "Example Server"
SERVER_VERSION = "1.41.0.0000-abcdef"

MUSIC_SECTION_KEY = "3"
MUSIC_SECTION_TITLE = "Example Music"
VIDEO_SECTION_KEY = "1"
VIDEO_SECTION_TITLE = "Example Films"

#: Tag vocabularies. Plex hands back numeric ids for these, and the client
#: library resolves a name to an id before it builds the URL -- so a test that
#: skipped the ids would not be testing the path the tool actually takes.
GENRES = {"11": "Jazz", "12": "Rock"}
STYLES = {"21": "Cool Jazz", "22": "Indie Rock"}
#: Plex's pressing tags. `pick --exclude-live` filters on these, and they are
#: numeric ids on the wire exactly like a genre -- which is why the tool resolves
#: the names rather than putting them in the URL as text.
SUBFORMATS = {"51": "Compilation", "52": "Live"}
TRACK_MOODS = {"31": "Mellow", "32": "Energetic"}
ARTIST_MOODS = {"41": "Reflective"}

ARTISTS = [
    {
        "key": 100,
        "title": "Example Artist",
        "guid": "plex://artist/a1b2c3d4e5f60718293a0100",
        "genres": ["11"],
        "styles": ["21"],
        "moods": ["41"],
        "userRating": 8.0,
        "addedAt": 1600000000,
        "childCount": 2,
        "leafCount": 4,
        "summary": "An invented artist used only by this test suite.",
    },
    {
        "key": 200,
        "title": "Second Example",
        "guid": "plex://artist/a1b2c3d4e5f60718293a0200",
        "genres": ["12"],
        "styles": ["22"],
        "moods": [],
        "userRating": None,
        "addedAt": 1610000000,
        "childCount": 1,
        "leafCount": 1,
        "summary": "",
    },
    {
        "key": 300,
        "title": "Various Artists",
        "guid": "plex://artist/a1b2c3d4e5f60718293a0300",
        "genres": ["11"],
        "styles": [],
        "moods": [],
        "userRating": None,
        "addedAt": 1620000000,
        "childCount": 1,
        "leafCount": 1,
        "summary": "",
    },
]

ALBUMS = [
    {
        "key": 110,
        "title": "Example Album",
        "artist": 100,
        "year": 1977,
        "subformat": [],
        "leafCount": 2,
        "userRating": 8.0,
        "addedAt": 1600000100,
        "studio": "Example Records",
        "summary": "",
    },
    {
        "key": 120,
        "title": "Example Anthology",
        "artist": 100,
        "year": 1995,
        # Tagged a compilation, so `pick --exclude-live` must drop its tracks.
        "subformat": ["51"],
        "leafCount": 2,
        "userRating": None,
        "addedAt": 1600000200,
        "studio": "",
        "summary": "",
    },
    {
        "key": 210,
        "title": "Second Album",
        "artist": 200,
        "year": 2001,
        "subformat": ["52"],
        "leafCount": 1,
        "userRating": None,
        "addedAt": 1610000100,
        "studio": "",
        "summary": "",
    },
    {
        "key": 310,
        "title": "Example Compilation",
        "artist": 300,
        "year": 2003,
        "subformat": ["51"],
        "leafCount": 1,
        "userRating": None,
        "addedAt": 1620000100,
        "studio": "",
        "summary": "",
    },
]

TRACKS = [
    {
        "key": 111,
        "title": "Example Track",
        "album": 110,
        "index": 1,
        "userRating": 8.0,
        "duration": 266000,
        "moods": ["31"],
        "analysis": 6,
        "originalTitle": "",
        "viewCount": 12,
        "skipCount": 1,
        "addedAt": 1600000110,
        "lastViewedAt": 1700000000,
        "file": "/example/library/Example Artist/Example Album/01 Example Track.flac",  # leakcheck: allow=media-path
        "container": "flac",
        "bitrate": 960,
        "size": 30000000,
        "accessible": 1,
        "exists": 1,
    },
    {
        "key": 112,
        "title": "Another Track",
        "album": 110,
        "index": 2,
        "userRating": 6.0,
        "duration": 199000,
        "moods": ["32"],
        "analysis": 6,
        "originalTitle": "",
        "viewCount": 3,
        "skipCount": 0,
        "addedAt": 1600000120,
        "lastViewedAt": 0,
        "file": "/example/library/Example Artist/Example Album/02 Another Track.flac",  # leakcheck: allow=media-path
        "container": "flac",
        "bitrate": 900,
        "size": 22000000,
        "accessible": 1,
        "exists": 1,
    },
    {
        # The same title on a second release by the same artist. This is what
        # `group=title` collapses and `--no-group` reveals.
        "key": 121,
        "title": "Example Track",
        "album": 120,
        "index": 5,
        "userRating": None,
        "duration": 262000,
        "moods": ["31"],
        "analysis": 6,
        "originalTitle": "",
        "viewCount": 0,
        "skipCount": 0,
        "addedAt": 1600000210,
        "lastViewedAt": 0,
        "file": "/example/library/Example Artist/Example Anthology/05 Example Track.mp3",  # leakcheck: allow=media-path
        "container": "mp3",
        "bitrate": 320,
        "size": 9000000,
        "accessible": 0,
        "exists": 1,
    },
    {
        # Locally matched: Plex never found this one in its catalogue, so its
        # guid is `local://<ratingKey>` -- the rating key with a scheme in front
        # of it, which is form 6 in AGENTS.md and is *not* durable. Roughly one
        # track in seven carries this shape on a real library, and the double
        # emitted none until it printed a durability note that was false for
        # them. It is the unanalysed track too, which is not a coincidence: an
        # item Plex could not match is an item Plex did not analyse.
        "key": 122,
        "title": "Anthology Only",
        "guid": "local://122",
        "album": 120,
        "index": 6,
        "userRating": 10.0,
        "duration": 180000,
        "moods": [],
        "analysis": 0,
        "originalTitle": "",
        "viewCount": 1,
        "skipCount": 4,
        "addedAt": 1600000220,
        "lastViewedAt": 0,
        "file": "/example/library/Example Artist/Example Anthology/06 Anthology Only.mp3",  # leakcheck: allow=media-path
        "container": "mp3",
        "bitrate": 320,
        "size": 7000000,
        "accessible": 1,
        "exists": 0,
    },
    {
        "key": 211,
        "title": "Loud Track",
        "album": 210,
        "index": 1,
        "userRating": 10.0,
        "duration": 210000,
        "moods": ["32"],
        "analysis": 6,
        "originalTitle": "",
        "viewCount": 7,
        "skipCount": 0,
        "addedAt": 1610000110,
        "lastViewedAt": 0,
        "file": "/example/library/Second Example/Second Album/01 Loud Track.flac",  # leakcheck: allow=media-path
        "container": "flac",
        "bitrate": 1000,
        "size": 25000000,
        "accessible": 1,
        "exists": 1,
    },
    {
        # A compilation track: the album artist is "Various Artists" and only
        # `originalTitle` says who is playing.
        "key": 311,
        "title": "Guest Track",
        "album": 310,
        "index": 1,
        "userRating": None,
        "duration": 240000,
        "moods": ["31"],
        "analysis": 6,
        "originalTitle": "Example Artist",
        "viewCount": 0,
        "skipCount": 0,
        "addedAt": 1620000110,
        "lastViewedAt": 0,
        "file": "/example/library/Various Artists/Example Compilation/01 Guest Track.flac",  # leakcheck: allow=media-path
        "container": "flac",
        "bitrate": 950,
        "size": 24000000,
        "accessible": 1,
        "exists": 1,
    },
]

#: One film, on the video library this server also has. It exists for exactly one
#: reason: a rating key that resolves here but cannot go into an audio playlist
#: is the *only* way to reach plexapi's mixed-media refusal, and a refusal with
#: no way to trigger it is a translation nobody has tested.
MOVIES = [
    {
        "key": 900,
        "title": "Example Film",
        "guid": "plex://movie/a1b2c3d4e5f60718293d0900",
        "year": 2011,
        "addedAt": 1630000000,
        "duration": 5400000,
    },
]

#: Playlists as the server holds them. Three, because all three matter: an
#: ordinary audio one that can be edited, a *smart* audio one that cannot, and a
#: video one that must never appear in a music tool's listing.
PLAYLISTS = [
    {
        "id": 501,
        "title": "Example Playlist",
        "type": "audio",
        "smart": 0,
        "items": [111, 112],
        "updatedAt": 1700000100,
    },
    {
        # `leafCount` is what the server *declares*, and on a smart playlist it
        # is a cached figure that drifts from what the saved search currently
        # returns -- observed on a real server as a declared 0 against 81 actual
        # items, and off by one even on a static playlist. The double kept the
        # two in agreement until `playlist list` and `playlist show` were caught
        # contradicting each other in the field.
        "id": 502,
        "title": "Example Smart Playlist",
        "type": "audio",
        "smart": 1,
        "items": [111, 211],
        "leafCount": 5,
        "updatedAt": 1700000200,
    },
    {
        "id": 503,
        "title": "Example Film Night",
        "type": "video",
        "smart": 0,
        "items": [900],
        "updatedAt": 1700000300,
    },
]

#: What plex.tv answers when the owner asks who this server is shared with. The
#: access token here is the whole point: it is the only place the mapping from a
#: username to a per-user token for this machine exists.
SHARED_USERS = [
    {
        "id": SHARED_USER_ID,
        "username": SHARED_USERNAME,
        "email": SHARED_EMAIL,
        "token": USER_TOKEN,
    },
]

#: Sonic neighbours, keyed by seed rating key, as (rating key, distance).
NEIGHBOURS = {
    111: [(211, 0.0821), (311, 0.1902)],
    121: [(111, 0.0100)],
}

#: One active session, shaped like a real one. `device`, `product` and
#: `platform` are three different strings on a real player and none of them is
#: `title`, which a real `<Player>` does not carry at all -- so a fixture where
#: they agreed would hide which of them `sessions` actually reads.
SESSIONS = [
    {
        "track": 111,
        "device": "Example Speaker",
        "product": "Plex for Example",
        "platform": "ExampleOS",
        "state": "playing",
    }
]

SEARCH_TYPES = {"8": "artist", "9": "album", "10": "track"}

#: The plex.tv **account** token, which is a different and broader credential
#: than :data:`TOKEN`: the server accepts one and plex.tv accepts the other, and
#: the whole point of the Sonos route's own variable is that they are not
#: interchangeable. Measured against a real installation: a server token gets a
#: flat 401 from plex.tv.
ACCOUNT_TOKEN = "example-token-0000000003"

#: The delegation token `/security/token` mints, on a server that will mint one.
DELEGATION_TOKEN = "example-token-0000000004"

#: Machine identifiers for the things that can be played to. On their own lines
#: and obviously synthetic, like :data:`MACHINE_ID`.
CLIENT_ID = "1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a"
SCREEN_ID = "2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b"
PORTLESS_ID = "4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d"
SPEAKER_ID = "3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c"

#: What `/clients` answers with.
#:
#: **Shape transcribed, with one caveat that has to be said out loud.** A
#: `/clients` entry is a ``<Server>`` element, and this attribute list is the one
#: the client library reads off one -- ``name`` (not ``title``),
#: ``machineIdentifier``, ``product``, ``deviceClass``, ``protocolVersion``,
#: ``protocolCapabilities``, plus the ``host``/``address``/``port`` trio -- taken
#: from ``plexapi.client.PlexClient._loadData`` and ``PlexServer.clients``, which
#: are the only public description of it. It is **not** copied from a live
#: capture: no client was advertising on the server this was written against, and
#: the honest thing is to say so rather than to imply a capture that does not
#: exist. See AGENTS.md, "The double-fidelity rule".
#:
#: The three rows are three different answers on purpose:
#:
#: * one that can play, and answers a playback command with the bare ``OK`` that
#:   Plexamp and Plex for Android send rather than with XML;
#: * one that answers but advertises no ``playback`` capability, so a tool that
#:   read the list without reading the capabilities would address it and watch
#:   nothing happen;
#: * one that advertises no ``port``, which is the case that makes
#:   ``PlexServer.clients()`` reach plex.tv for the missing number. Nothing here
#:   uses that helper, and this row is what proves it.
CLIENTS = [
    {
        "name": "Example Client",
        "machineIdentifier": CLIENT_ID,
        "host": "203.0.113.11",
        "address": "203.0.113.11",
        "port": "32500",
        "product": "Example Player",
        "deviceClass": "phone",
        "version": "4.0.0",
        "protocol": "plex",
        "protocolVersion": "1",
        "protocolCapabilities": "timeline,playback,playqueues",
        "answers": "OK",
    },
    {
        "name": "Example Screen",
        "machineIdentifier": SCREEN_ID,
        "host": "203.0.113.12",
        "address": "203.0.113.12",
        "port": "32500",
        "product": "Example Display",
        "deviceClass": "stb",
        "version": "2.0.0",
        "protocol": "plex",
        "protocolVersion": "1",
        "protocolCapabilities": "timeline,navigation",
        "answers": "xml",
    },
    {
        "name": "Example Portless",
        "machineIdentifier": PORTLESS_ID,
        "host": "203.0.113.13",
        "address": "203.0.113.13",
        "port": "",
        "product": "Example Player",
        "deviceClass": "pc",
        "version": "1.0.0",
        "protocol": "plex",
        "protocolVersion": "1",
        "protocolCapabilities": "timeline,playback",
        "answers": "xml",
    },
]

#: What ``sonos.plex.tv/resources`` answers with. Attributes transcribed from
#: ``plexapi.sonos.PlexSonosClient.__init__``, which is the only public
#: description of the element; ``lanIP`` is on it and is deliberately never read,
#: which is what the row shape has to prove.
SONOS_SPEAKERS = [
    {
        "title": "Example Speaker",
        "machineIdentifier": SPEAKER_ID,
        "product": "Sonos",
        "platform": "Sonos",
        "platformVersion": "80.0",
        "deviceClass": "speaker",
        "protocol": "plex",
        "protocolCapabilities": "timeline,playback,playqueues,provider-playback",
        "lanIP": "203.0.113.21",
    }
]


class Tables:
    """One server's own copy of the fixture.

    The tables were module-level constants until this tool could write. They
    cannot stay that way: a rating set by one test would be visible to the next,
    and a suite whose fixtures leak between cases is a suite that passes for
    reasons nobody chose. Every :class:`FakePlex` deep-copies them, so a write
    is visible to the next read *within one test* and to nothing outside it.
    """

    def __init__(self):
        self.artists = copy.deepcopy(ARTISTS)
        self.albums = copy.deepcopy(ALBUMS)
        self.tracks = copy.deepcopy(TRACKS)
        self.movies = copy.deepcopy(MOVIES)
        self.artist_by_key = {row["key"]: row for row in self.artists}
        self.album_by_key = {row["key"]: row for row in self.albums}
        self.by_key = {}
        for kind, rows in (
            ("artist", self.artists),
            ("album", self.albums),
            ("track", self.tracks),
            ("movie", self.movies),
        ):
            for row in rows:
                self.by_key[row["key"]] = (kind, row)

    def rows(self, libtype):
        return {"artist": self.artists, "album": self.albums, "track": self.tracks}[libtype]


# ------------------------------------------------------------- accepted parameters

#: Query parameters this server understands. Anything else is a 400.
#:
#: This is the assertion that makes the suite worth running. The failure mode
#: this tool exists to prevent is a filter that reaches the URL in a spelling
#: Plex does not define -- ``userRating__gte=8`` rather than ``userRating>=8`` --
#: which a permissive server would ignore, returning a plausible unfiltered
#: answer. Here it is a refusal.
KNOWN_PARAMS = {
    "type",
    "title",
    "sort",
    "limit",
    "group",
    "includeGuids",
    "includeMeta",
    "includeAdvanced",
    "includeCollections",
    "checkFiles",
    "maxDistance",
    "X-Plex-Container-Start",
    "X-Plex-Container-Size",
}

#: The parenthesis and boolean markers Plex's advanced search uses. They are not
#: filters and they are not skippable noise either: they carry the *structure* of
#: the expression, so they are read in order rather than looked up in a dict --
#: which is why :class:`FakeSession` hands the parameters over as an ordered list
#: as well as a mapping.
GROUPING_PARAMS = {"push", "pop", "or", "and"}

#: Field parameters, as ``<libtype>.<field>`` with an optional operator suffix.
#: The operator set is Plex's own, and deliberately does not contain ``__gte``
#: and friends: those are the client library's Python-side operators, and a URL
#: carrying one is a bug this double must expose rather than absorb.
KNOWN_FIELDS = {
    "artist.title",
    "album.title",
    "track.title",
    "artist.genre",
    "artist.style",
    "album.year",
    "track.mood",
    "album.mood",
    "artist.mood",
    "track.userRating",
    "album.userRating",
    "artist.userRating",
    "artist.addedAt",
    "album.addedAt",
    "track.addedAt",
    "track.lastViewedAt",
    "track.viewCount",
    "track.skipCount",
    "track.trash",
    "album.subformat",
}

#: Query parameters the playlist endpoints define. Same rule as everywhere else:
#: anything not here is a 400, so a write that reached the URL misspelled fails
#: the suite rather than being quietly absorbed.
KNOWN_PLAYLIST_PARAMS = {"playlistType", "sectionID", "title", "sort", "type", "smart", "uri"}

#: What ``/playQueues`` defines. Same rule as everywhere else: anything not here
#: is a 400, so a play queue built with a parameter Plex does not know fails the
#: suite rather than being quietly absorbed.
PLAYQUEUE_PARAMS = {
    "type",
    "uri",
    "playlistID",
    "key",
    "shuffle",
    "repeat",
    "continuous",
    "includeChapters",
    "includeRelated",
}

#: What ``/player/playback/playMedia`` requires. ``containerKey`` is the one
#: that matters: it names the play queue, and a playback command that points at
#: a queue this server never created is refused rather than answered with a
#: cheerful 200.
PLAY_REQUIRED = {
    "providerIdentifier",
    "machineIdentifier",
    "protocol",
    "address",
    "port",
    "offset",
    "key",
    "type",
    "containerKey",
    "commandID",
}
PLAY_OPTIONAL = {"token"}

#: What `/:/rate` requires. `identifier` is not decoration: without it Plex does
#: not know which agent's rating is being set.
RATE_PARAMS = {"key", "identifier", "rating"}
RATE_IDENTIFIER = "com.plexapp.plugins.library"
KNOWN_OPERATORS = {"", "=", "!", "!=", "<", ">", ">>", "<<", "<=", ">=", ">>=", "<<=", "&"}


class PlexRefusal(Exception):
    """A request this server refuses, carrying the status it answers with."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.text = message


# ----------------------------------------------------------------------- XML


def _attrs(pairs):
    return " ".join(f"{k}={quoteattr(str(v))}" for k, v in pairs if v not in (None, ""))


def _container(body, *, size, total=None, extra=()):
    head = _attrs(
        [
            ("size", size),
            ("totalSize", total if total is not None else size),
            ("identifier", "com.plexapp.plugins.library"),
            ("mediaTagPrefix", "/system/bundle/media/flags/"),
            *extra,
        ]
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<MediaContainer {head}>{body}</MediaContainer>'


def _tags(kind, ids, table):
    return "".join(f'<{kind} id="{i}" tag={quoteattr(table[i])}/>' for i in ids if i in table)


def artist_xml(row):
    head = _attrs(
        [
            ("ratingKey", row["key"]),
            ("key", "/library/metadata/{}/children".format(row["key"])),
            ("guid", row["guid"]),
            ("type", "artist"),
            ("title", row["title"]),
            ("titleSort", row["title"]),
            ("summary", row["summary"]),
            ("userRating", row["userRating"]),
            ("addedAt", row["addedAt"]),
            ("childCount", row["childCount"]),
            ("leafCount", row["leafCount"]),
        ]
    )
    body = (
        _tags("Genre", row["genres"], GENRES)
        + _tags("Style", row["styles"], STYLES)
        + _tags("Mood", row["moods"], ARTIST_MOODS)
    )
    return f"<Directory {head}>{body}</Directory>"


def album_xml(row, tables):
    artist = tables.artist_by_key[row["artist"]]
    head = _attrs(
        [
            ("ratingKey", row["key"]),
            ("key", "/library/metadata/{}/children".format(row["key"])),
            ("guid", "plex://album/a1b2c3d4e5f60718293b{:04d}".format(row["key"])),
            ("type", "album"),
            ("title", row["title"]),
            ("titleSort", row["title"]),
            ("parentRatingKey", artist["key"]),
            ("parentTitle", artist["title"]),
            ("parentGuid", artist["guid"]),
            ("year", row["year"]),
            ("leafCount", row["leafCount"]),
            ("userRating", row["userRating"]),
            ("addedAt", row["addedAt"]),
            ("studio", row["studio"]),
            ("summary", row["summary"]),
        ]
    )
    return f"<Directory {head}/>"


def track_xml(row, tables, *, check_files=False, distance=None, session=None, item_id=None):
    album = tables.album_by_key[row["album"]]
    artist = tables.artist_by_key[album["artist"]]
    part = _attrs(
        [
            ("id", row["key"]),
            ("key", "/library/parts/{}/file".format(row["key"])),
            ("file", row["file"]),
            ("container", row["container"]),
            ("size", row["size"]),
            ("duration", row["duration"]),
            # accessible and exists are absent unless the request asked the
            # server to stat the file, which is exactly what the real server
            # does and what makes "not checked" a testable state.
            ("accessible", row["accessible"] if check_files else None),
            ("exists", row["exists"] if check_files else None),
        ]
    )
    media_head = _attrs(
        [
            ("id", row["key"]),
            ("bitrate", row["bitrate"]),
            ("duration", row["duration"]),
            ("audioCodec", row["container"]),
        ]
    )
    media = f"<Media {media_head}><Part {part}/></Media>"
    player = ""
    if session:
        # A real session element always carries a User child, and the client
        # library reads it without guarding -- a session without one raises an
        # AttributeError rather than parsing to something empty. The double
        # models that, so the tool is exercised against the shape it will meet.
        #
        # TRANSCRIBED: the `<Player>` attributes are the ones a real
        # `/status/sessions` sends, and the absence of `title` is the load-
        # bearing half. This element once carried an invented `title=`, and
        # `sessions` read it -- so the column naming *where the music is
        # playing* was empty on every real session and full on every test.
        player = "<User {}/><Player {}/>".format(
            _attrs([("id", 1), ("title", "example-user")]),
            _attrs(
                [
                    ("address", "198.51.100.7"),
                    ("device", session["device"]),
                    ("machineIdentifier", "example-device-0001"),
                    ("platform", session["platform"]),
                    ("product", session["product"]),
                    ("profile", "Generic"),
                    ("state", session["state"]),
                    ("version", "3.0.0"),
                ]
            ),
        )
    head = _attrs(
        [
            ("ratingKey", row["key"]),
            ("key", "/library/metadata/{}".format(row["key"])),
            # An explicit guid wins, which is how a `local://` row is modelled;
            # the catalogue form is the default because most tracks carry it.
            (
                "guid",
                row.get("guid") or "plex://track/a1b2c3d4e5f60718293c{:04d}".format(row["key"]),
            ),
            ("type", "track"),
            ("title", row["title"]),
            ("titleSort", row["title"]),
            ("originalTitle", row["originalTitle"]),
            ("parentRatingKey", album["key"]),
            ("parentTitle", album["title"]),
            ("parentIndex", 1),
            ("grandparentRatingKey", artist["key"]),
            ("grandparentTitle", artist["title"]),
            ("index", row["index"]),
            ("year", album["year"]),
            ("duration", row["duration"]),
            ("userRating", row["userRating"]),
            ("viewCount", row["viewCount"]),
            ("skipCount", row["skipCount"]),
            ("addedAt", row["addedAt"]),
            ("lastViewedAt", row["lastViewedAt"] or None),
            ("musicAnalysisVersion", row["analysis"]),
            ("distance", distance),
            # Only present when the track is being listed as part of a playlist.
            # It is the handle `removeItems` deletes by, and it is per membership
            # rather than per track: the same song twice in a list has two.
            ("playlistItemID", item_id),
        ]
    )
    body = media + _tags("Mood", row["moods"], TRACK_MOODS) + player
    return f"<Track {head}>{body}</Track>"


def movie_xml(row, *, item_id=None):
    """A film, which exists here only so a mixed-media playlist can be refused."""
    head = _attrs(
        [
            ("ratingKey", row["key"]),
            ("key", "/library/metadata/{}".format(row["key"])),
            ("guid", row["guid"]),
            ("type", "movie"),
            ("title", row["title"]),
            ("titleSort", row["title"]),
            ("year", row["year"]),
            ("duration", row["duration"]),
            ("addedAt", row["addedAt"]),
            ("librarySectionID", VIDEO_SECTION_KEY),
            ("playlistItemID", item_id),
        ]
    )
    return f"<Video {head}/>"


def playlist_xml(row, tables):
    """One playlist as the server describes it.

    ``key`` carries the ``/items`` suffix a real server sends, because the client
    library strips it -- and a double that pre-stripped it would hide the day
    that stops being true.
    """
    duration = 0
    for entry in row["items"]:
        _kind, item = tables.by_key[entry["key"]]
        duration += item.get("duration") or 0
    head = _attrs(
        [
            ("ratingKey", row["id"]),
            ("key", "/playlists/{}/items".format(row["id"])),
            ("guid", "com.plexapp.agents.none://{:08d}".format(row["id"])),
            ("type", "playlist"),
            ("title", row["title"]),
            ("titleSort", row["title"]),
            ("summary", ""),
            ("smart", row["smart"]),
            ("playlistType", row["type"]),
            ("composite", "/playlist/{}/composite/1".format(row["id"])),
            ("duration", duration or None),
            # The declared count, which is not always the real one.
            ("leafCount", row.get("leafCount", len(row["items"]))),
            ("addedAt", 1700000000),
            ("updatedAt", row["updatedAt"]),
        ]
    )
    return f"<Playlist {head}/>"


def client_xml(row):
    """One `/clients` entry, addresses and all.

    The address attributes are here precisely because the tool must never print
    them: a double that left them out could not tell a command that withholds
    them from one that never had them.
    """
    head = _attrs(
        [
            ("name", row["name"]),
            ("host", row["host"]),
            ("address", row["address"]),
            ("port", row["port"]),
            ("machineIdentifier", row["machineIdentifier"]),
            ("version", row["version"]),
            ("protocol", row["protocol"]),
            ("product", row["product"]),
            ("deviceClass", row["deviceClass"]),
            ("protocolVersion", row["protocolVersion"]),
            ("protocolCapabilities", row["protocolCapabilities"]),
        ]
    )
    return f"<Server {head}/>"


def sonos_xml(row):
    head = _attrs(
        [
            ("title", row["title"]),
            ("machineIdentifier", row["machineIdentifier"]),
            ("product", row["product"]),
            ("platform", row["platform"]),
            ("platformVersion", row["platformVersion"]),
            ("deviceClass", row["deviceClass"]),
            ("protocol", row["protocol"]),
            ("protocolCapabilities", row["protocolCapabilities"]),
            ("lanIP", row["lanIP"]),
        ]
    )
    return f"<Player {head}/>"


# -------------------------------------------------------------- filter metadata
#
# TRANSCRIBED, NOT AUTHORED. Every table below is copied from a real
# `/library/sections/<key>/all?includeMeta=1` response (Plex Media Server
# 1.42.2). Nothing here may be invented, extended or "obviously" completed:
# these tables say what the *server* offers, and a guess in one of them builds
# the tool against a Plex that does not exist. See AGENTS.md, "The
# double-fidelity rule".
#
# The cost of ignoring that is on the record. `_INT_OPS` once carried `<=`
# ("is less than or equals") and `>=` ("is greater than or equals"), which real
# Plex does not define for any type, and `--rated-min` was built on one of them.
# It failed at every value against every real server and passed every test here.

_STRING_OPS = [
    ("=", "contains"),
    ("!=", "does not contain"),
    ("==", "is"),
    ("!==", "is not"),
    # Plex's "begins with"/"ends with". They are *not* numeric comparisons, and
    # reading them as such is how the invented integer operators got here.
    ("<=", "begins with"),
    (">=", "ends with"),
]
#: Real Plex offers no "greater than or equal" for an integer at all: `>>=` is
#: strictly greater and `<<=` is strictly less. "At least N" is therefore
#: `>>= N-1`, which is what `filters.rating_predicate` builds.
_INT_OPS = [
    ("=", "is"),
    ("!=", "is not"),
    (">>=", "is greater than"),
    ("<<=", "is less than"),
]
_TAG_OPS = [("=", "is"), ("!=", "is not")]
_DATE_OPS = [("<<=", "is before"), (">>=", "is after")]
_BOOL_OPS = [("=", "is true"), ("!=", "is false")]

#: Fields each libtype advertises, mirroring what a scanned music library
#: publishes. ``group`` is absent on purpose -- see :data:`GROUPABLE`.
SECTION_FIELDS = {
    "artist": [
        ("artist.title", "Title", "string"),
        ("artist.genre", "Genre", "tag"),
        ("artist.style", "Style", "tag"),
        ("artist.mood", "Mood", "tag"),
        ("artist.userRating", "Rating", "integer"),
        ("artist.addedAt", "Date Added", "date"),
    ],
    "album": [
        ("album.title", "Title", "string"),
        ("album.year", "Year", "integer"),
        ("album.mood", "Mood", "tag"),
        ("album.subformat", "Subformat", "tag"),
        ("album.userRating", "Rating", "integer"),
        ("album.addedAt", "Date Added", "date"),
    ],
    "track": [
        ("track.title", "Track Title", "string"),
        ("track.mood", "Track Mood", "tag"),
        ("track.userRating", "Track Rating", "integer"),
        ("track.addedAt", "Track Added At", "date"),
        ("track.lastViewedAt", "Track Last Played", "date"),
        # The never-played half of `--not-played-since`. It is `viewCount`
        # rather than an `unplayed` boolean because a real music section
        # advertises no such boolean: `track.unplayed` was in this table once,
        # nothing on the wire ever accepted it, and `pick` degraded on every
        # real server while passing here.
        ("track.viewCount", "Track Plays", "integer"),
        ("track.skipCount", "Track Skips", "integer"),
        ("track.trash", "Trash", "boolean"),
    ],
}

#: The same tables with everything `pick` depends on taken out, which is what
#: :class:`FakePlex` serves when ``spartan=True``. A server that does not
#: advertise a field is not a hypothetical: filter metadata is per-library and
#: changes with the Plex version, so the tool has to degrade with an explanation
#: rather than fail, and that path needs a server to test it against.
SPARTAN_FIELDS = {
    "artist": SECTION_FIELDS["artist"],
    "album": [f for f in SECTION_FIELDS["album"] if not f[0].endswith("subformat")],
    "track": [
        f for f in SECTION_FIELDS["track"] if not f[0].endswith(("lastViewedAt", "viewCount"))
    ],
}

#: A server that advertises the date but not the play count, which is the one
#: `--not-played-since` degradation that still returns an answer: the period
#: runs and the never-played half cannot be ORed in.
DATE_ONLY_FIELDS = {
    "artist": SECTION_FIELDS["artist"],
    "album": SECTION_FIELDS["album"],
    "track": [f for f in SECTION_FIELDS["track"] if not f[0].endswith("viewCount")],
}

#: The tag filters each libtype offers, as ``filter`` name to choices endpoint.
SECTION_FILTERS = {
    "artist": [("genre", "Genre"), ("style", "Style"), ("mood", "Mood")],
    "album": [("mood", "Mood"), ("subformat", "Subformat")],
    "track": [("mood", "Mood")],
}

SPARTAN_FILTERS = {
    "artist": SECTION_FILTERS["artist"],
    "album": [f for f in SECTION_FILTERS["album"] if f[0] != "subformat"],
    "track": SECTION_FILTERS["track"],
}

#: The sorts a scanned music library publishes. ``random`` is Plex's own shuffle
#: and is the one `pick` asks for; the spartan server withholds it, because a
#: picker that failed rather than saying "not shuffled" would be worse.
SECTION_SORTS = (
    ("titleSort", "Title", "asc"),
    ("addedAt", "Date Added", "desc"),
    ("userRating", "Rating", "desc"),
    ("random", "Randomly", "asc"),
)
SPARTAN_SORTS = tuple(s for s in SECTION_SORTS if s[0] != "random")

#: The ``group`` field is deliberately absent from this metadata, because it is
#: absent from a real server's too: the client library adds it by hand rather
#: than reading it, so ``group=title`` validates and reaches the wire whatever
#: the server advertises. What a server does *with* it is the open question, so
#: :class:`FakePlex` models both answers -- see its ``groupable`` argument.


def _meta_xml(fields_table=None, filters_table=None, sorts=None):
    fields_table = SECTION_FIELDS if fields_table is None else fields_table
    filters_table = SECTION_FILTERS if filters_table is None else filters_table
    sorts = SECTION_SORTS if sorts is None else sorts
    types = []
    for index, (libtype, code) in enumerate((("artist", 8), ("album", 9), ("track", 10))):
        fields = list(fields_table[libtype])
        field_xml = "".join(
            '<Field key="{}" title="{}" type="{}"/>'.format(*field) for field in fields
        )
        filter_xml = "".join(
            f'<Filter filter="{name}" filterType="string" key="/library/sections/{MUSIC_SECTION_KEY}/{libtype}/{name}" title="{title}" type="filter"/>'
            for name, title in filters_table[libtype]
        )
        sort_xml = "".join(
            f'<Sort defaultDirection="{direction}" descKey="{key}:desc" '
            f'key="{key}" title={quoteattr(title)}/>'
            for key, title, direction in sorts
        )
        types.append(
            f'<Type active="{1 if index == 0 else 0}" key="/library/sections/{MUSIC_SECTION_KEY}/all?type={code}" '
            f'type="{libtype}" title="{libtype}s">{filter_xml}{sort_xml}{field_xml}</Type>'
        )
    field_types = "".join(
        '<FieldType type="{}">{}</FieldType>'.format(
            name,
            "".join(f"<Operator key={quoteattr(k)} title={quoteattr(t)}/>" for k, t in ops),
        )
        for name, ops in (
            ("string", _STRING_OPS),
            ("integer", _INT_OPS),
            ("tag", _TAG_OPS),
            ("date", _DATE_OPS),
            ("boolean", _BOOL_OPS),
        )
    )
    return "<Meta>{}{}</Meta>".format("".join(types), field_types)


# ------------------------------------------------------------------ predicates


def _artist_of(kind, row, tables):
    if kind == "artist":
        return row
    if kind == "album":
        return tables.artist_by_key[row["artist"]]
    return tables.artist_by_key[tables.album_by_key[row["album"]]["artist"]]


def _album_of(kind, row, tables):
    if kind == "album":
        return row
    if kind == "track":
        return tables.album_by_key[row["album"]]
    return None


def _value_for(field, kind, row, tables):
    """The value one ``<libtype>.<field>`` predicate compares against.

    Scoping is resolved the way Plex resolves it: a track matches
    ``artist.genre`` through the artist it belongs to, which is why a
    track-level genre search on a library tagged the ordinary way finds nothing
    and the scoped one finds everything.
    """
    scope, _, name = field.partition(".")
    if scope == "artist":
        source = _artist_of(kind, row, tables)
    elif scope == "album":
        source = _album_of(kind, row, tables)
    else:
        source = row if kind == "track" else None
    if source is None:
        return None
    if name == "title":
        return source["title"]
    if name == "year":
        return source.get("year")
    if name == "userRating":
        return source.get("userRating")
    if name == "addedAt":
        return source.get("addedAt")
    if name == "lastViewedAt":
        # A track Plex has never played carries no lastViewedAt at all: the
        # column is null, not zero. What Plex *does* with that null in a "before
        # X" comparison is the part the double got wrong -- it modelled the null
        # as not matching, and on a real server it matches. Both halves are
        # modelled now: the attribute is absent from the XML, and `_matches`
        # treats the absence the way the server does.
        return source.get("lastViewedAt") or _NEVER_PLAYED
    if name == "viewCount":
        return source.get("viewCount") or 0
    if name == "skipCount":
        return source.get("skipCount") or 0
    if name == "trash":
        return 0
    if name == "genre":
        return source.get("genres", [])
    if name == "style":
        return source.get("styles", [])
    if name == "mood":
        return source.get("moods", [])
    if name == "subformat":
        return source.get("subformat", [])
    raise PlexRefusal(400, f"unknown field {field} in this container")


#: A date column the server holds as null, which is what a never-played track's
#: `lastViewedAt` is. Distinct from ``None`` because ``None`` here means "this
#: field does not apply to this row", and the two compare differently.
_NEVER_PLAYED = object()

#: Seconds in each unit Plex's relative dates use. `mon` is deliberately not `m`:
#: minutes are `m`, and getting that pair the wrong way round is a filter that
#: silently means something else.
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "mon": 2592000, "y": 31536000}


_RELATIVE = re.compile(r"^-?(\d+)(mon|[smhdwy])$")


def _is_relative(value) -> bool:
    return bool(_RELATIVE.match(str(value)))


def _relative_seconds(value) -> float:
    """A relative date as an absolute epoch, resolved the way a server would."""
    count, unit = _RELATIVE.match(str(value)).groups()
    return time.time() - int(count) * _UNITS[unit]


def _matches_date(operator, wanted, value) -> bool:
    threshold = _relative_seconds(wanted)
    moment = float(value)
    if operator == "<<":
        return moment < threshold
    if operator == ">>":
        return moment > threshold
    if operator == "<":
        return moment <= threshold
    if operator == ">":
        return moment >= threshold
    raise PlexRefusal(400, f"operator {operator} is not defined for a date")


def _matches(field, operator, wanted, kind, row, tables):
    value = _value_for(field, kind, row, tables)
    if value is _NEVER_PLAYED:
        # Measured, not reasoned about: on a real server a null date matches a
        # "before" comparison and not an "after" one -- 9 993 of 10 000
        # never-played tracks came back from `track.lastViewedAt<<=-30d`. SQL
        # would say neither, which is exactly why this had to be transcribed
        # rather than derived. `pick --not-played-since` was built on the
        # opposite assumption and described its own result wrongly as a result.
        # It holds for an absolute threshold as well as a relative one: there is
        # no date the column is not before.
        return operator in ("<<", "<")
    if value is None:
        return False
    if isinstance(value, list):
        # Tag fields carry ids; a comma-separated value is an OR, and `!` negates
        # the whole set -- which is what `album.subformat!=51,52` asks for.
        held = any(part in value for part in wanted.split(","))
        if operator in ("", "="):
            return held
        if operator == "!":
            return not held
        raise PlexRefusal(400, f"operator {operator} is not defined for a tag")
    if _is_relative(wanted):
        return _matches_date(operator, wanted, value)
    if isinstance(value, str):
        text, needle = value.lower(), wanted.lower()
        if operator == "":
            return needle in text
        if operator == "=":
            return text == needle
        if operator == "!":
            return needle not in text
        if operator == "<":
            return text.startswith(needle)
        if operator == ">":
            return text.endswith(needle)
        raise PlexRefusal(400, f"operator {operator} is not defined for a string")
    number = float(wanted)
    if operator == "":
        return float(value) == number
    if operator == "!":
        return float(value) != number
    if operator == ">":
        return float(value) >= number
    if operator == ">>":
        return float(value) > number
    if operator == "<":
        return float(value) <= number
    if operator == "<<":
        return float(value) < number
    raise PlexRefusal(400, f"operator {operator} is not defined for a number")


# --------------------------------------------------------------------- server


class FakePlex:
    """Routes a request the way a Plex Media Server does, and refuses like one."""

    def __init__(
        self,
        *,
        groupable=True,
        token=TOKEN,
        music_sections=1,
        spartan=False,
        shared_users=None,
        plex_tv_status=200,
        plex_tv_account=True,
        plex_tv_unreachable=False,
        refuse_user_token=False,
        fields=None,
        clients=None,
        sonos=None,
        sonos_status=200,
        mints_tokens=False,
    ):
        self.groupable = groupable
        self.token = token
        self.music_sections = music_sections
        self.tables = Tables()
        #: `spartan=True` is a server whose filter metadata lacks everything
        #: `pick` would like to use. It is not a hypothetical: filter metadata is
        #: per-library and moves with the Plex version, and the tool's contract
        #: is to degrade with an explanation rather than fail.
        self.fields = fields or (SPARTAN_FIELDS if spartan else SECTION_FIELDS)
        self.filters = SPARTAN_FILTERS if spartan else SECTION_FILTERS
        self.sorts = SPARTAN_SORTS if spartan else SECTION_SORTS
        self.playlists = copy.deepcopy(PLAYLISTS)
        self._next_playlist_id = 600
        self._next_item_id = 1000
        for playlist in self.playlists:
            playlist["items"] = [
                {"key": key, "item_id": self._item_id()} for key in playlist["items"]
            ]
        #: Ratings written during this test, keyed by *account* as well as item:
        #: a user rating is per-account in Plex, which is the whole reason
        #: `--user` exists.
        self.ratings = {}
        self.shared_users = SHARED_USERS if shared_users is None else shared_users
        self.plex_tv_status = plex_tv_status
        #: Whether plex.tv recognises this token as an account token at all.
        #: False models the token that works against the server and is refused
        #: by the cloud -- which is what a local-only server token is.
        self.plex_tv_account = plex_tv_account
        self.plex_tv_unreachable = plex_tv_unreachable
        #: A server that no longer accepts the per-user token even though
        #: plex.tv still lists it -- revoked, or a short-lived token that aged
        #: out. It is the one `--user` failure that arrives *after* the cloud
        #: call succeeds, so the tool has to blame the per-user token rather
        #: than PLEX_TOKEN, and a double that always accepted it could not test
        #: that attribution.
        self.refuse_user_token = refuse_user_token
        #: Every request this server was asked for, so a test can assert on the
        #: request the client actually built.
        self.requests = []
        #: The subset that was not a GET. A gate that is claimed to block has to
        #: be shown to block *here*, on the wire, not merely in an exit code.
        self.writes = []
        self.plex_tv_requests = []
        #: The clients this server can see. A list rather than a constant so a
        #: test can model an empty network, or two clients with the same name.
        self.clients_seen = CLIENTS if clients is None else clients
        self.sonos_speakers_seen = SONOS_SPEAKERS if sonos is None else sonos
        self.sonos_status = sonos_status
        #: Whether `/security/token` mints a delegation token. **False by
        #: default, because that is what a real server did**: a server whose
        #: token is not a plex.tv account token answers `403 Forbidden` there,
        #: and a double that always minted one would have hidden the fact that
        #: the client library's own play path fails outright on such a server.
        self.mints_tokens = mints_tokens
        self.playqueues = {}
        self._next_playqueue = 700
        #: Every playback command this server was asked to forward, so a test
        #: can assert on what was sent rather than on an exit code.
        self.played = []
        self.sonos_requests = []
        self._identity = "owner"

    def _item_id(self):
        self._next_item_id += 1
        return self._next_item_id

    # -- routing ---------------------------------------------------------

    def handle(self, path, query, headers, *, method="GET", pairs=None, host=""):
        pairs = list(query.items()) if pairs is None else list(pairs)
        record = {
            "path": path,
            "query": dict(query),
            # Ordered as well as mapped: a parenthesised filter expression is
            # carried by the order, and a test that only saw the mapping could
            # not tell `(A or B) and C` from `A or (B and C)`.
            "pairs": list(pairs),
            "headers": dict(headers),
            "method": method,
            "host": host,
        }
        if host == "sonos.plex.tv":
            self.sonos_requests.append(record)
            return self._sonos(path, query, headers, method)
        if host == "plex.tv":
            self.plex_tv_requests.append(record)
            return self._plex_tv(path, headers, method)

        self.requests.append(record)
        if method != "GET":
            self.writes.append(record)

        identity = self._identify(headers)

        start = int(headers.get("X-Plex-Container-Start", query.get("X-Plex-Container-Start", 0)))
        size = headers.get("X-Plex-Container-Size", query.get("X-Plex-Container-Size"))
        size = None if size is None else int(size)

        if path in ("/", ""):
            return self._root()
        if path.rstrip("/") == "/library":
            return self._library()
        if path.rstrip("/") == "/library/sections":
            return self._sections()
        if path.startswith("/library/sections/"):
            return self._section(path, query, pairs, start, size)
        if path.startswith("/library/metadata/"):
            return self._metadata(path, query)
        if path == "/status/sessions":
            return self._sessions()
        if path == "/:/rate":
            return self._rate(query, method, identity)
        if path == "/playlists" or path.startswith("/playlists/"):
            return self._playlists(path, query, method, start, size)
        if path == "/clients":
            return self._clients(method)
        if path == "/playQueues":
            return self._playqueue(query, method)
        if path == "/player/playback/playMedia":
            return self._play(query, headers, method)
        if path == "/security/token":
            return self._security_token(method)
        raise PlexRefusal(404, '<Response code="1000" status="Not Found"/>')

    def _identify(self, headers):
        """Which account this request is authenticated as, or a 401.

        Two tokens are accepted rather than one, because `--user` reconnects with
        the token plex.tv handed back and every per-account value after that has
        to be that account's.
        """
        token = headers.get("X-Plex-Token")
        identities = {self.token: "owner"}
        for user in self.shared_users:
            identities[user["token"]] = user["username"]
        if token not in identities or (self.refuse_user_token and token != self.token):
            raise PlexRefusal(
                401, '<Response code="1001" status="User could not be authenticated"/>'
            )
        self._identity = identities[token]
        return self._identity

    def _root(self):
        head = _attrs(
            [
                ("machineIdentifier", MACHINE_ID),
                ("friendlyName", SERVER_NAME),
                ("version", SERVER_VERSION),
                ("platform", "Linux"),
                ("myPlexSubscription", 1),
                ("allowSync", 1),
            ]
        )
        return f'<?xml version="1.0" encoding="UTF-8"?>\n<MediaContainer {head}></MediaContainer>'

    def _library(self):
        """The index a real server answers at ``/library``, which is what the
        client library asks for before it will list sections."""
        entries = "".join(
            f'<Directory key="{key}" title="{title}"/>'
            for key, title in (
                ("sections", "Library Sections"),
                ("recentlyAdded", "Recently Added"),
                ("onDeck", "On Deck"),
            )
        )
        return _container(entries, size=3)

    def _sections(self):
        entries = [
            f'<Directory key="{VIDEO_SECTION_KEY}" type="movie" title={quoteattr(VIDEO_SECTION_TITLE)} agent="tv.plex.agents.movie" '
            'scanner="Plex Movie" uuid="00000000-0000-0000-0000-000000000001"/>',
            f'<Directory key="{MUSIC_SECTION_KEY}" type="artist" title={quoteattr(MUSIC_SECTION_TITLE)} agent="tv.plex.agents.music" '
            'scanner="Plex Music" uuid="00000000-0000-0000-0000-000000000002"/>',
        ]
        if self.music_sections > 1:
            entries.append(
                '<Directory key="4" type="artist" title="Example Vinyl Rips" '
                'agent="tv.plex.agents.music" scanner="Plex Music" '
                'uuid="00000000-0000-0000-0000-000000000003"/>'
            )
        return _container("".join(entries), size=len(entries))

    # -- one section -----------------------------------------------------

    def _section(self, path, query, pairs, start, size):
        rest = path[len("/library/sections/") :]
        key, _, tail = rest.partition("/")
        if key not in (MUSIC_SECTION_KEY, "4"):
            raise PlexRefusal(404, "no such section")

        if tail in ("all", "collections") and query.get("includeMeta") == "1":
            body = (
                _meta_xml(self.fields, self.filters, self.sorts)
                if tail == "all"
                else "<Meta></Meta>"
            )
            return _container(body, size=0, total=len(self.tables.tracks))

        for libtype, filters in self.filters.items():
            for name, _title in filters:
                if tail == f"{libtype}/{name}":
                    return self._choices(name, libtype)

        if tail == "all":
            return self._all(query, pairs, start, size)
        raise PlexRefusal(404, f"no such section endpoint: {tail}")

    def _choices(self, name, libtype):
        table = {
            ("genre", "artist"): GENRES,
            ("style", "artist"): STYLES,
            ("mood", "artist"): ARTIST_MOODS,
            ("mood", "track"): TRACK_MOODS,
            ("mood", "album"): {},
            ("subformat", "album"): SUBFORMATS,
        }[(name, libtype)]
        entries = [
            f'<Directory fastKey="/library/sections/{MUSIC_SECTION_KEY}/all?{libtype}.{name}={i}" key="{i}" title={quoteattr(t)} type="{name}"/>'
            for i, t in sorted(table.items())
        ]
        return _container("".join(entries), size=len(entries))

    def _all(self, query, pairs, start, size):
        libtype = SEARCH_TYPES.get(query.get("type", "8"))
        if libtype is None:
            raise PlexRefusal(400, "unknown type {}".format(query.get("type")))

        rows = [self._rated(row) for row in self.tables.rows(libtype)]
        matched = [row for row in rows if self._passes(pairs, query, libtype, row)]

        if query.get("group") == "title" and self.groupable:
            # `groupable=False` models the other half of the open question: a
            # server that accepts the parameter and quietly ignores it. Nothing
            # in the request can tell the two apart, which is why the tool
            # checks the rows it got back rather than the query it sent.
            seen, collapsed = set(), []
            for row in matched:
                if row["title"].lower() in seen:
                    continue
                seen.add(row["title"].lower())
                collapsed.append(row)
            matched = collapsed

        matched = _sorted(matched, query.get("sort"), libtype)
        total = len(matched)
        if "limit" in query:
            matched = matched[: int(query["limit"])]
            total = len(matched)

        window = matched[start:] if size is None else matched[start : start + size]
        body = "".join(self._element(libtype, row) for row in window)
        extra = [
            ("librarySectionID", MUSIC_SECTION_KEY),
            ("librarySectionTitle", MUSIC_SECTION_TITLE),
            ("viewGroup", libtype),
        ]
        return _container(body, size=len(window), total=total, extra=extra)

    def _rated(self, row):
        """The row as *this account* sees it.

        Only the user rating is per-account here, which is enough: it is the one
        thing this tool writes and the one thing `--user` changes the answer to.
        """
        override = self.ratings.get((self._identity, row["key"]), _ABSENT)
        return row if override is _ABSENT else {**row, "userRating": override}

    def _passes(self, pairs, query, libtype, row):
        """Evaluate the filter expression in the order it arrived.

        Plex's advanced search is parenthesised -- ``push=1 A or=1 B pop=1`` --
        so a dictionary of parameters cannot represent it: the same key can
        appear more than once and the order carries the grouping. Reading the
        pairs is what lets an OR that reached the wire in the wrong shape fail
        here instead of quietly matching everything.
        """
        stack = [{"mode": "and", "results": []}]
        for name, value in pairs:
            if name == "push":
                stack.append({"mode": "and", "results": []})
                continue
            if name in ("or", "and"):
                stack[-1]["mode"] = name
                continue
            if name == "pop":
                if len(stack) == 1:
                    raise PlexRefusal(400, "pop without a matching push")
                group = stack.pop()
                stack[-1]["results"].append(_combine(group))
                continue
            if name in KNOWN_PARAMS:
                continue
            field, operator = _split_operator(name)
            if field not in KNOWN_FIELDS:
                # The refusal that matters: a filter spelled in a way Plex does
                # not define reaches here, and a server that shrugged would let
                # a no-op filter pass the whole test suite.
                raise PlexRefusal(
                    400, f"unknown filter parameter {name!r}; this server defines none such"
                )
            if operator not in KNOWN_OPERATORS:
                raise PlexRefusal(400, f"unknown operator {operator!r}")
            stack[-1]["results"].append(_matches(field, operator, value, libtype, row, self.tables))
        if len(stack) != 1:
            raise PlexRefusal(400, "push without a matching pop")
        if "title" in query and query["title"].lower() not in row["title"].lower():
            return False
        return _combine(stack[0])

    def _element(self, libtype, row):
        if libtype == "artist":
            return artist_xml(row)
        if libtype == "album":
            return album_xml(row, self.tables)
        return track_xml(row, self.tables)

    # -- one item --------------------------------------------------------

    def _metadata(self, path, query):
        rest = path[len("/library/metadata/") :]
        key, _, tail = rest.partition("/")
        try:
            rating_key = int(key)
        except ValueError:
            raise PlexRefusal(400, "rating key must be an integer") from None
        if rating_key not in self.tables.by_key:
            # A playlist's rating key lives in this namespace too, which was
            # checked against a real server rather than assumed:
            # `GET /library/metadata/<playlistRatingKey>` answers 200 with a
            # `<Playlist>` element, in the same container as a track's.
            for playlist in self.playlists:
                if playlist["id"] == rating_key and not tail:
                    return _container(playlist_xml(playlist, self.tables), size=1)
            raise PlexRefusal(404, "no item with that rating key")
        kind, row = self.tables.by_key[rating_key]
        row = self._rated(row)

        if tail == "nearest":
            if kind != "track":
                raise PlexRefusal(400, "sonic neighbours are per track")
            pairs = NEIGHBOURS.get(rating_key, [])
            limit = int(query.get("limit", 50))
            ceiling = float(query.get("maxDistance", 1.0))
            chosen = [(k, d) for k, d in pairs if d <= ceiling][:limit]
            body = "".join(
                track_xml(self.tables.by_key[k][1], self.tables, distance=d)
                for k, d in chosen
                if self.tables.by_key[k][0] == "track"
            )
            return _container(body, size=len(chosen))

        if tail:
            raise PlexRefusal(404, f"no such metadata endpoint: {tail}")

        check_files = query.get("checkFiles") == "1"
        return _container(self._item_xml(kind, row, check_files=check_files), size=1)

    def _item_xml(self, kind, row, *, check_files=False, item_id=None):
        if kind == "track":
            return track_xml(row, self.tables, check_files=check_files, item_id=item_id)
        if kind == "album":
            return album_xml(row, self.tables)
        if kind == "movie":
            return movie_xml(row, item_id=item_id)
        return artist_xml(row)

    def _sessions(self):
        body = "".join(
            track_xml(self.tables.by_key[s["track"]][1], self.tables, session=s) for s in SESSIONS
        )
        return _container(body, size=len(SESSIONS))

    # -- ratings ---------------------------------------------------------

    def _rate(self, query, method, identity):
        """``/:/rate``, refusing everything Plex refuses.

        The identifier is required because Plex needs to know whose rating scale
        is meant, and the range is 0-10 with -1 meaning "unrated". A double that
        accepted a 0-5 value here would let the star conversion break silently,
        which is the one bug this endpoint can actually have.
        """
        if method != "PUT":
            raise PlexRefusal(405, f"{method} is not defined for /:/rate")
        missing = sorted(RATE_PARAMS - set(query))
        if missing:
            raise PlexRefusal(400, f"missing parameter(s): {', '.join(missing)}")
        unknown = sorted(set(query) - RATE_PARAMS - KNOWN_PARAMS)
        if unknown:
            raise PlexRefusal(400, f"unknown parameter(s): {', '.join(unknown)}")
        if query["identifier"] != RATE_IDENTIFIER:
            raise PlexRefusal(400, "unknown identifier")
        try:
            rating_key = int(query["key"])
            rating = float(query["rating"])
        except ValueError:
            raise PlexRefusal(400, "key must be an integer and rating a number") from None
        if rating != -1 and not 0 <= rating <= 10:
            raise PlexRefusal(400, "rating must be between 0 and 10, or -1 to clear it")
        if rating_key not in self.tables.by_key:
            raise PlexRefusal(404, "no item with that rating key")
        self.ratings[(identity, rating_key)] = None if rating < 0 else rating
        return _container("", size=0)

    # -- playback --------------------------------------------------------

    def _clients(self, method):
        """``/clients``: what has announced itself to this server, addresses and all."""
        if method != "GET":
            raise PlexRefusal(405, f"{method} is not defined for /clients")
        body = "".join(client_xml(row) for row in self.clients_seen)
        return _container(body, size=len(self.clients_seen))

    def _security_token(self, method):
        """``/security/token``, which a real server refused.

        Measured: a Plex Media Server whose token is not a plex.tv account
        token answers ``403 Forbidden`` here. That is the default, so the path
        every test takes is the one a real installation takes, and the tool's
        "play without a delegation token" branch is exercised rather than
        assumed. ``mints_tokens=True`` is the other server.
        """
        if method != "GET":
            raise PlexRefusal(405, f"{method} is not defined for /security/token")
        if not self.mints_tokens:
            raise PlexRefusal(403, "<html><body><h1>403 Forbidden</h1></body></html>")
        return _container("", size=0, extra=[("token", DELEGATION_TOKEN)])

    def _playqueue(self, query, method):
        """``/playQueues``: build a queue from a uri, and refuse a bad one.

        The queue is expanded for real -- an album becomes its tracks, a
        playlist its items -- because a double that returned the same queue
        whatever was asked would let a `uri` that names the wrong thing pass.
        """
        if method != "POST":
            raise PlexRefusal(405, f"{method} is not defined for /playQueues")
        unknown = sorted(set(query) - PLAYQUEUE_PARAMS - KNOWN_PARAMS)
        if unknown:
            raise PlexRefusal(400, f"unknown parameter(s): {', '.join(unknown)}")
        missing = sorted({"type", "uri"} - set(query))
        if missing:
            raise PlexRefusal(400, f"missing parameter(s): {', '.join(missing)}")
        if query["type"] not in ("audio", "video", "photo"):
            raise PlexRefusal(400, f"unknown play queue type {query['type']!r}")
        keys = self._queue_keys(query["uri"])
        identifier = self._next_playqueue
        self._next_playqueue += 1
        self.playqueues[identifier] = keys
        body = "".join(track_xml(self.tables.by_key[k][1], self.tables) for k in keys)
        return _container(
            body,
            size=len(keys),
            extra=[
                ("playQueueID", identifier),
                ("playQueueTotalCount", len(keys)),
                ("playQueueSelectedItemOffset", 0),
                ("playQueueVersion", 1),
            ],
        )

    def _queue_keys(self, uri):
        """The track keys a `uri` names, refusing anything it does not.

        The prefix check is the same one the playlist endpoint makes and for the
        same reason: a uri naming another machine is a request this server
        cannot serve, and answering it would let a wrong machine identifier ship.
        """
        prefix = f"server://{MACHINE_ID}/com.plexapp.plugins.library"
        if not uri.startswith(prefix):
            raise PlexRefusal(400, "uri must name this server and its library")
        rest = uri[len(prefix) :]
        if rest.startswith("/playlists/"):
            wanted = rest[len("/playlists/") :].split("/")[0]
            for playlist in self.playlists:
                if str(playlist["id"]) == wanted:
                    return [entry["key"] for entry in playlist["items"]]
            raise PlexRefusal(404, "no playlist with that rating key")
        if not rest.startswith("/library/metadata/"):
            raise PlexRefusal(400, f"unsupported play queue uri {rest!r}")
        try:
            rating_key = int(rest[len("/library/metadata/") :].split("/")[0])
        except ValueError:
            raise PlexRefusal(400, "rating key must be an integer") from None
        if rating_key not in self.tables.by_key:
            raise PlexRefusal(404, "no item with that rating key")
        kind, _row = self.tables.by_key[rating_key]
        if kind == "track":
            return [rating_key]
        if kind == "album":
            return [t["key"] for t in self.tables.tracks if t["album"] == rating_key]
        if kind == "artist":
            albums = {a["key"] for a in self.tables.albums if a["artist"] == rating_key}
            return [t["key"] for t in self.tables.tracks if t["album"] in albums]
        raise PlexRefusal(400, f"a {kind} cannot be a play queue")

    def _play(self, query, headers, method):
        """``/player/playback/playMedia``, proxied to a client by this server.

        Refuses the way Plex does: the target header has to name a client this
        server can see, that client has to advertise ``playback``, and the
        ``containerKey`` has to name a play queue this server actually created.
        The last is the one worth having -- a playback command pointing at a
        queue that does not exist is exactly what a broken implementation sends,
        and a permissive double would answer it 200.
        """
        if method != "GET":
            raise PlexRefusal(405, f"{method} is not defined for /player/playback/playMedia")
        target = headers.get("X-Plex-Target-Client-Identifier")
        if not target:
            raise PlexRefusal(400, "X-Plex-Target-Client-Identifier is required")
        row = next(
            (c for c in self.clients_seen if c["machineIdentifier"] == target),
            None,
        )
        if row is None:
            raise PlexRefusal(404, "no client with that machine identifier")
        if "playback" not in row["protocolCapabilities"].split(","):
            raise PlexRefusal(400, "that client does not advertise the playback capability")
        missing = sorted(PLAY_REQUIRED - set(query))
        if missing:
            raise PlexRefusal(400, f"missing parameter(s): {', '.join(missing)}")
        unknown = sorted(set(query) - PLAY_REQUIRED - PLAY_OPTIONAL - KNOWN_PARAMS)
        if unknown:
            raise PlexRefusal(400, f"unknown parameter(s): {', '.join(unknown)}")
        if query["type"] != "music":
            raise PlexRefusal(400, "the remote-control API calls audio 'music'")
        wanted = query["containerKey"].split("?")[0]
        if not wanted.startswith("/playQueues/"):
            raise PlexRefusal(400, "containerKey must name a play queue")
        try:
            identifier = int(wanted[len("/playQueues/") :])
        except ValueError:
            raise PlexRefusal(400, "play queue id must be an integer") from None
        if identifier not in self.playqueues:
            raise PlexRefusal(404, "no play queue with that id")
        self.played.append(
            {"client": row["name"], "queue": identifier, "key": query["key"], "route": "local"}
        )
        if row["answers"] == "OK":
            # Not XML. Plexamp, Plex for Android and Plex for Samsung answer a
            # successful playback command with this, which is why the tool has
            # to treat a parse failure after a 200 as success.
            return "OK"
        return '<?xml version="1.0"?><Response code="200" status="OK"/>'

    def _sonos(self, path, query, headers, method):
        """``sonos.plex.tv``: the cloud route, answered by the same double.

        Routed on the hostname exactly as ``plex.tv`` is, which is what lets
        "the account token is missing" and "Sonos is unreachable" be test cases
        rather than hypotheticals. The token it demands is the **account**
        token, never the server one -- that separation is the whole reason the
        route has its own environment variable.
        """
        if method != "GET":
            raise PlexRefusal(405, f"{method} is not defined here")
        if headers.get("X-Plex-Token") != ACCOUNT_TOKEN:
            raise PlexRefusal(401, "<html><body><h1>401 Unauthorized</h1></body></html>")
        if self.sonos_status != 200:
            raise PlexRefusal(self.sonos_status, "the sonos service refused")
        if path == "/resources":
            body = "".join(sonos_xml(row) for row in self.sonos_speakers_seen)
            return _container(body, size=len(self.sonos_speakers_seen))
        if path == "/player/playback/playMedia":
            target = query.get("X-Plex-Target-Client-Identifier")
            row = next(
                (s for s in self.sonos_speakers_seen if s["machineIdentifier"] == target), None
            )
            if row is None:
                raise PlexRefusal(404, "no speaker with that machine identifier")
            if query.get("X-Plex-Token") != self.token:
                # Two credentials, and they are not the same one: the header
                # carries the account token and this parameter carries the
                # server token, because it is what the speaker streams with.
                raise PlexRefusal(400, "the server token is required to stream")
            self.played.append(
                {
                    "client": row["title"],
                    "queue": int(query["containerKey"].split("?")[0].rsplit("/", 1)[-1]),
                    "key": query.get("key"),
                    "route": "sonos",
                }
            )
            return '<?xml version="1.0"?><Response code="200" status="OK"/>'
        raise PlexRefusal(404, "no such sonos endpoint")

    # -- playlists -------------------------------------------------------

    def _playlists(self, path, query, method, start, size):
        rest = path[len("/playlists") :].strip("/")
        if not rest:
            if method == "POST":
                return self._create_playlist(query)
            if method != "GET":
                raise PlexRefusal(405, f"{method} is not defined for /playlists")
            return self._list_playlists(query)

        identifier, _, tail = rest.partition("/")
        playlist = self._playlist(identifier)
        if not tail:
            if method == "GET":
                return _container(playlist_xml(playlist, self.tables), size=1)
            if method == "DELETE":
                self.playlists.remove(playlist)
                return _container("", size=0)
            raise PlexRefusal(405, f"{method} is not defined for one playlist")
        if tail == "items":
            if method == "GET":
                return self._playlist_items(playlist, start, size)
            if method == "PUT":
                return self._add_items(playlist, query)
            raise PlexRefusal(405, f"{method} is not defined for playlist items")
        if tail.startswith("items/"):
            if method == "DELETE":
                return self._remove_item(playlist, tail[len("items/") :])
            raise PlexRefusal(405, f"{method} is not defined for one playlist item")
        raise PlexRefusal(404, f"no such playlist endpoint: {tail}")

    def _playlist(self, identifier):
        for playlist in self.playlists:
            if str(playlist["id"]) == str(identifier):
                return playlist
        raise PlexRefusal(404, "no playlist with that rating key")

    def _list_playlists(self, query):
        unknown = sorted(set(query) - KNOWN_PLAYLIST_PARAMS - KNOWN_PARAMS)
        if unknown:
            raise PlexRefusal(400, f"unknown parameter(s): {', '.join(unknown)}")
        rows = self.playlists
        wanted = query.get("playlistType")
        if wanted:
            if wanted not in ("audio", "video", "photo"):
                raise PlexRefusal(400, f"unknown playlistType {wanted!r}")
            rows = [row for row in rows if row["type"] == wanted]
        if query.get("title"):
            needle = query["title"].lower()
            rows = [row for row in rows if needle in row["title"].lower()]
        body = "".join(playlist_xml(row, self.tables) for row in rows)
        return _container(body, size=len(rows))

    def _create_playlist(self, query):
        missing = sorted({"uri", "type", "title", "smart"} - set(query))
        if missing:
            raise PlexRefusal(400, f"missing parameter(s): {', '.join(missing)}")
        if query["type"] not in ("audio", "video", "photo"):
            raise PlexRefusal(400, f"unknown playlist type {query['type']!r}")
        if query["smart"] != "0":
            raise PlexRefusal(400, "this double only creates ordinary playlists")
        keys = self._uri_keys(query["uri"], query["type"])
        self._next_playlist_id += 1
        row = {
            "id": self._next_playlist_id,
            "title": query["title"],
            "type": query["type"],
            "smart": 0,
            "items": [{"key": key, "item_id": self._item_id()} for key in keys],
            "updatedAt": 1700001000,
        }
        self.playlists.append(row)
        return _container(playlist_xml(row, self.tables), size=1)

    def _add_items(self, playlist, query):
        unknown = sorted(set(query) - KNOWN_PLAYLIST_PARAMS - KNOWN_PARAMS)
        if unknown:
            raise PlexRefusal(400, f"unknown parameter(s): {', '.join(unknown)}")
        if "uri" not in query:
            raise PlexRefusal(400, "missing parameter(s): uri")
        for key in self._uri_keys(query["uri"], playlist["type"]):
            playlist["items"].append({"key": key, "item_id": self._item_id()})
        return _container("", size=0)

    def _remove_item(self, playlist, item_id):
        for entry in playlist["items"]:
            if str(entry["item_id"]) == str(item_id):
                playlist["items"].remove(entry)
                return _container("", size=0)
        raise PlexRefusal(404, "no such item in that playlist")

    def _uri_keys(self, uri, playlist_type):
        """The rating keys inside a ``server://.../library/metadata/<keys>`` uri.

        The prefix is checked rather than skipped: Plex will not add an item
        from a server it was not told about, and a uri built against the wrong
        machine identifier is a bug that would otherwise look like success.
        """
        prefix = f"server://{MACHINE_ID}/com.plexapp.plugins.library/library/metadata/"
        if not uri.startswith(prefix):
            raise PlexRefusal(400, "uri does not name an item on this server")
        keys = []
        for raw in uri[len(prefix) :].split(","):
            try:
                key = int(raw)
            except ValueError:
                raise PlexRefusal(400, f"not a rating key: {raw!r}") from None
            if key not in self.tables.by_key:
                raise PlexRefusal(404, f"no item with rating key {key}")
            kind = self.tables.by_key[key][0]
            if _LIST_TYPES[kind] != playlist_type:
                raise PlexRefusal(400, f"a {kind} cannot go in a {playlist_type} playlist")
            keys.append(key)
        return keys

    def _playlist_items(self, playlist, start, size):
        entries = playlist["items"]
        window = entries[start:] if size is None else entries[start : start + size]
        body = "".join(
            self._item_xml(*self.tables.by_key[entry["key"]], item_id=entry["item_id"])
            for entry in window
        )
        return _container(body, size=len(window), total=len(entries))

    # -- plex.tv ---------------------------------------------------------

    def _plex_tv(self, path, headers, method):
        """The cloud calls this tool makes, and only the owner may make the first.

        Two endpoints rather than one, because plex.tv answers **401 to both**
        halves of a failure that has two very different causes. A token that
        belongs to a lesser account is refused by ``shared_servers`` and
        accepted by ``user``; a token plex.tv never issued -- a local-only
        server token, say, which works perfectly against the server itself -- is
        refused by both. Told apart, the recovery is different; conflated, the
        tool tells a user to change accounts when their token was never a
        plex.tv token at all.
        """
        if method != "GET":
            raise PlexRefusal(405, f"{method} is not defined here")
        if path == "/api/v2/user":
            if headers.get("X-Plex-Token") != self.token or not self.plex_tv_account:
                raise PlexRefusal(
                    401,
                    '<errors><error code="1001" message="User could not be authenticated"/>'
                    "</errors>",
                )
            return '<user id="1" username="example-owner"/>'
        if path != f"/api/servers/{MACHINE_ID}/shared_servers":
            raise PlexRefusal(404, "not found")
        if headers.get("X-Plex-Token") != self.token or self.plex_tv_status == 401:
            raise PlexRefusal(401, "<errors><error>Invalid authentication token.</error></errors>")
        if self.plex_tv_status != 200:
            raise PlexRefusal(self.plex_tv_status, '<Response status="Refused"/>')
        body = "".join(
            "<SharedServer {}/>".format(
                _attrs(
                    [
                        ("id", index + 1),
                        ("username", user["username"]),
                        ("email", user["email"]),
                        ("userID", user["id"]),
                        ("accessToken", user["token"]),
                        ("name", SERVER_NAME),
                        ("owned", 0),
                    ]
                )
            )
            for index, user in enumerate(self.shared_users)
        )
        return _container(body, size=len(self.shared_users))


#: What each media kind counts as when a playlist is built from it. Plex holds
#: one of these per playlist, which is the whole of the mixed-media rule.
_LIST_TYPES = {"artist": "audio", "album": "audio", "track": "audio", "movie": "video"}

#: Distinguishes "no rating was written" from "the rating was cleared", which
#: are different states and print differently.
_ABSENT = object()


def _combine(group):
    return any(group["results"]) if group["mode"] == "or" else all(group["results"])


def _split_operator(name):
    index = len(name)
    while index and name[index - 1] in "!<>=&":
        index -= 1
    return name[:index], name[index:]


def _sorted(rows, sort, libtype):
    if not sort:
        return sorted(rows, key=lambda row: row["title"].lower())
    field, _, direction = sort.partition(":")
    # A real server accepts a libtype-scoped sort (`album.addedAt:desc`), which
    # is what the client library builds; the scope is redundant once `type` has
    # already selected the libtype.
    field = field.rsplit(".", 1)[-1]
    reverse = direction == "desc"
    if field in ("titleSort", "title"):
        return sorted(rows, key=lambda row: row["title"].lower(), reverse=reverse)
    if field in ("addedAt", "userRating", "year"):
        return sorted(rows, key=lambda row: row.get(field) or 0, reverse=reverse)
    if field == "random":
        # Deliberately deterministic, and deliberately not the natural order: a
        # test asserting on a shuffled answer has to be reproducible, and a
        # "shuffle" that returned title order would let a missing sort pass.
        return sorted(rows, key=lambda row: (row["key"] * 7919) % 1009)
    raise PlexRefusal(400, f"unknown sort field {field!r}")


# ----------------------------------------------------------- transport double


class FakeResponse:
    def __init__(self, url, status_code, text):
        self.url = url
        self.status_code = status_code
        self.text = text


class FakeSession:
    """Stands in for ``requests.Session``, which is all the client library needs.

    The write verbs are here because the tool can now write. They are separate
    methods rather than one with a parameter for the same reason the real
    session has them: the client library reaches for ``session.put`` by name,
    and a double that only had ``get`` would make every write path untestable.
    """

    def __init__(self, server):
        self.server = server

    def get(self, url, headers=None, params=None, timeout=None, **kwargs):
        return self._request("GET", url, headers, params)

    def put(self, url, headers=None, params=None, timeout=None, **kwargs):
        return self._request("PUT", url, headers, params)

    def post(self, url, headers=None, params=None, timeout=None, **kwargs):
        return self._request("POST", url, headers, params)

    def delete(self, url, headers=None, params=None, timeout=None, **kwargs):
        return self._request("DELETE", url, headers, params)

    def _request(self, method, url, headers, params):
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or ""
        if host.endswith("plex.tv") and self.server.plex_tv_unreachable:
            import requests

            raise requests.exceptions.ConnectionError("plex.tv is not answering")
        # Ordered *and* mapped: the mapping is what most of the server reads,
        # and the order is what carries a parenthesised filter expression.
        pairs = list(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        pairs.extend((key, str(value)) for key, value in (params or {}).items())
        query = dict(pairs)
        try:
            body = self.server.handle(
                parts.path, query, headers or {}, method=method, pairs=pairs, host=host
            )
        except PlexRefusal as refusal:
            return FakeResponse(url, refusal.status, refusal.text)
        return FakeResponse(url, 200, body)


class UnreachableSession:
    """A server that is not there, for the connection-failure paths."""

    def __init__(self, exception=None):
        import requests

        self.exception = exception or requests.exceptions.ConnectionError("refused")

    def get(self, url, headers=None, params=None, timeout=None, **kwargs):
        raise self.exception


# -------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def _isolate_output():
    """Registered secrets are process-global; no test may inherit another's."""
    from plex_axi import output

    output.reset_secrets()
    output.set_debug(False)
    yield
    output.reset_secrets()
    output.set_debug(False)


@pytest.fixture
def plex_env():
    """The environment a configured invocation sees. No real values, ever."""
    return {
        "PLEX_URL": "http://plex.example.com:32400",
        "PLEX_TOKEN": TOKEN,
    }


@pytest.fixture
def server(monkeypatch):
    """A running fake Plex, wired in where the real session would be built."""
    from plex_axi import plex

    fake = FakePlex()

    def _build_session(**kwargs):
        return FakeSession(fake)

    monkeypatch.setattr(plex, "build_session", _build_session)
    return fake


@pytest.fixture
def writable_env(plex_env):
    """The environment of an installation whose operator has opened the gate.

    Separate from :func:`plex_env` on purpose: the default environment a test
    sees is one where writes are refused, so a command that mutated without
    being told twice fails somewhere.
    """
    from plex_axi import writes

    return {**plex_env, writes.ALLOW_VAR: writes.ALLOW_VALUE}


@pytest.fixture
def playing_env(plex_env):
    """The environment of an installation whose operator has opened *that* gate.

    A separate variable from the write gate, and a separate fixture, because the
    two answer different questions: one is "may this tool change my library" and
    the other is "does anything else in this house own the speakers". A test that
    reached for :func:`writable_env` here would be asserting a coupling the
    design deliberately refuses.
    """
    from plex_axi import playback

    return {**plex_env, playback.ALLOW_VAR: playback.ALLOW_VALUE}


@pytest.fixture
def sonos_env(playing_env):
    """...and who has also given the tool a plex.tv account token.

    The Sonos route needs a credential ``PLEX_TOKEN`` is not, so it needs an
    environment ``playing_env`` is not: with the gate open and this unset, the
    cloud route is not consulted at all and the answer says so.
    """
    from plex_axi import playback

    return {**playing_env, playback.ACCOUNT_TOKEN_VAR: ACCOUNT_TOKEN}


@pytest.fixture
def spartan_server(monkeypatch):
    """A server whose filter metadata lacks everything `pick` would like."""
    from plex_axi import plex

    fake = FakePlex(spartan=True)
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))
    return fake


@pytest.fixture
def date_only_server(monkeypatch):
    """A server offering `track.lastViewedAt` but not `track.viewCount`.

    The one `--not-played-since` degradation that still answers: the period
    runs and the never-played half cannot be ORed in. It needs its own server
    because the note `pick` prints there is a claim about the result, and a
    claim nothing runs against is a claim nobody checked.
    """
    from plex_axi import plex

    fake = FakePlex(fields=DATE_ONLY_FIELDS)
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))
    return fake


@pytest.fixture
def ungrouping_server(monkeypatch):
    """A fake Plex that accepts ``group=title`` and ignores it."""
    from plex_axi import plex

    fake = FakePlex(groupable=False)
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))
    return fake


@pytest.fixture
def unreachable(monkeypatch):
    from plex_axi import plex

    monkeypatch.setattr(plex, "build_session", lambda **kwargs: UnreachableSession())


class Result:
    """One invocation's exit code and both streams, kept together.

    stderr is captured and asserted on as often as stdout: it is not a safe
    channel for a credential just because agents do not read it.
    """

    __slots__ = ("code", "err", "out")

    def __init__(self, code, out, err):
        self.code = code
        self.out = out
        self.err = err

    def line(self, prefix):
        """The first output line starting with ``prefix``, or ``""``."""
        for line in self.out.splitlines():
            if line.strip().startswith(prefix):
                return line.strip()
        return ""

    def __contains__(self, needle):
        return needle in self.out


@pytest.fixture
def cli_run(plex_env, capsys):
    """Run one invocation with a configured environment and capture both streams."""
    from plex_axi import cli

    def _run(*argv, env=None):
        environ = dict(plex_env) if env is None else dict(env)
        code = cli.main(list(argv), environ=environ)
        captured = capsys.readouterr()
        return Result(code, captured.out, captured.err)

    return _run
