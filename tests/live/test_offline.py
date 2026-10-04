"""A: the surfaces that need no server, run as a subprocess the way an agent runs them."""

from __future__ import annotations

import json

from plex_axi import cli


def test_the_version_is_printed_bare_in_every_mode(run):
    versions = {
        run(flag, *mode).out.strip()
        for flag in ("--version", "-v")
        for mode in ((), ("--json",), ("--human",))
    }
    assert len(versions) == 1


def test_help_on_every_surface_and_as_json(run, proxy):
    for name in (None, *cli.command_order()):
        argv = ("--help",) if name is None else (name, "--help")
        text = run(*argv)
        assert text.code == 0 and text.out.startswith("usage:"), argv
        assert json.loads(run(*argv, "--json").out)["help"][0].startswith("usage:"), argv
    assert proxy.log == [], "help reached the server"


def test_an_unconfigured_environment_is_explained_not_crashed(run, proxy):
    for argv in (("search", "--artist", "x"), ("doctor",), ("track", "1"), ("playlist",)):
        result = run(*argv, "--json", unset=("PLEX_URL", "PLEX_TOKEN"))
        assert result.code == 1, argv
        assert result.json().get("help"), argv
    home = run(unset=("PLEX_URL", "PLEX_TOKEN"))
    assert home.code == 0 and "not set" in home.out
    assert run("context", unset=("PLEX_URL", "PLEX_TOKEN")).code == 0
    assert proxy.log == []


def test_a_badly_configured_environment_does_not_echo_the_secret(run, live):
    cases = [
        {"PLEX_URL": "ftp://plex.example.com"},
        {"PLEX_URL": ""},
        {"PLEX_TOKEN": "two words"},
        {"PLEX_URL": "http://user:hunter2hunter2@plex.example.com:32400"},
    ]
    for env in cases:
        result = run("search", "--artist", "x", env=env, check=False)
        assert result.code == 1
        assert "hunter2hunter2" not in result.out + result.err
        assert live.token not in result.out + result.err


def test_global_flags_are_validated(run, proxy):
    for argv in (
        ("--timeout", "soon", "doctor"),
        ("--timeout", "0", "doctor"),
        ("--section",),
        ("search", "--artist", "x", "--json", "--human"),
    ):
        assert run(*argv).code == 2, argv
    assert proxy.log == []
