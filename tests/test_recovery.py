"""The refusals that moved: their help lines are rendered now, and unchanged.

:mod:`axi_toolkit.plex.ids` and :mod:`axi_toolkit.plex.filters` carry recovery as
**data**. A line that used to be written out at the point of the raise --
``"Run `plex-axi search --track '<title>'` to get this server's rating key"`` --
is now :func:`~axi_toolkit.errors.run` intent with no tool name in it at all, and
``plex-axi`` is put in front of the words at :func:`plex_axi.errors.help_lines_for`.

That is a rewrite of the one thing a caller reads when it has got something
wrong, so this file pins the result rather than trusting it. Every line here was
captured from the tool before the move and is asserted byte for byte, including
the leading two spaces the ``help[N]:`` block indents them with.

**Two traps, and both are asserted rather than reasoned about.**

*The catch clause.* A refusal from those modules is an
:class:`axi_toolkit.errors.AxiError`, not this package's subclass, so an
``except AxiError`` that named only the subclass would drop it -- into
``INTERNAL_ERROR`` at the top of :func:`plex_axi.cli.main`, or into a
plexapi-shaped translation at either of the two pass-through guards inside
``run_search`` and ``pick``. All three are exercised here, and each one fails
loudly rather than subtly: the exit code, the code and the lines all change.

*The words after the name.* :func:`~axi_toolkit.plex.ids.validate_rating_key`
takes ``command`` -- the caller's own words -- and each command passes its own.
A single wrong tuple would send somebody to a command they did not type, which
no test that only checked the error code would notice.
"""

from __future__ import annotations

import pytest

CATALOGUE_GUID = "plex://track/a1b2c3d4e5f60718293a0100"


def _document(result) -> tuple:
    """The error line, the code, and the help lines exactly as printed."""
    error = code = ""
    help_lines = []
    inside = False
    for line in result.out.splitlines():
        if line.startswith("error: "):
            error = line[len("error: ") :]
        elif line.startswith("code: "):
            code = line[len("code: ") :]
        elif line.startswith("help["):
            inside = True
        elif inside:
            if not line.startswith("  "):
                break
            help_lines.append(line)
    return error, code, help_lines


# ------------------------------------------------------- the `plex://` forms


@pytest.mark.parametrize(
    ("argv", "rendered"),
    [
        (("track", "<key>"), "plex-axi track <rating_key>"),
        (("album", "<key>"), "plex-axi album <rating_key>"),
        (("artist", "<key>"), "plex-axi artist <rating_key>"),
        (("similar", "<key>"), "plex-axi similar <rating_key>"),
        (("rate", "<key>"), "plex-axi rate <rating_key>"),
    ],
)
def test_each_command_names_itself_in_the_refusal_it_raises(
    server, cli_run, writable_env, argv, rendered
):
    """The words are the command's own; the name in front of them is rendered."""
    result = cli_run(*[a.replace("<key>", "notanumber") for a in argv], env=writable_env)
    assert result.code == 2
    error, code, help_lines = _document(result)
    assert error == "\"a rating key is a number, got 'notanumber'\""
    assert code == "BAD_RATING_KEY"
    assert help_lines == [
        f"  Run `{rendered}`",
        "  Run `plex-axi search --artist '<name>'` to find one",
    ]


def test_a_catalogue_guid_is_refused_with_the_search_that_finds_the_key(server, cli_run):
    result = cli_run("track", CATALOGUE_GUID)
    assert result.code == 2
    error, code, help_lines = _document(result)
    assert error == f"\"'{CATALOGUE_GUID}' is a guid, not a rating key\""
    assert code == "GUID_NOT_RATING_KEY"
    assert help_lines == [
        "  A guid names an item in Plex's catalogue; a rating key names a row on this server",
        "  Run `plex-axi search --track '<title>'` to get this server's rating key",
    ]


def test_a_local_guid_is_refused_with_the_answer_already_inside_the_argument(server, cli_run):
    """Form six: the rating key with a scheme in front of it, handed straight back."""
    result = cli_run("album", "local://211")
    assert result.code == 2
    _error, code, help_lines = _document(result)
    assert code == "GUID_NOT_RATING_KEY"
    assert help_lines == [
        "  Plex gives an item it never matched a `local://` guid, which is this server's "
        "rating key with a scheme in front of it",
        "  Run `plex-axi album 211`",
    ]


def test_a_media_id_is_refused_with_the_field_that_carries_the_number(server, cli_run):
    result = cli_run("similar", "plex://abc/311")
    assert result.code == 2
    _error, code, help_lines = _document(result)
    assert code == "MEDIA_ID_NOT_RATING_KEY"
    assert help_lines == [
        "  Pass the number after the last slash, which is what `rating_key:` reports",
        "  Run `plex-axi similar <rating_key>`",
    ]


def test_a_playlist_key_refusal_carries_the_subcommand_and_the_title(server, cli_run, writable_env):
    """The longest command a recovery here names, and the one most easily lost.

    Three words plus a quoted title, all of them the caller's, and none of them
    stored beside the recovery -- so a wrong tuple would offer a command nobody
    typed while still reporting the right code.
    """
    result = cli_run(
        "playlist", "add", "Example Playlist", "--key", "local://311", env=writable_env
    )
    assert result.code == 2
    _error, code, help_lines = _document(result)
    assert code == "GUID_NOT_RATING_KEY"
    assert help_lines[-1] == "  Run `plex-axi playlist add 'Example Playlist' 311`"


# --------------------------------------------------------- the filter language


def test_a_rating_that_is_not_a_number_offers_the_same_flag_back(server, cli_run):
    result = cli_run("search", "--rated-min", "x")
    assert result.code == 2
    error, code, help_lines = _document(result)
    assert error == "\"--rated-min needs a rating in stars from 0 to 5, got 'x'\""
    assert code == "BAD_RATING"
    assert help_lines == ["  Run the command again with `--rated-min 4`"]


def test_a_rating_off_the_scale_says_the_scale_is_the_one_ratings_print_in(server, cli_run):
    result = cli_run("search", "--rated-min", "6")
    assert result.code == 2
    error, code, help_lines = _document(result)
    assert error == '"--rated-min is in stars from 0 to 5, got 6"'
    assert code == "BAD_RATING"
    assert help_lines == [
        "  Run the command again with `--rated-min 4`",
        "  Ratings print in stars too, so a rating read from a result can be passed back",
    ]


def test_a_malformed_period_lists_the_units_that_do_work(server, cli_run):
    result = cli_run("pick", "--not-played-since", "x")
    assert result.code == 2
    error, code, help_lines = _document(result)
    assert error == (
        '"--not-played-since needs a period like 30d, 6mon or 2y, '
        "or a date as YYYY-MM-DD, got 'x'\""
    )
    assert code == "BAD_PERIOD"
    assert help_lines == [
        "  Run the command again with `--not-played-since 30d`",
        "  units: s seconds, m minutes, h hours, d days, w weeks, mon months, y years",
    ]


def test_an_unknown_sort_direction_keeps_the_field_the_caller_typed(server, cli_run):
    result = cli_run("search", "--artist", "Example Artist", "--sort", "addedAt:up")
    assert result.code == 2
    error, code, help_lines = _document(result)
    assert error == "\"--sort direction must be asc or desc, got 'up'\""
    assert code == "BAD_SORT"
    assert help_lines == [
        "  Run the command again with `--sort addedAt:desc`",
        "  The field half is checked against this server; only the direction is fixed",
    ]


def test_a_sort_with_no_field_says_which_half_is_missing(server, cli_run):
    result = cli_run("search", "--artist", "Example Artist", "--sort", ":desc")
    assert result.code == 2
    _error, code, help_lines = _document(result)
    assert code == "BAD_SORT"
    assert help_lines == [
        "  Run the command again with `--sort addedAt:desc`",
        "  Run the same command with a bad field name to see the sorts this server offers",
    ]


# --------------------------------------------------- the guards that could eat it


def test_a_refusal_from_the_shared_package_is_never_reported_as_an_internal_error(server, cli_run):
    """The top-level clause in `cli.main`, which is the one that fails loudest.

    An `except` naming only this package's subclass would let the refusal reach
    the last-resort handler, which prints `INTERNAL_ERROR` and blames the tool
    for what is a typo in an argument.
    """
    result = cli_run("track", "notanumber")
    assert result.code == 2
    assert "INTERNAL_ERROR" not in result
    assert not server.requests, "a static refusal must not reach the server"


def test_picks_metadata_guard_passes_a_refusal_through_rather_than_rewrapping_it(server, cli_run):
    """`pick` wraps its whole filter build so a metadata read failure is explained.

    `parse_stars` raises inside that block, so the pass-through arm has to
    recognise a refusal raised by the shared package -- or a bad rating arrives
    as "this server would not say which filters it offers".
    """
    result = cli_run("pick", "--rated-min", "x")
    assert result.code == 2
    _error, code, _help = _document(result)
    assert code == "BAD_RATING"


def test_the_search_guard_passes_a_refusal_through_rather_than_translating_it(
    server, cli_run, monkeypatch
):
    """The same arm in `run_search`, and the only refusal that can reach it.

    ``assert_server_side`` fires on whatever plexapi did not recognise, which no
    caller can produce -- it is a bug in this tool -- so the leftover is injected
    here. What is being asserted is the arm, not the refusal: if it stopped
    recognising a shared-package error the message would become a plexapi
    translation and the code would become `UNKNOWN_FILTER_FIELD`, which reads as
    an answer about the server rather than a bug report about the tool.
    """
    from plexapi.library import LibrarySection

    original = LibrarySection._buildSearchKey

    def _leftover(self, **kwargs):
        key, _ = original(self, **kwargs)
        return key, {"userRating__gte": 8}

    monkeypatch.setattr(LibrarySection, "_buildSearchKey", _leftover)

    result = cli_run("search", "--artist", "Example Artist")
    assert result.code == 1
    error, code, help_lines = _document(result)
    assert code == "CLIENT_SIDE_FILTER"
    assert error == "refusing to filter on userRating__gte after the server has already answered"
    assert help_lines == [
        "  This is a bug in plex-axi: every filter must be a server-side Plex predicate",
        "  Report it at https://github.com/dmealing/plex-axi/issues",
    ]
