"""A pattern that judges a whole string must not end in ``$``.

In Python ``$`` matches at the end of the string *and* just before a trailing
newline, so ``^[0-9]+$`` accepts ``"123\\n"`` and stops one character short of
it. Four validation patterns here carried that anchor -- the year, the two
media id spellings and the bare rating key -- and so did the TOON encoder this
tool used to carry a copy of, where it let a key ending in a newline through
unquoted. ``\\Z`` matches at the end and nowhere else, and ``re.fullmatch``
needs no anchor at all.

This is the shared package's own check, held against this package, and it
states three different things on purpose:

- **No pattern in the package uses ``$`` outside multiline mode.** Each pattern
  is handed to the regular-expression parser and the parsed form is searched
  for the end-of-string-or-before-newline anchor, so ``\\$`` and ``[$]`` are not
  mistaken for one and a ``$`` in the middle of an alternation is not missed.
- **Every pattern anchored at both ends has an example here, and neither the
  example nor the example with a newline appended matches short of the end.**
  That is the behaviour the first rule protects, stated as behaviour, with
  fixed inputs: a randomised test finds a trailing newline only when it happens
  to draw one.
- **The public functions built on those patterns never hand a newline on.**

The first rule reads source, which is a weak instrument on its own: a
behaviour-preserving rewrite can move the text. It is here because the failure
it prevents is a single character that reads as correct, and the other two
rules only cover the patterns somebody remembered to give an example.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import re
import sys
from pathlib import Path

import pytest

import plex_axi
from plex_axi.toolkit import ids, matching

try:  # Python 3.11 moved the parser under ``re``; the old names warn and then go.
    from re import _constants as sre_constants
    from re import _parser as sre_parse
except ImportError:  # pragma: no cover - the 3.10 spelling
    import sre_constants
    import sre_parse

PACKAGE_ROOT = Path(plex_axi.__file__).resolve().parent

#: Every ``re`` function that takes a pattern first, and where its flags sit
#: when they are passed by position.
_FLAGS_POSITION = {
    "compile": 1,
    "match": 2,
    "fullmatch": 2,
    "search": 2,
    "findall": 2,
    "finditer": 2,
    "split": 3,
    "sub": 4,
    "subn": 4,
}


# ------------------------------------------------------------- reading a pattern


def _nodes(node):
    """Every ``(op, argument)`` pair in a parsed pattern, however deeply nested."""
    if isinstance(node, sre_parse.SubPattern):
        for op, argument in node.data:
            yield op, argument
            yield from _nodes(argument)
    elif isinstance(node, (tuple, list)):
        for child in node:
            yield from _nodes(child)


def dollar_anchors(source: str, flags: int = 0) -> int:
    """How many ``$`` anchors a pattern holds that can match before a trailing newline.

    Zero in multiline mode, where ``$`` means end of line and is the right spelling.
    """
    parsed = sre_parse.parse(source, flags)
    if parsed.state.flags & re.MULTILINE:
        return 0
    return sum(
        1
        for op, argument in _nodes(parsed)
        if op is sre_constants.AT and argument is sre_constants.AT_END
    )


def judges_the_whole_string(source: str, flags: int = 0) -> bool:
    """Anchored at the start and at the very end: a validator, not a prefix match."""
    data = sre_parse.parse(source, flags).data
    if len(data) < 2:
        return False
    starts = data[0][0] is sre_constants.AT and data[0][1] in (
        sre_constants.AT_BEGINNING,
        sre_constants.AT_BEGINNING_STRING,
    )
    ends = data[-1][0] is sre_constants.AT and data[-1][1] is sre_constants.AT_END_STRING
    return starts and ends


# ---------------------------------------------------------- finding the patterns


def _flags(call: ast.Call) -> int:
    position = _FLAGS_POSITION[call.func.attr]
    node = next((keyword.value for keyword in call.keywords if keyword.arg == "flags"), None)
    if node is None and len(call.args) > position:
        node = call.args[position]
    if node is None:
        return 0
    return int(eval(compile(ast.Expression(node), "<flags>", "eval"), {"re": re}))


def written_patterns() -> list[tuple[str, str, int]]:
    """Every pattern written as a literal in the package: where, its source, its flags."""
    found = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "re"
                and node.func.attr in _FLAGS_POSITION
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                continue
            where = f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno}"
            found.append((where, node.args[0].value, _flags(node)))
    return found


def _borrowed() -> set[int]:
    """The compiled patterns that belong to the shared package, by identity."""
    return {
        id(value)
        for name, module in list(sys.modules.items())
        if name == "axi_toolkit" or name.startswith("axi_toolkit.")
        for value in vars(module).values()
        if isinstance(value, re.Pattern)
    }


def compiled_patterns() -> list[tuple[str, re.Pattern]]:
    """Every compiled pattern of this package's own that a module holds once imported.

    A pattern imported from the shared package is that package's to read, and
    its own copy of this file does; it is left out by identity, so a pattern
    written here with the same text as one of theirs is still counted.
    """
    found = []
    modules = pkgutil.walk_packages(plex_axi.__path__, plex_axi.__name__ + ".")
    for name in ["plex_axi", *(info.name for info in modules)]:
        module = importlib.import_module(name)
        for attribute, value in vars(module).items():
            if isinstance(value, re.Pattern):
                found.append((f"{name}.{attribute}", value))
    borrowed = _borrowed()
    return [(name, pattern) for name, pattern in found if id(pattern) not in borrowed]


# ---------------------------------------------------------- the rule on the text


@pytest.mark.parametrize(
    ("source", "flags", "expected"),
    [
        (r"^[0-9]+$", 0, 1),
        (r"^(mon|[smhdwy])$", re.IGNORECASE, 1),
        (r"^a$|^b\Z", 0, 1),
        (r"^(?:a$|b$)", 0, 2),
        (r"^[0-9]+\Z", 0, 0),
        (r"^price: \$[0-9]+\Z", 0, 0),
        (r"^[$][0-9]+\Z", 0, 0),
        (r"^line$", re.MULTILINE, 0),
        (r"(?m)^line$", 0, 0),
        (r"[0-9]+", 0, 0),
    ],
)
def test_the_reader_tells_a_dollar_anchor_from_everything_that_looks_like_one(
    source, flags, expected
):
    """A check that has never failed is not yet a check: these are the ones it must."""
    assert dollar_anchors(source, flags) == expected


def test_no_pattern_in_the_package_can_stop_before_a_trailing_newline():
    offenders = [
        f"{where}: {source!r}"
        for where, source, flags in written_patterns()
        if dollar_anchors(source, flags)
    ]
    assert not offenders, (
        "`$` also matches just before a trailing newline; end the pattern in `\\Z`, "
        "or drop the anchors and call `fullmatch`:\n  " + "\n  ".join(offenders)
    )


def test_every_compiled_pattern_is_one_the_rule_above_read():
    """The rule reads ``re.<function>("literal")`` calls, so that is what must exist.

    A pattern built some other way -- an aliased import, a concatenation, a
    helper -- would be compiled and never read. This is the other half: every
    pattern a module actually holds has to be one the reader found.
    """
    read = {source for _, source, _ in written_patterns()}
    unread = [name for name, pattern in compiled_patterns() if pattern.pattern not in read]
    assert not unread, f"compiled, but not written where the rule can read it: {unread}"


# ------------------------------------------------------- the rule as behaviour

#: The two line patterns `hooks.py` writes inline, so they have no name to
#: import. Kept as the same source text; the table test below fails if either
#: drifts from what the module holds.
_TOML_SECTION = re.compile(r"^\s*(\[{1,2})([^\]]+)(\]{1,2})\s*(?:#.*)?\Z")
_TOML_HOOKS_ON = re.compile(r"^\s*hooks\s*=\s*true\s*(?:#.*)?\Z")

#: Every pattern in the package that judges a whole string, with one string it
#: accepts. Fixed inputs, not generated ones.
VALIDATORS = [
    (matching._YEAR, "1977"),
    (ids._MEDIA_ID, "plex://0123456789abcdef/12345"),
    (ids._LEGACY_MEDIA_ID, "plex://12345"),
    (ids._RATING_KEY, "12345"),
    (_TOML_SECTION, "[features]"),
    (_TOML_SECTION, "[[example]] # a table array"),
    (_TOML_HOOKS_ON, "hooks = true"),
]

#: The four that ended in ``$`` and therefore accepted the newline outright.
REFUSES_A_TRAILING_NEWLINE = VALIDATORS[:4]


@pytest.mark.parametrize(("pattern", "accepted"), VALIDATORS)
def test_a_match_never_stops_short_of_the_end_of_the_string(pattern, accepted):
    """Accept the whole string or refuse it; never accept all of it but the newline."""
    whole = pattern.match(accepted)
    assert whole is not None and whole.end() == len(accepted)
    with_newline = pattern.match(accepted + "\n")
    assert with_newline is None or with_newline.end() == len(accepted) + 1


@pytest.mark.parametrize(("pattern", "accepted"), REFUSES_A_TRAILING_NEWLINE)
def test_a_year_a_media_id_and_a_rating_key_refuse_a_trailing_newline(pattern, accepted):
    """The four patterns the anchor was wrong in, each with the input it let through."""
    assert pattern.match(accepted)
    assert pattern.match(accepted + "\n") is None
    assert pattern.match(accepted + "\r\n") is None


def test_every_pattern_that_judges_a_whole_string_has_an_example_above():
    """A new validator arrives with an example or this fails, so the table stays whole."""
    exemplified = {pattern.pattern for pattern, _ in VALIDATORS}
    missing = [
        f"{where}: {source!r}"
        for where, source, flags in written_patterns()
        if judges_the_whole_string(source, flags) and source not in exemplified
    ]
    assert not missing, "anchored at both ends, with no example in VALIDATORS:\n  " + "\n  ".join(
        missing
    )


# ------------------------------------------------- the functions built on them


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ("12345", ids.RATING_KEY),
        ("plex://12345", ids.LEGACY_MEDIA_ID),
        ("plex://0123456789abcdef/12345", ids.MEDIA_ID),
    ],
)
def test_an_identifier_pasted_with_its_line_ending_resolves_to_the_same_key(raw, kind):
    """A value read from a file arrives with a newline; the key must not keep it."""
    ref = ids.parse_reference(raw + "\n")
    assert (ref.kind, ref.key, ref.raw) == (kind, "12345", raw)


def test_a_newline_inside_an_identifier_is_not_a_reference():
    assert ids.parse_reference("123\n45").kind == ids.UNRECOGNISED


def test_a_year_pasted_with_its_line_ending_is_returned_without_it():
    assert matching.year("1977\n") == "1977"
    assert matching.year("19\n77") is None
