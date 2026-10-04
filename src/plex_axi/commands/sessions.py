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

from ..argspec import Command, Flag, Sub
from ..music import number
from ..output import HelpBlock
from ..plex import translate
from ..toolkit.search import playing_artist
from ._common import project, select_fields

#: Every column a session row can carry, and the four it carries by default.
#: Where the music is playing is the column this command exists for, so it is
#: the fourth; the player's state is counted in the summary line instead, and
#: the artist, album and rating are one ``--fields`` away.
FIELDS = ["key", "media_id", "title", "artist", "album", "device", "state", "rating"]
DEFAULT_FIELDS = ["key", "media_id", "title", "device"]

COMMAND = Command(
    name="sessions",
    summary="List the streams the server currently believes are playing",
    usage="usage: plex-axi sessions [--fields <a,b,c>]",
    default_sub="sessions",
    subs=(
        Sub(
            name="sessions",
            flags=(Flag("--fields", "<a,b,c>", note="replaces the default columns"),),
            summary="List active sessions",
        ),
    ),
    notes=(
        "music sessions are listed first; anything else is counted, not detailed",
        "nothing here can start, stop or address a stream: listing one is a read",
        f"columns: {', '.join(FIELDS)}",
    ),
    examples=("plex-axi sessions", "plex-axi sessions --fields key,title,artist,device,state"),
)


def COMMAND_FOR(name: str) -> Command:
    return COMMAND


def run(ctx, name: str, sub: str, parsed):
    fields = select_fields(parsed.get("fields"), FIELDS, DEFAULT_FIELDS)
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
        rows = [_row(session, server.machineIdentifier) for session in music]
        doc["states"] = _states(rows)
        doc["music"] = project(rows, fields)
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


def _states(rows: list) -> str:
    """How many music sessions are in each player state, as one phrase.

    The aggregate that lets the default row drop its ``state`` column: an agent
    asking "is anything actually playing?" reads it here without a fifth column
    on every row, and ``--fields ...,state`` says which one is which.
    """
    counts: dict = {}
    for row in rows:
        state = row.get("state") or "unknown"
        counts[state] = counts.get(state, 0) + 1
    return ", ".join(f"{n} {state}" for state, n in counts.items())


def _row(session, machine_identifier: str) -> dict:
    player = getattr(session, "player", None)
    album_artist = getattr(session, "grandparentTitle", "") or ""
    performer = getattr(session, "originalTitle", "") or ""
    return {
        "key": number(getattr(session, "ratingKey", None)),
        "media_id": media_id_for(machine_identifier, session),
        "title": getattr(session, "title", "") or "",
        "artist": playing_artist(album_artist, performer),
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
