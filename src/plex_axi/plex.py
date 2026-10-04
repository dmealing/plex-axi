"""The Plex connection: hardening, transport policy, and error translation.

Everything that talks to a Plex Media Server goes through here. Three things
this module owns are load-bearing and easy to lose:

* **Token hygiene.** plexapi will embed the token in any URL it hands out --
  artwork, stream and web URLs all call ``url(..., includeToken=True)`` -- and a
  single ``show_secrets`` line in a user's ``~/.config/plexapi/config.ini``
  turns that on for *every* ``url()`` call. :func:`harden` forces it off in all
  three places it can be read from, rather than relying on this tool never
  calling that method.
* **Transport policy.** plexapi has no retry and its timeout is a module-level
  global, so an explicit per-invocation timeout and a single connect retry have
  to be supplied by hand through a ``requests`` session.
* **Error translation.** Nothing from plexapi reaches the agent. Its exceptions
  carry the whole response body and its own package name; both are replaced with
  a sentence and a recovery command.
"""

from __future__ import annotations

import contextlib
import os
import re
from xml.etree.ElementTree import ParseError

# plexapi reads `log.show_secrets` from the environment at import time and uses
# it to decide whether to install its own secrets filter. Setting the variable
# before the import is the only way to influence that decision, and it is set
# rather than defaulted because the point is to override a user's config file.
os.environ["PLEXAPI_LOG_SHOW_SECRETS"] = "false"

# Auto-reload turns a missing attribute into a silent extra request per object.
# On a list of twenty albums, reading a field one of them happens not to carry
# fetches all twenty again -- and the caller sees a slow command rather than a
# reason. Off, an absent value stays absent and is reported as null, which is
# the honest answer; the two commands that genuinely need more data ask for it
# outright, with `reload(checkFiles=True)` and with a metadata fetch.
os.environ["PLEXAPI_PLEXAPI_AUTORELOAD"] = "false"

import plexapi
import requests
from plexapi.exceptions import BadRequest, NotFound, Unauthorized
from plexapi.server import PlexServer
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import __version__, output, shapes
from .errors import ApiError, AuthFailed, ConnectionFailed
from .errors import NotFound as AxiNotFound

#: Environment variable naming which music section to use when a server has
#: more than one. The ``--section`` flag overrides it.
SECTION_VAR = "PLEX_SECTION"

#: The libtype a music library section reports. Plex models a music library as a
#: library *of artists*; albums and tracks are its children.
MUSIC_SECTION_TYPE = "artist"

_hardened = False


class MalformedAnswer(requests.exceptions.RequestException):
    """A 200 whose body is not something a Plex Media Server sends.

    The client library checks the status code and then parses whatever came
    back, so three different non-answers used to reach the commands as three
    different wrong things: an empty body became ``None`` and the first attribute
    read raised ``AttributeError`` (reported as a bug in this tool), JSON or a
    truncated document raised ``ParseError`` (the same), and an HTML page parsed
    cleanly into an element with no children -- which every list command then
    reported as a successful, empty answer. All three are a transport fault:
    something answered, and it was not Plex's API.

    A ``RequestException`` so that every existing ``except`` around a request
    already treats it as the transport failing rather than as a refusal.
    """

    EMPTY = shapes.EMPTY
    UNPARSEABLE = shapes.UNPARSEABLE
    FOREIGN = shapes.FOREIGN

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class Server(PlexServer):
    """The client library's server, refusing an answer that is not Plex's.

    ``query`` is the one method every read in the client library goes through,
    which makes it the one place a non-answer can be caught before a command
    mistakes it for an empty library.
    """

    def query(self, key, method=None, headers=None, params=None, timeout=None, **kwargs):
        sender = method or self._session.get
        seen: dict = {}

        def recording(url, **sent):
            seen["response"] = sender(url, **sent)
            return seen["response"]

        # The client library logs the method by name.
        recording.__name__ = getattr(sender, "__name__", "get")
        try:
            data = super().query(
                key, method=recording, headers=headers, params=params, timeout=timeout, **kwargs
            )
        except ParseError:
            body = getattr(seen.get("response"), "text", "") or ""
            raise MalformedAnswer(shapes.answer_kind(body)) from None
        if sender != self._session.get:
            # A write legitimately answers with nothing: `/:/rate` and a
            # playlist deletion both return an empty 200.
            return data
        if data is None:
            raise MalformedAnswer(MalformedAnswer.EMPTY)
        if shapes.is_foreign_root(data.tag):
            raise MalformedAnswer(MalformedAnswer.FOREIGN)
        return data


def harden() -> None:
    """Make it impossible for this process to print a Plex token.

    Three separate switches decide whether plexapi reveals the token, and a tool
    that only avoids ``includeToken=True`` is relying on the least of them.
    """
    global _hardened
    if _hardened:
        return

    # 1. The environment, which `PlexConfig.get` consults before the config file.
    os.environ["PLEXAPI_LOG_SHOW_SECRETS"] = "false"
    os.environ["PLEXAPI_PLEXAPI_AUTORELOAD"] = "false"

    # 2. The parsed config file, in case it was read before this module loaded.
    with contextlib.suppress(AttributeError):  # a config shape change must not crash
        plexapi.CONFIG.data.setdefault("log", {})["show_secrets"] = "false"

    # 3. The logging filter itself. plexapi installs it at import time *unless*
    #    show_secrets was true then, so a user's config could have skipped it.
    #    Re-adding an already-present filter is a no-op in the stdlib.
    plexapi.log.addFilter(plexapi.logfilter)

    # 4. Identify the tool rather than the machine. Left alone, plexapi publishes
    #    the operating system's hostname as X-Plex-Device-Name and the machine's
    #    MAC address as X-Plex-Client-Identifier, both of which then sit in the
    #    server's device list. Plex does need the identifier to be stable per
    #    machine, so it is derived from the MAC rather than dropped -- a hash is
    #    just as stable and does not hand over the address itself.
    plexapi.X_PLEX_PRODUCT = "plex-axi"
    plexapi.X_PLEX_VERSION = __version__
    plexapi.X_PLEX_DEVICE = "plex-axi"
    plexapi.X_PLEX_DEVICE_NAME = "plex-axi"
    plexapi.X_PLEX_IDENTIFIER = _client_identifier()
    plexapi.X_PLEX_PLATFORM_VERSION = ""

    # The headers must be updated in place. `plexapi.server` binds the dict at
    # import time (`from plexapi import BASE_HEADERS`), so rebinding the module
    # attribute would leave the copy that is actually sent untouched -- which is
    # the sort of near-miss that looks like it worked.
    plexapi.BASE_HEADERS.clear()
    plexapi.BASE_HEADERS.update(plexapi.config.reset_base_headers())

    _hardened = True


def _client_identifier() -> str:
    """A stable per-machine client id that is not the machine's MAC address."""
    import hashlib
    import uuid

    digest = hashlib.sha256(f"plex-axi:{uuid.getnode()}".encode()).hexdigest()
    return f"plex-axi-{digest[:24]}"


def build_session(*, retries: int = 1) -> requests.Session:
    """A requests session that retries once on a failed connection.

    plexapi ships no retry at all. One connect retry covers the case this tool
    actually hits -- a server that is awake but was not ready for the first
    packet -- without turning a genuine outage into a long wait. Reads are
    deliberately not retried: a read that failed halfway may have been served.

    ``read=False`` rather than ``read=0``, and the difference is the error the
    caller sees. With ``0`` urllib3 counts a read timeout against a budget that
    is already spent and raises ``MaxRetryError``, which ``requests`` reports as
    a ``ConnectionError`` -- so a server that accepted the connection and was
    merely slow was described as unreachable, with advice to check its address.
    ``False`` re-raises the read timeout as itself.
    """
    session = requests.Session()
    retry = Retry(
        total=None,
        connect=retries,
        read=False,
        redirect=0,
        status=0,
        backoff_factor=0.3,
        allowed_methods=frozenset(["GET", "HEAD"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def connect(config, *, session=None, token: str | None = None) -> PlexServer:
    """Open a connection to the configured server, translating every failure.

    ``token`` overrides the configured one, which is how ``--user`` re-opens the
    same connection as somebody else. It is a parameter rather than a second
    code path so that the hardening, the transport policy and the error
    translation are the ones every connection gets.
    """
    harden()
    session = build_session() if session is None else session
    # `--debug` earns its advertisement here: the base URL and the timeout are
    # the two settings behind most connection failures, and both come from the
    # environment rather than the command line. Redacted like everything else --
    # a URL can carry userinfo.
    output.debug(f"connecting to {config.base_url} timeout={config.timeout:g}s")
    try:
        server = Server(
            config.base_url, token or config.token, session=session, timeout=config.timeout
        )
    except Unauthorized as exc:
        raise _auth_error(exc) from None
    except MalformedAnswer as exc:
        raise _malformed_error(config.base_url, exc) from None
    except (BadRequest, NotFound) as exc:
        raise _reachability_error(config, exc) from None
    except requests.exceptions.RequestException as exc:
        raise _transport_error(config, exc) from None
    if not getattr(server, "machineIdentifier", None):
        # Well-formed XML that is not a Plex root: every identifier this tool
        # prints is built on the machine identifier, so its absence is the
        # difference between a Plex Media Server and something else answering.
        raise _not_plex(config.base_url)
    # Belt and braces: even with the configuration forced off, pin the instance
    # attribute that `url()` actually consults.
    server._showSecrets = False
    output.debug(f"connected: {server.friendlyName} version {server.version}")
    return server


# --------------------------------------------------------------- translation


#: Plex answers a rejected token with an XML body carrying its own status text.
#: The distinction between a token that was never valid and one that has aged
#: out is only ever knowable from that text -- Plex uses 401 for both -- so it is
#: read here and reported as "rejected" when the server says neither.
_EXPIRED = re.compile(r"(?i)\bexpire[sd]?\b")
_INVALID = re.compile(r"(?i)not\s+authoriz|could\s+not\s+be\s+authenticated|invalid\s+token")


def classify_auth_failure(message: str) -> str:
    """Return ``expired``, ``invalid`` or ``rejected`` for a 401's response text."""
    if _EXPIRED.search(message):
        return "expired"
    if _INVALID.search(message):
        return "invalid"
    return "rejected"


_AUTH_DETAIL = {
    "expired": (
        "the token has expired",
        "Plex's newer sign-in issues short-lived tokens; mint a fresh one and re-export PLEX_TOKEN",
    ),
    "invalid": (
        "the token was not accepted",
        "Check PLEX_TOKEN against a token for this server; a token is per-account, not per-server",
    ),
    "rejected": (
        "the server rejected the token",
        "Re-read the token from the Plex web app and re-export PLEX_TOKEN",
    ),
}


def _auth_error(exc: Exception) -> AuthFailed:
    kind = classify_auth_failure(str(exc))
    detail, hint = _AUTH_DETAIL[kind]
    return AuthFailed(
        f"Plex refused the request: {detail}",
        help_lines=[hint, "Run `plex-axi doctor` to re-check the environment and the connection"],
        code=f"TOKEN_{kind.upper()}",
    )


def _transport_error(config, exc: Exception) -> ConnectionFailed:
    if isinstance(exc, requests.exceptions.Timeout):
        return ConnectionFailed(
            f"{config.base_url} did not answer within {config.timeout:g}s",
            help_lines=[
                "Run the command again with `--timeout 60`; the server is reachable but slow",
                "Check that PLEX_URL names the server on the local network, not plex.tv",
            ],
            code="TIMEOUT",
        )
    return ConnectionFailed(
        f"{config.base_url} could not be reached",
        help_lines=[
            "Check that PLEX_URL is the server's address and port, e.g. http://plex.example.com:32400",
            "Run `plex-axi doctor` to see which check fails",
        ],
        code="UNREACHABLE",
    )


def _reachability_error(config, exc: Exception) -> ConnectionFailed:
    """A well-formed HTTP answer that was not a working Plex Media Server.

    A 404 on ``/`` means something is listening on that address and it is not
    Plex -- a reverse proxy, a router admin page, the wrong port. Saying
    "unreachable" there would be the wrong failure reported as another.

    A 5xx is the opposite case and must not be given the same name: a Plex Media
    Server answers 503 while it starts and while it runs maintenance, so calling
    that "not Plex" sends the caller to check a port that is correct.
    """
    status, reason = describe_api_error(exc)
    if status >= 500:
        return _server_error(status, reason, what=config.base_url)
    return _not_plex(config.base_url)


def _not_plex(base_url: str) -> ConnectionFailed:
    return ConnectionFailed(
        f"{base_url} answered, but not as a Plex Media Server",
        help_lines=[
            "Check the port; a Plex Media Server serves its API on 32400 by default",
            "Run `plex-axi doctor` to see which check fails",
        ],
        code="NOT_PLEX",
    )


def _server_error(status: int, reason: str, *, what: str) -> ConnectionFailed:
    return ConnectionFailed(
        f"{what} answered {status} ({reason}): the server is starting, busy or failing",
        help_lines=[
            "Wait a moment and run the command again; a Plex Media Server answers 503 while "
            "it starts and while it runs maintenance",
            "Run `plex-axi doctor` to see whether it has recovered",
        ],
        code="SERVER_ERROR",
    )


_MALFORMED = {
    MalformedAnswer.EMPTY: "an empty answer",
    MalformedAnswer.UNPARSEABLE: "an answer that is not XML, or is cut short",
}


def _malformed_error(what: str, exc: MalformedAnswer) -> ConnectionFailed:
    """Something answered 200 and it was not Plex's API."""
    if exc.kind == MalformedAnswer.FOREIGN:
        return _not_plex(what)
    return ConnectionFailed(
        f"{what} sent {_MALFORMED[exc.kind]}",
        help_lines=[
            "Something between this machine and the server is answering in its place, or cut "
            "the answer short; check PLEX_URL names the server itself",
            "Run `plex-axi doctor` to see which check fails",
        ],
        code="BAD_RESPONSE",
    )


#: Plex error bodies are HTML or XML documents. Only the status line is useful
#: to an agent, and passing the body through would leak both noise and, on some
#: reverse proxies, the internal hostname.
_STATUS_LINE = re.compile(r"^\((\d{3})\)\s*([^;]*);")


def describe_api_error(exc: Exception) -> tuple:
    """Reduce a plexapi exception to ``(status, reason)`` fit to print."""
    text = str(exc)
    match = _STATUS_LINE.match(text)
    if match:
        return int(match.group(1)), match.group(2).strip().replace("_", " ")
    return 0, "the server refused the request"


def translate(exc: Exception, *, what: str, help_lines=None):
    """Convert a plexapi exception into the structured error the agent reads.

    Nothing from plexapi survives this boundary: not the package name, not the
    response body, not the traceback -- except on stderr under `--debug`, where
    the original text is what makes a translated message diagnosable. It goes
    through the same redactor as stdout.
    """
    output.debug(f"translating {type(exc).__name__} while reading {what}: {exc}")
    help_lines = list(help_lines or [])
    if isinstance(exc, Unauthorized):
        return _auth_error(exc)
    if isinstance(exc, NotFound):
        return AxiNotFound(
            f"{what} was not found on this server",
            help_lines=help_lines or ["Run `plex-axi` to see what this server holds"],
            code="NOT_FOUND",
        )
    if isinstance(exc, ParseError):
        exc = MalformedAnswer(MalformedAnswer.UNPARSEABLE)
    if isinstance(exc, MalformedAnswer):
        return _malformed_error(f"the server, asked for {what},", exc)
    if isinstance(exc, requests.exceptions.Timeout):
        return ConnectionFailed(
            f"the server did not answer in time while reading {what}",
            help_lines=[
                "Run the command again with `--timeout 60`; the server is reachable but slow",
                "Run `plex-axi doctor` to re-check the connection",
            ],
            code="TIMEOUT",
        )
    if isinstance(exc, requests.exceptions.RequestException):
        return ConnectionFailed(
            f"the server stopped answering while reading {what}",
            help_lines=help_lines or ["Run `plex-axi doctor` to re-check the connection"],
            code="UNREACHABLE",
        )
    status, reason = describe_api_error(exc)
    if status >= 500:
        return _server_error(status, reason, what=f"the server, asked for {what},")
    prefix = f"{status} " if status else ""
    return ApiError(
        f"the server refused to return {what} ({prefix}{reason})",
        # A refusal with nothing under it is a dead end: the caller has no way
        # to tell a bad argument from a broken server, so there is always a
        # next step, even when the caller of this function had none to offer.
        help_lines=help_lines
        or [
            "Run the command again with `--debug` for what the server answered",
            "Run `plex-axi doctor` to check the server and the library",
        ],
        code="REFUSED",
    )
