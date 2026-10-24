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

from plex_axi import music, plex
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
