"""The search path: the section, the operators, the count, and both artists.

These are the tests that would pass against a filter that does nothing, if the
double were not strict. Each one asserts on the URL the client library actually
built, because "did the filter apply?" is a question about the request.
"""

from __future__ import annotations


def _search_requests(server):
    """Every request to a section's item endpoint, in order."""
    return [
        r for r in server.requests if r["path"].endswith("/all") and "includeMeta" not in r["query"]
    ]


def test_search_runs_against_the_music_section_never_the_whole_library(server, cli_run):
    """M2: the section endpoint, resolved by type, and never ``/library/all``."""
    result = cli_run("search", "--artist", "Example Artist")
    assert result.code == 0
    paths = [r["path"] for r in server.requests]
    assert not any(path == "/library/all" for path in paths)
    assert any(path == "/library/sections/3/all" for path in paths)


def test_each_field_is_searched_on_its_own_plex_field(server, cli_run):
    """M1: two values, two fields -- not one string handed over as a blob."""
    result = cli_run("search", "--artist", "Example Artist", "--track", "Example Track")
    assert result.code == 0
    query = _search_requests(server)[0]["query"]
    assert query["artist.title"] == "Example Artist"
    assert query["track.title"] == "Example Track"
    # The failure this prevents: both values mashed into one `title` parameter.
    assert "title" not in query


def test_rating_uses_a_plex_operator_and_never_a_python_one(server, cli_run):
    """M3: ``userRating>=8`` on the wire, and no ``__gte`` anywhere near it."""
    result = cli_run("search", "--rated-min", "4")
    assert result.code == 0
    query = _search_requests(server)[0]["query"]
    assert query["track.userRating>"] == "8"
    assert not any("__" in name for name in query)


def test_rating_filter_actually_narrows_the_result(server, cli_run):
    """M3: proven by the rows, not only by the URL.

    The double applies the predicate itself, so a filter that reached the server
    in a spelling it does not define would be refused and a filter applied
    client-side after the limit would return the wrong rows.
    """
    everything = cli_run("search", "--artist", "Example Artist")
    filtered = cli_run("search", "--artist", "Example Artist", "--rated-min", "5")
    assert everything.code == 0 and filtered.code == 0
    assert "Anthology Only" in filtered
    assert "Another Track" in everything
    assert "Another Track" not in filtered


def test_a_python_style_operator_would_be_refused_by_the_server(server):
    """The double is strict enough for the tests above to mean something."""
    from conftest import PlexRefusal

    try:
        server.handle(
            "/library/sections/3/all",
            {"type": "10", "userRating__gte": "8"},
            {"X-Plex-Token": server.token},
        )
    except PlexRefusal as refusal:
        assert refusal.status == 400
    else:  # pragma: no cover - the assertion above is the point of the test
        raise AssertionError("the double accepted a filter Plex does not define")


def test_genre_is_scoped_to_the_artist_and_resolved_to_an_id(server, cli_run):
    """A genre search on tracks goes through ``artist.genre``, by tag id."""
    result = cli_run("search", "--genre", "Jazz")
    assert result.code == 0
    query = _search_requests(server)[0]["query"]
    assert query["artist.genre"] == "11"
    assert "Loud Track" not in result  # a Rock artist's track


def test_the_count_is_exact_and_costs_no_extra_body(server, cli_run):
    """M4: the total comes from a container-size-zero probe, not from the page."""
    result = cli_run("search", "--artist", "Example Artist", "--limit", "2")
    assert result.code == 0
    probes = [
        r for r in _search_requests(server) if r["headers"].get("X-Plex-Container-Size") == "0"
    ]
    assert probes, "no exact-count probe was made"
    # Four tracks by that artist, three distinct titles: the total is the total
    # of the query that was actually run, grouping included.
    assert result.line("count:") == "count: 2 of 3 total"


def test_the_minimum_track_row_carries_the_artist_and_the_album(server, cli_run):
    """M4: a track row without those two is not a music result."""
    result = cli_run("search", "--track", "Example Track", "--no-group")
    assert result.code == 0
    header = result.line("tracks[")
    assert "{key,title,artist,album" in header


def test_a_compilation_reports_the_performer_as_well_as_the_album_artist(server, cli_run):
    """S5: otherwise every track on the disc reports "Various Artists"."""
    result = cli_run("search", "--track", "Guest Track")
    assert result.code == 0
    assert "track_artist" in result.line("tracks[")
    assert "Various Artists" in result
    assert "Example Artist" in result


def test_the_performer_column_is_absent_when_it_would_repeat_the_artist(server, cli_run):
    result = cli_run("search", "--track", "Another Track")
    assert result.code == 0
    assert "track_artist" not in result.line("tracks[")


def test_grouping_collapses_repeated_titles_by_default(server, cli_run):
    """S3: one song on two releases is one row, and the output says so."""
    grouped = cli_run("search", "--track", "Example Track")
    assert grouped.code == 0
    assert grouped.line("grouped:") == "grouped: title"
    assert _search_requests(server)[0]["query"]["group"] == "title"
    assert grouped.line("tracks[").startswith("tracks[1]")


def test_no_group_shows_every_pressing(server, cli_run):
    result = cli_run("search", "--track", "Example Track", "--no-group")
    assert result.code == 0
    assert result.line("tracks[").startswith("tracks[2]")
    assert not result.line("grouped:")
    assert "group" not in _search_requests(server)[0]["query"]


def test_a_server_that_ignores_grouping_is_reported_not_believed(ungrouping_server, cli_run):
    """The claim is checked against the rows, not against the request sent.

    Asking for grouping proves nothing about whether it happened. A server that
    accepts the parameter and ignores it returns the repeats, and reporting
    `grouped: title` over them would be a plain untruth.
    """
    result = cli_run("search", "--track", "Example Track")
    assert result.code == 0
    assert result.line("tracks[").startswith("tracks[2]")
    assert "returned repeated titles" in result.line("grouped:")


def test_an_empty_result_names_the_filters_and_hands_back_the_vocabulary(server, cli_run):
    """S11: a definitive zero, with the command that fixes it."""
    result = cli_run("search", "--genre", "Jazz", "--artist", "Nobody At All")
    assert result.code == 0
    assert "0 tracks matched" in result
    assert "artist.title" in result
    assert "plex-axi genres" in result


def test_search_with_no_field_is_a_usage_error_not_a_whole_library_dump(server, cli_run):
    result = cli_run("search")
    assert result.code == 2
    assert "NO_FILTERS" in result


def test_ratings_print_in_the_same_stars_the_flag_takes(server, cli_run):
    """A rating read out of a result can be passed straight back in."""
    result = cli_run("search", "--track", "Loud Track", "--fields", "key,title,rating")
    assert result.code == 0
    rows = [ln.strip() for ln in result.out.splitlines() if ln.startswith("  2")]
    assert rows == ["211,Loud Track,5"]  # userRating 10.0 is five stars, unquoted


def test_the_query_fallback_searches_one_string_and_says_it_is_the_weak_path(server, cli_run):
    """M1: `--query` exists, and its help does not pretend it is equivalent."""
    result = cli_run("search", "--query", "Example Track")
    assert result.code == 0
    assert result.line("query:") == "query: Example Track"
    assert _search_requests(server)[0]["query"]["title"] == "Example Track"

    from plex_axi.commands.search import COMMAND

    query_flag = next(f for f in COMMAND.subs[0].flags if f.name == "--query")
    assert "WEAK PATH" in query_flag.note
    assert "--artist" in query_flag.note


def test_a_structured_flag_and_the_query_fallback_can_be_combined(server, cli_run):
    result = cli_run("search", "--artist", "Example Artist", "--query", "Another")
    assert result.code == 0
    sent = _search_requests(server)[0]["query"]
    assert sent["artist.title"] == "Example Artist"
    assert sent["title"] == "Another"
    assert result.line("tracks[").startswith("tracks[1]")


def test_a_sort_is_passed_to_the_server_rather_than_applied_here(server, cli_run):
    result = cli_run("search", "--artist", "Example Artist", "--sort", "userRating:desc")
    assert result.code == 0
    assert _search_requests(server)[0]["query"]["sort"] == "track.userRating:desc"


def test_an_unknown_field_is_rejected_with_the_available_ones(server, cli_run):
    result = cli_run("search", "--artist", "Example Artist", "--fields", "key,bpm")
    assert result.code == 2
    assert "unknown field: bpm" in result
    assert "duration" in result


def test_the_limit_is_bounded_at_both_ends(server, cli_run):
    for value in ("0", "-1", "abc", "10000"):
        assert cli_run("search", "--artist", "Example Artist", "--limit", value).code == 2


def test_an_out_of_range_rating_is_rejected_in_stars_not_in_plex_points(server, cli_run):
    result = cli_run("search", "--rated-min", "8")
    assert result.code == 2
    assert "stars from 0 to 5" in result


def test_searching_albums_and_artists_uses_their_own_endpoints(server, cli_run):
    albums = cli_run("search", "--artist", "Example Artist", "--type", "album")
    assert albums.code == 0
    assert albums.line("albums[").startswith("albums[2]{key,title,artist,year}")

    artists = cli_run("search", "--genre", "Jazz", "--type", "artist")
    assert artists.code == 0
    assert "Example Artist" in artists
    assert "Second Example" not in artists
