"""The pure text rules, stated on their own.

`plex_axi.matching` takes strings and returns strings: no server, no command
line, no error class. These tests take the same view of it, so that the module
and its tests can be lifted into a shared package together.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from plex_axi import matching

APOS, OPEN, CLOSE, ELL, HYPH, DASH = "\u2019", "\u201c", "\u201d", "\u2026", "\u2010", "\u2013"


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        ("Example Track", "Example Track"),
        ("Last, First", "Last First"),
        ("trailing,", "trailing"),
        (",leading", "leading"),
        ("two  spaces", "two spaces"),
        ("  padded  ", "padded"),
        ("tab\tand\nnewline", "tab and newline"),
        ("a,,b", "a b"),
        (",", ""),
        (" , , ", ""),
        ("", ""),
    ],
)
def test_a_value_is_cleaned_of_what_the_server_misreads(raw, cleaned):
    assert matching.clean_text(raw) == cleaned


def test_a_cleaned_value_never_holds_a_comma_or_an_empty_word():
    for raw in ("a,b", "a , b", ",,", "x,", " lead", "a  b", "a,\u00a0b"):
        cleaned = matching.clean_text(raw)
        assert "," not in cleaned
        assert "" not in cleaned.split(" ") or cleaned == ""


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("plain words", ["plain words"]),
        ("don't", ["don't", f"don{APOS}t"]),
        ('say "hi"', ['say "hi"', f"say {OPEN}hi{CLOSE}"]),
        ("wait...", ["wait...", f"wait{ELL}"]),
        ("well-known", ["well-known", f"well{HYPH}known", f"well{DASH}known"]),
        (f"don{APOS}t", [f"don{APOS}t", "don't"]),
        (f"wait{ELL}", [f"wait{ELL}", "wait..."]),
    ],
)
def test_each_punctuation_spelling_a_title_might_hold(typed, expected):
    assert matching.spellings(typed) == expected


def test_the_typed_value_is_always_first_and_the_list_is_bounded():
    for typed in ("x", 'it\'s - "all"... here', f"{APOS}{OPEN}{CLOSE}{ELL}{HYPH}{DASH}", ""):
        variants = matching.spellings(typed)
        assert variants[0] == typed
        assert len(variants) == len(set(variants)) <= matching.MAX_SPELLINGS


def test_no_spelling_holds_a_comma_so_they_can_be_joined_as_alternatives():
    for typed in ("don't stop", "rock - paper", 'the "one"'):
        assert all("," not in variant for variant in matching.spellings(typed))


@pytest.mark.parametrize(
    ("value", "folded"),
    [
        ("Caf\u00e9", "cafe"),
        (f"Don{APOS}t Stop", "don t stop"),
        ("Bj\u00f6rk", "bjork"),
        ("AC/DC", "ac dc"),
        ("  Mixed   CASE  ", "mixed case"),
        ("\u00c5ngstr\u00f6m", "angstrom"),
    ],
)
def test_folding_reduces_a_name_to_what_its_spellings_share(value, folded):
    assert matching.fold(value) == folded


@pytest.mark.parametrize(
    ("typed", "held", "matches"),
    [
        ("cafe", "Caf\u00e9 Example", True),
        ("exa caf", "Caf\u00e9 Example", True),
        ("dont", f"Don{APOS}t Stop", False),
        ("don't", f"Don{APOS}t Stop", True),
        ("xample", "Example", False),
        ("example", "", False),
        ("", "anything", True),
    ],
)
def test_a_loose_match_is_word_prefixes_after_folding(typed, held, matches):
    assert matching.loosely_matches(typed, held) is matches


@pytest.mark.parametrize("value", ["1977", " 2001 ", "0000"])
def test_a_year_is_four_ascii_digits(value):
    assert matching.year(value) == value.strip()


@pytest.mark.parametrize(
    "value", ["", "abc", "19", "20255", "1990-1999", "19 77", "\uff11\uff19\uff17\uff17"]
)
def test_anything_else_is_not_a_year(value):
    assert matching.year(value) is None


def test_the_module_imports_nothing_of_this_tools():
    """What keeps it movable: the standard library and nothing else."""
    tree = ast.parse(Path(matching.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, "a relative import ties this module to the tool"
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "re", "unicodedata"}, imported
