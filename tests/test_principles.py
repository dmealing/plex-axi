"""The AXI principles this tool once met only in part, each pinned to its behaviour.

An audit against the standard found six partial principles; each test here
names the principle it holds the tool to, so a regression reads as the
principle it breaks rather than as a changed string.
"""

from __future__ import annotations

import re

import pytest

from plex_axi import cli
from plex_axi.commands import api

#: Every default list surface, and the header its rows render under.
LIST_SURFACES = [
    (("search", "--artist", "Example Artist", "--no-group"), "tracks["),
    (("search", "--artist", "Example Artist", "--type", "album"), "albums["),
    (("search", "--artist", "Example", "--type", "artist"), "artists["),
    (("pick", "--rated-min", "3"), "tracks["),
    (("recent",), "albums["),
    (("recent", "--type", "track"), "tracks["),
    (("recent", "--type", "artist"), "artists["),
    (("similar", "111"), "tracks["),
    (("playlist", "list"), "playlists["),
    (("playlist", "show", "Example Playlist"), "tracks["),
    (("sessions",), "music["),
]


def _columns(header: str) -> list:
    return re.search(r"\{([^}]*)\}", header).group(1).split(",")


# ------------------------------------------------------- AXI 2: small defaults


@pytest.mark.parametrize(
    "argv,header", LIST_SURFACES, ids=lambda v: " ".join(v) if isinstance(v, tuple) else None
)
def test_every_default_list_schema_is_four_columns_at_most(server, cli_run, argv, header):
    """AXI 2: three or four fields per list item by default, not five or more.

    The one exception is data-driven and not part of the default: a compilation
    row adds ``track_artist`` beside ``artist``, because there the fourth column
    alone says "Various Artists" for every track. The fixture's only such row is
    on a compilation, so the bar is measured without it.
    """
    result = cli_run(*argv)
    assert result.code == 0
    columns = [name for name in _columns(result.line(header)) if name != "track_artist"]
    assert len(columns) <= 4, f"{' '.join(argv)} prints {columns}"
    assert "media_id" in columns


@pytest.mark.parametrize(
    "argv,fields",
    [
        (("sessions",), "key,artist,album,state,rating"),
        (("playlist", "list"), "key,title,items,updated"),
        (("similar", "111"), "distance,key,artist"),
    ],
)
def test_the_columns_left_out_of_a_default_are_one_fields_flag_away(server, cli_run, argv, fields):
    """AXI 2: offer `--fields` so a dropped column is still reachable."""
    result = cli_run(*argv, "--fields", fields)
    assert result.code == 0
    assert any(line.endswith("{" + fields + "}:") for line in result.out.splitlines())


def test_an_unknown_session_field_is_refused_with_the_real_ones(server, cli_run):
    result = cli_run("sessions", "--fields", "key,player")
    assert result.code == 2
    assert "unknown field: player" in result
    assert "device" in result


def test_the_session_state_column_became_a_summary_line(server, cli_run):
    """AXI 4: whether anything is actually playing, counted rather than columned."""
    result = cli_run("sessions")
    assert result.line("states:") == "states: 1 playing"


def test_the_declared_item_count_note_appears_only_beside_the_column(server, cli_run):
    assert "declares" not in cli_run("playlist", "list").out
    assert "declares" in cli_run("playlist", "list", "--fields", "key,items").out


# ------------------------------------------------------------ AXI 3: truncation


def test_api_bounds_a_long_child_list_by_count_and_says_how_many(server, cli_run, monkeypatch):
    """AXI 3: `api` was bounded only by depth, so a one-level-deep listing of a
    whole library printed every item in it."""
    monkeypatch.setattr(api, "MAX_CHILDREN", 2)
    result = cli_run("api", "/library/sections/3/all")
    assert result.code == 0
    assert "Directory[2]:" in result
    assert result.line("_Directory:") == "_Directory: 2 of 3 shown"
    assert "Run `plex-axi api /library/sections/3/all --full`" in result


def test_api_previews_a_long_value_with_its_full_length(server, cli_run, monkeypatch):
    monkeypatch.setattr(api, "PREVIEW_CHARS", 10)
    result = cli_run("api", "/library/sections/3/all")
    assert result.code == 0
    summary = result.line("summary:")
    whole = "An invented artist used only by this test suite."
    assert summary == f'summary: "{whole[:10]}... (truncated, {len(whole)} chars total)"'
    assert "--full" in result


def test_api_full_lifts_both_bounds(server, cli_run, monkeypatch):
    monkeypatch.setattr(api, "MAX_CHILDREN", 2)
    monkeypatch.setattr(api, "PREVIEW_CHARS", 10)
    result = cli_run("api", "/library/sections/3/all", "--full")
    assert result.code == 0
    assert "Directory[3]:" in result
    assert "truncated" not in result.out
    assert "_Directory" not in result.out
    assert "--full" not in result.out


def test_api_offers_an_escape_hatch_only_when_it_was_needed(server, cli_run):
    """AXI 3: suggest `--full` only when content was actually truncated."""
    result = cli_run("api", "/library/sections")
    assert result.code == 0
    assert "--full" not in result.out
    assert "--depth" not in result.out


def test_api_carries_the_query_into_the_suggested_follow_up(server, cli_run, monkeypatch):
    monkeypatch.setattr(api, "MAX_CHILDREN", 1)
    result = cli_run("api", "/library/sections/3/all", "--query", "type=8")
    assert "Run `plex-axi api /library/sections/3/all --query type=8 --full`" in result


# --------------------------------------------------- AXI 8: content first


def test_the_home_view_never_exits_non_zero_for_the_state_it_reports(unreachable, cli_run):
    """AXI 8: bare `plex-axi` is content with next steps, configured or not."""
    assert cli_run().code == 0
    assert cli_run(env={}).code == 0


def test_the_unreachable_home_view_suggests_each_next_step_once(unreachable, cli_run):
    lines = [line.strip() for line in cli_run().out.splitlines() if line.startswith("  Run")]
    assert len(lines) == len(set(lines))


# ---------------------------------------------- AXI 9: contextual disclosure


@pytest.mark.parametrize("libtype", ["track", "album", "artist"])
def test_recent_carries_the_type_into_its_follow_up(server, cli_run, libtype):
    """AXI 9: `recent --type track` once suggested `recent --limit 100`, which
    answers with albums."""
    result = cli_run("recent", "--type", libtype)
    assert f"Run `plex-axi recent --type {libtype} --limit 100` to look further back" in result


def test_recent_carries_named_fields_into_its_follow_up(server, cli_run):
    result = cli_run("recent", "--type", "track", "--fields", "key,added")
    assert "Run `plex-axi recent --type track --fields key,added --limit 100`" in result
    assert "for each row's date" not in result.out


def test_a_cut_short_playlist_listing_says_how_to_see_the_rest(server, cli_run):
    """AXI 9: reveal truncated lists."""
    result = cli_run("playlist", "list", "--limit", "1")
    assert "Run `plex-axi playlist list --limit 2` for all 2 playlists" in result
    assert "for all" not in cli_run("playlist", "list").out


def test_a_cut_short_playlist_shows_how_to_see_the_rest(server, cli_run):
    result = cli_run("playlist", "show", "Example Playlist", "--limit", "1")
    assert "Run `plex-axi playlist show 501 --limit 2` for all 2 items" in result


def test_a_reveal_hint_never_exceeds_the_commands_own_limit():
    from plex_axi.commands._common import more_hint

    assert more_hint("plex-axi x", 900, 500, "tracks") == (
        "Run `plex-axi x --limit 500` for the first 500 of 900 tracks"
    )


# ------------------------------------------------- AXI 10: the version probe


def test_the_version_probe_needs_no_command_table(monkeypatch, capsys):
    """The bare version is answered before any command module is consulted."""
    from plex_axi import __version__

    monkeypatch.setattr(cli, "modules", lambda environ=None: pytest.fail("loaded the table"))
    assert cli.main(["--version"], environ={}) == 0
    assert capsys.readouterr().out == f"{__version__}\n"


def test_recents_look_further_back_hint_stays_within_its_own_limit(server, cli_run):
    """A suggestion the command would refuse is not a next step."""
    result = cli_run("recent", "--limit", "200")
    assert "Run `plex-axi recent --type album --limit 500` to look further back" in result
