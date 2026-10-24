"""`search --artist-key/--album-key` and `pick --artist/--mood/--style`.

Offline, through the Plex double. What the double can show is the request the
tool builds and that the rows narrow when the server applies it. It cannot show
that a real server honours `album.id` on a track search: the client library
documents the field and adds it by hand, `artist.id` was measured against a real
server, and `album.id` has not been asked of one. These tests do not claim it.
"""

from __future__ import annotations

import json

import pytest


def _queries(server):
    return [
        r["query"]
        for r in server.requests
        if r["path"].endswith("/all") and "includeMeta" not in r["query"] and "type" in r["query"]
    ]


def _rows(result, noun="tracks"):
    return json.loads(result.out)[noun]


def test_album_key_asks_the_server_for_the_tracks_under_that_album(server, cli_run):
    result = cli_run("search", "--album-key", "110", "--no-group", "--json")
    assert result.code == 0
    assert _queries(server)[-1]["album.id"] == "110"
    rows = _rows(result)
    assert len(rows) == 2
    assert {row["key"] for row in rows} == {111, 112}


def test_artist_key_narrows_to_that_artist_and_not_a_namesake(server, cli_run):
    everything = _rows(cli_run("search", "--artist", "Example", "--no-group", "--json"))
    result = cli_run("search", "--artist-key", "200", "--no-group", "--json")
    assert result.code == 0
    assert _queries(server)[-1]["artist.id"] == "200"
    keys = {row["key"] for row in _rows(result)}
    assert keys == {211}
    # The text search also finds Example Artist's track; the key does not.
    assert {111, 211} <= {row["key"] for row in everything}


def test_a_key_filter_is_echoed_as_the_predicate_that_ran(server, cli_run):
    result = cli_run("search", "--album-key", "110", "--type", "album")
    assert result.code == 0
    assert 'album.id,is,"110"' in result.out


def test_a_key_combines_with_the_text_flags(server, cli_run):
    result = cli_run("search", "--artist-key", "100", "--genre", "Jazz", "--no-group")
    assert result.code == 0
    query = _queries(server)[-1]
    assert query["artist.id"] == "100"
    assert query["artist.genre"] == "11"


def test_a_key_alone_is_a_search_and_not_a_missing_field_error(server, cli_run):
    assert cli_run("search", "--album-key", "110").code == 0


@pytest.mark.parametrize("flag", ["--artist-key", "--album-key"])
@pytest.mark.parametrize(
    "value, code",
    [
        ("Example", "BAD_RATING_KEY"),
        ("plex://1234567890abcdef/110", "MEDIA_ID_NOT_RATING_KEY"),
        ("local://110", "GUID_NOT_RATING_KEY"),
    ],
)
def test_a_key_that_is_not_a_rating_key_is_refused_before_the_server_is_asked(
    server, cli_run, flag, value, code
):
    result = cli_run("search", flag, value)
    assert result.code == 2
    assert f"code: {code}" in result.out
    assert not [r for r in server.requests if r["path"].endswith("/all")]


def test_an_album_key_with_no_tracks_is_an_answer_and_exits_zero(server, cli_run):
    result = cli_run("search", "--album-key", "99999", "--no-group")
    assert result.code == 0
    assert "0 tracks matched" in result.out


def test_pick_by_artist_is_a_server_side_title_predicate(server, cli_run):
    result = cli_run("pick", "--artist", "Second Example", "--json")
    assert result.code == 0
    assert _queries(server)[-1]["artist.title"] == "Second Example"
    assert {row["key"] for row in _rows(result)} == {211}
    echoed = json.loads(result.out)["filters"]
    assert echoed == [
        {
            "field": "artist.title",
            "operator": "has words beginning",
            "value": "Second Example",
        }
    ]


def test_pick_by_mood_and_style_resolve_to_tag_ids(server, cli_run):
    result = cli_run("pick", "--mood", "Mellow", "--style", "Cool Jazz", "--json")
    assert result.code == 0
    query = _queries(server)[-1]
    assert query["track.mood"] == "31"
    assert query["artist.style"] == "21"
    # Mellow tracks by the one Cool Jazz artist, grouped by title; Guest Track
    # is Mellow too, by an artist with no style.
    assert {row["title"] for row in _rows(result)} == {"Example Track"}


def test_pick_reports_a_field_this_server_does_not_offer(monkeypatch, cli_run):
    import conftest
    from plex_axi import plex

    bare = {
        libtype: [f for f in fields if not f[0].endswith((".title", ".mood", ".style"))]
        for libtype, fields in conftest.SECTION_FIELDS.items()
    }
    fake = conftest.FakePlex(fields=bare)
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: conftest.FakeSession(fake))
    result = cli_run("pick", "--artist", "Example Artist", "--mood", "Mellow", "--style", "x")
    assert result.code == 0
    assert "unapplied[3]" in result.out
    for flag in ("--artist", "--mood", "--style"):
        assert flag in result.out
