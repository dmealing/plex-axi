"""S8: the gate, and the two commands that can get through it.

This file exists because of one sentence that used to be true everywhere in this
repository: *plex-axi is read-only*. It is not true any more, and a claim that
stops being true silently is worse than one that was never made. So the tests
here are about the boundary rather than about the features:

* with the gate closed, a mutating command reaches the server **zero times** --
  asserted on the requests the double received, not on an exit code, because an
  exit code can be right while a request went out anyway;
* every command declares whether it reads or writes, and the declaration is what
  `--help` and the generated skill both print;
* `api` still refuses every method but GET, gate open or shut.
"""

from __future__ import annotations

import pytest

from conftest import FakePlex, FakeSession
from plex_axi import cli, writes

#: One invocation per mutating subcommand, all of which must be refused before
#: a socket is opened.
MUTATIONS = (
    ("rate", "111", "--stars", "5", "--write"),
    ("playlist", "create", "New Example", "--key", "111", "--write"),
    ("playlist", "add", "Example Playlist", "--key", "121", "--write"),
    ("playlist", "remove", "Example Playlist", "--key", "111", "--write"),
)


# ------------------------------------------------------------------ the gate


@pytest.mark.parametrize("argv", MUTATIONS, ids=lambda a: " ".join(a[:2]))
def test_a_closed_gate_means_the_server_is_never_contacted(server, cli_run, argv):
    """The acceptance test for S8, and the only one that cannot be faked.

    A refusal that read the item first, decided it could not write and said so
    would produce exactly the same exit code and message as this -- and would
    have told the server what was attempted. Zero requests is the claim.
    """
    result = cli_run(*argv)
    assert result.code == 1
    assert "WRITES_DISABLED" in result
    assert server.requests == []
    assert server.writes == []


def test_the_refusal_says_exactly_what_to_set(server, cli_run):
    result = cli_run("rate", "111", "--stars", "5", "--write")
    assert f"{writes.ALLOW_VAR}={writes.ALLOW_VALUE}" in result
    assert "--write" in result
    assert "Nothing was sent to the server" in result


def test_a_gate_set_to_something_else_is_refused_by_name(server, cli_run, plex_env):
    """A variable set to "yes" is an operator who meant to open it.

    Treating that as false and refusing with "not set" would send them looking
    for a variable they had already exported.
    """
    result = cli_run(
        "rate", "111", "--stars", "5", "--write", env={**plex_env, writes.ALLOW_VAR: "yes"}
    )
    assert result.code == 1
    assert "'yes'" in result
    assert repr(writes.ALLOW_VALUE) in result
    assert server.requests == []


@pytest.mark.parametrize("value", ["true", "TRUE", " True "])
def test_the_gate_opens_on_the_documented_value_however_it_is_cased(
    server, cli_run, plex_env, value
):
    result = cli_run("rate", "111", "--stars", "5", env={**plex_env, writes.ALLOW_VAR: value})
    assert result.code == 0
    assert "rating_after" in result


@pytest.mark.parametrize("argv", MUTATIONS, ids=lambda a: " ".join(a[:2]))
def test_without_the_write_flag_the_gate_is_open_and_nothing_is_written(
    server, cli_run, writable_env, argv
):
    """The second conjunct earns its place by answering, not by nagging.

    A preview reads the item or the playlist and prints what would change, which
    is a useful answer in its own right -- and the place both playlist refusals
    are caught before anything is sent.
    """
    result = cli_run(*[token for token in argv if token != "--write"], env=writable_env)
    assert result.code == 0
    assert "nothing was sent to the server" in result
    assert server.writes == []
    assert server.requests != []  # it did read, which is how it knows what to say


def test_the_home_view_reports_whether_this_installation_can_write(server, cli_run, writable_env):
    closed = cli_run()
    assert closed.code == 0
    assert closed.line("writes:").startswith("writes: disabled")
    assert writes.ALLOW_VAR in closed.line("writes:")

    open_gate = cli_run(env=writable_env)
    assert open_gate.line("writes:").startswith("writes: enabled")
    assert "--write" in open_gate.line("writes:")


# --------------------------------------------------------- the declaration


@pytest.mark.parametrize("noun", sorted(cli.COMMAND_ORDER))
def test_every_command_states_its_access_in_help(server, cli_run, noun):
    """S8: "not a footnote". It is the line under the description."""
    result = cli_run(noun, "--help")
    assert result.code == 0
    lines = result.out.splitlines()
    header = next(i for i, line in enumerate(lines) if line.startswith("access"))
    assert header <= 3, "access must sit under the description, not among the notes"
    block = "\n".join(lines[header : header + 4])
    assert writes.READ_ONLY in block or writes.MUTATING in block


@pytest.mark.parametrize("noun", ["rate", "playlist"])
def test_a_mutating_command_names_the_gate_in_its_own_help(server, cli_run, noun):
    result = cli_run(noun, "--help")
    assert writes.MUTATING in result
    assert writes.ALLOW_VAR in result
    assert "--write" in result


def test_playlist_help_separates_the_reads_from_the_writes(server, cli_run):
    """One noun, both sides of the line: a single verdict would be wrong twice."""
    result = cli_run("playlist", "--help")
    assert "access[2]:" in result
    assert "list, show: read-only" in result
    assert "create, add, remove: mutating" in result


def test_the_read_only_commands_are_still_read_only(server, cli_run, writable_env):
    """Opening the gate must not make a read command capable of writing."""
    for argv in (
        ("search", "--artist", "Example Artist"),
        ("pick",),
        ("genres",),
        ("track", "111"),
        ("similar", "111"),
        ("recent",),
        ("playlist",),
        ("playlist", "show", "Example Playlist"),
        ("sessions",),
        ("api", "/"),
        ("doctor",),
        (),
    ):
        assert cli_run(*argv, env=writable_env).code == 0, argv
    assert server.writes == []


def test_api_refuses_write_methods_even_with_the_gate_open(server, cli_run, writable_env):
    """A raw POST hole would make the gate meaningless, so there is not one."""
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        result = cli_run("api", method, "/playlists", env=writable_env)
        assert result.code == 2
        assert "read-only" in result
    assert server.requests == []


# -------------------------------------------------------------------- rate


def test_rate_sends_plexs_own_scale_and_prints_stars(server, cli_run, writable_env):
    """Stars in, stars out, and 0-10 on the wire, which is the trap."""
    result = cli_run("rate", "111", "--stars", "5", "--write", env=writable_env)
    assert result.code == 0
    assert result.line("rating:") == "rating: 5 stars"
    write = server.writes[-1]
    assert write["method"] == "PUT" and write["path"] == "/:/rate"
    assert write["query"]["rating"] == "10.0"
    assert write["query"]["key"] == "111"


def test_the_rating_printed_back_is_read_from_the_server(server, cli_run, writable_env):
    """AXI 5/6: say what the world looks like now, from state that was read."""
    assert cli_run("rate", "111", "--stars", "2", "--write", env=writable_env).code == 0
    later = cli_run("track", "111", env=writable_env)
    assert later.line("rating:") == "rating: 2"


def test_rating_something_to_the_value_it_already_has_writes_nothing(server, cli_run, writable_env):
    """AXI 6: the desired state already holds, so this is an outcome, not a change."""
    result = cli_run("rate", "111", "--stars", "4", "--write", env=writable_env)
    assert result.code == 0
    assert "no change" in result.line("applied:")
    assert server.writes == []


def test_a_rating_can_be_cleared(server, cli_run, writable_env):
    result = cli_run("rate", "111", "--clear", "--write", env=writable_env)
    assert result.code == 0
    assert result.line("rating:") == "rating: unrated"
    assert server.writes[-1]["query"]["rating"] == "-1"


@pytest.mark.parametrize("bad", ["9", "-1", "four"])
def test_a_rating_outside_the_star_scale_is_a_usage_error(server, cli_run, writable_env, bad):
    result = cli_run("rate", "111", "--stars", bad, "--write", env=writable_env)
    assert result.code == 2
    assert "0 to 5" in result
    assert server.requests == []


def test_asking_to_set_and_clear_at_once_is_refused(server, cli_run, writable_env):
    result = cli_run("rate", "111", "--stars", "4", "--clear", "--write", env=writable_env)
    assert result.code == 2
    assert "CONFLICTING_FLAGS" in result


def test_rate_needs_a_rating(server, cli_run, writable_env):
    result = cli_run("rate", "111", "--write", env=writable_env)
    assert result.code == 2
    assert "MISSING_RATING" in result


def test_rate_refuses_something_that_is_not_music(server, cli_run, writable_env):
    result = cli_run("rate", "900", "--stars", "4", "--write", env=writable_env)
    assert result.code == 2
    assert "rates music only" in result
    assert server.writes == []


# ---------------------------------------------------------------- playlist


def test_the_playlist_listing_is_audio_typed(server, cli_run):
    """S6: `playlists()` returns every type unless it is told otherwise.

    The film playlist on this server is the check: a listing that showed it
    would be answering a different question, and the next thing a caller did
    with it would meet the mixed-media refusal.
    """
    result = cli_run("playlist")
    assert result.code == 0
    assert "Example Playlist" in result
    assert "Example Film Night" not in result
    listings = [r for r in server.requests if r["path"] == "/playlists"]
    assert listings and all(r["query"].get("playlistType") == "audio" for r in listings)


def test_a_playlist_is_matched_exactly_and_a_miss_hands_back_the_real_titles(server, cli_run):
    """W10: no substring matching, no article stripping. Case folding only."""
    assert cli_run("playlist", "show", "example playlist").code == 0
    assert cli_run("playlist", "show", "Example").code == 1

    miss = cli_run("playlist", "show", "Example")
    assert "NO_SUCH_PLAYLIST" in miss
    assert "'Example Playlist'" in miss


def test_adding_to_a_smart_playlist_is_refused_and_says_why(server, cli_run, writable_env):
    """S6, failure mode one: a smart playlist's contents are a saved search."""
    result = cli_run(
        "playlist", "add", "Example Smart Playlist", "--key", "121", "--write", env=writable_env
    )
    assert result.code == 1
    assert "SMART_PLAYLIST" in result
    assert "saved search" in result
    assert server.writes == []


def test_adding_a_film_to_an_audio_playlist_is_refused_and_says_why(server, cli_run, writable_env):
    """S6, failure mode two: Plex holds one media type per playlist."""
    result = cli_run(
        "playlist", "add", "Example Playlist", "--key", "900", "--write", env=writable_env
    )
    assert result.code == 1
    assert "MIXED_MEDIA_TYPES" in result
    assert "same kind of media" in result
    assert server.writes == []


def test_the_two_playlist_refusals_are_told_apart(server, cli_run, writable_env):
    """One means pick a different playlist; the other means pick different items.

    Both arrive as the same exception type carrying the same shape of message,
    which is why the landscape's tools surface them raw and neither is usable.
    """
    smart = cli_run(
        "playlist", "add", "Example Smart Playlist", "--key", "121", "--write", env=writable_env
    )
    mixed = cli_run(
        "playlist", "add", "Example Playlist", "--key", "900", "--write", env=writable_env
    )
    assert "SMART_PLAYLIST" in smart and "MIXED_MEDIA_TYPES" not in smart
    assert "MIXED_MEDIA_TYPES" in mixed and "SMART_PLAYLIST" not in mixed


def test_the_smart_refusal_survives_the_client_librarys_own_check(server, writable_env):
    """The translation is of the exception, not of a flag this tool read first.

    `addItems` refuses a smart playlist before any request leaves, so the tool
    would meet the message even if it never looked at `smart` itself. This calls
    the translator with the library's own wording to prove it is that message
    being read, not a state the command happened to have handy.
    """
    from plexapi.exceptions import BadRequest

    from plex_axi.commands.playlist import _write_error

    error = _write_error(
        BadRequest("Cannot add items to a smart playlist."),
        action="add items to",
        title="Example Playlist",
        keys=["111"],
    )
    assert error.code == "SMART_PLAYLIST"

    mixed = _write_error(
        BadRequest("Can not mix media types when building a playlist: audio and video"),
        action="add items to",
        title="Example Playlist",
        keys=["900"],
    )
    assert mixed.code == "MIXED_MEDIA_TYPES"
    for message in (error.message, mixed.message, *error.help_lines, *mixed.help_lines):
        assert "plexapi" not in message.lower()


def test_a_playlist_can_be_created_added_to_and_trimmed(server, cli_run, writable_env):
    created = cli_run(
        "playlist", "create", "Example Mix", "--key", "111", "--write", env=writable_env
    )
    assert created.code == 0
    assert created.line("type:") == "type: audio"
    assert created.line("holds:") == "holds: 1 items"

    added = cli_run("playlist", "add", "Example Mix", "--key", "112", "--write", env=writable_env)
    assert added.code == 0
    assert added.line("holds:") == "holds: 2 items"

    removed = cli_run(
        "playlist", "remove", "Example Mix", "--key", "111", "--write", env=writable_env
    )
    assert removed.code == 0
    assert removed.line("holds:") == "holds: 1 items"

    shown = cli_run("playlist", "show", "Example Mix", env=writable_env)
    assert "Another Track" in shown
    assert "Example Track" not in shown


def test_creating_a_playlist_that_exists_is_refused_with_the_command_that_works(
    server, cli_run, writable_env
):
    result = cli_run(
        "playlist", "create", "Example Playlist", "--key", "111", "--write", env=writable_env
    )
    assert result.code == 1
    assert "PLAYLIST_EXISTS" in result
    assert "playlist add 'Example Playlist'" in result
    assert server.writes == []


def test_removing_something_that_is_not_in_the_playlist_is_refused(server, cli_run, writable_env):
    result = cli_run(
        "playlist", "remove", "Example Playlist", "--key", "122", "--write", env=writable_env
    )
    assert result.code == 1
    assert "NOT_IN_PLAYLIST" in result
    assert server.writes == []


def test_removing_a_track_a_playlist_holds_twice_removes_one_copy(
    monkeypatch, cli_run, writable_env
):
    """The client library resolves a track to its *first* membership.

    Deleting every membership from one `--key` would remove more than the caller
    named, and the second delete would be issued against an id that no longer
    exists -- which arrives as "the playlist was not found", a different untruth.
    """
    from conftest import FakePlex, FakeSession
    from plex_axi import plex

    fake = FakePlex()
    doubled = next(p for p in fake.playlists if p["title"] == "Example Playlist")
    doubled["items"].append({"key": 111, "item_id": fake._item_id()})
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))

    result = cli_run(
        "playlist", "remove", "Example Playlist", "--key", "111", "--write", env=writable_env
    )
    assert result.code == 0
    assert "appears more than once" in result
    assert len([w for w in fake.writes if w["method"] == "DELETE"]) == 1
    assert [entry["key"] for entry in doubled["items"]] == [112, 111]


def test_a_playlist_edit_needs_at_least_one_key(server, cli_run, writable_env):
    result = cli_run("playlist", "add", "Example Playlist", "--write", env=writable_env)
    assert result.code == 2
    assert "MISSING_KEY" in result
    assert server.requests == []


def test_a_playlist_key_is_validated_before_anything_is_sent(server, cli_run, writable_env):
    result = cli_run(
        "playlist",
        "add",
        "Example Playlist",
        "--key",
        "plex://track/a1b2c3d4e5f60718293c0111",
        "--write",
        env=writable_env,
    )
    assert result.code == 2
    assert "GUID_NOT_RATING_KEY" in result
    assert server.requests == []


def test_an_empty_playlist_list_says_so(monkeypatch, cli_run):
    fake = FakePlex()
    fake.playlists = []
    from plex_axi import plex

    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))
    result = cli_run("playlist")
    assert result.code == 0
    assert "0 audio playlists on this server" in result
    assert "playlist create" in result
