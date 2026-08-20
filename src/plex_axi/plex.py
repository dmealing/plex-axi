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

from . import __version__
from .errors import ApiError, AuthFailed, ConnectionFailed
from .errors import NotFound as AxiNotFound

#: Environment variable naming which music section to use when a server has
#: more than one. The ``--section`` flag overrides it.
SECTION_VAR = "PLEX_SECTION"

#: The libtype a music library section reports. Plex models a music library as a
#: library *of artists*; albums and tracks are its children.
MUSIC_SECTION_TYPE = "artist"

_hardened = False


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
    """
    session = requests.Session()
    retry = Retry(
        total=None,
        connect=retries,
        read=0,
        redirect=0,
        status=0,
        backoff_factor=0.3,
        allowed_methods=frozenset(["GET", "HEAD"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def connect(config, *, session=None) -> PlexServer:
    """Open a connection to the configured server, translating every failure."""
    harden()
    session = build_session() if session is None else session
    try:
        server = PlexServer(config.base_url, config.token, session=session, timeout=config.timeout)
    except Unauthorized as exc:
        raise _auth_error(exc) from None
    except (BadRequest, NotFound) as exc:
        raise _reachability_error(config, exc) from None
    except requests.exceptions.RequestException as exc:
        raise _transport_error(config, exc) from None
    # Belt and braces: even with the configuration forced off, pin the instance
    # attribute that `url()` actually consults.
    server._showSecrets = False
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
                "Run the command again with `--timeout 60` if the server is slow to wake",
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
    """A well-formed HTTP answer that was not a Plex Media Server.

    A 404 on ``/`` means something is listening on that address and it is not
    Plex -- a reverse proxy, a router admin page, the wrong port. Saying
    "unreachable" there would be the wrong failure reported as another.
    """
    return ConnectionFailed(
        f"{config.base_url} answered, but not as a Plex Media Server",
        help_lines=[
            "Check the port; a Plex Media Server serves its API on 32400 by default",
            f"Run `plex-axi api / ` to see what {config.base_url} actually returns",
        ],
        code="NOT_PLEX",
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
    response body, not the traceback.
    """
    help_lines = list(help_lines or [])
    if isinstance(exc, Unauthorized):
        return _auth_error(exc)
    if isinstance(exc, NotFound):
        return AxiNotFound(
            f"{what} was not found on this server",
            help_lines=help_lines or ["Run `plex-axi` to see what this server holds"],
            code="NOT_FOUND",
        )
    if isinstance(exc, requests.exceptions.RequestException):
        return ConnectionFailed(
            f"the server stopped answering while reading {what}",
            help_lines=help_lines or ["Run `plex-axi doctor` to re-check the connection"],
            code="UNREACHABLE",
        )
    status, reason = describe_api_error(exc)
    prefix = f"{status} " if status else ""
    return ApiError(
        f"the server refused to return {what} ({prefix}{reason})",
        help_lines=help_lines,
        code="REFUSED",
    )
