"""M9: doctor, which has to be right about *which* check failed.

A diagnostic that reports the wrong failure is worse than no diagnostic, so each
of these asserts on the check that failed as well as on the exit code.
"""

from __future__ import annotations

import plexapi.exceptions
import pytest
import requests

from conftest import FakePlex, FakeSession, UnreachableSession


def test_every_check_passes_against_a_healthy_server(server, cli_run):
    result = cli_run("doctor")
    assert result.code == 0
    assert result.line("healthy:") == "healthy: true"
    for check in ("environment", "server", "music library", "filter fields"):
        assert check in result


def test_no_environment_is_a_clear_error_and_a_non_zero_exit(cli_run):
    """The acceptance case: no configuration at all, nothing to guess from."""
    result = cli_run("doctor", env={})
    assert result.code == 1
    assert "PLEX_URL and PLEX_TOKEN not set" in result
    assert "export PLEX_URL" in result
    # It must not have tried to connect to anything.
    assert "server" not in result.line("checks[")


def test_an_unreachable_server_fails_at_the_server_check(unreachable, cli_run):
    result = cli_run("doctor")
    assert result.code == 1
    assert "could not be reached" in result
    assert "environment,ok" in result


def test_a_timeout_is_reported_as_a_timeout_not_as_unreachable(monkeypatch, cli_run):
    """Two different failures with two different fixes."""
    from plex_axi import plex

    monkeypatch.setattr(
        plex,
        "build_session",
        lambda **kwargs: UnreachableSession(requests.exceptions.ReadTimeout("slow")),
    )
    result = cli_run("doctor")
    assert result.code == 1
    assert "did not answer within" in result
    assert "--timeout 60" in result


@pytest.mark.parametrize(
    ("status_text", "expected"),
    [
        ("User could not be authenticated", "TOKEN_INVALID"),
        ("The access token has expired", "TOKEN_EXPIRED"),
        ("Nope", "TOKEN_REJECTED"),
    ],
)
def test_a_rejected_token_distinguishes_invalid_from_expired(status_text, expected):
    """Plex answers 401 to both; only its own text tells them apart."""
    from plex_axi.plex import _auth_error

    error = _auth_error(plexapi.exceptions.Unauthorized("(401) unauthorized; " + status_text))
    assert error.code == expected


def test_a_wrong_token_fails_at_the_server_check_with_a_token_error(monkeypatch, cli_run):
    from plex_axi import plex

    fake = FakePlex(token="a-different-token-000001")
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))
    result = cli_run("doctor")
    assert result.code == 1
    assert "TOKEN_INVALID" in result or "refused the request" in result
    assert "plexapi" not in result.out.lower()


def test_a_server_with_no_music_library_fails_at_the_library_check(monkeypatch, cli_run):
    from plex_axi import plex

    fake = FakePlex()
    original = fake._sections

    def _video_only():
        text = original()
        return text.replace('type="artist"', 'type="movie"')

    fake._sections = _video_only
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))
    result = cli_run("doctor")
    assert result.code == 1
    assert "no music library" in result
    assert "server,ok" in result


def test_two_music_libraries_ask_which_one_rather_than_guessing(monkeypatch, cli_run):
    from plex_axi import plex

    fake = FakePlex(music_sections=2)
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))
    result = cli_run("doctor")
    assert result.code == 1
    assert "2 music libraries" in result
    assert "--section" in result
    assert "Example Music" in result


def test_the_named_section_is_honoured_from_the_flag_and_the_environment(
    monkeypatch, cli_run, plex_env
):
    from plex_axi import plex

    fake = FakePlex(music_sections=2)
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))

    by_flag = cli_run("--section", "Example Music", "doctor")
    assert by_flag.code == 0

    environ = dict(plex_env)
    environ["PLEX_SECTION"] = "Example Vinyl Rips"
    by_env = cli_run("doctor", env=environ)
    assert by_env.code == 0
    assert "Example Vinyl Rips" in by_env


def test_a_library_that_cannot_answer_about_its_fields_fails_that_check(monkeypatch, cli_run):
    """A library still scanning advertises no fields, and a search built on it
    would return an empty answer that looks like a real one."""
    from plex_axi import plex
    from plex_axi.commands import doctor

    fake = FakePlex()
    monkeypatch.setattr(plex, "build_session", lambda **kwargs: FakeSession(fake))
    monkeypatch.setattr(doctor, "REQUIRED_FIELDS", ("title", "aFieldNoLibraryHas"))
    result = cli_run("doctor")
    assert result.code == 1
    assert "does not advertise" in result
