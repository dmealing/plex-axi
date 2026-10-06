"""The double is held to a capture of a real server: names only.

``tests/conftest.py`` answers in place of a Plex Media Server, and the rule for
it is *transcribe, never author*: nothing the server answers may be invented.
The rule was a sentence. A track's ``year`` attribute was invented anyway, the
tool read it, and the year was empty on every real server while every test
passed. So did an artist's ``childCount`` and an album row's ``leafCount`` --
both found by this file the first time it ran.

``tests/fixtures/plex-shape/capture.json`` is what a real server sent, reduced
to names by ``scripts/shape-capture.py``: element names, attribute names, field
keys and types, operator keys and titles, sort keys. No value from the library
is in it. This file asks one question of every table and element the double
has: *is that a name the server actually sends?*

It runs offline. Whether the capture still matches a server is a different
question, asked by ``scripts/shape-capture.py --check`` and by the live suite.

**What a failure means.** The double emits a name the capture does not have.
Either the double invented it -- remove it, and fix whatever in the tool was
reading it -- or the server sends it only in a state the capture did not
observe, in which case the attribute's declaration in ``metaobjects/`` carries an
``unobserved`` bag *with the reason it could not be observed*. A reason is
required; "it is probably fine" is how the invented attributes got there.

**What is declared once, and generated.** Which attributes a track, an album, an
artist and a playlist carry, which of them each printed row reads, and the
reasons above are the model in ``metaobjects/``. ``tests/plexmodel/`` is
generated from it: the builders the double makes those four elements through,
and the check that every declared attribute is one the capture has. The tests
at the end of this file break that check on purpose, so that it cannot stop
detecting anything and still pass.
"""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

import conftest
from conftest import (
    KNOWN_FIELDS,
    SECTION_FIELDS,
    SECTION_FILTERS,
    SECTION_SORTS,
    TOKEN,
    FakePlex,
)
from plex_axi import music
from plex_axi.commands import playlist, similar
from plex_axi.model import rows as vocabulary
from plexmodel import capture_contract as contract
from plexmodel import elements

CAPTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "plex-shape" / "capture.json").read_text(
        encoding="utf-8"
    )
)
ELEMENTS = CAPTURE["elements"]

#: Names the double emits that the capture could not have seen, each with why:
#: generated from the ``unobserved`` reasons in ``metaobjects/meta.plex.yaml``.
#: The capture server had sonic analysis off, nothing playing, no client
#: advertising and no rated album, so those states were not there to read.
UNOBSERVED = contract.UNOBSERVED

#: Fields the server accepts on the wire and does not advertise. Each was
#: measured against a real server, and each is a deliberate exception to "the
#: tool only sends what the section advertises".
ACCEPTED_UNADVERTISED = {"track.originalTitle", "artist.id"}


def _get(server, path, query=None):
    return ElementTree.fromstring(server.handle(path, query or {}, {"X-Plex-Token": TOKEN}))


def _names(elements) -> set:
    found: set = set()
    for element in elements:
        found.update(element.attrib)
    return found


def _extra(elements, *captured, allow=()) -> set:
    known = set().union(*(set(ELEMENTS[name]) for name in captured))
    return _names(elements) - known - set(allow)


# --------------------------------------------------------------- the filter language


@pytest.mark.parametrize(
    ("kind", "table"),
    [
        ("string", "_STRING_OPS"),
        ("integer", "_INT_OPS"),
        ("tag", "_TAG_OPS"),
        ("date", "_DATE_OPS"),
        ("boolean", "_BOOL_OPS"),
    ],
)
def test_every_operator_table_is_the_servers_own(kind, table):
    """Exact, keys and titles, in order: one invented operator cost a release."""
    assert [list(pair) for pair in getattr(conftest, table)] == CAPTURE["field_types"][kind]


@pytest.mark.parametrize("libtype", sorted(SECTION_FIELDS))
def test_every_field_the_double_advertises_is_one_the_server_does(libtype):
    real = CAPTURE["types"][libtype]["fields"]
    for key, _title, kind in SECTION_FIELDS[libtype]:
        assert key in real, f"the double advertises {key}, which no real section does"
        assert real[key] == kind, f"{key} is {real[key]!r} on a real server, not {kind!r}"


@pytest.mark.parametrize("libtype", sorted(SECTION_FILTERS))
def test_every_tag_filter_the_double_offers_is_one_the_server_does(libtype):
    offered = {name for name, _title in SECTION_FILTERS[libtype]}
    assert offered - set(CAPTURE["types"][libtype]["filters"]) == set()


def test_every_sort_the_double_offers_is_one_the_server_does():
    offered = {key for key, _title, _direction in SECTION_SORTS}
    for libtype, real in CAPTURE["types"].items():
        assert offered - set(real["sorts"]) == set(), libtype


def test_a_field_the_double_accepts_is_advertised_or_a_named_exception():
    """The double refuses an unknown field, so this set is what the tool may send."""
    advertised = {key for entry in CAPTURE["types"].values() for key in entry["fields"]}
    assert KNOWN_FIELDS - advertised == ACCEPTED_UNADVERTISED
    for key in ACCEPTED_UNADVERTISED:
        assert all(key != field for fields in SECTION_FIELDS.values() for field, *_ in fields)


# ------------------------------------------------------------------------- elements


def test_the_root_and_the_sections_carry_only_real_attributes():
    server = FakePlex()
    assert _extra([_get(server, "/")], "root") == set()
    assert _extra(list(_get(server, "/library/sections")), "section") == set()


@pytest.mark.parametrize(("libtype", "code"), [("artist", "8"), ("album", "9"), ("track", "10")])
def test_a_list_row_carries_only_attributes_a_real_row_does(libtype, code):
    server = FakePlex()
    container = _get(server, "/library/sections/3/all", {"type": code})
    assert set(container.attrib) - set(ELEMENTS["search.container"]) == set()
    allow = UNOBSERVED.get(libtype, {})
    assert _extra(list(container), f"{libtype}.row", allow=allow) == set()


@pytest.mark.parametrize(("libtype", "key"), [("artist", 100), ("album", 110), ("track", 111)])
def test_a_detail_view_carries_only_attributes_a_real_one_does(libtype, key):
    server = FakePlex()
    item = _get(server, f"/library/metadata/{key}")[0]
    allow = UNOBSERVED.get(libtype, {})
    assert _extra([item], f"{libtype}.detail", f"{libtype}.row", allow=allow) == set()
    assert {child.tag for child in item} - set(ELEMENTS[f"{libtype}.detail.children"]) == set()


def test_media_and_part_carry_only_real_attributes():
    server = FakePlex()
    track = _get(server, "/library/metadata/111")[0]
    media = track.findall("Media")
    assert _extra(media, "media") == set()
    assert _extra([part for entry in media for part in entry], "part") == set()
    checked = _get(server, "/library/metadata/111", {"checkFiles": "1"})[0]
    parts = [part for entry in checked.findall("Media") for part in entry]
    assert _extra(parts, "part.checked") == set()
    assert {"accessible", "exists"} <= _names(parts)


def test_an_artist_carries_no_count_so_the_view_has_to_ask():
    """Neither `childCount` nor `leafCount`: the double invented both, once."""
    for name in ("artist.row", "artist.detail"):
        assert not {"childCount", "leafCount"} & set(ELEMENTS[name]), name
    assert "librarySectionID" in ELEMENTS["artist.detail"]
    assert "totalSize" in ELEMENTS["search.container"]


def test_playlists_and_their_items_carry_only_real_attributes():
    server = FakePlex()
    assert _extra(list(_get(server, "/playlists", {"playlistType": "audio"})), "playlist") == set()
    items = _get(server, "/playlists/501/items")
    assert set(items.attrib) - set(ELEMENTS["playlist.items.container"]) == set()
    allow = UNOBSERVED["track"]  # a playlist's item is a Track element
    assert _extra(list(items), "playlist.item", "track.row", allow=allow) == set()


def test_the_library_preferences_are_the_servers_own():
    server = FakePlex()
    settings = list(_get(server, "/library/sections/3/prefs"))
    assert {setting.tag for setting in settings} == {"Setting"}
    assert _extra(settings, "setting") == set()
    assert {s.attrib["id"] for s in settings} <= set(ELEMENTS["setting.ids"])
    assert "musicAnalysis" in ELEMENTS["setting.ids"]


def test_the_free_text_search_answers_in_the_servers_shape():
    server = FakePlex()
    hubs = _get(server, "/hubs/search", {"query": "example"})
    assert _extra(list(hubs), "hub") == set()
    for hub in hubs:
        kind = hub.attrib["type"]
        assert {child.tag for child in hub} <= set(ELEMENTS[f"hub.{kind}.tag"])
        assert _extra(list(hub), f"hub.{kind}") == set()


def test_the_account_element_is_the_servers_own():
    server = FakePlex()
    account = _get(server, "/myplex/account")
    assert [account.tag] == ELEMENTS["myplex.tag"]
    assert _extra([account], "myplex") == set()
    assert "authToken" in ELEMENTS["myplex"]  # the attribute `api` must redact


def test_every_exception_states_why_it_could_not_be_observed():
    for names in UNOBSERVED.values():
        for name, reason in names.items():
            assert len(reason) > 20, name


def test_the_capture_holds_names_and_nothing_else():
    """No value from a library: every leaf is a name, a type or an operator title."""
    assert set(CAPTURE) == {"captured", "elements", "field_types", "types"}
    for name, values in ELEMENTS.items():
        assert all(isinstance(value, str) and value.isascii() for value in values), name
        assert all(" " not in value and "/" not in value for value in values), name


# ------------------------------------------------- the generated check, broken on purpose


def _declared(fqn, **changes):
    return {fqn: {**contract.DECLARED[fqn], **changes}}


def test_the_capture_check_refuses_an_attribute_no_server_sent():
    """The defect this file exists for, put back: a track `year`."""
    track = "plex::library::Track"
    fields = (*contract.DECLARED[track]["fields"], "year")
    assert contract.never_sent(ELEMENTS, _declared(track, fields=fields)) == {track: ["year"]}
    # A reason excuses it, and only a reason does.
    excused = {**contract.DECLARED[track]["unobserved"], "year": "a reason"}
    declared = _declared(track, fields=fields, unobserved=excused)
    assert contract.never_sent(ELEMENTS, declared) == {}
    # An answer the capture does not hold at all is not read as "nothing missing".
    declared = _declared(track, capture=("track.nowhere",), unobserved={})
    assert contract.never_sent(ELEMENTS, declared) == {track: sorted(fields[:-1])}


def test_the_capture_check_fails_in_one_direction_only():
    """A server sends far more than the tool reads; that is reported, not refused."""
    extra = contract.undeclared(ELEMENTS)
    assert all(extra[fqn] for fqn in contract.DECLARED)
    assert contract.never_sent(ELEMENTS) == {}
    assert "capture check: passed" in contract.report(ELEMENTS)


def test_a_row_may_not_read_what_only_another_answer_carries():
    """An album's track count is on its detail view and never on a row."""
    rows = {
        "album": {
            **contract.ROWS["album"],
            "reads": (*contract.ROWS["album"]["reads"], "leafCount"),
        }
    }
    assert "leafCount" in ELEMENTS["album.detail"]
    assert contract.never_read(ELEMENTS, rows) == {"album row, from album.row": ["leafCount"]}


def test_the_double_cannot_build_an_element_with_an_invented_attribute():
    with pytest.raises(KeyError, match="year"):
        elements.track(ratingKey=1, type="track", title="Example Track", year=1999)
    with pytest.raises(KeyError, match="ratingKey"):
        elements.track(type="track", title="Example Track")
    assert list(elements.track(title="Example Track", type="track", ratingKey=1)) == [
        "title",
        "type",
        "ratingKey",
    ]


# ------------------------------------------------- the model, held to the row builders

#: What a row builder reads off an item that is not an attribute of its element.
_BEYOND_A_TRACK = {
    "_data": "the element the client library built the object from, not an attribute",
    "year": "a fallback for a server that sends one; no captured track does",
}
BEYOND_THE_MODEL = {"track": _BEYOND_A_TRACK, "similar": _BEYOND_A_TRACK}


def _reads_of(*functions) -> set:
    """Every name read off the first parameter: `getattr(item, "x")` and `item.x`."""
    found: set = set()
    for function in functions:
        tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
        item = tree.body[0].args.args[0].arg
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and getattr(node.value, "id", None) == item:
                found.add(node.attr)
            elif (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "getattr"
                and getattr(node.args[0], "id", None) == item
            ):
                found.add(node.args[1].value)
    return found


@pytest.mark.parametrize(
    ("row", "builders"),
    [
        ("track", (music.track_row, music.track_year)),
        # A neighbour is a track row with the distance `similar` adds to it.
        ("similar", (music.track_row, music.track_year, similar._distance)),
        ("album", (music.album_row,)),
        ("artist", (music.artist_row,)),
        ("playlist", (playlist._playlist_row,)),
    ],
)
def test_a_row_builder_reads_exactly_what_the_model_says_its_row_reads(row, builders):
    """The model's `READS` is a claim about hand-written code, so it is checked against it."""
    declared = {name for names in vocabulary.READS[row].values() for name in names}
    assert _reads_of(*builders) - set(BEYOND_THE_MODEL.get(row, {})) == declared


@pytest.mark.parametrize("libtype", ["artist", "album", "track"])
def test_a_row_builder_fills_exactly_the_columns_the_model_offers(libtype):
    item = type("Item", (), {"ratingKey": 1})()
    built = music.ROW_BUILDERS[libtype](item, conftest.MACHINE_ID)
    assert list(built) == list(vocabulary.FIELDS[libtype])
    assert set(vocabulary.DEFAULT[libtype]) <= set(built)
