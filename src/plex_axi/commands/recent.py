"""`plex-axi recent` -- what arrived lately, music-typed.

Plex has a generic recently-added endpoint that spans every library on the
server, which on a mixed server answers a music question with films. The music
section carries typed variants -- ``recentlyAddedTracks``, ``recentlyAddedAlbums``
and ``recentlyAddedArtists`` -- and those are what this reads.

Albums are the default because that is the unit music arrives in: importing one
record adds one artist, one album and a dozen tracks, and a track-shaped answer
buries the news in its own tracklist.
"""

from __future__ import annotations

from ..argspec import Command, Flag, Sub
from ..music import available_fields, default_fields, rows_for, with_track_artist
from ..output import HelpBlock
from ..plex import translate
from ._common import parse_libtype, parse_limit, project, select_fields

DEFAULT_LIMIT = 20

#: The typed method for each libtype. The generic `/library/recentlyAdded` is
#: deliberately not reachable from here: it spans video too.
METHODS = {
    "track": "recentlyAddedTracks",
    "album": "recentlyAddedAlbums",
    "artist": "recentlyAddedArtists",
}

COMMAND = Command(
    name="recent",
    summary="List what was added to the music library most recently",
    usage="usage: plex-axi recent [--type album] [flags]",
    default_sub="recent",
    subs=(
        Sub(
            name="recent",
            flags=(
                Flag("--type", "<track|album|artist>", default="album"),
                Flag("--limit", "<n>", default=DEFAULT_LIMIT),
                Flag("--fields", "<a,b,c>", note="replaces the default columns"),
            ),
            summary="List recent additions",
        ),
    ),
    notes=("scoped to the music library: the server-wide recently-added list spans video too",),
    examples=(
        "plex-axi recent",
        "plex-axi recent --type track --limit 50",
    ),
)


def COMMAND_FOR(name: str) -> Command:
    return COMMAND


def run(ctx, name: str, sub: str, parsed):
    libtype = parse_libtype(parsed.get("type"), default="album")
    limit = parse_limit(parsed.get("limit"), default=DEFAULT_LIMIT)
    section = ctx.section()

    try:
        items = list(getattr(section, METHODS[libtype])(maxresults=limit))
    except Exception as exc:
        raise translate(exc, what=f"recently added {libtype}s") from None

    rows = rows_for(libtype, items, section._server.machineIdentifier)
    available = [*available_fields(libtype)]
    default = default_fields(libtype)
    if "added" in available and "added" not in default:
        default = [*default, "added"]
    chosen = parsed.get("fields")
    fields = select_fields(chosen, available, default)
    if libtype == "track" and not chosen:
        fields = with_track_artist(fields, rows)

    doc = {"count": f"{len(rows)} most recent", "library": section.title}
    if not rows:
        doc[f"{libtype}s"] = f"0 {libtype}s in this library"
        doc["help"] = HelpBlock(
            ["Run `plex-axi doctor` to confirm the library has finished scanning"]
        )
        return doc

    doc[f"{libtype}s"] = project(rows, fields)
    doc["help"] = HelpBlock(
        [
            f"Run `plex-axi {libtype} <key>` for what a row omits: when it was last played, "
            "its tags, and the durable guid",
            f"Run `plex-axi recent --limit {limit * 5}` to look further back",
        ]
    )
    return doc
