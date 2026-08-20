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

Every name, path and identifier in the fixture is invented. Nothing here came
from a real library.
"""

from __future__ import annotations

import urllib.parse
from xml.sax.saxutils import quoteattr

import pytest

# --------------------------------------------------------------------- fixture data

TOKEN = "example-token-0000000001"
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
        "key": 122,
        "title": "Anthology Only",
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

#: Sonic neighbours, keyed by seed rating key, as (rating key, distance).
NEIGHBOURS = {
    111: [(211, 0.0821), (311, 0.1902)],
    121: [(111, 0.0100)],
}

SESSIONS = [{"track": 111, "device": "Example Player", "state": "playing"}]

BY_KEY = {}
for _row in ARTISTS:
    BY_KEY[_row["key"]] = ("artist", _row)
for _row in ALBUMS:
    BY_KEY[_row["key"]] = ("album", _row)
for _row in TRACKS:
    BY_KEY[_row["key"]] = ("track", _row)

ALBUM_BY_KEY = {row["key"]: row for row in ALBUMS}
ARTIST_BY_KEY = {row["key"]: row for row in ARTISTS}

SEARCH_TYPES = {"8": "artist", "9": "album", "10": "track"}


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
}
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


def album_xml(row):
    artist = ARTIST_BY_KEY[row["artist"]]
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


def track_xml(row, *, check_files=False, distance=None, session=None):
    album = ALBUM_BY_KEY[row["album"]]
    artist = ARTIST_BY_KEY[album["artist"]]
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
        player = "<User {}/><Player {}/>".format(
            _attrs([("id", 1), ("title", "example-user")]),
            _attrs(
                [
                    ("title", session["device"]),
                    ("state", session["state"]),
                    ("machineIdentifier", "example-device-0001"),
                ]
            ),
        )
    head = _attrs(
        [
            ("ratingKey", row["key"]),
            ("key", "/library/metadata/{}".format(row["key"])),
            ("guid", "plex://track/a1b2c3d4e5f60718293c{:04d}".format(row["key"])),
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
        ]
    )
    body = media + _tags("Mood", row["moods"], TRACK_MOODS) + player
    return f"<Track {head}>{body}</Track>"


# -------------------------------------------------------------- filter metadata

_STRING_OPS = [
    ("=", "contains"),
    ("!=", "does not contain"),
    ("==", "is"),
    ("!==", "is not"),
    ("<=", "begins with"),
    (">=", "ends with"),
]
_INT_OPS = [
    ("=", "is"),
    ("!=", "is not"),
    (">>=", "is greater than"),
    ("<<=", "is less than"),
    ("<=", "is less than or equals"),
    (">=", "is greater than or equals"),
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
        ("album.userRating", "Rating", "integer"),
        ("album.addedAt", "Date Added", "date"),
    ],
    "track": [
        ("track.title", "Title", "string"),
        ("track.mood", "Mood", "tag"),
        ("track.userRating", "Rating", "integer"),
        ("track.addedAt", "Date Added", "date"),
    ],
}

#: The tag filters each libtype offers, as ``filter`` name to choices endpoint.
SECTION_FILTERS = {
    "artist": [("genre", "Genre"), ("style", "Style"), ("mood", "Mood")],
    "album": [("mood", "Mood")],
    "track": [("mood", "Mood")],
}

#: The ``group`` field is deliberately absent from this metadata, because it is
#: absent from a real server's too: the client library adds it by hand rather
#: than reading it, so ``group=title`` validates and reaches the wire whatever
#: the server advertises. What a server does *with* it is the open question, so
#: :class:`FakePlex` models both answers -- see its ``groupable`` argument.


def _meta_xml():
    types = []
    for index, (libtype, code) in enumerate((("artist", 8), ("album", 9), ("track", 10))):
        fields = list(SECTION_FIELDS[libtype])
        field_xml = "".join(
            '<Field key="{}" title="{}" type="{}"/>'.format(*field) for field in fields
        )
        filter_xml = "".join(
            f'<Filter filter="{name}" filterType="string" key="/library/sections/{MUSIC_SECTION_KEY}/{libtype}/{name}" title="{title}" type="filter"/>'
            for name, title in SECTION_FILTERS[libtype]
        )
        sort_xml = (
            '<Sort default="asc" defaultDirection="asc" descKey="titleSort:desc" '
            'key="titleSort" title="Title"/>'
            '<Sort defaultDirection="desc" descKey="addedAt:desc" key="addedAt" title="Date Added"/>'
            '<Sort defaultDirection="desc" descKey="userRating:desc" key="userRating" title="Rating"/>'
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


def _artist_of(kind, row):
    if kind == "artist":
        return row
    if kind == "album":
        return ARTIST_BY_KEY[row["artist"]]
    return ARTIST_BY_KEY[ALBUM_BY_KEY[row["album"]]["artist"]]


def _album_of(kind, row):
    if kind == "album":
        return row
    if kind == "track":
        return ALBUM_BY_KEY[row["album"]]
    return None


def _value_for(field, kind, row):
    """The value one ``<libtype>.<field>`` predicate compares against.

    Scoping is resolved the way Plex resolves it: a track matches
    ``artist.genre`` through the artist it belongs to, which is why a
    track-level genre search on a library tagged the ordinary way finds nothing
    and the scoped one finds everything.
    """
    scope, _, name = field.partition(".")
    if scope == "artist":
        source = _artist_of(kind, row)
    elif scope == "album":
        source = _album_of(kind, row)
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
    if name == "genre":
        return source.get("genres", [])
    if name == "style":
        return source.get("styles", [])
    if name == "mood":
        return source.get("moods", [])
    raise PlexRefusal(400, f"unknown field {field} in this container")


def _matches(field, operator, wanted, kind, row):
    value = _value_for(field, kind, row)
    if value is None:
        return False
    if isinstance(value, list):
        # Tag fields carry ids; a comma-separated value is an OR.
        return any(part in value for part in wanted.split(","))
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

    def __init__(self, *, groupable=True, token=TOKEN, music_sections=1):
        self.groupable = groupable
        self.token = token
        self.music_sections = music_sections
        #: Every (path, query, headers) triple this server was asked for, so a
        #: test can assert on the request the client actually built.
        self.requests = []

    # -- routing ---------------------------------------------------------

    def handle(self, path, query, headers):
        self.requests.append({"path": path, "query": dict(query), "headers": dict(headers)})
        if headers.get("X-Plex-Token") != self.token:
            raise PlexRefusal(
                401, '<Response code="1001" status="User could not be authenticated"/>'
            )

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
            return self._section(path, query, start, size)
        if path.startswith("/library/metadata/"):
            return self._metadata(path, query)
        if path == "/status/sessions":
            return self._sessions()
        raise PlexRefusal(404, '<Response code="1000" status="Not Found"/>')

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

    def _section(self, path, query, start, size):
        rest = path[len("/library/sections/") :]
        key, _, tail = rest.partition("/")
        if key not in (MUSIC_SECTION_KEY, "4"):
            raise PlexRefusal(404, "no such section")

        if tail in ("all", "collections") and query.get("includeMeta") == "1":
            body = _meta_xml() if tail == "all" else "<Meta></Meta>"
            return _container(body, size=0, total=len(TRACKS))

        for libtype, filters in SECTION_FILTERS.items():
            for name, _title in filters:
                if tail == f"{libtype}/{name}":
                    return self._choices(name, libtype)

        if tail == "all":
            return self._all(query, start, size)
        raise PlexRefusal(404, f"no such section endpoint: {tail}")

    def _choices(self, name, libtype):
        table = {
            ("genre", "artist"): GENRES,
            ("style", "artist"): STYLES,
            ("mood", "artist"): ARTIST_MOODS,
            ("mood", "track"): TRACK_MOODS,
            ("mood", "album"): {},
        }[(name, libtype)]
        entries = [
            f'<Directory fastKey="/library/sections/{MUSIC_SECTION_KEY}/all?{libtype}.{name}={i}" key="{i}" title={quoteattr(t)} type="{name}"/>'
            for i, t in sorted(table.items())
        ]
        return _container("".join(entries), size=len(entries))

    def _all(self, query, start, size):
        libtype = SEARCH_TYPES.get(query.get("type", "8"))
        if libtype is None:
            raise PlexRefusal(400, "unknown type {}".format(query.get("type")))

        rows = {"artist": ARTISTS, "album": ALBUMS, "track": TRACKS}[libtype]
        matched = [row for row in rows if self._passes(query, libtype, row)]

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

    def _passes(self, query, libtype, row):
        for name, value in query.items():
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
            if not _matches(field, operator, value, libtype, row):
                return False
        return "title" not in query or query["title"].lower() in row["title"].lower()

    def _element(self, libtype, row):
        if libtype == "artist":
            return artist_xml(row)
        if libtype == "album":
            return album_xml(row)
        return track_xml(row)

    # -- one item --------------------------------------------------------

    def _metadata(self, path, query):
        rest = path[len("/library/metadata/") :]
        key, _, tail = rest.partition("/")
        try:
            rating_key = int(key)
        except ValueError:
            raise PlexRefusal(400, "rating key must be an integer") from None
        if rating_key not in BY_KEY:
            raise PlexRefusal(404, "no item with that rating key")
        kind, row = BY_KEY[rating_key]

        if tail == "nearest":
            if kind != "track":
                raise PlexRefusal(400, "sonic neighbours are per track")
            pairs = NEIGHBOURS.get(rating_key, [])
            limit = int(query.get("limit", 50))
            ceiling = float(query.get("maxDistance", 1.0))
            chosen = [(k, d) for k, d in pairs if d <= ceiling][:limit]
            body = "".join(
                track_xml(BY_KEY[k][1], distance=d) for k, d in chosen if BY_KEY[k][0] == "track"
            )
            return _container(body, size=len(chosen))

        if tail:
            raise PlexRefusal(404, f"no such metadata endpoint: {tail}")

        check_files = query.get("checkFiles") == "1"
        if kind == "track":
            body = track_xml(row, check_files=check_files)
        elif kind == "album":
            body = album_xml(row)
        else:
            body = artist_xml(row)
        return _container(body, size=1)

    def _sessions(self):
        body = "".join(track_xml(BY_KEY[s["track"]][1], session=s) for s in SESSIONS)
        return _container(body, size=len(SESSIONS))


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
    raise PlexRefusal(400, f"unknown sort field {field!r}")


# ----------------------------------------------------------- transport double


class FakeResponse:
    def __init__(self, url, status_code, text):
        self.url = url
        self.status_code = status_code
        self.text = text


class FakeSession:
    """Stands in for ``requests.Session``, which is all the client library needs."""

    def __init__(self, server):
        self.server = server

    def get(self, url, headers=None, params=None, timeout=None, **kwargs):
        return self._request(url, headers, params)

    def _request(self, url, headers, params):
        parts = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        for key, value in (params or {}).items():
            query[key] = str(value)
        try:
            body = self.server.handle(parts.path, query, headers or {})
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
