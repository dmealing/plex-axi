"""S1: `pick`, and the one claim it makes -- that the server did the choosing.

Every assertion here is about the *request*. A picker whose filters ran in
Python would return plausible rows and would be wrong in a way no output could
show: a client-side predicate is applied after the server has already sliced the
result set, so `--limit 10` with a post-filter returns however many of the first
ten survive rather than ten of the matches. So these tests read the query string
the client library built, and the double refuses anything Plex does not define.
"""

from __future__ import annotations

import pytest


def _queries(server, *, path="/library/sections/3/all"):
    """Every query this server was asked, for the search endpoint only."""
    return [r["query"] for r in server.requests if r["path"] == path]


def _search_queries(server):
    """The queries that were searches rather than metadata fetches."""
    return [q for q in _queries(server) if "type" in q and q.get("includeMeta") != "1"]


def test_pick_shuffles_with_the_servers_own_sort(server, cli_run):
    """S1: `sort=random` over the whole match set, not a shuffle of one page."""
    result = cli_run("pick")
    assert result.code == 0
    assert result.line("shuffled:") == "shuffled: server-side (sort=random)"
    assert all(q.get("sort") == "track.random" for q in _search_queries(server))


def test_every_filter_reaches_the_url_as_a_plex_predicate(server, cli_run):
    """S1/M3: the whole point. The double refuses any spelling Plex lacks."""
    result = cli_run(
        "pick",
        "--rated-min",
        "4",
        "--genre",
        "Jazz",
        "--not-played-since",
        "30d",
        "--exclude-live",
    )
    assert result.code == 0
    query = _search_queries(server)[-1]
    # Plex's own operator forms, never the client library's Python lookalikes
    # and never the `>=` that no real music section defines for an integer.
    assert query["track.userRating>>"] == "7"
    assert query["artist.genre"] == "11"  # resolved to the tag id, not the name
    assert query["track.lastViewedAt<<"] == "-30d"
    assert query["album.subformat!"] == "51,52"
    assert not any(name.endswith("__gte") for name in query)


def test_exclude_live_drops_the_pressings_plex_tags_as_such(server, cli_run):
    """The filter is applied by the double's own predicate code, not asserted."""
    everything = cli_run("pick")
    assert "Loud Track" in everything  # on an album tagged Live

    filtered = cli_run("pick", "--exclude-live")
    assert filtered.code == 0
    assert "Loud Track" not in filtered
    assert "Guest Track" not in filtered  # on a compilation
    assert "Example Track" in filtered


def test_not_played_since_includes_a_track_that_was_never_played(server, cli_run):
    """The half every other reading of this flag gets wrong.

    A track Plex has never played carries no `lastViewedAt` at all, and whether
    the server's own "is before" matches that null is invisible from the
    request. So the never-played half is asked for explicitly and server-side --
    `track.viewCount=0`, ORed with the date -- which is why "Guest Track", never
    played, is in this answer whatever this server does with a null.

    B4: it used to ask for `track.unplayed`, a field no real music section
    advertises. This assertion is the one that would have caught it, because the
    double no longer advertises it either.
    """
    result = cli_run("pick", "--not-played-since", "30d")
    assert result.code == 0
    assert "Guest Track" in result
    query = _search_queries(server)[-1]
    assert query["push"] == "1" and query["pop"] == "1" and query["or"] == "1"
    assert query["track.viewCount"] == "0"
    assert "track.unplayed" not in query
    # The OR ran, so there is nothing to report as unapplied and no note about
    # what the date predicate did or did not include.
    assert "unapplied" not in result


def test_an_absolute_date_is_echoed_as_the_date_and_not_prefixed(server, cli_run):
    """The `filters:` echo is a promise about the predicate that ran, and the
    `-` prefix belongs to a relative period -- it is where the client library's
    own normalisation puts it. `-2020-01-01` is not a day anybody asked for."""
    result = cli_run("pick", "--not-played-since", "2020-01-01")
    assert result.code == 0
    echoed = _echoed_period(result)
    assert echoed.endswith(",2020-01-01")
    # The predicate ran, and as a date: the library converts an absolute date to
    # the epoch the server compares against, so the wire carries digits rather
    # than a calendar.
    query = _search_queries(server)[-1]
    assert query["track.lastViewedAt<<"].isdigit()
    assert query["push"] == "1" and query["or"] == "1" and query["track.viewCount"] == "0"

    # The relative form keeps its sign, which is the half the prefix is for.
    assert "-30d" in _echoed_period(cli_run("pick", "--not-played-since", "30d"))


def _echoed_period(result):
    """The `filters:` row a run printed for the last-played predicate."""
    return next(
        line for line in result.out.splitlines() if line.lstrip().startswith("track.lastViewedAt")
    )


def test_the_or_is_a_real_parenthesised_expression_on_the_wire(server, cli_run):
    """A parenthesised OR is structure, and structure can arrive flattened.

    Plex spells it `push=1 A or=1 B pop=1`, and the order is the whole of the
    meaning: the same parameters without the markers would AND everything and
    return a different, plausible set. So the double reads them in order, and
    this reads the order the client library actually sent.
    """
    assert cli_run("pick", "--not-played-since", "30d", "--rated-min", "4").code == 0
    names = [name for name, _ in _last_search(server)["pairs"]]
    markers = [name for name in names if name in ("push", "pop", "or", "and")]
    # `(rating and (last played or never played))`: two groups, the inner one
    # the OR. The `and` between them is what stops the OR swallowing the rating.
    assert markers == ["push", "and", "push", "or", "pop", "pop"]
    inner = names[names.index("push", names.index("and")) + 1 : names.index("pop")]
    assert inner == ["track.lastViewedAt<<", "or", "track.viewCount"]
    assert "track.userRating>>" in names and "track.userRating>>" not in inner
    # `group` is a SQL GROUP BY rather than a predicate, so it belongs outside
    # every parenthesis; inside one it would group half the query.
    assert names.index("group") < names.index("push")


def _last_search(server):
    for record in reversed(server.requests):
        if record["path"] == "/library/sections/3/all" and "type" in record["query"]:
            return record
    raise AssertionError("no search request was made")


def test_a_filter_this_server_cannot_offer_is_reported_not_dropped(spartan_server, cli_run):
    """S1: "say so in the output rather than silently post-filtering"."""
    result = cli_run("pick", "--not-played-since", "30d", "--exclude-live", "--rated-min", "4")
    assert result.code == 0
    assert "unapplied[2]" in result
    assert "--not-played-since" in result
    assert "--exclude-live" in result
    # The one it *can* do still ran, server-side.
    assert any("track.userRating>>" in q for q in _search_queries(spartan_server))


def test_a_server_without_a_random_sort_says_so_rather_than_failing(spartan_server, cli_run):
    """plexapi refuses an unadvertised sort field outright, so this is checked first."""
    result = cli_run("pick")
    assert result.code == 0
    assert "does not advertise a random sort" in result.line("shuffled:")
    assert all("sort" not in q for q in _search_queries(spartan_server))


def test_a_half_available_period_filter_says_which_half_ran(date_only_server, cli_run):
    """A server with `lastViewedAt` but no `viewCount` gets the date predicate
    alone, and a reason that describes the answer rather than asserting one.

    B4: the reason used to end "so tracks it has never played are not
    included", which is false on a real server -- Plex's date comparison matches
    the null. The command produced the right answer and explained it wrongly,
    which is worse than a wrong answer, because a caller who believes it adds a
    compensating query for tracks that are already in the list.
    """
    result = cli_run("pick", "--not-played-since", "30d")
    assert result.code == 0
    assert "does not offer track.viewCount" in result
    # The claim is settled by the rows, and "Guest Track" is never played.
    assert "returned never-played tracks anyway" in result
    assert "are not included" not in result
    # The date predicate ran on its own: no OR, and no play count on the wire.
    query = _search_queries(date_only_server)[-1]
    assert query["track.lastViewedAt<<"] == "-30d"
    assert "track.viewCount" not in query and "push" not in query


@pytest.mark.parametrize("value", ["yesterday", "30", "d30", "-", "2020/01/01"])
def test_a_period_that_is_not_one_is_a_usage_error(server, cli_run, value):
    """Rejected before the client library sees it, so the message names the flag."""
    result = cli_run("pick", "--not-played-since", value)
    assert result.code == 2
    assert "--not-played-since" in result
    assert not server.requests


def test_pick_collapses_repeated_titles_like_search_does(server, cli_run):
    result = cli_run("pick")
    assert result.code == 0
    assert result.line("grouped:") == "grouped: title"
    titles = [line.split(",")[1] for line in result.out.splitlines() if line.startswith("  1")]
    assert len(titles) == len(set(titles))


def test_a_zero_result_is_an_answer_and_exits_zero(server, cli_run):
    result = cli_run("pick", "--genre", "Jazz", "--rated-min", "5", "--exclude-live")
    assert result.code == 0
    assert "0 tracks matched every filter" in result


def test_a_library_that_will_not_describe_its_filters_fails_rather_than_shrugging(
    monkeypatch, server, cli_run
):
    """A server that will not say is not a server that says no.

    "This server does not offer that field" and "it would not say what it offers"
    are different answers. Reporting the second as the first would hand back an
    unfiltered result set under a note saying the filter was merely unavailable.
    """
    import conftest

    def _refuse(*args, **kwargs):
        raise conftest.PlexRefusal(500, "the library is still scanning")

    monkeypatch.setattr(conftest, "_meta_xml", _refuse)
    result = cli_run("pick", "--rated-min", "4")
    assert result.code == 1
    assert "filter metadata" in result
    assert "unapplied" not in result
    assert "plexapi" not in result.out.lower()


def test_pick_is_read_only_and_says_so(server, cli_run):
    help_text = cli_run("pick", "--help")
    assert help_text.code == 0
    assert "read-only" in help_text
    assert cli_run("pick").code == 0
    assert server.writes == []
