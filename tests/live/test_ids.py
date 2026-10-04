"""E: every identifier the tool prints is one the tool accepts back."""

from __future__ import annotations

MALFORMED = [
    "abc",
    "12a",
    "-5",
    "1.5",
    "0x1f",
    "plex://track/12345",
    "plex://track/a1b2c3d4e5f60718293c0111",
    "plex://",
    "local://",
    "plex:///12",
    "\uff11\uff12\uff13",
    "\u0661\u0662\u0663",
    "12 34",
    "12;rm",
    "../12",
]


def test_a_key_and_a_media_id_from_a_row_both_resolve(run, catalogue):
    rows = run("search", "--rated-min", "0.5", "--limit", "5", "--json").json().get("tracks")
    if not isinstance(rows, list):
        rows = run("recent", "--type", "track", "--limit", "5", "--json").json()["tracks"]
    assert rows
    for row in rows:
        assert row["media_id"] == f"plex://{catalogue.machine}/{row['key']}"
        by_key = run("track", str(row["key"]), "--json").json()
        by_media_id = run("track", row["media_id"], "--json").json()
        assert by_key == by_media_id


def test_media_ids_resolve_for_every_noun_that_takes_one(run, catalogue):
    """D13: `media_id` is printed in every row and was refused by every command."""
    track, album, artist = catalogue.tracks[0], catalogue.albums[0], catalogue.artists[0]
    prefix = f"plex://{catalogue.machine}/"
    assert run("track", prefix + track["ratingKey"]).code == 0
    assert run("album", prefix + album["ratingKey"]).code == 0
    assert run("artist", prefix + artist["ratingKey"]).code == 0
    assert run("similar", prefix + track["ratingKey"]).code == 0
    if catalogue.playlists:
        key = catalogue.playlists[0]["ratingKey"]
        assert run("playlist", "show", prefix + key, "--limit", "1").code == 0


def test_a_media_id_for_another_server_is_a_lookup_outcome(run, catalogue):
    result = run("track", "plex://" + "ab" * 20 + "/" + catalogue.tracks[0]["ratingKey"])
    assert result.code == 1
    assert "MEDIA_ID_OTHER_SERVER" in result.out


def test_a_malformed_key_is_refused_before_the_wire(run, proxy):
    """D23 among them: digits that are not ASCII reached the server."""
    for value in MALFORMED:
        for noun in ("track", "album", "artist", "similar"):
            proxy.reset()
            result = run(noun, value)
            assert result.code == 2, (noun, value.encode("unicode_escape"))
            assert proxy.log == [], (noun, value.encode("unicode_escape"))


def test_the_wrong_kind_of_item_exits_one_after_a_lookup(run, proxy, catalogue):
    """D18: it takes a request to learn what a key names, so it is not exit 2."""
    result = run("track", catalogue.albums[0]["ratingKey"])
    assert result.code == 1 and "WRONG_ITEM_TYPE" in result.out
    assert proxy.log
    if catalogue.playlists:
        key = catalogue.playlists[0]["ratingKey"]
        for noun in ("track", "album", "artist"):
            wrong = run(noun, key, "--json")
            assert wrong.code == 1
            for line in wrong.json()["help"]:
                assert "search --type" not in line  # D11: not a runnable command


def test_a_key_that_does_not_exist_is_not_found(run):
    assert run("track", "999999999").code == 1
