"""The exit-code contract, as one table, held against the source.

One rule: a static problem with the invocation exits 2, and an outcome of a
lookup against live state exits 1. The rule was only ever written as prose, so
nothing noticed when ``WRONG_ITEM_TYPE`` -- which takes two requests to find out
-- exited 2. :data:`CONTRACT` is the rule as data: every error code this tool
can print, with the exit code it owes.

Two things are asserted, and the second is the one that keeps the table honest:

* every code literal in the source raises through a class whose exit code is
  the one the table gives it;
* the table and the source name **the same set** of codes, in both directions --
  a code added without a row fails, and so does a row that outlived its code.
"""

from __future__ import annotations

import ast
from pathlib import Path

import axi_toolkit.plex

from support import ERRORS

SRC = Path(__file__).resolve().parents[1] / "src" / "plex_axi"
TOOLKIT = Path(axi_toolkit.plex.__file__).resolve().parent

USAGE, LOOKUP = 2, 1

#: Every error code, and the exit code it owes.
CONTRACT = {
    # -- the invocation is wrong, and nothing needed to be asked to know it: 2
    "UNKNOWN_FLAG": USAGE,
    "UNKNOWN_COMMAND": USAGE,
    "OUT_OF_SCOPE": USAGE,
    "UNKNOWN_SUBCOMMAND": USAGE,
    "MISSING_SUBCOMMAND": USAGE,
    "MISSING_ARGUMENT": USAGE,
    "UNEXPECTED_ARGUMENT": USAGE,
    "MISSING_VALUE": USAGE,
    "NO_FILTERS": USAGE,
    "EMPTY_VALUE": USAGE,
    "EMPTY_TITLE": USAGE,
    "BAD_LIMIT": USAGE,
    "BAD_TYPE": USAGE,
    "BAD_YEAR": USAGE,
    "BAD_RATING": USAGE,
    "BAD_RATING_KEY": USAGE,
    "MEDIA_ID_NOT_RATING_KEY": USAGE,
    "GUID_NOT_RATING_KEY": USAGE,
    "UNKNOWN_FIELD": USAGE,
    "UNKNOWN_SORT_FIELD": USAGE,
    "UNKNOWN_LIBTYPE": USAGE,
    "NO_SUCH_FILTER_FIELD": USAGE,
    "BAD_SORT": USAGE,
    "BAD_PERIOD": USAGE,
    "BAD_DISTANCE": USAGE,
    "BAD_DEPTH": USAGE,
    "BAD_TIMEOUT": USAGE,
    "BAD_SECTION": USAGE,
    "BAD_USER": USAGE,
    "BAD_PAIR": USAGE,
    "BAD_PATH": USAGE,
    "BAD_HOME": USAGE,
    "RELATIVE_PATH": USAGE,
    "MISSING_PATH": USAGE,
    "READ_ONLY": USAGE,
    "UNSUPPORTED_METHOD": USAGE,
    "STATE_CHANGING_PATH": USAGE,
    "TOKEN_IN_QUERY": USAGE,
    "MISSING_RATING": USAGE,
    "MISSING_KEY": USAGE,
    "CONFLICTING_FLAGS": USAGE,
    # -- configuration, the connection, or what the server said: 1
    "NOT_CONFIGURED": LOOKUP,
    "BAD_TOKEN": LOOKUP,
    "BAD_URL": LOOKUP,
    "UNREACHABLE": LOOKUP,
    "TIMEOUT": LOOKUP,
    "NOT_PLEX": LOOKUP,
    "BAD_RESPONSE": LOOKUP,
    "SERVER_ERROR": LOOKUP,
    "NOT_XML": LOOKUP,
    "NOT_FOUND": LOOKUP,
    "REFUSED": LOOKUP,
    "NO_MUSIC_SECTION": LOOKUP,
    "NO_SUCH_SECTION": LOOKUP,
    "AMBIGUOUS_SECTION": LOOKUP,
    "UNKNOWN_FILTER_FIELD": LOOKUP,
    "UNKNOWN_OPERATOR": LOOKUP,
    "CLIENT_SIDE_FILTER": LOOKUP,
    "WRONG_ITEM_TYPE": LOOKUP,
    "MEDIA_ID_OTHER_SERVER": LOOKUP,
    "NOT_A_TRACK": LOOKUP,
    "NO_SUCH_PLAYLIST": LOOKUP,
    "SMART_PLAYLIST": LOOKUP,
    "PLAYLIST_EXISTS": LOOKUP,
    "MIXED_MEDIA_TYPES": LOOKUP,
    "WRITES_DISABLED": LOOKUP,
    "PLAYBACK_DISABLED": LOOKUP,
    "NO_TARGETS": LOOKUP,
    "NO_SUCH_TARGET": LOOKUP,
    "AMBIGUOUS_TARGET": LOOKUP,
    "NO_PLAY_QUEUE": LOOKUP,
    "SKILL_STALE": LOOKUP,
    "INTERNAL_ERROR": LOOKUP,
    # -- `--user`, which asks plex.tv, and the Sonos route, which asks Plex's cloud
    "NO_MACHINE_IDENTIFIER": LOOKUP,
    "NOT_SERVER_OWNER": LOOKUP,
    "NO_SUCH_USER": LOOKUP,
    "NO_USER_TOKEN": LOOKUP,
    "USER_TOKEN_REFUSED": LOOKUP,
    "PLEX_TV_REFUSED": LOOKUP,
    "PLEX_TV_TOKEN_REJECTED": LOOKUP,
    "PLEX_TV_UNPARSEABLE": LOOKUP,
    "PLEX_TV_UNREACHABLE": LOOKUP,
    "SONOS_REFUSED": LOOKUP,
    "SONOS_TOKEN_REFUSED": LOOKUP,
    "SONOS_UNPARSEABLE": LOOKUP,
    "SONOS_UNREACHABLE": LOOKUP,
}

#: Usage errors that are only knowable from the server's own vocabulary. The
#: value is the caller's argument -- a sort key, a tag field, a libtype -- and it
#: is wrong the way a misspelled flag is wrong, so it exits 2; but which sorts a
#: library offers is the library's to say, so the server is asked first. They are
#: the whole exception to "exit 2 means nothing was sent", and they are named so
#: that a fourth cannot join them unnoticed.
ASKS_FIRST = {"UNKNOWN_SORT_FIELD", "NO_SUCH_FILTER_FIELD", "UNKNOWN_LIBTYPE"}

#: Codes whose name is assembled at run time, so no literal names them. Listed
#: by the prefix the source builds them from.
BUILT = {
    "TOKEN_": ("TOKEN_EXPIRED", "TOKEN_INVALID", "TOKEN_REJECTED"),
    "BAD_": ("BAD_TIMEOUT", "BAD_SECTION", "BAD_USER"),
}

#: Which exit code a class raises with. Anything not a usage error exits 1.
_USAGE_CLASSES = {"UsageError"}


def _literals(root: Path) -> dict:
    """``code -> set of exit codes`` for every ``code=`` or ``"code":`` literal."""
    found: dict = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg != "code" or not isinstance(keyword.value, ast.Constant):
                        continue
                    name = getattr(node.func, "id", getattr(node.func, "attr", ""))
                    exit_code = USAGE if name in _USAGE_CLASSES else LOOKUP
                    found.setdefault(keyword.value.value, set()).add(exit_code)
            if isinstance(node, ast.Dict):
                keys = [getattr(key, "value", None) for key in node.keys]
                if "code" not in keys or not isinstance(
                    node.values[keys.index("code")], ast.Constant
                ):
                    continue
                code = node.values[keys.index("code")].value
                exit_code = LOOKUP
                if "__exit_code__" in keys:
                    exit_code = node.values[keys.index("__exit_code__")].value
                found.setdefault(code, set()).add(exit_code)
    return found


def _source_codes() -> dict:
    found = _literals(SRC)
    for code, exits in _literals(TOOLKIT).items():
        found.setdefault(code, set()).update(exits)
    return found


def test_every_code_in_the_source_exits_the_way_the_table_says():
    wrong = {
        code: sorted(exits)
        for code, exits in _source_codes().items()
        if code in CONTRACT and exits != {CONTRACT[code]}
    }
    assert wrong == {}, wrong


def test_the_table_and_the_source_name_the_same_codes():
    source = set(_source_codes())
    built = {code for codes in BUILT.values() for code in codes}
    table = set(CONTRACT) | built
    assert source - table == set(), f"codes with no row: {sorted(source - table)}"
    assert set(CONTRACT) - source - built == set(), (
        f"rows with no code: {sorted(set(CONTRACT) - source - built)}"
    )


def test_a_usage_error_is_decided_before_the_server_is_asked(server, cli_run):
    """Exit 2 means static: the server is never told about it."""
    for argv, code in ERRORS:
        server.requests.clear()
        result = cli_run(*argv)
        assert result.code == code, (argv, result.out)
        if code == USAGE and not any(f"code: {name}" in result.out for name in ASKS_FIRST):
            assert server.requests == [], argv


def test_every_swept_error_prints_a_code_the_table_knows(server, cli_run):
    import json

    built = {code for codes in BUILT.values() for code in codes}
    for argv, code in ERRORS:
        doc = json.loads(cli_run("--json", *argv).out)
        assert doc.get("code") in set(CONTRACT) | built, (argv, doc)
        assert CONTRACT.get(doc["code"], code) == code, (argv, doc["code"])
        assert doc.get("help"), f"{argv} has no next step"
