"""The error-classification paths, one case per exception type.

A coverage report put these lines at the bottom of the suite: the branches that
turn a client-library exception into the structured error an agent reads. They
are the code that runs when something is wrong, which is when a wrong answer
costs the most, so each exception type is driven through the double's transport
(`server.fault`) wherever a command can reach it, and through the translator
directly where only a hand-built exception can.
"""

from __future__ import annotations

from xml.etree.ElementTree import ParseError

import pytest
import requests
from plexapi.exceptions import BadRequest, NotFound, Unauthorized

from conftest import ACCOUNT_TOKEN, SHARED_USERNAME, TOKEN
from plex_axi import cloud, config, music, plex
from plex_axi.errors import AnyAxiError

SEARCH = ("search", "--artist", "Example Artist")


@pytest.mark.parametrize(
    "fault, code",
    [
        ({"status": 401, "body": "token expired"}, "TOKEN_EXPIRED"),
        ({"status": 401, "body": "You are not authorized to access this"}, "TOKEN_INVALID"),
        ({"status": 401, "body": ""}, "TOKEN_REJECTED"),
        ({"status": 503, "body": "<html>starting</html>"}, "SERVER_ERROR"),
        ({"status": 500, "body": "<html>broken</html>"}, "SERVER_ERROR"),
        ({"status": 200, "body": "<MediaContainer"}, "BAD_RESPONSE"),
        ({"status": 200, "body": ""}, "BAD_RESPONSE"),
        ({"raise": requests.exceptions.ConnectionError("reset")}, "UNREACHABLE"),
        ({"raise": requests.exceptions.ReadTimeout("slow")}, "TIMEOUT"),
    ],
)
def test_a_transport_fault_on_the_search_is_classified(server, cli_run, fault, code):
    server.fault = {**fault, "match": "/library/sections/3/all"}
    result = cli_run(*SEARCH)
    assert result.code == 1
    assert f"code: {code}" in result.out
    # Nothing from the client library crosses the boundary, on either stream.
    assert "plexapi" not in (result.out + result.err).lower()


@pytest.mark.parametrize(
    "exc, code",
    [
        (Unauthorized("(401) unauthorized; token expired"), "TOKEN_EXPIRED"),
        (ParseError("syntax error"), "BAD_RESPONSE"),
        (requests.exceptions.ConnectionError("reset"), "UNREACHABLE"),
        (requests.exceptions.ReadTimeout("slow"), "TIMEOUT"),
        (NotFound("(404) not_found; /library/metadata/1"), "NOT_FOUND"),
        (BadRequest("(503) service_unavailable; busy"), "SERVER_ERROR"),
        (BadRequest("(400) bad_request; nope"), None),
        (BadRequest("something with no status line"), None),
    ],
)
def test_translate_names_every_exception_type_it_is_handed(exc, code):
    error = plex.translate(exc, what="the thing")
    assert isinstance(error, AnyAxiError)
    if code is not None:
        assert error.code == code
    else:
        assert error.help_lines, "a refusal with nothing under it is a dead end"
    assert "plexapi" not in str(error).lower()


def test_a_refusal_without_a_status_line_reports_no_status():
    assert plex.describe_api_error(BadRequest("no status here")) == (
        0,
        "the server refused the request",
    )
    assert plex.describe_api_error(BadRequest("(400) bad_request; x")) == (400, "bad request")


@pytest.mark.parametrize(
    "message, code, advice",
    [
        (
            "Unknown filter field 'nope' for libtype 'track'. Available fields: [a, b]",
            "UNKNOWN_FILTER_FIELD",
            "filter fields for track: a, b",
        ),
        (
            "Unknown operator '>=' for field 'x'. Available operators: [=, !=]",
            "UNKNOWN_OPERATOR",
            "This is a bug in plex-axi",
        ),
        ("Unknown libtype 'nope'", "UNKNOWN_LIBTYPE", "--type"),
        (
            "Unknown sort field 'nope' for libtype 'track'. Available sorts: [a, b]",
            "UNKNOWN_SORT_FIELD",
            "sort fields for track: a, b",
        ),
        ("(500) internal_server_error; boom", "SERVER_ERROR", None),
    ],
)
def test_a_filter_validation_failure_becomes_a_recoverable_error(message, code, advice):
    error = music._filter_error(BadRequest(message), "track")
    assert error.code == code
    if advice:
        assert any(advice in line for line in error.help_lines)


def test_an_unknown_operator_never_recommends_the_flag_that_failed():
    error = music._filter_error(BadRequest("Unknown operator '>=' for field 'x'"), "track")
    assert not any("--rated-min" in line for line in error.help_lines)


@pytest.mark.parametrize(
    "build, fault, token, code, says",
    [
        ({"sonos_status": 500}, None, "account", "SONOS_REFUSED", "refused to list the speakers"),
        ({"sonos_status": 403}, None, "account", "SONOS_TOKEN_REFUSED", "(403)"),
        ({}, None, "server", "SONOS_TOKEN_REFUSED", "(401)"),
        (
            {},
            {"raise": requests.exceptions.ConnectionError("reset")},
            "account",
            "SONOS_UNREACHABLE",
            "could not be reached",
        ),
        (
            {},
            {"raise": requests.exceptions.ReadTimeout("slow")},
            "account",
            "SONOS_UNREACHABLE",
            "did not answer within",
        ),
        (
            {},
            {"status": 200, "body": "<html>sign in</html"},
            "account",
            "SONOS_UNPARSEABLE",
            "not with a list of speakers",
        ),
    ],
)
def test_a_sonos_route_failure_is_classified(
    make_server, plex_env, build, fault, token, code, says
):
    fake = make_server(**build)
    if fault:
        fake.fault = {**fault, "host": cloud.SONOS, "match": "/resources"}
    with pytest.raises(AnyAxiError) as raised:
        cloud.speakers(config.load(plex_env), ACCOUNT_TOKEN if token == "account" else TOKEN)
    assert raised.value.code == code
    assert says in raised.value.message
    assert raised.value.help_lines


@pytest.mark.parametrize(
    "build, fault, code, says",
    [
        ({"plex_tv_status": 500}, None, "PLEX_TV_REFUSED", "refused to list"),
        ({"plex_tv_status": 401}, None, "NOT_SERVER_OWNER", "admin-only"),
        (
            {"plex_tv_status": 401, "plex_tv_account": False},
            None,
            "PLEX_TV_TOKEN_REJECTED",
            "does not recognise PLEX_TOKEN",
        ),
        (
            {},
            {"status": 200, "body": "<html>sign in</html"},
            "PLEX_TV_UNPARSEABLE",
            "not with a sharing record",
        ),
        (
            {},
            {"raise": requests.exceptions.ConnectionError("reset")},
            "PLEX_TV_UNREACHABLE",
            "could not be reached",
        ),
        (
            {},
            {"raise": requests.exceptions.ReadTimeout("slow")},
            "PLEX_TV_UNREACHABLE",
            "did not answer within",
        ),
    ],
)
def test_a_plex_tv_failure_behind_user_is_classified(
    make_server, cli_run, build, fault, code, says
):
    fake = make_server(**build)
    if fault:
        fake.fault = {**fault, "host": "plex.tv", "match": "/shared_servers"}
    result = cli_run("--user", SHARED_USERNAME, "search", "--track", "Example Track")
    assert result.code == 1
    assert f"code: {code}" in result.out
    assert says in result.out
    assert "plexapi" not in (result.out + result.err).lower()
