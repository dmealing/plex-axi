"""Configuration: the environment is the only channel, and it is normalised."""

from __future__ import annotations

import pytest

from plex_axi import config
from plex_axi.errors import ConfigError


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://plex.example.com:32400", "http://plex.example.com:32400"),
        ("http://plex.example.com:32400/", "http://plex.example.com:32400"),
        ("https://plex.example.com:32400", "https://plex.example.com:32400"),
        # A bare host gets the port a Plex Media Server actually listens on. A
        # Plex URL without one is a mistake far more often than it is a proxy,
        # and a proxy will have been written with its port.
        ("plex.example.com", "http://plex.example.com:32400"),
        ("plex.example.com:8443", "http://plex.example.com:8443"),
        ("https://plex.example.com", "https://plex.example.com:32400"),
    ],
)
def test_a_base_url_is_normalised(raw, expected):
    assert config.normalize_base_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "ftp://plex.example.com", "://nope"])
def test_an_unusable_url_is_refused_by_name(raw):
    with pytest.raises(ConfigError) as caught:
        config.normalize_base_url(raw)
    assert caught.value.code == "BAD_URL"


def test_both_variables_are_required_and_named_when_absent():
    with pytest.raises(ConfigError) as caught:
        config.load({})
    assert "PLEX_URL and PLEX_TOKEN" in caught.value.message
    assert caught.value.code == "NOT_CONFIGURED"


def test_only_the_missing_one_is_named():
    with pytest.raises(ConfigError) as caught:
        config.load({"PLEX_URL": "http://plex.example.com:32400"})
    assert caught.value.message.startswith("PLEX_TOKEN is not set")


@pytest.mark.parametrize("alias", ["PLEX_SERVER", "PLEX_BASEURL"])
def test_an_alias_variable_is_accepted(alias):
    resolved = config.load({alias: "http://plex.example.com:32400", "PLEX_TOKEN": "abc12345"})
    assert resolved.base_url == "http://plex.example.com:32400"


def test_there_is_no_token_flag_anywhere_in_the_cli():
    """A token on a command line lands in shell history and the process table."""
    from plex_axi import cli

    for noun in cli.COMMAND_ORDER:
        command = cli._MODULES[noun].COMMAND_FOR(noun)
        for sub in command.subs:
            for flag in sub.flags:
                assert "token" not in flag.name.lower()
    assert not any("token" in flag.lower() for flag in cli.GLOBAL_FLAGS)


def test_the_environment_report_never_reveals_the_token():
    described = config.describe_environment(
        {"PLEX_URL": "http://plex.example.com:32400", "PLEX_TOKEN": "abc12345"}
    )
    assert described == {
        "url_var": "PLEX_URL",
        "url_set": True,
        "token_var": "PLEX_TOKEN",
        "token_set": True,
    }
