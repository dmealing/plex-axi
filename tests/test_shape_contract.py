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
observe, in which case it goes in :data:`UNOBSERVED` *with the reason it could
not be observed*. A reason is required; "it is probably fine" is how the
invented attributes got there.
"""

from __future__ import annotations

import json
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

CAPTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "plex-shape" / "capture.json").read_text(
        encoding="utf-8"
    )
)
ELEMENTS = CAPTURE["elements"]

#: Names the double emits that the capture could not have seen, each with why.
#: The capture server had sonic analysis off, nothing playing, no client
#: advertising and no rated album, so the states below were not there to read.
UNOBSERVED = {
    "track": {
        "musicAnalysisVersion": "sonic analysis was off for the captured library",
        "distance": "only on `/nearest`, which answers nothing with analysis off",
    },
    "album": {
        "userRating": "sent only on a rated item, and no album in the sample was rated",
    },
    "playlist.item": {
        "musicAnalysisVersion": "sonic analysis was off for the captured library",
        "playlistItemID": "sent on a playlist's items; the sampled playlist was a smart one",
    },
}

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
    allow = UNOBSERVED["playlist.item"]
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


# ----------------------------------------------------- what the tool reads, it gets


def test_every_attribute_a_row_reads_is_one_a_real_row_sends():
    """The other direction: a column that reads a name no real row carries is null.

    The row builders read attributes by name; each name read here has to be one
    a real row has, or the column it fills is empty everywhere but in the tests.
    """
    reads = {
        "track": {
            "ratingKey",
            "title",
            "grandparentTitle",
            "originalTitle",
            "parentTitle",
            "parentYear",
            "userRating",
            "duration",
            "viewCount",
            "skipCount",
            "index",
            "addedAt",
            "guid",
        },
        "album": {"ratingKey", "title", "parentTitle", "year", "addedAt", "guid"},
        "artist": {"ratingKey", "title", "userRating", "addedAt", "guid"},
    }
    for libtype, names in reads.items():
        missing = names - set(ELEMENTS[f"{libtype}.row"]) - set(UNOBSERVED.get(libtype, {}))
        assert missing == set(), f"a {libtype} row never carries {sorted(missing)}"


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
