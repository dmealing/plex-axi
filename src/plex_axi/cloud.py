"""Plex for Sonos: the cloud playback route, and what it costs to use it.

A Sonos speaker is not a Plex client on the local network and never appears in
``/clients``. Plex reaches one through a service of its own: the speaker is
linked to a **plex.tv account**, an endpoint at ``sonos.plex.tv`` lists the
linked speakers, and a playback command sent there is forwarded to the speaker,
which then streams from the Plex Media Server. Plex for Sonos is a current
product, not a discontinued one, and for somebody with Sonos speakers and no
home-automation system it is the only thing that makes a media id useful.

Three facts about this route are load-bearing and all three are in `--help`:

* **It needs a different credential, and the difference is not cosmetic.**
  ``PLEX_TOKEN`` is a token for one server. plex.tv answers it with a flat
  ``401`` -- measured, not assumed. So the account token has its own variable,
  :data:`~plex_axi.playback.ACCOUNT_TOKEN_VAR`, it is registered as a secret the
  moment it is read exactly like every other credential here, and the failure
  says *which* credential is missing rather than surfacing plex.tv's status code
  and leaving an operator to guess that the token they already exported is the
  wrong kind.
* **It goes over Plex's cloud, so anything else watching the house will be
  stale.** A local playback command is a request to the Plex Media Server and a
  home-automation system watching that server sees the session appear. This one
  is a request to Plex's service; the session still turns up eventually, but the
  dispatch itself is invisible to everything on the local network. That is
  information for the operator, not a refusal: it is exactly why the playback
  gate is off by default, and an operator who has opened it has answered the
  question this warning asks.
* **It needs the server to be reachable from outside.** The command hands the
  speaker the server's address, and this tool points at ``PLEX_URL``, which is
  deliberately the address on the local network. Where remote access is not
  working, or ``PLEX_URL`` names a host only the local network can resolve, the
  speaker will be told to stream from somewhere it cannot reach.

**This is deliberately not the client library's Sonos client.** ``plexapi.sonos``
reaches ``PlexSonosClient`` through ``MyPlexAccount.sonos_speakers()``, and the
account object is the thing this package has never let into its process: it
resolves speakers by name, it dispatches playback, and it is one attribute
access away from every module here. So this file does what :mod:`plex_axi.users`
does for ``--user`` -- asks the one documented endpoint with ``requests`` and
parses the answer with the standard library. The request shapes below are
transcribed from ``plexapi.sonos``, which is the only public description of
them; nothing is authored. See ``tests/test_no_dispatch.py`` for why that
distinction is the part of the old rule that survived intact.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree

import requests

from .errors import ApiError, AuthFailed, ConnectionFailed
from .playback import CLOUD, MEDIA_TYPE, PLAYQUEUE_PATH, PROVIDER, Target

#: Plex's Sonos service. It emulates the player control API closely, which is
#: why the playback parameters below are the local ones with three additions.
SONOS = "sonos.plex.tv"
RESOURCES = f"https://{SONOS}/resources"
PLAY = f"https://{SONOS}/player/playback/playMedia"

#: What this route is, in one line, printed beside every Sonos row and in the
#: answer to a play that took it. An operator running anything else that watches
#: the server should read this once.
ROUTE_NOTE = (
    "the sonos route goes through Plex's cloud rather than the local server, so anything "
    "watching this server for a session will lag the command; it also needs the server to be "
    "reachable from outside the local network"
)


def speakers(config, token: str) -> list:
    """The Sonos speakers linked to this plex.tv account, as targets."""
    response = _get(RESOURCES, token, timeout=config.timeout)
    status = getattr(response, "status_code", 0)
    if status in (401, 403):
        raise _refusal(status)
    if status != 200:
        # The body is a plex.tv document and may carry account details, so only
        # the status reaches the caller.
        raise ApiError(
            f"{SONOS} refused to list the speakers on this account ({status})",
            help_lines=[
                "Plex for Sonos needs a Plex Pass subscription and speakers linked to the "
                "account; check both in the Plex app",
                "Every local client still works without it: run `plex-axi clients`",
            ],
            code="SONOS_REFUSED",
        )
    return _parse(getattr(response, "text", "") or "")


def play(server, config, target: Target, item, playqueue: int, token: str) -> str:
    """Send one playback command to a Sonos speaker through Plex's cloud."""
    from urllib.parse import urlsplit

    import plexapi

    parts = urlsplit(config.base_url)
    params = {
        "type": MEDIA_TYPE,
        "providerIdentifier": PROVIDER,
        "containerKey": f"{PLAYQUEUE_PATH}/{playqueue}?own=1",
        "key": item.key,
        "offset": 0,
        "machineIdentifier": server.machineIdentifier,
        "protocol": parts.scheme,
        "address": parts.hostname or "",
        "port": parts.port or "",
        "commandID": 1,
        # Two different credentials, which is the part of this request most
        # easily got wrong. The header carries the *account* token, because the
        # request is to plex.tv's service; this parameter carries the *server*
        # token, because it is what the speaker will use to stream. Transcribed
        # from `plexapi.sonos`, not inferred.
        "X-Plex-Client-Identifier": plexapi.X_PLEX_IDENTIFIER,
        "X-Plex-Token": config.token,
        "X-Plex-Target-Client-Identifier": target.machine_identifier,
    }
    response = _get(
        PLAY,
        token,
        timeout=config.timeout,
        params=params,
        headers={"X-Plex-Target-Client-Identifier": target.machine_identifier},
    )
    status = getattr(response, "status_code", 0)
    if status in (401, 403):
        raise _refusal(status)
    if status not in (200, 201, 204):
        raise ApiError(
            f"{SONOS} refused the playback command ({status})",
            help_lines=[
                "The speaker may have gone offline; run `plex-axi clients` to re-list them",
                ROUTE_NOTE,
            ],
            code="SONOS_REFUSED",
        )
    return f"sent to {target.title} through {SONOS}"


# -------------------------------------------------------------------- helpers


def _get(url: str, token: str, *, timeout: float, params=None, headers=None):
    from .plex import build_session, harden

    harden()
    import plexapi

    sent = dict(plexapi.BASE_HEADERS)
    sent["X-Plex-Token"] = token
    sent["Accept"] = "application/xml"
    sent.update(headers or {})
    try:
        return build_session().get(url, headers=sent, params=params, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise _unreachable(exc, timeout) from None


def _refusal(status: int) -> AuthFailed:
    """A 401 or 403 from plex.tv, named as the credential problem it almost always is.

    The message says which variable, because the mistake this reports is
    specific and common: `PLEX_TOKEN` is a server token, plex.tv does not accept
    it, and an operator who has one exported reads a bare 401 as "my token is
    wrong" rather than "my token is the wrong kind".
    """
    from .playback import ACCOUNT_TOKEN_VAR

    return AuthFailed(
        f"{SONOS} refused the account token ({status})",
        help_lines=[
            f"{ACCOUNT_TOKEN_VAR} must be a **plex.tv account** token, which is a broader "
            "credential than PLEX_TOKEN: a server token is refused here with exactly this "
            "status, whatever it can do against the server",
            "Sign in to plex.tv and read the token from the Plex web app; see "
            "https://support.plex.tv/articles/204059436",
            "Every local client still works without it: run `plex-axi clients`",
        ],
        code="SONOS_TOKEN_REFUSED",
    )


def _unreachable(exc: Exception, timeout: float) -> ConnectionFailed:
    timed_out = isinstance(exc, requests.exceptions.Timeout)
    return ConnectionFailed(
        f"{SONOS} did not answer within {timeout:g}s"
        if timed_out
        else f"{SONOS} could not be reached",
        help_lines=[
            "The sonos route is the one part of this tool that needs Plex's cloud; every "
            "local client works without it",
            "Run `plex-axi clients` to see what the server itself can reach",
        ],
        code="SONOS_UNREACHABLE",
    )


def _parse(text: str) -> list:
    """The speaker list as targets. A malformed answer is not a crash."""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        raise ApiError(
            f"{SONOS} answered, but not with a list of speakers",
            help_lines=["Run `plex-axi clients` for the local clients, which need no cloud call"],
            code="SONOS_UNPARSEABLE",
        ) from None
    return [_target(element) for element in root]


def _target(element) -> Target:
    """One speaker as a target.

    ``lanIP`` is on the element and is deliberately not read: it is an address
    on the operator's own network, nothing here needs it, and this repository is
    public.
    """
    capabilities = tuple(
        part.strip()
        for part in (element.get("protocolCapabilities") or "").split(",")
        if part.strip()
    )
    return Target(
        title=element.get("title") or "",
        machine_identifier=element.get("machineIdentifier") or "",
        product=element.get("product") or "",
        device=element.get("deviceClass") or element.get("platform") or "",
        route=CLOUD,
        capabilities=capabilities,
        element=element,
    )
