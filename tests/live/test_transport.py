"""T: what the tool says when the network or the server misbehaves.

The faults are injected by the proxy, in front of the real server, because a
mock that raises a chosen exception can only test the branch somebody already
thought of. Two defects lived here for that reason: a slow server was reported
as unreachable (the unit test injected the exception the fix was supposed to
produce), and an answer that was not Plex's was reported as a bug in this tool
or, worse, as an empty library.
"""

from __future__ import annotations

import pytest

COMMANDS = [
    ("search", "--rated-min", "4", "--limit", "2"),
    ("playlist", "list"),
    ("sessions",),
    ("genres",),
    ("recent",),
    ("doctor",),
]

BODIES = {
    "empty": (b"", "BAD_RESPONSE"),
    "json": (b'{"MediaContainer": {}}', "BAD_RESPONSE"),
    "html": (b"<!DOCTYPE html><html><head><title>Login</title></head><body></html>", "NOT_PLEX"),
}


def _settled(result, code: str) -> None:
    assert "INTERNAL_ERROR" not in result.out, result.argv
    if result.argv != ("doctor",):
        assert f"code: {code}" in result.out, (result.argv, result.out[:200])
    assert "help[" in result.out, result.argv


@pytest.mark.parametrize("kind", sorted(BODIES))
def test_d08_a_200_that_is_not_plexs_is_a_transport_error(run, proxy, kind):
    body, code = BODIES[kind]
    for argv in COMMANDS:
        proxy.fault = {"status": 200, "body": body, "ctype": "text/html"}
        result = run(*argv)
        assert result.code == 1, (kind, argv, result.out[:200])
        _settled(result, code)


def test_d08_a_truncated_answer_is_not_a_bug_in_the_tool(run, proxy):
    for argv in COMMANDS:
        proxy.fault = {"truncate": True, "match": "/library"}
        result = run(*argv)
        assert "INTERNAL_ERROR" not in result.out, argv
        assert result.code in (0, 1)


@pytest.mark.parametrize("status", [500, 503])
def test_d08_a_busy_server_is_not_called_not_plex(run, proxy, status):
    for argv in COMMANDS:
        proxy.fault = {"status": status, "body": b"<html><body>unavailable</body></html>"}
        result = run(*argv)
        assert result.code == 1, argv
        assert "NOT_PLEX" not in result.out, argv
        _settled(result, "SERVER_ERROR")


def test_d08_one_failing_path_after_a_good_connection_is_not_an_empty_success(run, proxy):
    proxy.fault = {"status": 200, "body": b"<html><body>x</body></html>", "match": "/playlists"}
    result = run("playlist", "list")
    assert result.code == 1 and "0 audio playlists" not in result.out
    proxy.fault = {"status": 200, "body": b"", "match": "/status/sessions"}
    result = run("sessions")
    assert result.code == 1 and "0 streams" not in result.out


def test_d08_the_home_view_exits_zero_whatever_the_server_does(run, proxy):
    for fault in (
        {"status": 200, "body": b""},
        {"status": 200, "body": b"<html><body>x</body></html>"},
        {"status": 503},
        {"status": 401, "body": b"<html>Unauthorized</html>"},
        {"drop": True},
    ):
        proxy.fault = fault
        result = run()
        assert result.code == 0, fault
        assert "not reached" in result.line("server:"), fault


def test_d09_a_slow_server_is_a_timeout_with_the_advice_that_fixes_it(run, proxy):
    proxy.fault = {"delay": 4}
    result = run("--timeout", "1", "search", "--rated-min", "4", timeout=60)
    assert result.code == 1
    assert "code: TIMEOUT" in result.out
    assert "did not answer within 1s" in result.out
    assert "--timeout 60" in result.out
    assert "UNREACHABLE" not in result.out
    assert result.seconds < 15, "the timeout was not bounded"


def test_d09_a_slow_path_mid_command_is_a_timeout_too(run, proxy):
    proxy.fault = {"delay": 4, "match": "/playlists"}
    result = run("--timeout", "1", "playlist", "list", timeout=60)
    assert result.code == 1
    assert "code: TIMEOUT" in result.out and "--timeout 60" in result.out


def test_a_wrong_token_is_reported_as_one(run, proxy):
    """Simulated: a server that trusts its local network accepts any token."""
    proxy.fault = {"status": 401, "body": b'<Response code="1001" status="Unauthorized"/>'}
    result = run("search", "--rated-min", "4")
    assert result.code == 1
    assert "TOKEN_" in result.out and "PLEX_TOKEN" in result.out


def test_a_dropped_connection_is_unreachable(run, proxy):
    proxy.fault = {"drop": True}
    result = run("search", "--rated-min", "4", timeout=60)
    assert result.code == 1 and "code: UNREACHABLE" in result.out


def test_nothing_listening_and_no_such_host_are_unreachable_and_fast(run):
    for url in ("http://127.0.0.1:9", "http://plex-axi-live-test.invalid:32400"):
        result = run("search", "--rated-min", "4", env={"PLEX_URL": url}, timeout=60)
        assert result.code == 1, url
        assert "code: UNREACHABLE" in result.out, url
        assert result.seconds < 20, url
        home = run(env={"PLEX_URL": url}, timeout=60)
        assert home.code == 0


def test_something_that_is_not_plex_at_all(live, stub):
    """Well-formed XML with no machine identifier: answered, but not as Plex."""
    stub.canned["/"] = '<MediaContainer size="0"/>'
    result = live.run("doctor", via=stub)
    assert result.code == 1 and "not as a Plex Media Server" in result.out
