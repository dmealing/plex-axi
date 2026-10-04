"""Helpers shared by the offline suite and the live one.

Three things both suites need and neither should own: decoding the default
output with a decoder this project did not write, pulling the commands out of a
document's help lines, and running one of those commands through the CLI's own
parser. They live here, importable from ``tests/`` and ``tests/live/`` alike, so
a rule about what counts as a runnable suggestion is stated once.
"""

from __future__ import annotations

import json
import re
import shlex

#: The `help[N]:` block header. It is the one deliberate departure from strict
#: TOON -- one suggestion per line, because suggestions are command lines full
#: of commas -- so it is lifted out before an independent decoder sees the rest.
_HELP = re.compile(r"^(?P<indent> *)help\[(?P<count>\d+)\]:\s*$")

#: A command this tool suggests: its own name, inside backticks.
_SUGGESTION = re.compile(r"`(plex-axi(?: [^`]*)?)`")

#: Values no title should be able to turn into a second command or a second
#: line. Used by the quoting property test and by the offline fuzz.
HOSTILE = [
    "plain",
    "two words",
    "it's",
    'say "hi"',
    "x$(touch MARKER)",
    "x`touch MARKER`",
    "a;b",
    "a && b",
    "a | b",
    "a > b",
    "$HOME",
    "back\\slash",
    "tab\there",
    "line\nbreak",
    "carriage\rreturn",
    "--flag",
    "-",
    "",
    " lead",
    "trail ",
    "comma, separated",
    "trailing,",
    "caf\u00e9",
    "don\u2019t",
    "\u201cquoted\u201d",
    "emoji \U0001f3b5",
    "*",
    "~",
    "#hash",
    "a=b",
    "<angle>",
    "{brace}",
    "nul\x00byte",
    "\x1b[31mred",
    "\u2028separator",
]


def toon_doc(text: str) -> dict:
    """Decode default output with the official TOON decoder.

    Independent on purpose: the encoder is this project's, and an encoder
    checked only against itself agrees with itself.
    """
    import toon_format

    kept, helps, lines, index = [], None, text.split("\n"), 0
    while index < len(lines):
        match = _HELP.match(lines[index])
        if match:
            count, indent = int(match["count"]), len(match["indent"]) + 2
            helps = [line[indent:] for line in lines[index + 1 : index + 1 + count]]
            index += 1 + count
            continue
        kept.append(lines[index])
        index += 1
    doc = toon_format.decode("\n".join(kept)) if "".join(kept).strip() else {}
    if helps is not None:
        doc["help"] = helps
    return doc


def help_lines(json_text: str) -> list:
    """The help lines of a ``--json`` document, at any depth."""
    found: list = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "help" and isinstance(value, list):
                    found.extend(str(line) for line in value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads(json_text))
    return found


def suggestions(json_text: str) -> list:
    """Every backticked `plex-axi ...` command a ``--json`` document suggests."""
    found = []
    for line in help_lines(json_text):
        found.extend(_SUGGESTION.findall(line))
    return found


def parses(line: str, environ=None) -> list:
    """Run one suggested command through the CLI's own dispatcher and parser.

    Raises whatever the CLI would raise for it. Returns the words, so a caller
    can go on to execute them. A placeholder (``<key>``) parses like any other
    word, which is the point: the *shape* of the suggestion has to be one the
    tool accepts even before the caller fills it in.
    """
    from plex_axi import cli
    from plex_axi.argspec import parse

    words = shlex.split(line)
    assert words and words[0] == "plex-axi", line
    globals_, rest = cli._split_globals(words[1:])
    if not rest or "--help" in rest or "-h" in rest or globals_.get("help"):
        return words
    if rest[0].startswith("<"):
        return words  # `plex-axi --timeout 60 <command>`: the command is the slot
    available = cli.modules(environ)
    assert rest[0] in available, f"{line!r} names a command this installation does not have"
    command = available[rest[0]].COMMAND_FOR(rest[0])
    sub, argv = cli._pick_sub(command, rest[1:])
    parse(sub, argv, command=command)
    return words


def has_placeholder(line: str) -> bool:
    """Whether a suggestion still has a ``<slot>`` for the caller to fill in."""
    return bool(re.search(r"<[^<>`]+>", line))


#: Every read surface, as one invocation each. The offline sweeps -- the
#: independent decode, the suggestion check, the request budget -- all walk this
#: list, so a surface added here is covered by all three.
READS = [
    (),
    ("search", "--artist", "Example Artist"),
    ("search", "--artist", "Example Artist", "--no-group"),
    ("search", "--artist", "Example Artist", "--type", "album"),
    ("search", "--artist", "Example", "--type", "artist"),
    ("search", "--track", "Example Track"),
    ("search", "--album", "Example Album"),
    ("search", "--genre", "Jazz"),
    ("search", "--mood", "Mellow"),
    ("search", "--style", "Cool Jazz", "--type", "artist"),
    ("search", "--year", "1977"),
    ("search", "--rated-min", "4"),
    ("search", "--query", "Example"),
    ("search", "--artist", "Zzzqqq Nobody"),
    ("search", "--artist", "Example Artist", "--fields", "key,title,year,rating,added"),
    ("search", "--artist", "Example Artist", "--sort", "addedAt:desc"),
    ("pick",),
    ("pick", "--rated-min", "4", "--limit", "2"),
    ("pick", "--genre", "Jazz", "--not-played-since", "30d", "--exclude-live"),
    ("genres",),
    ("moods",),
    ("moods", "--type", "artist"),
    ("styles",),
    ("track", "111"),
    ("track", "111", "--check-files"),
    ("track", "122"),
    ("album", "110"),
    ("artist", "100"),
    ("similar", "111"),
    ("similar", "122"),
    ("recent",),
    ("recent", "--type", "track", "--limit", "2"),
    ("playlist",),
    ("playlist", "list", "--fields", "key,title,items"),
    ("playlist", "show", "501"),
    ("playlist", "show", "Example Smart Playlist"),
    ("playlist", "show", "501", "--limit", "1"),
    ("sessions",),
    ("api", "/"),
    ("api", "/library/sections"),
    ("api", "/library/metadata/111", "--depth", "1"),
    ("api", "/status/sessions"),
    ("doctor",),
    ("context",),
]

#: Invocations that end in an error or a refusal, with the exit code each owes.
#: A static problem exits 2; an outcome of a lookup against live state exits 1.
ERRORS = [
    (("nosuch",), 2),
    (("play", "111"), 2),
    (("movies",), 2),
    (("tracks",), 2),
    (("search",), 2),
    (("search", "help"), 2),
    (("search", "--nosuch", "x"), 2),
    (("search", "--title", "x"), 2),
    (("search", "--artist"), 2),
    (("search", "--artist", " , "), 2),
    (("search", "--year", "abc"), 2),
    (("search", "--artist", "x", "--limit", "0"), 2),
    (("search", "--artist", "x", "--limit", "501"), 2),
    (("search", "--artist", "x", "--type", "film"), 2),
    (("search", "--artist", "x", "--rated-min", "9"), 2),
    (("search", "--artist", "x", "--fields", "nosuch"), 2),
    (("search", "--artist", "x", "--sort", "addedAt:sideways"), 2),
    (("search", "--artist", "x", "--sort", "nosuch:desc"), 2),
    (("search", "--artist", "x", "--json", "--human"), 2),
    (("pick", "--not-played-since", "soon"), 2),
    (("track",), 2),
    (("track", "abc"), 2),
    (("track", "plex://track/111"), 2),
    (("track", "plex://track/a1b2c3d4e5f60718293c0111"), 2),
    (("track", "local://122"), 2),
    (("track", "111", "222"), 2),
    (("track", "999999"), 1),
    (("track", "110"), 1),
    (("album", "111"), 1),
    (("artist", "501"), 1),
    (("similar", "110"), 1),
    (("similar", "111", "--max-distance", "far"), 2),
    (("playlist", "nosuchsub"), 2),
    (("playlist", "show"), 2),
    (("playlist", "show", "No Such Playlist"), 1),
    (("playlist", "add", "501"), 2),
    (("playlist", "add", "501", "--key", "abc"), 2),
    (("playlist", "add", "501", "--key", "local://122"), 2),
    (("playlist", "add", "501", "--key", "111"), 1),
    (("playlist", "create", "", "--key", "111"), 2),
    (("rate", "111"), 2),
    (("rate", "111", "--stars", "0"), 2),
    (("rate", "111", "--stars", "2.25"), 2),
    (("rate", "111", "--stars", "4", "--clear"), 2),
    (("rate", "local://122", "--stars", "4"), 2),
    (("rate", "111", "--stars", "4"), 1),
    (("api",), 2),
    (("api", "library/sections"), 2),
    (("api", "http://plex.example.com:32400/library/sections"), 2),
    (("api", "POST", "/library/sections"), 2),
    (("api", "HEAD", "/"), 2),
    (("api", "OPTIONS", "/"), 2),
    (("api", "GET"), 2),
    (("api", "/", "extra"), 2),
    (("api", "/", "--depth", "99"), 2),
    (("api", "/", "--query", "novalue"), 2),
    (("api", "/:/rate", "--query", "key=111"), 2),
    (("api", "/library/sections/3/refresh"), 2),
    (("api", "/library/../identity"), 2),
    (("api", "/no/such/path"), 1),
    (("setup",), 2),
    (("setup", "skill"), 2),
    (("--timeout", "soon", "doctor"), 2),
    (("--timeout",), 2),
    (("--section",), 2),
    (("--user",), 2),
    (("--section", "No Such Library", "search", "--artist", "x"), 1),
]


#: The most requests each command may send, by its first word. Measured against
#: a real server at a recording proxy and again against the double; the two
#: agreed. A command is allowed what it costs today and no more, so a change
#: that makes `search` take thirty requests instead of seven fails here rather
#: than being found as "it feels slower".
#:
#: Four or five of every library command's requests rediscover the section --
#: `/`, `/library`, `/library/sections`, the section's filter metadata -- before
#: the command asks its own question. That overhead is in these numbers.
REQUEST_BUDGET = {
    "(home)": 12,
    "search": 7,
    "search:tag": 9,  # one more round trip resolves a tag's name to its id
    "search:empty": 10,  # a zero result asks the free-text search what was meant
    "pick": 13,
    "genres": 6,
    "moods": 6,
    "styles": 6,
    "track": 3,  # the third is `--check-files`
    "album": 2,
    "artist": 4,  # an artist carries no counts: its albums and tracks are counted
    "similar": 3,
    "recent": 6,
    "playlist": 4,  # one page of items, and the count behind it
    "sessions": 2,
    "api": 2,
    "doctor": 6,
    "context": 0,
}


def budget_for(argv: tuple, *, empty: bool = False) -> int:
    """The ceiling one invocation is held to."""
    if not argv:
        return REQUEST_BUDGET["(home)"]
    name = argv[0]
    if name == "search":
        if empty:
            return REQUEST_BUDGET["search:empty"]
        if any(flag in argv for flag in ("--genre", "--mood", "--style")):
            return REQUEST_BUDGET["search:tag"]
    return REQUEST_BUDGET[name]
