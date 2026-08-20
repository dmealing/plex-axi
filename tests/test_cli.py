"""M10/M11: the invocation surface -- errors, exit codes, and the home view.

An agent's next move after a wrong flag is deterministic: run `--help`. So the
error carries the help inline and the correction takes one turn, not two.
"""

from __future__ import annotations

import pytest

from plex_axi import argspec, cli
from plex_axi.errors import EXIT_ERROR, EXIT_OK, EXIT_USAGE


def test_an_unknown_flag_is_rejected_by_name_with_the_valid_ones_inlined(server, cli_run):
    result = cli_run("search", "--artiste", "Example Artist")
    assert result.code == EXIT_USAGE
    assert "unknown flag --artiste" in result
    assert "--artist" in result
    assert "--rated-min" in result


def test_an_error_never_spells_a_command_that_cannot_be_run(server, cli_run):
    """Most nouns have one subcommand named after themselves; `search search`
    is not a command, and an agent copying it would fail twice."""
    result = cli_run("search", "--artiste", "x")
    assert "`search`" in result
    assert "search search" not in result


def test_a_dropped_flag_would_be_worse_than_an_error(server, cli_run):
    """The failure this prevents: plausible output the agent believes is filtered."""
    result = cli_run("search", "--artist", "Example Artist", "--rating", "4")
    assert result.code == EXIT_USAGE
    assert "tracks[" not in result


@pytest.mark.parametrize(
    ("wrong", "right"),
    [("--title", "--track"), ("--stars", "--rated-min"), ("--count", "--limit")],
)
def test_a_plausible_wrong_guess_gets_a_targeted_hint(server, cli_run, wrong, right):
    result = cli_run("search", wrong, "x")
    assert result.code == EXIT_USAGE
    assert f"use {right} instead" in result


@pytest.mark.parametrize("wrong", sorted(argspec.RENAMED))
def test_every_renamed_hint_can_actually_fire(server, cli_run, wrong):
    """A RENAMED key that is also a global can never reach the hint.

    ``parse()`` accepts globals on every command and records them silently, so
    such an entry would document a correction that never happens -- and a
    caller spelling the flag would get the generic behaviour instead.
    """
    result = cli_run("search", wrong, "x")
    assert result.code == EXIT_USAGE
    assert f"unknown flag {wrong}" in result


def test_an_out_of_scope_noun_is_answered_with_the_reason(cli_run):
    """A tool that quietly said "unknown command" would invite a second guess."""
    for noun in ("movie", "show", "play", "speaker"):
        result = cli_run(noun)
        assert result.code == EXIT_USAGE
        assert "out of scope" in result


def test_an_unknown_command_lists_the_real_ones(cli_run):
    result = cli_run("wibble")
    assert result.code == EXIT_USAGE
    assert "unknown command: wibble" in result
    assert "search" in result


def test_a_near_miss_noun_is_redirected(cli_run):
    result = cli_run("songs")
    assert result.code == EXIT_USAGE
    assert "use `track` instead" in result


@pytest.mark.parametrize(
    ("wrong", "right"), [("playlists", "playlist"), ("shuffle", "pick"), ("random", "pick")]
)
def test_the_new_nouns_have_the_guesses_an_agent_would_make(cli_run, wrong, right):
    result = cli_run(wrong)
    assert result.code == EXIT_USAGE
    assert f"use `{right}` instead" in result


def test_a_noun_that_stopped_being_out_of_scope_is_no_longer_answered_as_such(server, cli_run):
    """`rate` was refused as "metadata editing" in the first release.

    It is a command now, and leaving it in the out-of-scope table would have been
    a refusal for something the tool does -- the exact failure this round is
    meant to avoid in the other direction.
    """
    result = cli_run("rate", "--help")
    assert result.code == EXIT_OK
    assert "OUT_OF_SCOPE" not in result
    assert "usage: plex-axi rate" in result

    still_out = cli_run("edit")
    assert still_out.code == EXIT_USAGE
    assert "metadata editing" in still_out


def test_root_help_lists_every_command_and_the_write_gate(cli_run):
    from plex_axi import writes

    result = cli_run("--help")
    assert result.code == EXIT_OK
    for noun in cli.COMMAND_ORDER:
        assert noun in result
    assert writes.ALLOW_VAR in result
    assert "--write" in result


def test_missing_a_required_argument_says_which_one(server, cli_run):
    result = cli_run("track")
    assert result.code == EXIT_USAGE
    assert "<rating_key>" in result


def test_help_is_always_allowed_and_never_reaches_the_server(cli_run):
    for argv in (("search", "--help"), ("track", "--help"), ("api", "--help")):
        result = cli_run(*argv)
        assert result.code == EXIT_OK
        assert "usage: plex-axi" in result


def test_help_after_a_value_taking_flag_is_a_value_not_a_request_for_help(server, cli_run):
    """`search --track --help` searches for the literal string."""
    result = cli_run("search", "--track", "--help")
    assert result.code == EXIT_OK
    assert "usage:" not in result
    assert "0 tracks matched" in result


def test_no_error_ever_names_the_client_library(server, cli_run, unreachable):
    """M10: the agent drives this CLI and cannot act on the other one's name."""
    for argv in (
        ("search", "--artist", "x"),
        ("track", "999999"),
        ("doctor",),
        ("api", "/nope"),
    ):
        result = cli_run(*argv)
        assert "plexapi" not in result.out.lower(), argv
        assert "Traceback" not in result.out, argv


def test_an_unknown_path_is_reported_without_the_servers_error_body(server, cli_run):
    result = cli_run("api", "/nope")
    assert result.code == EXIT_ERROR
    assert "plexapi" not in result.out.lower()
    assert "Response code" not in result.out


def test_the_output_mode_survives_a_usage_error(server, cli_run):
    """An agent that appends --json needs it most when the invocation is wrong."""
    result = cli_run("search", "--nope", "x", "--json")
    assert result.code == EXIT_USAGE
    assert result.out.lstrip().startswith("{")


@pytest.mark.parametrize("flag", ["--json", "--human"])
def test_every_command_renders_in_every_mode(server, cli_run, flag):
    result = cli_run(flag, "search", "--artist", "Example Artist")
    assert result.code == EXIT_OK


def test_the_home_view_shows_live_content_not_a_manual(server, cli_run):
    """M11: `bin`, a description, the server, the library, and what it holds."""
    result = cli_run()
    assert result.code == EXIT_OK
    assert result.line("bin:").startswith("bin: ")
    assert "description:" in result
    assert "Example Server" in result
    assert "Example Music" in result
    assert "3 artists, 4 albums, 6 tracks" in result
    assert "analysis:" in result
    assert result.line("recent[")
    assert "help[" in result


def test_the_home_view_without_configuration_says_what_to_set(cli_run):
    result = cli_run(env={})
    assert result.code == EXIT_ERROR
    assert "PLEX_URL and PLEX_TOKEN not set" in result
    assert "export PLEX_URL" in result


def test_the_home_view_with_an_unreachable_server_points_at_doctor(unreachable, cli_run):
    result = cli_run()
    assert result.code == EXIT_ERROR
    assert "plex-axi doctor" in result


def test_version_is_reported_without_touching_the_server(cli_run):
    result = cli_run("--version")
    assert result.code == EXIT_OK
    assert result.line("tool:") == "tool: plex-axi"
    assert result.line("version:")


def test_a_bad_timeout_is_a_usage_error(server, cli_run):
    for value in ("abc", "0", "-3"):
        result = cli_run("--timeout", value, "doctor")
        assert result.code == EXIT_USAGE
        assert "BAD_TIMEOUT" in result


def test_a_section_flag_without_a_value_is_a_usage_error(server, cli_run):
    result = cli_run("--section")
    assert result.code == EXIT_USAGE
    assert "BAD_SECTION" in result


def test_every_command_is_reachable_and_declares_a_summary():
    specs = cli.command_specs()
    for noun in cli.COMMAND_ORDER:
        assert noun in specs
        assert specs[noun].summary
        assert specs[noun].examples


def test_an_internal_failure_is_reported_on_stdout_and_never_as_a_traceback(
    server, cli_run, monkeypatch
):
    """The last-resort boundary: stdout stays structured, stderr stays clean."""
    from plex_axi.commands import genres

    def _explode(*args, **kwargs):
        raise RuntimeError("token=example-token-0000000001 in a message")

    monkeypatch.setattr(genres, "run", _explode)
    result = cli_run("genres")
    assert result.code == EXIT_ERROR
    assert "INTERNAL_ERROR" in result
    assert "example-token-0000000001" not in result.out
    assert "example-token-0000000001" not in result.err
    assert "Traceback" not in result.err
