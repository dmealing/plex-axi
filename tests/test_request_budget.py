"""How many requests each command may send.

Nothing else in the suite would notice a command going from seven requests to
thirty: every assertion about its output would still pass. The live audit found
exactly that kind of cost by timing -- `playlist show` fetched all ten thousand
items of a playlist to print fifty -- and a timing is the wrong instrument for
it, because a test double answers in microseconds whatever is asked.

So the count is the measure. `support.REQUEST_BUDGET` is the ceiling per
command; the live suite holds the same table against a real server at a
recording proxy, where it was first measured.
"""

from __future__ import annotations

import pytest

from support import READS, REQUEST_BUDGET, budget_for


@pytest.mark.parametrize("argv", READS, ids=lambda argv: " ".join(argv)[:60] or "home")
def test_a_command_stays_inside_its_request_budget(server, cli_run, argv):
    result = cli_run(*argv)
    assert result.code == 0, result.out
    empty = "0 of 0 total" in result.out
    sent = len(server.requests)
    assert sent <= budget_for(argv, empty=empty), [r["path"] for r in server.requests]


def test_every_read_is_a_get(server, cli_run):
    for argv in READS:
        cli_run(*argv)
    assert server.writes == []
    assert {record["method"] for record in server.requests} == {"GET"}


def test_a_long_playlist_costs_what_a_short_one_does(server, cli_run):
    """The count behind `playlist show` must not grow with the playlist."""
    for key in range(2000, 2400):
        server.tables.add("track", key, f"Filler Example {key}", album=110)
    server.playlists[0]["items"] = [
        {"key": key, "item_id": 5000 + key} for key in range(2000, 2400)
    ]
    result = cli_run("playlist", "show", "501", "--limit", "5")
    assert result.line("count:") == "count: 5 of 400 items"
    assert len(server.requests) <= REQUEST_BUDGET["playlist"]
    sizes = {
        record["headers"].get("X-Plex-Container-Size")
        for record in server.requests
        if record["path"].endswith("/items")
    }
    assert sizes == {"0", "5"}


def test_the_token_travels_in_a_header_and_never_in_a_url(server, cli_run):
    for argv in READS:
        cli_run(*argv)
    for record in server.requests:
        assert not any("token" in key.lower() for key in record["query"]), record["path"]
        assert record["headers"].get("X-Plex-Token")


def test_every_budget_row_is_exercised():
    """A row nothing reads is a number nobody checks."""
    used = {"(home)" if not argv else argv[0] for argv in READS}
    used |= {"search:tag", "search:empty"}
    assert used == set(REQUEST_BUDGET)
