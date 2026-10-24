"""The public surface of `plex_axi.toolkit`, pinned name by name and signature by signature.

Other programs import this package, and its docstrings promise that a name in
`__all__` is not removed or changed in meaning without a release note. Nothing
failed when one was: `test_toolkit.py` checks that `__all__` is consistent and
that the modules are pure, and checks behaviour, but a renamed parameter or a
dropped function still passed it. This is the snapshot that does not.

A failure here is not necessarily a bug. It is the point at which the change is
either undone or recorded: update the snapshot below *and* say so in the release
note, in the same commit. Constants are pinned by type only, because their values
are covered by the behaviour tests that use them.
"""

from __future__ import annotations

import inspect
import types

from plex_axi import toolkit

SURFACE = {
    "ACTION_ENDINGS": "const tuple",
    "ACTION_PREFIXES": "const tuple",
    "AMBIGUOUS": "const str",
    "ANALYSIS_SETTING": "const str",
    "EMPTY": "const str",
    "EMPTY_NAME": "const str",
    "FOREIGN": "const str",
    "LEGACY_MEDIA_ID": "const str",
    "MAX_SPELLINGS": "const int",
    "MEDIA_ID": "const str",
    "MISSING": "const str",
    "NEAREST_KINDS": "const dict",
    "NEAREST_PATH": "const str",
    "NEAREST_SHOWN": "const int",
    "NON_ASCII_DIGITS": "const str",
    "PERFORMER_FIELD": "const str",
    "PERFORMER_TITLE": "const str",
    "RATING_KEY": "const str",
    "RESOLVED": "const str",
    "Reference": "class(kind: 'str', key: 'str | None', machine: 'str | None', raw: 'str') -> None",
    "Resolution": "class(status: 'str', match: 'object' = None, candidates: 'tuple' = ()) -> None",
    "TEXT_FLAGS": "const tuple",
    "TEXT_OPERATOR": "const str",
    "UNPARSEABLE": "const str",
    "UNRECOGNISED": "const str",
    "acts_on_get": "def(path: 'str') -> 'bool'",
    "answer_kind": "def(body: 'str') -> 'str'",
    "artist_or_performer": "def(artist_field: 'str', value) -> 'dict'",
    "clean_text": "def(raw) -> 'str'",
    "compose": "def(filters: 'dict', groups: 'list') -> 'dict'",
    "exact_matches": "def(rows, typed, *, names=None) -> 'list'",
    "filter_value": "def(raw)",
    "fold": "def(value: 'str') -> 'str'",
    "has_dot_segments": "def(path: 'str') -> 'bool'",
    "ids": "module",
    "is_credential_name": "def(name: 'str') -> 'bool'",
    "is_foreign_root": "def(tag: 'str') -> 'bool'",
    "is_server_fault": "def(status) -> 'bool'",
    "loosely_matches": "def(typed: 'str', held: 'str') -> 'bool'",
    "matching": "module",
    "nearest_request": "def(typed: 'str', section_key, *, shown: 'int' = 3) -> 'tuple'",
    "nearest_rows": "def(answer, kind: 'str', *, shown: 'int' = 3) -> 'list'",
    "nearest_titles": "def(fetch, texts: 'dict', *, section_key, on_error=None) -> 'list'",
    "normalise_path": "def(path: 'str') -> 'str'",
    "parse_reference": "def(raw) -> 'Reference'",
    "parsed_fault": "def(root_tag)",
    "performer_honoured": "def(rows, typed: 'str') -> 'bool'",
    "playing_artist": "def(album_artist, performer) -> 'str'",
    "preferences_path": "def(section_key) -> 'str'",
    "resolve_name": "def(typed, candidates, *, name=None) -> 'Resolution'",
    "same_name": "def(typed, held) -> 'bool'",
    "same_server": "def(machine, server_machine) -> 'bool'",
    "search": "module",
    "shapes": "module",
    "sonic_analysis": "def(preferences)",
    "spellings": "def(value: 'str') -> 'list'",
    "to_ascii": "def(value: 'str') -> 'str'",
    "track_artist": "def(album_artist, performer) -> 'str'",
    "track_year": "def(attributes)",
    "year": "def(raw)",
}


def _describe(value) -> str:
    if isinstance(value, types.ModuleType):
        return "module"
    if inspect.isclass(value):
        try:
            return "class" + str(inspect.signature(value))
        except (TypeError, ValueError):
            return "class"
    if callable(value):
        return "def" + str(inspect.signature(value))
    return "const " + type(value).__name__


def test_the_exported_names_are_exactly_the_snapshot():
    assert set(toolkit.__all__) == set(SURFACE)


def test_every_exported_name_keeps_its_kind_and_signature():
    changed = {
        name: (SURFACE[name], _describe(getattr(toolkit, name)))
        for name in SURFACE
        if _describe(getattr(toolkit, name)) != SURFACE[name]
    }
    assert not changed, f"public surface changed (pinned, now): {changed}"
