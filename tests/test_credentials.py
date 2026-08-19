"""M8: the token, and every path it could escape by.

A Plex token is a bearer credential for the whole library, and the client
library hands it out in more places than a reader expects: any artwork, stream
or web URL it builds embeds the token when ``includeToken`` is set -- and a
single line in a user's own config file sets it for every one of them. So this
tests the switches, not only the calls.

stderr is asserted on as often as stdout. It is not a safe channel because
agents do not read it: it still reaches terminals, log files and CI output.
"""

from __future__ import annotations

import plexapi

from conftest import TOKEN
from plex_axi import output, plex


def test_the_token_is_registered_before_anything_can_print_it(plex_env):
    from plex_axi import config

    config.load(plex_env)
    assert output.redact("the token is " + TOKEN) == "the token is <redacted>"


def test_a_token_shaped_url_parameter_is_redacted_even_if_never_registered():
    """The backstop for a value this process never saw configured."""
    output.reset_secrets()
    text = "http://plex.example.com:32400/photo?X-Plex-Token=abc123def456ghi789"  # leakcheck: allow=plex-token
    assert "abc123def456ghi789" not in output.redact(text)
    assert "X-Plex-Token=<redacted>" in output.redact(text)


def test_secret_disclosure_is_forced_off_in_every_place_it_is_read():
    """Three switches, and avoiding one call covers none of them."""
    plexapi.CONFIG.data.setdefault("log", {})["show_secrets"] = "true"
    plex._hardened = False
    plex.harden()
    assert plexapi.CONFIG.get("log.show_secrets") == "false"
    assert plexapi.logfilter in plexapi.log.filters


def test_the_connection_pins_the_attribute_that_url_actually_consults(server, plex_env):
    from plex_axi import config

    connection = plex.connect(config.load(plex_env))
    assert connection._showSecrets is False
    # The check that matters: the URL builder does not append the token.
    assert "X-Plex-Token" not in connection.url("/library/sections")


def test_the_outgoing_headers_identify_the_tool_and_not_the_machine(server, cli_run):
    """plexapi publishes the hostname and the MAC address unless told not to."""
    import socket
    import uuid

    assert cli_run("doctor").code == 0
    headers = server.requests[-1]["headers"]
    assert headers["X-Plex-Product"] == "plex-axi"
    assert headers["X-Plex-Device-Name"] == "plex-axi"
    assert socket.gethostname() not in headers.values()
    assert hex(uuid.getnode()) not in headers["X-Plex-Client-Identifier"]
    assert str(uuid.getnode()) not in headers["X-Plex-Client-Identifier"]


def test_no_output_stream_carries_the_token_on_any_command(server, cli_run):
    for argv in (
        ("search", "--artist", "Example Artist"),
        ("track", "111", "--check-files"),
        ("api", "/"),
        ("doctor",),
        ("sessions",),
        (),
    ):
        result = cli_run(*argv)
        assert TOKEN not in result.out, argv
        assert TOKEN not in result.err, argv


def test_a_failure_carries_no_token_on_either_stream(unreachable, cli_run):
    result = cli_run("--debug", "search", "--artist", "Example Artist")
    assert result.code == 1
    assert TOKEN not in result.out
    assert TOKEN not in result.err


def test_a_token_in_a_url_query_is_refused_rather_than_sent(server, cli_run):
    """The escape hatch must not become the way a token reaches shell history."""
    result = cli_run("api", "/library/sections", "--query", "X-Plex-Token=whatever")
    assert result.code == 2
    assert "TOKEN_IN_QUERY" in result


def test_a_trailing_newline_is_stripped_rather_than_refused(plex_env):
    """`PLEX_TOKEN=$(cat token.txt)` is the common case, not a mistake."""
    from plex_axi import config

    environ = dict(plex_env)
    environ["PLEX_TOKEN"] = TOKEN + "\n"
    assert config.load(environ).token == TOKEN


def test_a_token_broken_across_lines_is_refused_before_it_reaches_a_header(plex_env):
    """An HTTP client raises a ValueError embedding the whole header, which leaks it."""
    from plex_axi import config
    from plex_axi.errors import ConfigError

    broken = dict(plex_env)
    broken["PLEX_TOKEN"] = TOKEN[:5] + "\n" + TOKEN[5:]
    try:
        config.load(broken)
    except ConfigError as exc:
        assert exc.code == "BAD_TOKEN"
    else:  # pragma: no cover
        raise AssertionError("a token with an embedded newline was accepted")


def test_url_userinfo_is_stripped_and_registered(plex_env):
    from plex_axi import config

    environ = dict(plex_env)
    environ["PLEX_URL"] = "http://someone:hunter2000@plex.example.com:32400"
    resolved = config.load(environ)
    assert resolved.base_url == "http://plex.example.com:32400"
    assert "hunter2000" not in output.redact(resolved.base_url + " hunter2000")
