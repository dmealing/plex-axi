"""`plex-axi sessions` -- what the server believes is playing.

This is the cross-check. When something on the network says it is playing and
the library says otherwise, one of them is wrong, and this is the only command
that reports Plex's own side of that disagreement.

It reports *sessions*, not clients: the player's name arrives as an attribute of
a stream the server is already serving. Nothing here can start, stop or address
anything -- listing what is playing is a read, and this tool does only reads.
"""

from __future__ import annotations

from axi_toolkit.plex.filters import stars
from axi_toolkit.plex.ids import media_id_for

from ..argspec import Command, Sub
from ..music import number
from ..output import HelpBlock
from ..plex import translate

COMMAND = Command(
    name="sessions",
    summary="List the streams the server currently believes are playing",
    usage="usage: plex-axi sessions",
    default_sub="sessions",
    subs=(Sub(name="sessions", summary="List active sessions"),),
    notes=(
        "music sessions are listed first; anything else is counted, not detailed",
        "nothing here can start, stop or address a stream: listing one is a read",
    ),
    examples=("plex-axi sessions",),
)


def COMMAND_FOR(name: str) -> Command:
    return COMMAND


def run(ctx, name: str, sub: str, parsed):
    server = ctx.server()
    try:
        sessions = list(server.sessions())
    except Exception as exc:
        raise translate(exc, what="the active sessions") from None

    music = [s for s in sessions if getattr(s, "type", "") == "track"]
    other = len(sessions) - len(music)

    doc = {"count": f"{len(sessions)} active"}
    if not sessions:
        doc["sessions"] = "0 streams are playing right now"
        return doc

    if music:
        doc["music"] = [_row(session, server.machineIdentifier) for session in music]
    else:
        doc["music"] = "0 of the active streams is music"
    if other:
        # Counted rather than listed: video is out of scope, and a music tool
        # reporting film titles would be answering a question nobody asked.
        doc["other"] = f"{other} non-music stream(s), not detailed here"

    if music:
        doc["help"] = HelpBlock(
            [
                "Run `plex-axi track <key>` for one of these in full: tags, analysis version "
                "and file details"
            ]
        )
    return doc


def _row(session, machine_identifier: str) -> dict:
    player = getattr(session, "player", None)
    album_artist = getattr(session, "grandparentTitle", "") or ""
    performer = getattr(session, "originalTitle", "") or ""
    return {
        "key": number(getattr(session, "ratingKey", None)),
        "media_id": media_id_for(machine_identifier, session),
        "title": getattr(session, "title", "") or "",
        "artist": performer or album_artist,
        "album": getattr(session, "parentTitle", "") or "",
        "device": _device(player),
        "state": getattr(player, "state", "") or "",
        "rating": stars(getattr(session, "userRating", None)),
    }


def _device(player) -> str:
    """The name of the thing playing, from whichever attribute carries one.

    **A real `<Player>` has no `title`.** It carries `device`, `product` and
    `platform`, which are three different strings -- "Sonos", "Plex for Sonos",
    "Sonos" -- and this column read `title` alone, so the one field that says
    *where the music is playing* was empty on every real session.

    The order is most-specific first: `device` is the name of the box, `product`
    the application on it, `platform` the family it belongs to. Any of them
    beats an empty cell, and reporting which is which is not worth a column.
    """
    for attribute in ("title", "device", "product", "platform"):
        value = getattr(player, attribute, "") or ""
        if value:
            return value
    return ""
