"""`plex-axi clients` -- the targets `play` can address, and only those.

This command exists only while the playback gate is open; with it closed the
noun is unknown and the out-of-scope message is the one it has always been. See
:mod:`plex_axi.playback` for why invisibility is part of the gate rather than a
nicety.

What it adds over `api /clients` is the part a caller would otherwise have to
know: a client that answers is not necessarily a client that can play, because
``protocolCapabilities`` is what says so and a client offering `timeline` and
`navigation` alone will accept a playback command and do nothing. The ones that
cannot play are counted rather than hidden, so "my speaker is not listed" and
"my speaker cannot be addressed this way" are different answers. It also asks
the Sonos route when, and only when, that credential is present, and says which
routes it consulted either way -- an empty list that never asked plex.tv and an
empty list that did are not the same result.

**No addresses are printed, from either route.** A `/clients` element carries
``host``, ``address`` and ``port``, and a Sonos resource carries ``lanIP``; none
of them is needed to address a target, and this repository is public.
"""

from __future__ import annotations

from .. import playback
from ..argspec import Command, Sub
from ..output import HelpBlock

COMMAND = Command(
    name="clients",
    summary="List the players this server can start music on",
    usage="usage: plex-axi clients",
    default_sub="clients",
    subs=(Sub(name="clients", summary="List the playback targets"),),
    notes=(
        "only targets advertising the `playback` capability are listed; the rest are counted, "
        "because a client that cannot play will accept the command and do nothing",
        "a Plex client is visible only while its app is running and on the same network as "
        "the server, so this list is a snapshot rather than an inventory",
        f"the `{playback.CLOUD}` route is consulted only when {playback.ACCOUNT_TOKEN_VAR} is "
        "set, and the answer says which routes ran",
        "no network address is printed for any target; `--client` takes the title or the "
        "machine_id",
        f"this command exists only while {playback.ALLOW_VAR}={playback.ALLOW_VALUE}",
    ),
    examples=("plex-axi clients",),
)


def COMMAND_FOR(name: str) -> Command:
    return COMMAND


def run(ctx, name: str, sub: str, parsed):
    # The same latch `play` uses. Listing targets cannot start anything, but it
    # is still half of the capability the gate hides, so it is behind the gate
    # rather than merely behind the dispatcher.
    playback.require(ctx.environ, action="list playback targets")

    server = ctx.server()
    found = playback.survey(server, ctx.config(), ctx.environ)
    targets, hidden = found["targets"], found["hidden"]

    doc = {"count": f"{len(targets)} of {len(targets) + len(hidden)} can play"}
    if targets:
        doc["clients"] = [target.row() for target in targets]
    else:
        doc["clients"] = "0 targets can play right now"
    if hidden:
        doc["hidden"] = (
            f"{len(hidden)} target(s) answered but do not advertise {playback.PLAYBACK_CAPABILITY}"
        )
    doc["routes"] = found["routes"]

    if any(target.route == playback.CLOUD for target in targets):
        from ..cloud import ROUTE_NOTE

        doc["note"] = ROUTE_NOTE

    doc["help"] = HelpBlock(_help(targets))
    return doc


def _help(targets: list) -> list:
    if not targets:
        return [
            "Open a Plex client on the network and run `plex-axi clients` again",
            "Run `plex-axi sessions` to see whether the server thinks anything is playing",
        ]
    first = targets[0]
    return [
        f"Run `plex-axi play <rating_key> --client '{first.title}'` to see what would happen",
        f"Run `plex-axi play <rating_key> --client '{first.title}' {playback.CONFIRM_FLAG}` "
        "to start it",
        "Run `plex-axi search --artist '<name>'` for a rating key to play",
    ]
