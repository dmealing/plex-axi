"""`plex_axi.toolkit`: the library surface, and the wall around it.

Two things are stated here. The first is the rules themselves that are not
already stated in `test_matching.py` and `test_shapes.py` -- choosing among held
names, exact-name filtering, the performer rules, the nearest-title reading and
identifier parsing -- each as plain values in and plain values out.

The second is what makes the package a library rather than a corner of the CLI:
it imports nothing that prints, connects or names a command, and it carries no
recovery text. Both are checked by walking the code, because a rule that only
exists as a sentence is one somebody eventually skips.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest

from plex_axi import toolkit
from plex_axi.toolkit import ids, matching, search, shapes

PACKAGE = Path(toolkit.__file__).resolve().parent
SOURCE = PACKAGE.parent

APOS = "\u2019"

# ------------------------------------------------------- choosing among names


def test_one_exact_name_is_resolved():
    result = matching.resolve_name("Example Artist", ["Example Artist", "Example Artist Band"])
    assert result.resolved and result.match == "Example Artist"


def test_a_name_resolves_through_folding():
    held = [f"Don{APOS}t Example", "Other"]
    result = matching.resolve_name("dont example", held)
    assert result.status == matching.MISSING
    result = matching.resolve_name("don't example", held)
    assert result.status == matching.RESOLVED and result.match == held[0]
    assert matching.resolve_name("exámple", ["Example"]).match == "Example"


def test_a_folded_tie_returns_the_candidates_and_picks_none():
    held = ["Example", "EXAMPLE", "Exámple", "Example Two"]
    result = matching.resolve_name("example", held)
    assert result.status == matching.AMBIGUOUS
    assert result.match is None
    assert result.candidates == ("Example", "EXAMPLE", "Exámple")


def test_the_spelling_typed_breaks_a_folded_tie():
    result = matching.resolve_name("EXAMPLE", ["Example", "EXAMPLE"])
    assert result.resolved and result.match == "EXAMPLE"


def test_a_miss_returns_the_near_names_and_never_the_first():
    held = ["Example Band", "The Example Trio", "Unrelated"]
    result = matching.resolve_name("Example", held)
    assert result.status == matching.MISSING
    assert result.match is None
    assert result.candidates == ("Example Band", "The Example Trio")
    assert matching.resolve_name("Nothing", held).candidates == ()


@pytest.mark.parametrize("typed", ["", " , ,", "...", None])
def test_nothing_typed_is_its_own_answer(typed):
    result = matching.resolve_name(typed if typed is not None else "", ["Example"])
    assert result.status == matching.EMPTY_NAME and not result.resolved


def test_candidates_can_be_rows():
    rows = [{"key": 1, "title": "Example"}, {"key": 2, "title": "Example Band"}]
    result = matching.resolve_name("example", rows, name=lambda row: row["title"])
    assert result.match == rows[0]


def test_a_name_inside_another_name_is_not_that_name():
    assert matching.same_name("Example", "example")
    assert not matching.same_name("Example", "Example Band")
    assert not matching.same_name("", "")


def test_exact_matches_drops_the_artist_whose_name_only_contains_the_word():
    rows = [
        {"artist": "Example", "performer": ""},
        {"artist": "The Example Band", "performer": ""},
        {"artist": "Various Artists", "performer": "Example"},
        {"artist": "Various Artists", "performer": "Example Trio"},
    ]
    kept = matching.exact_matches(
        rows, "example", names=lambda row: (row["artist"], row["performer"])
    )
    assert kept == [rows[0], rows[2]]
    assert matching.exact_matches(["Example", "Example Band"], "Example") == ["Example"]


# ------------------------------------------------------------- search rules


def test_a_filter_value_is_cleaned_and_spelled():
    assert search.filter_value("Last,  First") == "Last First"
    assert search.filter_value("Don't") == ["Don't", f"Don{APOS}t"]
    assert search.filter_value(" , ") is None


def test_the_performer_group_composes_as_a_sibling():
    group = search.artist_or_performer("artist.title", "Example")
    assert group == {"or": [{"artist.title": "Example"}, {search.PERFORMER_FIELD: "Example"}]}
    assert search.compose({}, [group]) == group
    assert search.compose({"album.year": "1977"}, [group]) == {
        "and": [{"album.year": "1977"}, group]
    }
    assert search.compose({"album.year": "1977"}, []) == {"album.year": "1977"}


def test_an_unfiltered_page_shows_the_performer_field_did_not_run():
    assert search.performer_honoured([], "Example")
    assert search.performer_honoured([("Various Artists", "Example Artist")], "example")
    assert search.performer_honoured([("Example Artist", None)], "example")
    assert not search.performer_honoured([("Other", ""), ("Another", "Somebody")], "example")


def test_the_performer_is_shown_only_where_it_says_something():
    assert search.track_artist("Various Artists", "Example Artist") == "Example Artist"
    assert search.track_artist("Example Artist", "Example Artist") == ""
    assert search.track_artist("Example Artist", None) == ""
    assert search.playing_artist("Various Artists", "Example Artist") == "Example Artist"
    assert search.playing_artist("Example Artist", "") == "Example Artist"


def test_a_tracks_year_is_its_albums():
    assert search.track_year({"parentYear": "1977", "year": "2001"}) == "1977"
    assert search.track_year({"year": "2001"}) == "2001"
    assert search.track_year({}) is None


def test_sonic_analysis_is_read_from_the_preference():
    def prefs(value):
        return ElementTree.fromstring(
            f'<MediaContainer><Setting id="other" value="true"/>{value}</MediaContainer>'
        )

    assert search.sonic_analysis(prefs('<Setting id="musicAnalysis" value="true"/>')) is True
    assert search.sonic_analysis(prefs('<Setting id="musicAnalysis" value="false"/>')) is False
    assert search.sonic_analysis(prefs("")) is None
    assert search.preferences_path(3) == "/library/sections/3/prefs"


HUBS = """<MediaContainer>
  <Hub type="artist"><Directory ratingKey="501" title="Example Artist"/></Hub>
  <Hub type="track">
    <Track ratingKey="111" title="Example Track" grandparentTitle="Example Artist"/>
    <Track ratingKey="112" title="Example Track Two" parentTitle="Example Album"/>
    <Track ratingKey="113" title="Three"/><Track ratingKey="114" title="Four"/>
  </Hub>
</MediaContainer>"""


def test_nearest_titles_asks_once_per_name_and_reads_the_right_hub():
    asked = []

    def fetch(path, params):
        asked.append((path, params))
        return ElementTree.fromstring(HUBS)

    rows = search.nearest_titles(fetch, {"artist": "exampl", "query": "trak"}, section_key=3)
    assert asked == [
        ("/hubs/search", {"query": "exampl", "sectionId": 3, "limit": 3}),
        ("/hubs/search", {"query": "trak", "sectionId": 3, "limit": 3}),
    ]
    assert rows[0] == {
        "type": "artist",
        "key": 501,
        "title": "Example Artist",
        "artist": "",
        "_flag": "artist",
    }
    assert [(row["key"], row["artist"], row["_flag"]) for row in rows[1:]] == [
        (111, "Example Artist", "query"),
        (112, "Example Album", "query"),
        (113, "", "query"),
    ]


def test_a_failed_nearest_lookup_is_reported_and_not_raised():
    seen = []

    def fetch(path, params):
        raise RuntimeError("no")

    assert search.nearest_titles(fetch, {"track": "x"}, section_key=1, on_error=seen.append) == []
    assert [type(exc) for exc in seen] == [RuntimeError]
    assert search.nearest_titles(fetch, {"track": "x"}, section_key=1) == []


# ------------------------------------------------------------- answer shapes


def test_a_parsed_answer_is_judged_by_its_root():
    assert shapes.parsed_fault(None) == shapes.EMPTY
    assert shapes.parsed_fault("html") == shapes.FOREIGN
    assert shapes.parsed_fault("MediaContainer") is None


@pytest.mark.parametrize(
    ("status", "fault"), [(503, True), (500, True), ("502", True), (404, False), (0, False)]
)
def test_a_5xx_is_a_server_that_is_there_and_not_working(status, fault):
    assert shapes.is_server_fault(status) is fault
    assert shapes.is_server_fault(None) is False


# --------------------------------------------------------------- identifiers

MACHINE = "0123456789abcdef0123456789abcdef01234567"


@pytest.mark.parametrize(
    ("raw", "kind", "key", "machine"),
    [
        (f"plex://{MACHINE}/111", ids.MEDIA_ID, "111", MACHINE),
        (" plex://111 ", ids.LEGACY_MEDIA_ID, "111", None),
        ("111", ids.RATING_KEY, "111", None),
        ("\uff11\uff11\uff11", ids.NON_ASCII_DIGITS, "111", None),
        ("plex://track/111", ids.UNRECOGNISED, None, None),
        ("plex://track/0123456789abcdef01234567", ids.UNRECOGNISED, None, None),
        ("local://111", ids.UNRECOGNISED, None, None),
        ("abc", ids.UNRECOGNISED, None, None),
        ("", ids.UNRECOGNISED, None, None),
    ],
)
def test_an_identifier_is_taken_apart_and_nothing_is_raised(raw, kind, key, machine):
    ref = ids.parse_reference(raw)
    assert (ref.kind, ref.key, ref.machine, ref.raw) == (kind, key, machine, raw.strip())
    assert ref.usable is (kind in (ids.MEDIA_ID, ids.LEGACY_MEDIA_ID, ids.RATING_KEY))


def test_a_media_id_belongs_to_the_server_it_names():
    assert ids.same_server(MACHINE, MACHINE.upper())
    assert ids.same_server(None, MACHINE)
    assert not ids.same_server("f" * 40, MACHINE)


# ------------------------------------------------------------------ the wall

#: What the toolkit may never reach, directly or through anything it imports.
FORBIDDEN = {
    "plex_axi.argspec",
    "plex_axi.cli",
    "plex_axi.cloud",
    "plex_axi.commands",
    "plex_axi.errors",
    "plex_axi.hooks",
    "plex_axi.music",
    "plex_axi.output",
    "plex_axi.playback",
    "plex_axi.plex",
    "plex_axi.skill",
    "plex_axi.users",
    "plex_axi.writes",
}

#: Third-party packages a pure rule has no use for.
FORBIDDEN_ROOTS = {"plexapi", "requests", "urllib3", "axi_toolkit"}


def _module_file(name: str):
    """The source file of a module of this distribution, or ``None``."""
    path = SOURCE.parent.joinpath(*name.split("."))
    if path.with_suffix(".py").is_file():
        return path.with_suffix(".py")
    if (path / "__init__.py").is_file():
        return path / "__init__.py"
    return None


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(SOURCE.parent).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imports(path: Path) -> set:
    """Every module ``path`` imports, anywhere in it, as absolute names."""
    name = _module_name(path)
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join([*anchor, base] if base else anchor)
            found.add(base)
            # `from . import x` names a submodule as surely as `import .x` would.
            found.update(f"{base}.{alias.name}" for alias in node.names)
    return found


def _reachable() -> dict:
    """Every module the toolkit reaches, mapped to the module that imported it."""
    seen: dict = {}
    queue = [(path, "") for path in sorted(PACKAGE.glob("*.py"))]
    while queue:
        path, via = queue.pop()
        name = _module_name(path)
        if name in seen:
            continue
        seen[name] = via
        for imported in sorted(_imports(path)):
            target = _module_file(imported)
            if target is not None:
                queue.append((target, name))
            elif imported not in seen:
                seen[imported] = name
    return seen


def test_the_toolkit_reaches_nothing_that_prints_connects_or_names_a_command():
    reached = _reachable()
    offending = {
        name: via
        for name, via in reached.items()
        if any(name == bad or name.startswith(bad + ".") for bad in FORBIDDEN)
        or name.split(".")[0] in FORBIDDEN_ROOTS
    }
    assert not offending, f"the toolkit imports {offending}"
    assert "plex_axi.toolkit.matching" in reached, "the walk found nothing to check"


def test_the_walk_would_catch_an_import_of_the_cli(tmp_path, monkeypatch):
    """The guard above, pointed at a module that breaks the rule."""
    bad = PACKAGE / "_probe_for_test.py"
    bad.write_text("def late():\n    from ..commands import search\n", encoding="utf-8")
    try:
        reached = _reachable()
    finally:
        bad.unlink()
    assert "plex_axi.commands" in reached or "plex_axi.commands.search" in reached


def test_importing_the_toolkit_loads_no_client_library_and_no_cli():
    script = (
        "import sys, plex_axi.toolkit as t\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in "
        "('plexapi', 'requests', 'axi_toolkit') or (m.startswith('plex_axi.') and "
        "not m.startswith('plex_axi.toolkit')))\n"
        "print(','.join(bad))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert done.stdout.strip() == ""


def _strings_outside_docstrings(tree) -> list:
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


@pytest.mark.parametrize("path", sorted(PACKAGE.glob("*.py")), ids=lambda path: path.name)
def test_the_toolkit_carries_no_recovery_text(path):
    """No command line, no flag and no tool name in anything it could return."""
    text = path.read_text(encoding="utf-8")
    assert "plex-axi" not in text, "the tool's name belongs to the CLI"
    for value in _strings_outside_docstrings(ast.parse(text)):
        assert "Run `" not in value and not value.startswith("--"), value
    for node in ast.walk(ast.parse(text)):
        assert not isinstance(node, ast.Raise), f"{path.name} raises; errors are data here"
        assert not isinstance(node, (ast.AsyncFunctionDef, ast.Await)), "synchronous on purpose"


def test_the_public_names_are_explicit_and_real():
    assert len(set(toolkit.__all__)) == len(toolkit.__all__)
    for name in toolkit.__all__:
        assert hasattr(toolkit, name), name
    for module in (ids, matching, search, shapes):
        public = {
            name
            for name, value in vars(module).items()
            if not name.startswith("_")
            and getattr(value, "__module__", module.__name__) == module.__name__
            and not isinstance(value, type(ast))
            and name not in ("annotations", "dataclass")
        }
        assert public <= set(toolkit.__all__), sorted(public - set(toolkit.__all__))
