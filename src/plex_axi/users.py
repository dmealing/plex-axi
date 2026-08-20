"""`--user`: reading the library as somebody else, and saying what that costs.

Ratings and playlists are **per account**. Plex holds one set for the admin and
a different set for every person the server is shared with, so "what is rated
four stars" and "what is on the kitchen playlist" have as many answers as there
are accounts. `--user` is how a caller asks for one of the other ones.

Two facts about it are not incidental and both are in `--help`:

* **It is admin-only.** The list of per-user access tokens is the owner's, and a
  token that is itself a shared one gets a 401 asking for it.
* **It needs plex.tv.** Everything else in this tool works with the cloud down,
  because ``PLEX_URL`` names the server on the local network. This one cannot:
  the mapping from a username to that user's token for this server exists only
  in Plex's account service. So `--user` is the single command surface that
  stops working when plex.tv does, and the failure says exactly that rather than
  arriving as an unexplained 401.

**This is deliberately not the client library's user switch.** That path costs
three round-trips, two of them to plex.tv, and reaches it through the account
object -- the same object that resolves speakers by name and dispatches playback
to them. This module asks plex.tv one question with ``requests`` and parses the
answer, which is one round-trip instead of two and keeps the playback surface
out of the process entirely. See ``tests/test_no_dispatch.py`` for why the second
half of that sentence is the important one.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree

import requests

from .errors import ApiError, AuthFailed, AxiError, ConnectionFailed
from .output import register_secret

#: The owner's sharing record for one server: who it is shared with, and the
#: access token each of them uses against *this* machine. One GET, admin-only.
SHARED_SERVERS = "https://plex.tv/api/servers/{machine}/shared_servers"

#: Where the round-trip goes, named in every failure so the cause is never a
#: mystery when the local server is plainly answering.
PLEX_TV = "plex.tv"


def connect_as(server, config, name: str):
    """Return a connection to the same server authenticated as ``name``."""
    from .plex import connect

    token = access_token(config, server.machineIdentifier, name)
    return connect(config, token=token)


def access_token(config, machine_identifier: str, name: str) -> str:
    """One user's access token for this server, from the owner's sharing record."""
    shares = _shared_servers(config, machine_identifier)
    wanted = str(name).strip().casefold()
    for share in shares:
        if wanted and wanted in {
            share["username"].casefold(),
            share["email"].casefold(),
            share["id"].casefold(),
        }:
            token = share["token"]
            if not token:
                raise AxiError(
                    f"plex.tv has no access token for {name!r} on this server",
                    help_lines=[
                        "The share may not have been accepted yet; check it in Plex's own "
                        "sharing settings",
                        "Run the command without `--user` to read as the account PLEX_TOKEN "
                        "belongs to",
                    ],
                    code="NO_USER_TOKEN",
                )
            # A per-user token is a bearer credential exactly like the admin's,
            # and it arrived from outside this process's configuration -- so it
            # is registered here, before anything can print it.
            register_secret(token)
            return token

    known = ", ".join(
        sorted(s["username"] or s["email"] for s in shares if s["username"] or s["email"])
    )
    raise AxiError(
        f"this server is not shared with a Plex account called {name!r}",
        help_lines=[
            f"accounts this server is shared with: {known}"
            if known
            else "this server is not shared with any other Plex account",
            "Plex Home users are managed separately and are not in the sharing record; "
            "read as one by exporting that user's own PLEX_TOKEN instead",
            "Run the command without `--user` to read as the account PLEX_TOKEN belongs to",
        ],
        code="NO_SUCH_USER",
    )


def _shared_servers(config, machine_identifier: str) -> list:
    from .plex import build_session, harden

    if not machine_identifier:
        raise AxiError(
            "this server did not report a machine identifier, so --user cannot be resolved",
            help_lines=["Run `plex-axi doctor` to check what the server answers with"],
            code="NO_MACHINE_IDENTIFIER",
        )

    harden()
    import plexapi

    headers = dict(plexapi.BASE_HEADERS)
    headers["X-Plex-Token"] = config.token
    headers["Accept"] = "application/xml"
    url = SHARED_SERVERS.format(machine=machine_identifier)

    try:
        response = build_session().get(url, headers=headers, timeout=config.timeout)
    except requests.exceptions.RequestException as exc:
        raise _unreachable(config, exc) from None

    status = getattr(response, "status_code", 0)
    if status in (401, 403):
        raise AuthFailed(
            f"{PLEX_TV} refused to list this server's shared users",
            help_lines=[
                "`--user` is admin-only: only the account that owns the server can read the "
                "per-user tokens, and PLEX_TOKEN is not that account's",
                "Run the command without `--user` to read as the account PLEX_TOKEN belongs to",
            ],
            code="NOT_SERVER_OWNER",
        )
    if status != 200:
        # The body is a plex.tv error document and may carry account details, so
        # only the status reaches the caller.
        raise ApiError(
            f"{PLEX_TV} refused to list this server's shared users ({status})",
            help_lines=[
                "`--user` needs a round-trip to plex.tv; every other command works without one",
                "Run the command without `--user` to read as the account PLEX_TOKEN belongs to",
            ],
            code="PLEX_TV_REFUSED",
        )

    return _parse(getattr(response, "text", "") or "")


def _unreachable(config, exc: Exception) -> ConnectionFailed:
    timed_out = isinstance(exc, requests.exceptions.Timeout)
    return ConnectionFailed(
        f"{PLEX_TV} did not answer within {config.timeout:g}s"
        if timed_out
        else f"{PLEX_TV} could not be reached",
        help_lines=[
            "`--user` is the one flag here that needs plex.tv: the mapping from a username to "
            "that user's token for this server exists only in Plex's account service",
            "Run the command without `--user`; everything else works against the local server "
            "with plex.tv down",
        ],
        code="PLEX_TV_UNREACHABLE",
    )


def _parse(text: str) -> list:
    """The sharing record as plain rows. A malformed answer is not a crash."""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        raise ApiError(
            f"{PLEX_TV} answered, but not with a sharing record",
            help_lines=["Run the command without `--user` to read as PLEX_TOKEN's own account"],
            code="PLEX_TV_UNPARSEABLE",
        ) from None
    return [
        {
            "username": element.get("username") or "",
            "email": element.get("email") or "",
            "id": element.get("userID") or "",
            "token": element.get("accessToken") or "",
        }
        for element in root.iter("SharedServer")
    ]
