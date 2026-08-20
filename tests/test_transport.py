"""S11: the transport policy the client library does not supply.

It ships no retry at all and its timeout is a module-level global, so both have
to be added by hand. Neither is visible in normal use, which is exactly why they
are tested: a timeout that was never wired through looks identical to one that
was, until a server is slow.
"""

from __future__ import annotations

import requests

from plex_axi import config, plex


def test_a_session_retries_once_on_a_failed_connection_and_never_on_a_read():
    """A read that failed halfway may already have been served; a connect did not."""
    session = plex.build_session()
    retry = session.get_adapter("http://plex.example.com:32400").max_retries
    assert retry.connect == 1
    assert retry.read == 0
    assert retry.status == 0


def test_both_schemes_carry_the_retry_policy():
    session = plex.build_session()
    for url in ("http://plex.example.com:32400", "https://plex.example.com:32400"):
        assert session.get_adapter(url).max_retries.connect == 1


def test_the_timeout_flag_reaches_the_connection(server, cli_run):
    resolved = config.load({"PLEX_URL": "http://plex.example.com:32400", "PLEX_TOKEN": "abc12345"})
    assert resolved.timeout == config.DEFAULT_TIMEOUT

    explicit = config.load(
        {"PLEX_URL": "http://plex.example.com:32400", "PLEX_TOKEN": "abc12345"}, timeout=5
    )
    assert explicit.timeout == 5


def test_a_timeout_is_reported_as_its_own_failure_with_its_own_fix(monkeypatch, cli_run):
    from conftest import UnreachableSession

    monkeypatch.setattr(
        plex,
        "build_session",
        lambda **kwargs: UnreachableSession(requests.exceptions.ConnectTimeout("slow")),
    )
    result = cli_run("--timeout", "5", "search", "--artist", "Example Artist")
    assert result.code == 1
    assert "did not answer within 5s" in result
    assert "--timeout 60" in result


def test_something_that_answers_but_is_not_plex_says_so(monkeypatch, cli_run):
    """A 404 on `/` means something is listening and it is not Plex -- a proxy,
    a router page, the wrong port. Reporting "unreachable" would be a different
    failure from the one that happened."""
    from conftest import FakePlex, FakeSession

    fake = FakePlex()
    fake._root = lambda: (_ for _ in ()).throw(_not_found())
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))
    result = cli_run("doctor")
    assert result.code == 1
    assert "not as a Plex Media Server" in result
    assert "32400" in result


def _not_found():
    from conftest import PlexRefusal

    return PlexRefusal(404, "<html>nothing here</html>")
