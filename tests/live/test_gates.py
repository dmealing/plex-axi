"""G, H: both gates, observed at the proxy rather than inferred from an exit code.

Nothing here writes and nothing here plays. A refused write must reach the
server zero times; a preview must send GETs only; and the interlock -- which
would answer a non-GET with 403 -- must never fire. ``--now`` is not passed
anywhere in this suite: the runner refuses it.
"""

from __future__ import annotations

from plex_axi import cli, playback

WRITES = {"PLEX_AXI_ALLOW_WRITES": "true"}
PLAYBACK = {"PLEX_AXI_ALLOW_PLAYBACK": "true"}

#: What a closed playback gate must not show, anywhere: the same strings the
#: offline sweep in `tests/test_playback.py` looks for.
PLAYBACK_VOCABULARY = (
    "plex-axi play ",
    "plex-axi clients",
    playback.ALLOW_VAR,
    playback.ACCOUNT_TOKEN_VAR,
    playback.CONFIRM_FLAG,
    playback.DISPATCHING,
    "--client",
)


def _mutations(catalogue):
    track = catalogue.tracks[0]["ratingKey"]
    return [
        ("rate", track, "--stars", "4"),
        ("rate", track, "--stars", "4", "--write"),
        ("rate", track, "--clear", "--write"),
        ("playlist", "create", "zz-plex-axi-never-created", "--key", track),
        ("playlist", "create", "zz-plex-axi-never-created", "--key", track, "--write"),
        ("playlist", "add", "zz-plex-axi-never-created", "--key", track, "--write"),
        ("playlist", "remove", "zz-plex-axi-never-created", "--key", track, "--write"),
    ]


def test_a_refused_write_reaches_the_server_zero_times(run, proxy, catalogue):
    for argv in _mutations(catalogue):
        result = run(*argv, "--json")
        assert result.code == 1, argv
        doc = result.json()
        assert doc["code"] == "WRITES_DISABLED"
        # D14: the refusal names the gate for the operator and hands nobody a command.
        assert not any("`export" in line or line.startswith("Run") for line in doc["help"])
    assert proxy.log == []


def test_only_the_one_value_opens_the_write_gate(run, proxy, catalogue):
    track = catalogue.tracks[0]["ratingKey"]
    for value in ("yes", "1", "on", "false", " ", "enabled"):
        result = run("rate", track, "--stars", "4", env={"PLEX_AXI_ALLOW_WRITES": value})
        assert result.code == 1, value
    assert proxy.log == []
    for value in ("true", "TRUE", " true "):
        assert run("rate", track, "--stars", "4", env={"PLEX_AXI_ALLOW_WRITES": value}).code == 0


def test_a_preview_sends_gets_only_and_says_nothing_was_sent(run, proxy, catalogue):
    unrated = [row for row in catalogue.tracks if not row.get("userRating")]
    track = (unrated or catalogue.tracks)[0]["ratingKey"]
    plain = [p for p in catalogue.playlists if p.get("smart") != "1"]
    previews = [
        ("rate", track, "--stars", "4"),
        ("rate", track, "--clear"),
        ("playlist", "create", "zz-plex-axi-preview-only", "--key", track),
    ]
    if plain:
        previews.append(("playlist", "add", plain[0]["ratingKey"], "--key", track))
        previews.append(("playlist", "remove", plain[0]["ratingKey"], "--key", track))
    for argv in previews:
        result = run(*argv, env=WRITES)
        assert result.code == 0, (argv, result.out[:300])
        assert (
            "nothing was sent to the server" in result.out
            or "no-op" in result.out
            or ("no change" in result.out)
        ), argv
    assert proxy.methods == {"GET"}
    assert proxy.blocked == []


def test_validation_in_a_preview(run, proxy, catalogue):
    """D10, D17, D27: caught before anything is written, with the gate open."""
    track = catalogue.tracks[0]["ratingKey"]
    album = catalogue.albums[0]["ratingKey"]
    assert run("rate", track, "--stars", "0", env=WRITES).code == 2
    assert run("rate", track, "--stars", "2.25", env=WRITES).code == 2
    assert run("playlist", "create", "", "--key", track, env=WRITES).code == 2
    refused = run("playlist", "create", "zz-plex-axi-preview-only", "--key", album, env=WRITES)
    assert refused.code == 1 and "NOT_A_TRACK" in refused.out
    smart = [p for p in catalogue.playlists if p.get("smart") == "1"]
    if smart:
        result = run("playlist", "add", smart[0]["ratingKey"], "--key", track, env=WRITES)
        assert result.code == 1 and "SMART_PLAYLIST" in result.out
        shown = run("playlist", "show", smart[0]["ratingKey"], "--limit", "1")
        assert "playlist remove" not in shown.out  # D11: not offered where it is refused
    assert proxy.methods <= {"GET"}
    assert proxy.blocked == []


def test_a_closed_playback_gate_is_invisible_on_every_surface(run):
    surfaces = [("--help",), (), ("context",), ("doctor",)]
    surfaces += [(name, "--help") for name in cli.command_order()]
    for argv in surfaces:
        for mode in ((), ("--json",), ("--human",)):
            out = run(*argv, *mode).out
            for word in PLAYBACK_VOCABULARY:
                assert word not in out, (argv, mode, word)


def test_playback_nouns_do_not_exist_while_the_gate_is_closed(run, proxy):
    for noun in ("play", "clients", "pause", "stop", "speaker"):
        result = run(noun, "1")
        assert result.code == 2, noun
    refused = run("play", "1", env={"PLEX_AXI_ALLOW_PLAYBACK": "yes"}, check=False)
    assert refused.code == 1 and "PLAYBACK_DISABLED" in refused.out
    assert proxy.log == []


def test_an_open_playback_gate_previews_and_sends_nothing(run, proxy, catalogue):
    """Never `--now`: the preview is the whole of what this suite asks."""
    track = catalogue.tracks[0]["ratingKey"]
    listed = run("clients", env=PLAYBACK, check=False)
    assert listed.code == 0
    preview = run("play", track, env=PLAYBACK, check=False)
    assert preview.code in (0, 1)
    assert "started" not in preview.out
    assert proxy.methods <= {"GET"}
    assert proxy.blocked == [], "a playback request was attempted"
    assert not any("/player/" in path or "/playQueues" in path for path in proxy.paths)


def test_the_two_gates_do_not_open_each_other(run, proxy, catalogue):
    track = catalogue.tracks[0]["ratingKey"]
    assert run("play", track, env=WRITES).code == 2
    result = run("rate", track, "--stars", "4", "--write", env=PLAYBACK, check=False)
    assert result.code == 1 and "WRITES_DISABLED" in result.out
    assert proxy.log == []
