"""What a Plex Media Server's answer looks like, and what one of its paths does.

Three small judgements, each learned from a real server and each a pure function
of the text in front of it:

* **Is this answer Plex's at all?** The client library checks a status code and
  parses whatever came back, so an empty body, a JSON document, a truncated one
  and somebody else's HTML page each used to arrive as something else: a crash,
  or an empty library reported as a success. :func:`answer_kind` names which of
  them a body is.
* **Does requesting this path change something?** Plex acts on a GET at several
  paths -- a rating is set, a scan is started, a client is told to play -- so
  "this tool only sends GETs" is not the same claim as "this tool only reads".
  :func:`acts_on_get` is the difference.
* **Is this attribute a credential?** The server hands out tokens under names
  that say so. :func:`is_credential_name` reads the name.

**Nothing here imports anything of this tool's.** No error class, no output
boundary, no transport, no XML library: strings in, a string or a boolean out.
The refusals and the redaction built on these judgements are written where a
command line or a document is in hand -- :mod:`plex_axi.plex` and
:mod:`plex_axi.commands.api` -- which is what lets the rules themselves be
lifted into a shared package unchanged.
"""

from __future__ import annotations

import re
from urllib.parse import unquote

# ------------------------------------------------------------- answer shapes

#: The body is nothing at all.
EMPTY = "empty"
#: The body is not XML, or stops partway through.
UNPARSEABLE = "unparseable"
#: The body is a web page: something else is answering at that address.
FOREIGN = "foreign"

_HTML_START = re.compile(r"(?is)^\s*(<!doctype\s+html|<html[\s>])")


def answer_kind(body: str) -> str:
    """Which non-answer ``body`` is, for a body that could not be read as Plex's.

    Called once parsing has failed or produced nothing. An HTML page is named
    as one even though most HTML is not well-formed XML, because "a web page is
    answering here" is the useful diagnosis and "this is not XML" is not.
    """
    text = body or ""
    if not text.strip():
        return EMPTY
    if _HTML_START.match(text):
        return FOREIGN
    return UNPARSEABLE


def is_foreign_root(tag: str) -> bool:
    """Whether a document that *did* parse is a web page rather than Plex's."""
    return str(tag).lower() == "html"


# ------------------------------------------------------- credential attributes

_CREDENTIAL_NAME = re.compile(r"(?i)token|secret|password|passwd|authkey|apikey|credential")


def is_credential_name(name: str) -> bool:
    """Whether an attribute's *name* says its value is a credential.

    ``authToken`` on the server's link to its owner's account, ``token`` on a
    delegation answer: neither value ever passed through a tool's configuration,
    so no registered literal can know it. The name is what gives it away.
    """
    return bool(_CREDENTIAL_NAME.search(str(name)))


# ------------------------------------------------------- paths that act on a GET

#: Path prefixes whose GET changes something: Plex's action namespace (rate,
#: scrobble, timeline, progress, preferences), commands relayed to a client,
#: play queues, and the server's own maintenance tasks.
ACTION_PREFIXES = ("/:/", "/player/", "/playqueues", "/butler", "/updater", "/actions/")

#: Path endings that start work on the server whatever comes before them.
ACTION_ENDINGS = (
    "/refresh",
    "/analyze",
    "/emptytrash",
    "/optimize",
    "/unmatch",
    "/match",
    "/scrobble",
    "/unscrobble",
    "/clean/bundles",
)


def normalise_path(path: str) -> str:
    """A path as a server would resolve it, for deciding what it addresses.

    Percent-decoding and collapsing repeated slashes are both things a server
    does before routing, so a check has to do them first or ``/%3A/rate`` and
    ``//:/rate`` walk past it. Lower-cased, because the routing is not
    case-sensitive either.
    """
    decoded = path
    for _ in range(3):
        again = unquote(decoded)
        if again == decoded:
            break
        decoded = again
    return re.sub(r"/{2,}", "/", decoded).lower()


def has_dot_segments(path: str) -> bool:
    """Whether a path climbs with ``.`` or ``..``, which no Plex API path does."""
    return any(segment in (".", "..") for segment in normalise_path(path).split("/"))


def acts_on_get(path: str) -> bool:
    """Whether merely requesting ``path`` changes something on the server."""
    plain = normalise_path(path).rstrip("/")
    probe = plain + "/"
    if any(probe.startswith(prefix.rstrip("/") + "/") for prefix in ACTION_PREFIXES):
        return True
    return any(plain.endswith(ending) for ending in ACTION_ENDINGS)
