"""The playback gate, and the requirement that makes it different from the write gate.

Gating execution is not sufficient here and that is the whole design. If `play`
appeared in `--help`, in the no-argument home view or in the generated skill,
then an agent in a house that also runs a home-automation CLI would see two ways
to start music and would sometimes choose the wrong one -- which is the failure
the original no-playback decision existed to avoid. So the first half of this
file asserts *invisibility*: with the gate closed, no surface this tool has
mentions the capability, and the refusal a caller meets is the one it has always
met. The second half asserts the behaviour once an operator has opted in.

``tests/test_no_dispatch.py`` carries the other half of the bargain -- what the
package may reach for, whatever the gate says -- and its docstring records what
was permanently given up to have this at all.
"""

from __future__ import annotations

import pytest

from conftest import CLIENTS, SONOS_SPEAKERS, FakePlex, FakeSession
from plex_axi import cli, playback, skill, writes

#: Every string that would betray the capability. Deliberately includes the
#: environment variables: an agent that saw the name of the gate would know
#: there was a gate.
TELLS = (
    "plex-axi play ",
    "plex-axi clients",
    playback.ALLOW_VAR,
    playback.ACCOUNT_TOKEN_VAR,
    playback.CONFIRM_FLAG,
    playback.DISPATCHING,
    "--client",
)

#: The addresses the double's `/clients` and Sonos rows carry. Nothing this tool
#: prints may contain one: they describe the operator's own network, nothing
#: needs them to address a target, and a row shape that leaked one would be a
#: single careless fixture away from a public commit.
ADDRESSES = tuple(
    value for row in CLIENTS for value in (row["host"], row["address"]) if value
) + tuple(row["lanIP"] for row in SONOS_SPEAKERS)


def _surfaces(cli_run, env) -> dict:
    """Every place this tool describes itself, as one dictionary of text."""
    texts = {"root help": cli_run("--help", env=env).out, "home": cli_run(env=env).out}
    for noun in cli.command_order(env):
        texts[f"{noun} --help"] = cli_run(noun, "--help", env=env).out
    specs = cli.command_specs(env)
    texts["skill"] = skill.render([specs[noun] for noun in cli.command_order(env)])
    return texts


# ------------------------------------------------------------- invisibility


@pytest.mark.parametrize("noun", sorted(playback.COMMANDS))
def test_a_closed_gate_makes_the_command_unknown_rather_than_refused(server, cli_run, noun):
    """Not "you may not", which would advertise it. "There is no such command"."""
    result = cli_run(noun, "111")
    assert result.code == 2
    assert "OUT_OF_SCOPE" in result
    assert "never dispatches playback" in result.out
    assert server.requests == []
    assert server.played == []


def test_a_closed_gate_reaches_the_server_zero_times(server, cli_run):
    """The acceptance test, and the only one that cannot be faked.

    A refusal that resolved the item first, found the client and then declined
    would produce the same exit code and the same message -- and would have told
    the server what was attempted.
    """
    assert cli_run("play", "111", "--client", "Example Client", "--now").code == 2
    assert cli_run("clients").code == 2
    assert server.requests == []
    assert server.writes == []
    assert server.played == []


def test_no_surface_mentions_playback_while_the_gate_is_closed(server, cli_run, plex_env):
    """The requirement in one assertion, over every surface at once.

    Root help, the home view, every command's `--help`, and the generated skill.
    A new surface that describes the tool has to be added here, or it is not
    covered -- which is why this is written as a sweep rather than as one test
    per document.
    """
    for where, text in _surfaces(cli_run, plex_env).items():
        for tell in TELLS:
            assert tell not in text, f"{where} mentions {tell!r} with the gate closed"


def test_the_command_table_itself_does_not_carry_the_playback_nouns(plex_env):
    """Not merely hidden from the rendering: absent from what the CLI dispatches on."""
    assert set(cli.command_order(plex_env)) == set(cli.COMMAND_ORDER)
    assert not set(cli.command_specs(plex_env)) & set(playback.COMMANDS)
    # ...and with no environment at all, which is what the committed skill and
    # the tests that pin the public surface read.
    assert set(cli.command_order()) == set(cli.COMMAND_ORDER)


def test_the_closed_gate_renders_exactly_what_it_rendered_before(server, cli_run, plex_env):
    """A gate set to a value that is not `true` still shows nothing.

    Two environments that differ only in a variable neither of them opens the
    gate with must describe the tool identically; otherwise the variable is
    itself the advertisement.
    """
    other = {**plex_env, playback.ALLOW_VAR: "no"}
    assert _surfaces(cli_run, other) == _surfaces(cli_run, plex_env)


def test_the_generated_skill_still_says_the_tool_never_plays_anything(plex_env):
    specs = cli.command_specs(plex_env)
    content = skill.render([specs[noun] for noun in cli.command_order(plex_env)])
    assert skill.NO_PLAYBACK_CLAIM in content
    assert "never plays anything" in content
    assert skill.PLAYBACK_CLAIM not in content


def test_a_gate_set_to_something_else_is_refused_by_name(server, cli_run, plex_env):
    """The one place this gate is *less* secretive than it could be, on purpose.

    Somebody who has exported the variable has typed the capability's name, so
    there is nothing left to hide from them -- and "unknown command" would send
    them hunting for a variable they had already set. They get the write gate's
    refusal-by-name, for the write gate's reason.
    """
    result = cli_run("play", "111", env={**plex_env, playback.ALLOW_VAR: "yes"})
    assert result.code == 1
    assert "PLAYBACK_DISABLED" in result
    assert "'yes'" in result
    assert repr(playback.ALLOW_VALUE) in result
    assert server.requests == []


def test_the_gate_is_not_the_write_gate(server, cli_run, writable_env):
    """Opening one must not open the other, in either direction.

    They answer different questions -- "may this change my library" and "does
    anything else here own the speakers" -- and an operator who answered one has
    said nothing about the other.
    """
    assert cli_run("play", "111", "--client", "Example Client", env=writable_env).code == 2
    assert server.requests == []
    for text in _surfaces(cli_run, writable_env).values():
        for tell in TELLS:
            assert tell not in text


def test_opening_playback_does_not_open_writes(server, cli_run, playing_env):
    result = cli_run("rate", "111", "--stars", "5", "--write", env=playing_env)
    assert result.code == 1
    assert "WRITES_DISABLED" in result
    assert server.writes == []


def test_the_second_latch_holds_even_if_the_dispatcher_did_not(plex_env):
    """`playback.require` is defence in depth, so it is tested directly.

    The CLI refuses to route a playback noun with the gate closed, which means
    this function is unreachable through the CLI -- and therefore untested by
    every test above. "Zero requests when the gate is closed" should not rest on
    the dispatcher alone.
    """
    with pytest.raises(playback.PlaybackRefused):
        playback.require(plex_env, action="play 111")
    playback.require({**plex_env, playback.ALLOW_VAR: "TRUE"}, action="play 111")


def test_an_open_gate_corrects_a_misspelled_playback_noun_rather_than_refusing_it(
    server, cli_run, playing_env
):
    """`speakers` is `clients` spelled wrong, and that is all it is.

    Answering it "out of scope" in the same error whose `commands:` line lists
    `clients` would contradict itself -- so with the gate open these nouns take
    the alias correction every other near miss gets. Closed, they keep the
    answer that names nothing, which is what the gate owes somebody who has not
    opted in.
    """
    for noun in ("speakers", "player", "client", "speaker"):
        result = cli_run(noun, env=playing_env)
        assert result.code == 2
        assert f"unknown command: {noun}; use `clients` instead" in result.out
        assert "out of scope" not in result.out
    for noun in ("speakers", "player"):
        closed = cli_run(noun)
        assert closed.code == 2
        assert "out of scope" in closed.out


# ------------------------------------------------------------------ clients


def test_clients_lists_only_what_can_actually_play(server, cli_run, playing_env):
    result = cli_run("clients", env=playing_env)
    assert result.code == 0
    assert "Example Client" in result
    # Advertises `timeline,navigation` and no `playback`: a tool that read the
    # list without reading the capabilities would address it and watch nothing
    # happen.
    assert "Example Screen" not in result
    assert result.line("count:") == "count: 2 of 3 can play"
    assert "do not advertise playback" in result.out


def test_a_client_that_advertises_no_port_is_still_listed(server, cli_run, playing_env):
    """The row that makes `PlexServer.clients()` reach plex.tv for the number.

    Nothing here uses that helper -- it is on the forbidden list -- and this row
    is what proves the difference rather than asserting it.
    """
    assert "Example Portless" in cli_run("clients", env=playing_env)
    assert server.plex_tv_requests == []


@pytest.mark.parametrize(
    "argv",
    [
        ("clients",),
        ("play", "111", "--client", "Example Client"),
        ("play", "111", "--client", "Example Client", "--now"),
    ],
    ids=lambda a: " ".join(a[:2]),
)
def test_no_network_address_is_ever_printed(server, cli_run, sonos_env, argv):
    """A `/clients` row carries three addresses and a Sonos row carries a fourth.

    None of them is needed to address a target, and this repository is public.
    The double carries them precisely so that withholding them is a test rather
    than an assumption.
    """
    result = cli_run(*argv, env=sonos_env)
    for address in ADDRESSES:
        assert address not in result.out, f"{address} reached stdout"
        assert address not in result.err, f"{address} reached stderr"


def test_the_answer_says_which_routes_it_consulted(server, cli_run, playing_env, sonos_env):
    """An empty list that never asked plex.tv is a different answer from one that did."""
    without = cli_run("clients", env=playing_env)
    assert "not consulted" in without.out
    assert playback.ACCOUNT_TOKEN_VAR in without.out
    assert server.sonos_requests == []

    with_token = cli_run("clients", env=sonos_env)
    assert "Example Speaker" in with_token
    assert [row["path"] for row in server.sonos_requests] == ["/resources"]


# ------------------------------------------------------- choosing the target


def test_several_targets_and_no_flag_is_a_refusal_that_names_them(server, cli_run, playing_env):
    result = cli_run("play", "111", "--now", env=playing_env)
    assert result.code == 1
    assert "AMBIGUOUS_TARGET" in result
    assert "Example Client" in result
    assert "Example Portless" in result
    assert server.played == []


def test_one_target_is_defaulted_to_and_the_answer_says_so(monkeypatch, cli_run, playing_env):
    """Defaulting is a convenience; defaulting *silently* is not.

    A second client appearing on the network later has to change the output
    rather than change which room the music comes out of without saying so.
    """
    from plex_axi import plex

    fake = FakePlex(clients=CLIENTS[:1])
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))
    result = cli_run("play", "111", "--now", env=playing_env)
    assert result.code == 0
    assert result.line("target:") == "target: Example Client"
    assert "the only target advertising playback" in result.out


def test_no_targets_at_all_is_an_outcome_not_a_crash(monkeypatch, cli_run, playing_env):
    from plex_axi import plex

    fake = FakePlex(clients=[])
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))
    result = cli_run("play", "111", "--now", env=playing_env)
    assert result.code == 1
    assert "NO_TARGETS" in result
    assert "only visible while its app is running" in result.out


def test_a_target_is_matched_exactly_and_a_miss_hands_back_the_real_ones(
    server, cli_run, playing_env
):
    """No substring, no nearest neighbour: guessing is how music starts in the wrong room."""
    result = cli_run("play", "111", "--client", "Example", "--now", env=playing_env)
    assert result.code == 1
    assert "NO_SUCH_TARGET" in result
    assert "Example Client" in result
    assert server.played == []


def test_a_target_can_be_named_by_machine_id(server, cli_run, playing_env):
    from conftest import CLIENT_ID

    result = cli_run("play", "111", "--client", CLIENT_ID, "--now", env=playing_env)
    assert result.code == 0
    assert [row["client"] for row in server.played] == ["Example Client"]


def test_two_targets_with_one_name_is_a_refusal_rather_than_a_coin_toss(
    monkeypatch, cli_run, playing_env
):
    """Two phones set up by the same person is not exotic.

    Picking the first would put music in a room nobody named, which is the
    failure the whole resolution path exists to avoid.
    """
    import copy

    from plex_axi import plex

    twin = copy.deepcopy(CLIENTS[0])
    twin["machineIdentifier"] = "5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e"
    fake = FakePlex(clients=[CLIENTS[0], twin])
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))

    result = cli_run("play", "111", "--client", "Example Client", "--now", env=playing_env)
    assert result.code == 1
    assert "AMBIGUOUS_TARGET" in result
    assert fake.played == []
    # ...and the machine id, which is what does name one, still resolves.
    assert (
        cli_run("play", "111", "--client", twin["machineIdentifier"], "--now", env=playing_env).code
        == 0
    )


def test_a_target_that_cannot_play_is_named_as_such_rather_than_as_absent(
    server, cli_run, playing_env
):
    result = cli_run("play", "111", "--client", "Example Screen", "--now", env=playing_env)
    assert result.code == 1
    assert "do not advertise playback" in result.out


# --------------------------------------------------------------- playing it


def test_without_the_confirmation_flag_nothing_is_sent(server, cli_run, playing_env):
    """The second conjunct, and it is a preview rather than a nag.

    It resolves the item, resolves the target and says which one it picked --
    which is where "three clients and you named none of them" is caught for
    free -- and sends no playback command and creates no play queue.
    """
    result = cli_run("play", "111", "--client", "Example Client", env=playing_env)
    assert result.code == 0
    assert playback.PREVIEW_LINE in result.out
    assert server.played == []
    assert server.writes == []
    assert "started" not in result.out


@pytest.mark.parametrize(
    ("key", "kind", "queued"),
    [
        ("111", "track", 1),
        ("110", "album", 2),
        ("501", "playlist", 2),
        ("100", "artist", 4),
    ],
)
def test_every_music_kind_plays_and_the_queue_holds_what_it_should(
    server, cli_run, playing_env, key, kind, queued
):
    """The play queue is expanded for real by the double, so this is a claim.

    An album that reached the client as a queue of one item would have played a
    single track and looked like it worked.
    """
    result = cli_run("play", key, "--client", "Example Client", "--now", env=playing_env)
    assert result.code == 0, result.out
    assert result.line("type:") == f"type: {kind}"
    assert len(server.played) == 1
    assert len(server.playqueues[server.played[0]["queue"]]) == queued


def test_the_playback_command_names_the_queue_the_server_just_created(server, cli_run, playing_env):
    """The double refuses a `containerKey` naming a queue it never made.

    Which is what makes this a test rather than a restatement: a playback
    command pointing at a queue that does not exist is exactly what a broken
    implementation sends, and a permissive server would answer it 200.
    """
    assert cli_run("play", "111", "--client", "Example Client", "--now", env=playing_env).code == 0
    (created,) = [r for r in server.requests if r["path"] == "/playQueues"]
    (sent,) = [r for r in server.requests if r["path"] == "/player/playback/playMedia"]
    assert created["method"] == "POST"
    assert sent["query"]["containerKey"].startswith(f"/playQueues/{server.played[0]['queue']}?")
    assert sent["headers"]["X-Plex-Target-Client-Identifier"] == CLIENTS[0]["machineIdentifier"]
    assert sent["query"]["type"] == "music"


def test_a_client_that_answers_ok_rather_than_xml_is_a_success(server, cli_run, playing_env):
    """Plexamp and Plex for Android answer a successful command with `OK`.

    Not XML, so parsing it raises -- after the 200 has already been read. The
    double models exactly that for the client that plays, which means every test
    above is taking this path rather than a tidier one that does not exist.
    """
    assert CLIENTS[0]["answers"] == "OK"
    result = cli_run("play", "111", "--client", "Example Client", "--now", env=playing_env)
    assert result.code == 0
    assert "started:" in result.out


def test_a_server_that_will_not_mint_a_delegation_token_still_plays(server, cli_run, playing_env):
    """Measured on a real server: `/security/token` answered 403.

    The client library asks for one unconditionally and lets the failure
    propagate, which would turn every play into a 403 on such a server. The
    token is optional here, and the double refuses to mint one by default so
    that this is the path every other test takes too.
    """
    assert server.mints_tokens is False
    result = cli_run("play", "111", "--client", "Example Client", "--now", env=playing_env)
    assert result.code == 0
    (sent,) = [r for r in server.requests if r["path"] == "/player/playback/playMedia"]
    assert "token" not in sent["query"]


def test_a_server_that_does_mint_one_sends_it_and_never_prints_it(
    monkeypatch, cli_run, playing_env
):
    from conftest import DELEGATION_TOKEN
    from plex_axi import plex

    fake = FakePlex(mints_tokens=True)
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))
    result = cli_run(
        "play", "111", "--client", "Example Client", "--now", "--debug", env=playing_env
    )
    assert result.code == 0
    (sent,) = [r for r in fake.requests if r["path"] == "/player/playback/playMedia"]
    assert sent["query"]["token"] == DELEGATION_TOKEN
    # A delegation token is a bearer credential that travels in a URL, so it is
    # registered as a secret the moment it arrives -- stderr included.
    assert DELEGATION_TOKEN not in result.out
    assert DELEGATION_TOKEN not in result.err


@pytest.mark.parametrize("argv", [("play", "900"), ("play", "503")])
def test_something_that_is_not_music_is_refused_before_anything_is_sent(
    server, cli_run, playing_env, argv
):
    result = cli_run(*argv, "--client", "Example Client", "--now", env=playing_env)
    assert result.code == 2
    assert "WRONG_ITEM_TYPE" in result
    assert server.played == []


def test_a_guid_where_a_rating_key_belongs_fails_the_way_it_always_has(
    server, cli_run, playing_env
):
    """The same validation every other command uses, and before the connection."""
    result = cli_run(
        "play", "plex://track/a1b2c3d4e5f60718293c0111", "--client", "x", env=playing_env
    )
    assert result.code == 2
    assert "GUID_NOT_RATING_KEY" in result
    assert server.requests == []


def test_debug_says_something_on_a_play_and_nothing_without_the_flag(server, cli_run, playing_env):
    argv = ("play", "111", "--client", "Example Client", "--now")
    assert cli_run(*argv, env=playing_env).err == ""
    assert "play queue" in cli_run(*argv, "--debug", env=playing_env).err


# ------------------------------------------------------------- the sonos route


def test_the_sonos_route_needs_its_own_credential_and_says_which(monkeypatch, cli_run, playing_env):
    """A server token gets a flat 401 from plex.tv -- measured, not assumed.

    An operator with `PLEX_TOKEN` exported reads a bare 401 as "my token is
    wrong" rather than "my token is the wrong kind", which is the mistake this
    message exists to prevent. The refusal is a fact about one route, so the
    local clients are still listed and the explanation travels in the row for
    the route that failed rather than failing the whole answer.
    """
    from plex_axi import plex

    fake = FakePlex()
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))
    env = {**playing_env, playback.ACCOUNT_TOKEN_VAR: "example-token-0000000009"}
    result = cli_run("clients", env=env)
    assert result.code == 0
    assert "Example Client" in result.out
    assert "refused the account token (401)" in result.out
    assert playback.ACCOUNT_TOKEN_VAR in result.out
    assert "broader credential than PLEX_TOKEN" in result.out


def test_a_sonos_speaker_can_be_played_to_and_the_route_is_named(server, cli_run, sonos_env):
    result = cli_run("play", "111", "--client", "Example Speaker", "--now", env=sonos_env)
    assert result.code == 0
    assert result.line("route:") == "route: sonos"
    assert [row["route"] for row in server.played] == ["sonos"]
    # The consequence an operator has to know, printed where they will read it.
    assert "goes through Plex's cloud" in result.out


def test_the_account_token_is_registered_as_a_secret(server, cli_run, sonos_env):
    from conftest import ACCOUNT_TOKEN

    result = cli_run(
        "play", "111", "--client", "Example Speaker", "--now", "--debug", env=sonos_env
    )
    assert result.code == 0
    assert ACCOUNT_TOKEN not in result.out
    assert ACCOUNT_TOKEN not in result.err


def test_the_sonos_service_being_down_does_not_take_the_local_route_with_it(
    monkeypatch, cli_run, sonos_env
):
    """The cloud failing is a fact about the cloud, not about the local clients.

    `clients` still answers with what the server itself can see, the failure is
    reported beside the row for the route that failed, and the command exits 0
    because the question it was asked -- what can play -- was answered. The
    underlying error stays a `--debug` line, like every diagnostic here.
    """
    from plex_axi import plex

    fake = FakePlex(plex_tv_unreachable=True)
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))
    result = cli_run("clients", env=sonos_env)
    assert result.code == 0
    assert "Example Client" in result.out
    assert "sonos.plex.tv could not be reached" in result.out
    assert result.err == ""
    debugged = cli_run("clients", "--debug", env=sonos_env)
    assert "sonos route failed" in debugged.err


# ----------------------------------------------------------- the declaration


@pytest.mark.parametrize("noun", sorted(playback.COMMANDS))
def test_every_playback_command_states_its_access_in_help(server, cli_run, playing_env, noun):
    lines = cli_run(noun, "--help", env=playing_env).out.splitlines()
    assert any(line.startswith("access") for line in lines[:6])


def test_play_declares_dispatching_and_clients_declares_read_only(server, cli_run, playing_env):
    """`clients` cannot start anything, and describing it as if it could would be a lie.

    The access vocabulary has to stay honest in both directions or it stops
    being read.
    """
    assert playback.ACCESS[playback.DISPATCHING] in cli_run("play", "--help", env=playing_env).out
    assert writes.ACCESS[writes.READ_ONLY] in cli_run("clients", "--help", env=playing_env).out


def test_the_open_gate_describes_playback_everywhere_it_describes_itself(
    server, cli_run, playing_env
):
    """The other direction of the invisibility sweep: opened, it is not half-hidden."""
    texts = _surfaces(cli_run, playing_env)
    assert playback.ALLOW_VAR in texts["root help"]
    assert playback.CONFIRM_FLAG in texts["root help"]
    assert playback.state(playing_env) in texts["home"]
    assert "### `plex-axi play`" in texts["skill"]
    assert skill.PLAYBACK_CLAIM in texts["skill"]
    assert skill.NO_PLAYBACK_CLAIM not in texts["skill"]
