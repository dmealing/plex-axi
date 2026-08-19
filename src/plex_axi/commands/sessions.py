"""`plex-axi sessions` -- what the server believes is playing.

This is the cross-check. When something on the network says it is playing and
the library says otherwise, one of them is wrong, and this is the only command
that reports Plex's own side of that disagreement.

It reports *sessions*, not clients: the player's name arrives as an attribute of
a stream the server is already serving. Nothing here can start, stop or address
anything -- listing what is playing is a read, and this tool does only reads.
"""

from __future__ import annotations

from ..argspec import Command, Sub
from ..music import number, stars
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
        "read-only: this command reports sessions and cannot control one",
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
        doc["music"] = [_row(session) for session in music]
    else:
        doc["music"] = "0 of the active streams is music"
    if other:
        # Counted rather than listed: video is out of scope, and a music tool
        # reporting film titles would be answering a question nobody asked.
        doc["other"] = f"{other} non-music stream(s), not detailed here"

    if music:
        doc["help"] = HelpBlock(
            ["Run `plex-axi track <key>` for the detail and media id of one of these"]
        )
    return doc


def _row(session) -> dict:
    player = getattr(session, "player", None)
    album_artist = getattr(session, "grandparentTitle", "") or ""
    performer = getattr(session, "originalTitle", "") or ""
    return {
        "key": number(getattr(session, "ratingKey", None)),
        "title": getattr(session, "title", "") or "",
        "artist": performer or album_artist,
        "album": getattr(session, "parentTitle", "") or "",
        "device": getattr(player, "title", "") or "",
        "state": getattr(player, "state", "") or "",
        "rating": stars(getattr(session, "userRating", None)),
    }
