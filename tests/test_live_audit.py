"""One regression per finding from a live audit against a real server.

The tool was built entirely against the double in ``conftest.py``, and this file
is where the difference between that and a Plex Media Server is written down as
assertions. Every test here failed before its fix, and most of them could only
be written *after* the double was corrected -- B1, B3 and B4 were invisible
locally precisely because the double had invented the capability the tool was
built on.

The topical files carry the ordinary versions of these claims. This one exists
so the list stays checkable: fifteen findings, fifteen names, each naming the
symptom a real server produced rather than the implementation that fixed it.
B1 through B14 are the first audit's fourteen bugs; B15 is a design gap a later
one found, which is why it reads as an absence rather than a wrong answer.
"""

from __future__ import annotations

import ast
import itertools
import re
from pathlib import Path

import pytest

from conftest import MACHINE_ID, SECTION_FIELDS, FakePlex, FakeSession
from plex_axi import commands

# ------------------------------------------------------------------- B1: rated-min


def test_b1_rated_min_uses_an_operator_this_server_actually_offers(server, cli_run):
    """B1: `--rated-min` was dead at every value, 0 through 5.

    Real Plex advertises ``=``, ``!=``, ``>>=`` and ``<<=`` for an integer and
    nothing else, and both inequalities are strict. The tool sent ``userRating>``,
    which plexapi normalises to a ``>=`` the server does not define, so every
    single invocation failed with ``UNKNOWN_OPERATOR`` -- including the one the
    error's own help text recommended.
    """
    for value in ("1", "2", "3", "4", "5", "4.5", "2.5"):
        result = cli_run("search", "--rated-min", value, "--limit", "3")
        assert result.code == 0, (value, result.out)
        assert "UNKNOWN_OPERATOR" not in result


def test_b1_at_least_n_stars_is_strictly_greater_than_the_star_below(server, cli_run):
    """The arithmetic, checked on the wire: at least N stars is ``> 2N - 1``."""
    for stars, threshold in ((1, "1"), (2, "3"), (3, "5"), (4, "7"), (5, "9"), (4.5, "8")):
        server.requests.clear()
        assert cli_run("search", "--rated-min", str(stars), "--limit", "1").code == 0
        query = _last_search(server)["query"]
        assert query["track.userRating>>"] == threshold, stars


def test_b1_the_rows_returned_are_the_ones_at_that_rating_or_better(server, cli_run):
    """Proved by the rows, because the double applies the predicate itself."""
    # Ratings in the fixture: 8 (4 stars), 6 (3), 10 (5), and two unrated.
    four = cli_run("search", "--artist", "Example Artist", "--rated-min", "4", "--no-group")
    assert four.code == 0
    assert "Example Track" in four  # userRating 8
    assert "Anthology Only" in four  # userRating 10
    assert "Another Track" not in four  # userRating 6 -- three stars

    five = cli_run("search", "--artist", "Example Artist", "--rated-min", "5", "--no-group")
    assert five.code == 0
    assert "Anthology Only" in five
    assert "Example Track" not in five


def test_b1_half_a_star_is_the_boundary_between_rated_and_unrated(server, cli_run):
    """`--rated-min 0.5` is ``userRating > 0``: everything with any rating."""
    server.requests.clear()
    assert cli_run("search", "--rated-min", "0.5", "--limit", "5").code == 0
    assert _last_search(server)["query"]["track.userRating>>"] == "0"


def test_b1_rated_min_zero_filters_nothing_and_says_so(server, cli_run):
    """The decision B1 forced, made explicitly rather than by arithmetic.

    Zero is the bottom of the scale, so it constrains nothing. Building
    ``userRating > -1`` instead would quietly mean "rated at all" and withhold
    every unrated item -- on a real library the overwhelming majority of it --
    behind a flag that reads as "no minimum". "Rated at all" already has an exact
    spelling: `--rated-min 0.5`.
    """
    result = cli_run("search", "--rated-min", "0", "--track", "Example Track")
    assert result.code == 0
    assert "userRating" not in result
    assert "no rating filter was applied" in result
    assert "--rated-min 0.5" in result
    assert not any("userRating" in name for name in _last_search(server)["query"])

    # Alone it narrows nothing at all, and the refusal says why this flag did
    # not count rather than claiming no flag was passed.
    bare = cli_run("search", "--rated-min", "0")
    assert bare.code == 2
    assert "NO_FILTERS" in bare
    assert "bottom of the scale" in bare


def test_b1_pick_takes_the_same_predicate_as_search(server, cli_run):
    """`pick` builds its own filters, so it had its own copy of the bug."""
    server.requests.clear()
    assert cli_run("pick", "--rated-min", "4").code == 0
    query = _last_search(server)["query"]
    assert query["track.userRating>>"] == "7"
    assert "track.userRating>" not in query


def test_b1_the_double_now_refuses_the_operator_the_real_server_refuses(server):
    """The fix is only as real as the double that drove it.

    This is the assertion that makes every test above mean something: the
    invented ``>=`` is gone from the integer operator table, so a tool that went
    back to it would fail here rather than passing locally and dying in the field.
    """
    integer_ops = {key for key, _title in _int_ops()}
    assert integer_ops == {"=", "!=", ">>=", "<<="}
    assert ">=" not in integer_ops and "<=" not in integer_ops


def _int_ops():
    from conftest import _INT_OPS

    return _INT_OPS


# --------------------------------------------------------------- B2: the handoff id


#: Every surface that prints rows, and the header its rows arrive under. Named
#: rather than inlined so that the sweep below can be checked for completeness
#: by :func:`test_b2_the_sweep_reaches_every_module_that_builds_a_row`.
ROW_BEARING_SURFACES = [
    (("search", "--track", "Example Track", "--no-group"), "tracks["),
    (("pick",), "tracks["),
    (("recent",), "albums["),
    (("recent", "--type", "track"), "tracks["),
    (("recent", "--type", "artist"), "artists["),
    (("similar", "111"), "tracks["),
    (("playlist", "show", "Example Playlist"), "tracks["),
    (("sessions",), "music["),
    (("search", "--artist", "Example Artist", "--type", "album"), "albums["),
    (("search", "--genre", "Jazz", "--type", "artist"), "artists["),
]


@pytest.mark.parametrize(("argv", "header"), ROW_BEARING_SURFACES)
def test_b2_every_row_bearing_surface_carries_the_media_id(server, cli_run, argv, header):
    """B2: the tool ends at a labelled id, and six surfaces printed `key` only.

    A list view without one costs the caller a detail request per row to finish
    the job the command was for.
    """
    result = cli_run(*argv)
    assert result.code == 0, argv
    assert "media_id" in result.line(header), argv
    assert f"plex://{MACHINE_ID}/" in result.out, argv


def _row_building_modules() -> set:
    """Every command module that turns a server object into a row.

    Either it calls :func:`plex_axi.music.rows_for` or it defines a builder of
    its own. Both are read off the parse tree rather than the file's text, so a
    module that merely *names* one in its prose is not swept for it.

    The bound, stated rather than left to be discovered: a module that inlines
    its rows in a comprehension without naming a builder is not found this way.
    ``home`` does exactly that, and it is not a row-bearing surface in this
    sweep's sense either -- it prints a summary, not a `{...}` header a caller
    reads columns off. Both conventions the codebase uses for a *reusable* row
    builder are covered, which is what a new noun would reach for.
    """
    found = set()
    for path in Path(commands.__file__).parent.glob("[!_]*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                (isinstance(node, ast.Name) and node.id == "rows_for")
                or (isinstance(node, ast.Attribute) and node.attr == "rows_for")
                or (isinstance(node, ast.FunctionDef) and node.name.endswith("_row"))
            ):
                found.add(path.stem)
                break
    return found


def test_b2_the_sweep_reaches_every_module_that_builds_a_row():
    """The one thing the sweep above cannot say about itself.

    A list of surfaces written out one by one is only as complete as the last
    person to remember it. A new row-building command joins the codebase, never
    reaches ``ROW_BEARING_SURFACES``, and is then untested *and silent about
    it* -- which from here reads exactly like coverage. So the modules that
    build rows are discovered rather than recalled, and a surface that is not
    swept fails this rather than nothing.
    """
    swept = {argv[0] for argv, _header in ROW_BEARING_SURFACES}
    missing = _row_building_modules() - swept
    assert not missing, f"builds rows but is not swept above: {sorted(missing)}"


def test_b2_the_media_id_in_a_row_is_the_one_the_detail_view_prints(server, cli_run):
    """The same identifier, not merely one of the same shape."""
    listed = cli_run("search", "--track", "Guest Track")
    detail = cli_run("track", "311")
    assert listed.code == 0 and detail.code == 0
    assert f"plex://{MACHINE_ID}/311" in listed.out
    assert detail.line("media_id:").endswith(f'"plex://{MACHINE_ID}/311"')


def test_b2_a_playlist_listing_carries_an_identifier_that_can_be_used(server, cli_run):
    """B2: `playlist list` printed no identifier of any kind.

    A playlist could only be named by its exact title, and real titles carry
    emoji and typographic apostrophes -- so the listing handed back the one
    thing that is awkward to type and nothing else.
    """
    listed = cli_run("playlist", "list")
    assert listed.code == 0
    # Two, not three: the video playlist on this server stays invisible.
    assert listed.line("playlists[").startswith(
        "playlists[2]{key,media_id,title,items,smart,updated}"
    )

    key = re.search(r"^  (\d+),", listed.out, re.M).group(1)
    shown = cli_run("playlist", "show", key)
    assert shown.code == 0
    assert shown.line("playlist:") == "playlist: Example Playlist"


def test_b2_a_playlist_has_a_handoff_id_of_its_own(server, cli_run):
    """B2, the case that started it: playing a *whole playlist*.

    A playlist's rating key lives in the same `/library/metadata` namespace as a
    track's -- fetching it returns the playlist -- which is exactly what a
    consumer does when it parses `plex://<machineIdentifier>/<ratingKey>`. So a
    playlist has a media id like anything else, and printing only `key` left the
    caller to assemble that string by hand: the hand-assembly the six-forms rule
    exists to prevent, in the one case where the container is obviously what is
    wanted rather than a row of it.
    """
    listed = cli_run("playlist", "list")
    assert listed.code == 0
    assert f'"plex://{MACHINE_ID}/501"' in listed.out

    shown = cli_run("playlist", "show", "Example Playlist")
    assert shown.code == 0
    assert shown.line("key:") == "key: 501"
    assert shown.line("media_id:") == f'media_id: "plex://{MACHINE_ID}/501"'
    # And the track rows still carry their own, for the case where one song is
    # what was meant.
    assert f'"plex://{MACHINE_ID}/111"' in shown.out


def test_b2_a_title_that_is_all_digits_still_resolves_by_title(server, cli_run):
    """The key is tried first, so a playlist named "2024" must still be findable."""
    server.playlists.append(
        {"id": 599, "title": "2024", "type": "audio", "smart": 0, "items": [], "updatedAt": 1}
    )
    result = cli_run("playlist", "show", "2024")
    assert result.code == 0
    assert result.line("playlist:") == 'playlist: "2024"'
    assert result.line("key:") == "key: 599"


def test_b2_the_guid_stays_out_of_the_default_row(server, cli_run):
    """The other half of the decision: `media_id` is actionable, `guid` is not.

    A `guid` is the durable identifier a human writes down, and it is not even
    durable for a locally-matched item (B5) -- so doubling every row's width for
    it is a poor trade. It stays reachable by name and in the detail views.
    """
    default = cli_run("search", "--track", "Example Track")
    assert default.code == 0
    assert "guid" not in default.line("tracks[")

    asked = cli_run("search", "--track", "Example Track", "--fields", "key,guid")
    assert asked.code == 0
    assert asked.line("tracks[").startswith("tracks[1]{key,guid}")


# ------------------------------------------------------------- B3: the session device


def test_b3_a_session_names_the_player(server, cli_run):
    """B3: `device` was empty on every real session.

    The double invented a `<Player title=...>`; a real one carries `device`,
    `product` and `platform` and no `title` at all. So the one column that says
    *where the music is playing* read an attribute that is never there.
    """
    result = cli_run("sessions")
    assert result.code == 0
    assert "Example Speaker" in result
    assert result.line("music[").startswith("music[1]{key,media_id,title,artist,album,device,")


# ---------------------------------------------------------------- B4: the false note


def test_b4_pick_does_not_claim_never_played_tracks_are_missing(server, cli_run):
    """B4: the note said never-played tracks "are not included". They were.

    A tool that reports what it did must not report something it did not do --
    and this was worse than a wrong answer, because the answer was right and a
    caller who believed the explanation would add a compensating query for
    tracks already in the list.
    """
    result = cli_run("pick", "--not-played-since", "30d")
    assert result.code == 0
    assert "are not included" not in result
    # "Guest Track" has never been played and is in the answer.
    assert "Guest Track" in result


def test_b4_the_never_played_half_is_a_field_this_server_advertises(server, cli_run):
    """`track.unplayed` is not a field any real music section offers.

    It was in the double's table and nowhere else, so `pick` degraded on every
    real server and took the good path in every test. `track.viewCount` is the
    real spelling, and the OR is still a real parenthesised expression.
    """
    advertised = {key for key, _title, _type in SECTION_FIELDS["track"]}
    assert "track.unplayed" not in advertised
    assert "track.viewCount" in advertised

    server.requests.clear()
    assert cli_run("pick", "--not-played-since", "30d").code == 0
    query = _last_search(server)["query"]
    assert query["track.viewCount"] == "0"
    assert query["push"] == "1" and query["or"] == "1" and query["pop"] == "1"


def test_b4_a_degraded_period_describes_the_answer_instead_of_asserting_one(
    date_only_server, cli_run
):
    """Where the never-played half cannot be asked for, the rows settle it.

    Whether Plex's own "is before" matches a null `lastViewedAt` is the server's
    business and is invisible from the request -- so the reason is read off the
    result, the way `music._verify_grouping` reads grouping off the rows.
    """
    result = cli_run("pick", "--not-played-since", "30d")
    assert result.code == 0
    assert "does not offer track.viewCount" in result
    assert "returned never-played tracks anyway" in result


# ------------------------------------------------------------ B5: the local:// guid


def test_b5_a_local_guid_gets_a_note_that_is_true_of_it(server, cli_run):
    """B5: form six, and about one track in seven carries it.

    `local://<ratingKey>` is the rating key with a scheme in front of it, so the
    printed promise -- "guid is the identifier that survives" -- is false for
    exactly those items, and it is printed where somebody is about to paste one
    into a configuration file.
    """
    local = cli_run("track", "122")
    assert local.code == 0
    assert local.line("guid:") == 'guid: "local://122"'
    assert "guid is the identifier that survives" not in local
    assert "so it changes with it" in local
    assert "match this one by artist and title" in local


def test_b5_an_ordinary_guid_keeps_the_ordinary_note(server, cli_run):
    """The note is conditional, not replaced: most items are still durable."""
    catalogue = cli_run("track", "111")
    assert catalogue.code == 0
    assert re.fullmatch(r'guid: "plex://track/[0-9a-f]{24}"', catalogue.line("guid:"))
    assert "guid is the identifier that survives" in catalogue


def test_b5_the_handoff_block_is_still_exactly_four_fields(server, cli_run):
    """Only the note's *text* is conditional. The shape is not."""
    for key in ("111", "122"):
        result = cli_run("track", key)
        assert result.code == 0
        lines = result.out.splitlines()
        block = [
            line.strip().partition(":")[0]
            for line in itertools.takewhile(
                lambda line: line.startswith("  "), lines[lines.index("item:") + 1 :]
            )
        ]
        assert block == ["media_id", "rating_key", "guid", "note"], key


def test_b5_a_local_guid_passed_as_a_rating_key_is_answered_with_the_key(server, cli_run):
    """The recovery is inside the argument, so it is quoted back rather than
    replaced with a direction to go and look one up."""
    result = cli_run("track", "local://122")
    assert result.code == 2
    assert "GUID_NOT_RATING_KEY" in result
    assert "plex-axi track 122" in result


# ----------------------------------------------------------- B6: contradictory counts


def test_b6_the_two_playlist_commands_do_not_contradict_each_other(server, cli_run):
    """B6: `playlist list` said 0 items where `playlist show` returned 81.

    `leafCount` is what the server *declares*, and for a smart playlist it is a
    cached figure. A listing has nothing else to print, so it says which number
    it is; `show` has the real contents in hand and names the disagreement.
    """
    listed = cli_run("playlist", "list")
    assert listed.code == 0
    # The listing has only the declared count to print, so it prints it and
    # says which number it is.
    assert f'502,"plex://{MACHINE_ID}/502",Example Smart Playlist,5,' in listed.out
    assert "the count this server declares" in listed

    shown = cli_run("playlist", "show", "Example Smart Playlist")
    assert shown.code == 0
    assert shown.line("count:") == "count: 2 of 2 items"
    assert "this server declares 5 items" in shown


def test_b6_a_playlist_whose_count_agrees_says_nothing_extra(server, cli_run):
    result = cli_run("playlist", "show", "Example Playlist")
    assert result.code == 0
    assert "declares" not in result


# ----------------------------------------------------------------- B7: --sort direction


@pytest.mark.parametrize("value", ["userRating:sideways", "userRating:", "addedAt:descending"])
def test_b7_an_unknown_sort_direction_is_a_usage_error(server, cli_run, value):
    """B7: the direction reached the server untouched.

    An unknown one is not a 400 there but a 404 on the result set, so a typo
    arrived as "the search results was not found on this server" with exit 1 --
    a sentence about the library, and a lookup exit code, for a bad argument.
    """
    result = cli_run("search", "--track", "Example Track", "--sort", value)
    assert result.code == 2
    assert "BAD_SORT" in result
    assert "asc or desc" in result
    assert not server.requests


def test_b7_a_sort_without_a_field_names_the_missing_half(server, cli_run):
    result = cli_run("search", "--track", "Example Track", "--sort", ":desc")
    assert result.code == 2
    assert "BAD_SORT" in result
    assert "needs a field" in result


def test_b7_an_uppercase_direction_is_accepted_and_normalised(server, cli_run):
    """`--type Track` is already case-insensitive; refusing `DESC` was arbitrary."""
    result = cli_run("search", "--track", "Example Track", "--sort", "addedAt:DESC")
    assert result.code == 0
    assert _last_search(server)["query"]["sort"].endswith(":desc")


def test_b7_the_field_half_is_still_checked_against_the_server(server, cli_run):
    """The half that always worked keeps working, and still lists the real sorts."""
    result = cli_run("search", "--track", "Example Track", "--sort", "nosuchfield:desc")
    assert result.code == 2
    assert "UNKNOWN_SORT_FIELD" in result
    assert "titleSort" in result


# --------------------------------------------------------------------- B8: --debug


def test_b8_debug_writes_a_diagnostic_on_a_successful_command(server, cli_run):
    """B8: root `--help` advertised diagnostics on stderr and none were written.

    `output.debug` had zero call sites, so the flag was inert on every path --
    including the errors a caller is most likely to be debugging.
    """
    result = cli_run("--debug", "search", "--track", "Example Track")
    assert result.code == 0
    assert result.err
    assert "search key:" in result.err
    assert "command=search" in result.err


def test_b8_debug_writes_a_diagnostic_on_a_handled_error(server, cli_run):
    """The half that mattered most: a structured error told you nothing extra."""
    result = cli_run("--debug", "track", "999999")
    assert result.code == 1
    assert "NOT_FOUND" in result.err


def test_b8_without_the_flag_stderr_stays_empty(server, cli_run):
    for argv in (("search", "--track", "Example Track"), ("track", "999999")):
        result = cli_run(*argv)
        assert result.err == "", argv


def test_b8_a_diagnostic_is_redacted_like_everything_else(server, cli_run):
    """stderr is not a safe channel for a credential just because agents ignore it."""
    from conftest import TOKEN

    result = cli_run("--debug", "search", "--track", "Example Track")
    assert TOKEN not in result.err
    assert TOKEN not in result.out


# ---------------------------------------------------------------------- B9: --fields


def test_b9_fields_is_authoritative(server, cli_run):
    """B9: `--fields key` answered `{key,track_artist}`.

    `track_artist` was appended whenever a row carried a distinct performer, so
    the column set depended on the *data* and two runs of the same command could
    return different schemas.
    """
    result = cli_run("search", "--track", "Guest Track", "--fields", "key")
    assert result.code == 0
    assert result.line("tracks[").startswith("tracks[1]{key}")

    both = cli_run("search", "--track", "Guest Track", "--fields", "key,title")
    assert both.code == 0
    assert both.line("tracks[").startswith("tracks[1]{key,title}")


def test_b9_the_default_still_grows_the_performer_column_when_it_says_something(server, cli_run):
    """S5 is a property of the default, which is a suggestion, not a contract."""
    result = cli_run("search", "--track", "Guest Track")
    assert result.code == 0
    assert "track_artist" in result.line("tracks[")
    assert "Various Artists" in result


@pytest.mark.parametrize("argv", [("pick",), ("recent", "--type", "track"), ("similar", "111")])
def test_b9_every_command_with_fields_honours_it(server, cli_run, argv):
    result = cli_run(*argv, "--fields", "key")
    assert result.code == 0, argv
    assert result.line("tracks[").endswith("{key}:"), argv


# ------------------------------------------------------------------ B10: a bad path


def test_b10_a_relative_api_path_is_a_usage_error(server, cli_run):
    """B10: reported as `UNREACHABLE`, exit 1 -- the server's fault, it said.

    The server is fine. `requests` resolves a relative path against the base
    URL's directory, so the server never saw the path that was typed.
    """
    result = cli_run("api", "library/sections")
    assert result.code == 2
    assert "RELATIVE_PATH" in result
    assert "plex-axi api /library/sections" in result
    assert not server.requests


def test_b10_the_method_form_is_checked_too(server, cli_run):
    result = cli_run("api", "GET", "library/sections")
    assert result.code == 2
    assert "RELATIVE_PATH" in result


def test_b10_an_absolute_path_still_works(server, cli_run):
    assert cli_run("api", "/library/sections").code == 0


# ------------------------------------------------------- B11: an unknown subcommand


def test_b11_an_unknown_subcommand_is_named_as_one(server, cli_run):
    """B11: reported as an unexpected argument to a subcommand nobody typed.

    "unexpected argument 'nosuchsub' for `playlist list`" blames the argument
    rather than the name, invents a subcommand the caller did not write, and
    never lists the five that would have worked -- the one thing needed to
    recover. Its help was `Run `plex-axi playlist list `` , trailing space and all.
    """
    result = cli_run("playlist", "nosuchsub")
    assert result.code == 2
    assert "UNKNOWN_SUBCOMMAND" in result
    assert "unknown subcommand 'nosuchsub'" in result
    for name in ("list", "show", "create", "add", "remove"):
        assert name in result
    assert not server.requests


def test_b11_a_command_whose_argument_looks_like_a_name_is_untouched(server, cli_run):
    """The rule only fires where the token cannot be a legitimate argument."""
    assert cli_run("track", "111").code == 0
    assert cli_run("similar", "111").code == 0
    assert cli_run("api", "/library/sections").code == 0


def test_b11_a_suggested_command_has_no_trailing_space_inside_the_backticks(server, cli_run):
    """A space before the closing backtick reads as an argument left unnamed.

    `Run `plex-axi playlist list `` was what the old message suggested, and a
    subcommand that takes no positional arguments produced it every time.
    """
    result = cli_run("playlist", "list", "extra", "words")
    assert result.code == 2
    quoted = re.findall(r"`([^`]*)`", result.out)
    assert quoted
    assert all(text == text.strip() for text in quoted), quoted


def test_b2_no_help_line_sends_a_caller_to_fetch_an_id_the_row_already_has(
    server, cli_run, writable_env
):
    """The B12 defect, one release later: advice that costs a round trip for nothing.

    Six list views said "Run `plex-axi track <key>` for one item's detail and
    its media id" -- true when a row carried only `key`, and an advertised
    round trip for a value already on the screen once it did not. Advice has to
    be re-read whenever the output it points away from changes.
    """
    for argv in (
        ("search", "--track", "Example Track", "--no-group"),
        ("pick",),
        ("recent",),
        ("recent", "--type", "track"),
        ("similar", "111"),
        ("playlist", "list"),
        ("playlist", "show", "Example Playlist"),
        ("sessions",),
    ):
        result = cli_run(*argv, env=writable_env)
        assert result.code == 0, argv
        advice = [line for line in result.out.splitlines() if line.strip().startswith("Run ")]
        assert advice, argv
        for line in advice:
            assert "media id" not in line, (argv, line)
            assert "media_id" not in line, (argv, line)


# ------------------------------------------------------------- B12: similar's advice


def test_b12_the_advice_names_a_value_the_tool_can_actually_print(server, cli_run):
    """B12: it said to read `analysis`: 0. `track` never prints a bare 0.

    An unanalysed item reads "0 (not analysed: ...)" and one the server said
    nothing about reads "not reported by this server", so the advice sent the
    reader looking for something that cannot appear.
    """
    result = cli_run("similar", "122")  # the unanalysed track
    assert result.code == 0
    assert "0 sonically similar tracks" in result
    assert "read `analysis`: 0 means" not in result
    assert "a version number means it was analysed" in result

    detail = cli_run("track", "122")
    assert detail.code == 0
    assert detail.line("analysis:").startswith('analysis: "0 (not analysed')


# ------------------------------------------------------------------- B13: --user 401


def test_b13_a_token_plex_tv_does_not_know_is_not_reported_as_the_wrong_account(
    monkeypatch, cli_run
):
    """B13: plex.tv answers 401 to two failures with opposite recoveries.

    A token that belongs to a lesser account is refused by `shared_servers` and
    accepted by `/api/v2/user`. A token plex.tv never issued is refused by both
    -- and a server that permits unauthenticated access on the local network
    hands out exactly that: a token that works perfectly against the server and
    is not an account token at all. Reporting the second as `NOT_SERVER_OWNER`
    sends an operator hunting through sharing settings for a problem that is not
    there.
    """
    from plex_axi import plex

    fake = FakePlex(plex_tv_status=401, plex_tv_account=False)
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))

    result = cli_run("--user", "example-friend", "search", "--track", "Example Track")
    assert result.code == 1
    assert "PLEX_TV_TOKEN_REJECTED" in result
    assert "NOT_SERVER_OWNER" not in result
    assert "not about ownership" in result


def test_b13_a_valid_account_that_is_not_the_owner_still_reports_ownership(monkeypatch, cli_run):
    """The older diagnosis is still the right one for the failure it describes."""
    from plex_axi import plex

    fake = FakePlex(plex_tv_status=401, plex_tv_account=True)
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))

    result = cli_run("--user", "example-friend", "search", "--track", "Example Track")
    assert result.code == 1
    assert "NOT_SERVER_OWNER" in result
    assert "admin-only" in result


def test_b13_the_extra_question_is_asked_only_when_the_first_one_failed(server, cli_run):
    """One request on the happy path, as before."""
    assert cli_run("--user", "example-friend", "search", "--track", "Example Track").code == 0
    assert [r["path"] for r in server.plex_tv_requests] == [
        f"/api/servers/{MACHINE_ID}/shared_servers"
    ]


# ------------------------------------------------------------------ B14: the article


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (("track", "110"), "is an album on this server, not a track"),
        (("track", "100"), "is an artist on this server, not a track"),
        (("album", "111"), "is a track on this server, not an album"),
        (("artist", "111"), "is a track on this server, not an artist"),
    ],
)
def test_b14_the_article_agrees_with_the_noun(server, cli_run, argv, expected):
    """B14: "a album", "a artist" -- in the messages read most closely."""
    result = cli_run(*argv)
    assert result.code == 2
    assert expected in result


def test_b14_no_output_anywhere_says_a_album_or_a_artist(server, cli_run, writable_env):
    """Swept, because the phrasing is built by interpolation in several places."""
    for argv in (
        ("track", "110"),
        ("album", "111"),
        ("artist", "111"),
        ("similar", "110"),
        ("rate", "110", "--stars", "4"),
        ("moods", "--type", "album"),
    ):
        result = cli_run(*argv, env=writable_env)
        assert not re.search(r"\ba (album|artist|item)\b", result.out), argv


# ------------------------------------------------------- B15: a track's added date


def test_b15_a_track_can_report_when_it_was_added(server, cli_run):
    """B15: `added` was offered on an album and an artist, and not on a track.

    A track carries ``addedAt`` like everything else the scanner writes, and
    "what turned up recently" is exactly the question `--fields` exists to let a
    caller ask without spending a detail request per row. Asking for it on the
    one libtype most likely to want it was an unknown-field usage error.
    """
    result = cli_run("search", "--track", "Example Track", "--no-group", "--fields", "key,added")
    assert result.code == 0, result.out
    assert result.line("tracks[").endswith("{key,added}:")
    assert re.search(r"\d{4}-\d{2}-\d{2}", result.out), result.out


def test_b15_the_added_date_is_the_one_the_detail_view_prints(server, cli_run):
    """The same value, not merely one of the same shape."""
    listed = cli_run("search", "--track", "Example Track", "--no-group", "--fields", "key,added")
    detail = cli_run("track", "111")
    assert listed.code == 0 and detail.code == 0
    assert detail.line("added:").split(":", 1)[1].strip().strip('"') in listed.out


def test_b15_recently_added_tracks_now_say_when(server, cli_run):
    """`recent` already appends `added` to any libtype that offers it.

    The branch was there and a track was the one libtype it could not reach, so
    the recently-added list said everything except the thing it was sorted by.
    """
    result = cli_run("recent", "--type", "track")
    assert result.code == 0
    assert "added" in result.line("tracks[")


# ------------------------------------------------------------------------ helpers


def _last_search(server):
    for record in reversed(server.requests):
        if record["path"].endswith("/all") and "type" in record["query"]:
            return record
    raise AssertionError("no search request was made")
