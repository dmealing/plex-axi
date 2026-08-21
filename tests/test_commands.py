"""The remaining commands: vocabulary, detail, similarity, recency, sessions, api.

Each command here earns its place by doing something the raw `api` escape hatch
cannot, and each test says which thing that is.
"""

from __future__ import annotations

from conftest import FakePlex, FakeSession
from plex_axi.commands import sessions

# ------------------------------------------------------------- M12: vocabulary


def test_genres_returns_the_exact_strings_the_server_will_accept(server, cli_run):
    """M12: guessing between "jazz", "Jazz" and "Vocal Jazz" is the whole problem."""
    result = cli_run("genres")
    assert result.code == 0
    assert result.line("genres[") == "genres[2]: Jazz,Rock"
    assert result.line("field:") == "field: artist.genre"
    assert "not a synonym" in result


def test_genres_reads_the_artist_because_that_is_where_plex_keeps_them(server, cli_run):
    assert cli_run("genres").code == 0
    paths = [r["path"] for r in server.requests]
    assert "/library/sections/3/artist/genre" in paths


def test_moods_default_to_the_track_and_can_be_asked_of_the_artist(server, cli_run):
    """Moods are written at every level, so the level is a flag, not an assumption."""
    tracks = cli_run("moods")
    assert tracks.code == 0
    assert tracks.line("field:") == "field: track.mood"
    assert "Mellow" in tracks

    artists = cli_run("moods", "--type", "artist")
    assert artists.code == 0
    assert artists.line("field:") == "field: artist.mood"
    assert "Reflective" in artists


def test_styles_are_listed_and_searchable(server, cli_run):
    listed = cli_run("styles")
    assert listed.code == 0
    assert "Cool Jazz" in listed
    found = cli_run("search", "--style", "Cool Jazz")
    assert found.code == 0
    assert "Example Track" in found


def test_an_empty_vocabulary_is_stated_rather_than_left_blank(monkeypatch, cli_run):
    from plex_axi import plex

    fake = FakePlex()
    original = fake._choices
    fake._choices = lambda name, libtype: original("mood", "album")
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))
    result = cli_run("genres")
    assert result.code == 0
    assert "0 genres on this library" in result


# ------------------------------------------------------------------ S4: detail


def test_the_track_detail_reports_the_analysis_version(server, cli_run):
    """S4: nothing else in the landscape exposes it, and a zero is not a rating."""
    analysed = cli_run("track", "111")
    assert analysed.code == 0
    assert analysed.line("analysis:") == "analysis: 6"

    unanalysed = cli_run("track", "122")
    assert unanalysed.code == 0
    assert "not analysed" in unanalysed.line("analysis:")
    assert "no seed" in unanalysed.line("analysis:")


def test_file_availability_is_not_checked_unless_it_is_asked_for(server, cli_run):
    """S4: the empty value means "the server never looked", not "missing"."""
    default = cli_run("track", "111")
    assert default.code == 0
    assert "not checked (run with --check-files)" in default
    assert "file:" not in default
    assert not any(r["query"].get("checkFiles") for r in server.requests)


def test_check_files_costs_a_second_request_and_reports_what_it_found(server, cli_run):
    result = cli_run("track", "111", "--check-files")
    assert result.code == 0
    assert result.line("availability:") == "availability: readable by the server"
    assert any(r["query"].get("checkFiles") == "1" for r in server.requests)


def test_a_missing_file_and_an_unreadable_one_are_different_answers(server, cli_run):
    unreadable = cli_run("track", "121", "--check-files")
    assert "not readable by the server" in unreadable

    missing = cli_run("track", "122", "--check-files")
    assert "cannot find the file" in missing


def test_a_compilation_track_detail_reports_both_artists(server, cli_run):
    """S5 again, in the view a human reads before pasting an id somewhere."""
    result = cli_run("track", "311")
    assert result.code == 0
    assert result.line("artist:") == "artist: Various Artists"
    assert result.line("track_artist:") == "track_artist: Example Artist"


def test_album_and_artist_detail_views_link_onward(server, cli_run):
    album = cli_run("album", "110")
    assert album.code == 0
    assert album.line("album:") == "album: Example Album"
    assert "plex-axi artist 100" in album

    artist = cli_run("artist", "100")
    assert artist.code == 0
    assert artist.line("artist:") == "artist: Example Artist"
    assert "--type album" in artist


def test_asking_for_the_wrong_noun_says_what_the_key_actually_is(server, cli_run):
    result = cli_run("track", "110")
    assert result.code == 2
    # B14: "a album" reads as carelessness in the message most likely to be
    # read word by word, and two of the three nouns here begin with a vowel.
    assert "is an album on this server, not a track" in result
    assert "plex-axi album 110" in result


def test_a_rating_key_that_does_not_resolve_says_keys_move(server, cli_run):
    result = cli_run("track", "999999")
    assert result.code == 1
    assert "library rebuild" in result or "not resolve" in result


# ---------------------------------------------------------------- S2: similar


def test_similar_prints_the_servers_own_distance(server, cli_run):
    """S2: without the distance a caller cannot tell a match from the tail."""
    result = cli_run("similar", "111")
    assert result.code == 0
    assert result.line("tracks[").startswith("tracks[2]{distance,")
    rows = [ln.strip() for ln in result.out.splitlines() if ln.startswith("  0.")]
    assert rows[0].startswith("0.0821,")


def test_similar_honours_a_maximum_distance_server_side(server, cli_run):
    result = cli_run("similar", "111", "--max-distance", "0.1")
    assert result.code == 0
    assert result.line("tracks[").startswith("tracks[1]")
    assert any(r["query"].get("maxDistance") == "0.1" for r in server.requests)


def test_similar_on_an_album_says_similarity_is_per_track(server, cli_run):
    result = cli_run("similar", "110")
    assert result.code == 2
    assert "per track" in result


def test_no_neighbours_points_at_the_analysis_rather_than_the_library(server, cli_run):
    result = cli_run("similar", "122")
    assert result.code == 0
    assert "0 sonically similar tracks" in result
    assert "analysis" in result


def test_a_bad_distance_is_a_usage_error(server, cli_run):
    for value in ("2", "-1", "close"):
        assert cli_run("similar", "111", "--max-distance", value).code == 2


# ----------------------------------------------------------------- S10: recent


def test_recent_uses_the_music_typed_endpoint_not_the_server_wide_one(server, cli_run):
    """S10: `/library/recentlyAdded` spans video, which is the wrong answer."""
    result = cli_run("recent")
    assert result.code == 0
    paths = [r["path"] for r in server.requests]
    assert "/library/recentlyAdded" not in paths
    assert "/library/sections/3/all" in paths


def test_a_list_view_never_fetches_each_row_again(server, cli_run):
    """The client library re-fetches an object when an absent attribute is read.

    On a list that is one extra request per row, and the caller sees only a slow
    command. Auto-reload is off, so an absent value is reported as absent.
    """
    for argv in (
        ("recent",),
        ("search", "--artist", "Example Artist"),
        ("recent", "--type", "artist"),
    ):
        server.requests.clear()
        assert cli_run(*argv).code == 0, argv
        per_item = [
            r["path"] for r in server.requests if r["path"].startswith("/library/metadata/")
        ]
        assert per_item == [], (argv, per_item)


def test_recent_defaults_to_albums_because_that_is_how_music_arrives(server, cli_run):
    result = cli_run("recent")
    assert result.code == 0
    assert result.line("albums[")
    assert "Example Compilation" in result


def test_recent_can_be_asked_for_tracks_or_artists(server, cli_run):
    assert cli_run("recent", "--type", "track").line("tracks[")
    assert cli_run("recent", "--type", "artist").line("artists[")


def test_a_bad_type_is_rejected_by_name(server, cli_run):
    result = cli_run("recent", "--type", "movie")
    assert result.code == 2
    assert "--type must be one of" in result


# --------------------------------------------------------------- S7: sessions


def test_sessions_report_what_the_server_believes_is_playing(server, cli_run):
    result = cli_run("sessions")
    assert result.code == 0
    assert result.line("count:") == "count: 1 active"
    # B3: a real `<Player>` carries no `title`, so this column read an attribute
    # that is never there and was empty on every real session. `device` is the
    # name of the box; `product` and `platform` are the fallbacks behind it.
    assert "Example Speaker" in result
    assert "playing" in result


def test_a_session_names_the_player_from_whatever_attribute_carries_one():
    """B3: `device`, `product` and `platform` are three strings, and a real
    `<Player>` carries no `title` at all.

    Reading `title` alone left the one column that says *where the music is
    playing* empty on every real session and full on every test, because the
    double had invented the attribute. The fallback runs most-specific first.
    """

    class Player:
        def __init__(self, **attributes):
            self.__dict__.update(attributes)

    assert sessions._device(Player(device="Box", product="App", platform="OS")) == "Box"
    assert sessions._device(Player(device="", product="App", platform="OS")) == "App"
    assert sessions._device(Player(device="", product="", platform="OS")) == "OS"
    assert sessions._device(Player(device="", product="", platform="")) == ""
    assert sessions._device(None) == ""


def test_no_sessions_is_a_definitive_zero(monkeypatch, cli_run):
    from plex_axi import plex

    fake = FakePlex()
    monkeypatch.setattr(fake, "_sessions", lambda: __import__("conftest")._container("", size=0))
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))
    result = cli_run("sessions")
    assert result.code == 0
    assert "0 streams are playing right now" in result


# -------------------------------------------------------------------- S12: api


def test_api_reaches_any_read_path(server, cli_run):
    result = cli_run("api", "/library/sections")
    assert result.code == 0
    assert "Example Music" in result


def test_api_refuses_a_write_method_rather_than_documenting_that_it_should_not(server, cli_run):
    """A gate a raw POST could walk around is not a gate.

    `rate` and `playlist` write, and both are refused, previewable and specific
    about what they touch. A raw path that could POST would be none of those and
    would make the gate meaningless, so `api` stays GET-only whatever is enabled.
    """
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        result = cli_run("api", method, "/library/sections")
        assert result.code == 2
        assert "read-only" in result


def test_api_refuses_head_rather_than_sending_the_get_it_would_become(server, cli_run):
    """A HEAD has no body to render, and a defaulted request method sends a GET.

    Answering a HEAD by rendering a GET's body under `request.method: HEAD`
    would be output naming a request that was never made.
    """
    result = cli_run("api", "HEAD", "/library/sections")
    assert result.code == 2
    assert "HEAD" in result
    assert "GET" in result
    assert not server.requests


def test_api_passes_query_parameters_through(server, cli_run):
    result = cli_run("api", "/library/sections/3/all", "--query", "type=10", "--query", "limit=2")
    assert result.code == 0
    assert any(r["query"].get("limit") == "2" for r in server.requests)


def test_api_needs_a_path(server, cli_run):
    result = cli_run("api")
    assert result.code == 2
    assert "a path is required" in result


def test_api_depth_is_bounded(server, cli_run):
    assert cli_run("api", "/", "--depth", "99").code == 2
    assert cli_run("api", "/", "--depth", "abc").code == 2
