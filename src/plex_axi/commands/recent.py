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

import shlex

from ..argspec import Command, Flag, Sub
from ..music import available_fields, default_fields, rows_for, with_track_artist
from ..output import HelpBlock
from ..plex import translate
from ._common import parse_libtype, parse_limit, project, select_fields

DEFAULT_LIMIT = 20
MAX_LIMIT = 500

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
    limit = parse_limit(parsed.get("limit"), default=DEFAULT_LIMIT, maximum=MAX_LIMIT)
    section = ctx.section()

    try:
        items = list(getattr(section, METHODS[libtype])(maxresults=limit))
    except Exception as exc:
        raise translate(exc, what=f"recently added {libtype}s") from None

    rows = rows_for(libtype, items, section._server.machineIdentifier)
    chosen = parsed.get("fields")
    fields = select_fields(chosen, available_fields(libtype), default_fields(libtype))
    if libtype == "track" and not chosen:
        fields = with_track_artist(fields, rows)

    doc = {"count": f"{len(rows)} most recent", "library": section.title}
    if not rows:
        doc[f"{libtype}s"] = f"0 {libtype}s in this library"
        doc["help"] = HelpBlock(
            ["Run `plex-axi doctor` to confirm the library has finished scanning"]
        )
        return doc

    added = _added_span(rows)
    if added:
        doc["added"] = added
    doc[f"{libtype}s"] = project(rows, fields)
    # Every flag that shaped this answer is carried into the follow-up, so
    # "look further back" means further back through *these* rows rather than
    # through the album default the bare command would fall back to.
    carried = f"--type {libtype}" + (f" --fields {shlex.quote(chosen)}" if chosen else "")
    lines = [
        f"Run `plex-axi {libtype} <key>` for what a row omits: when it was last played, "
        "its tags, and the durable guid",
        f"Run `plex-axi recent {carried} --limit {min(limit * 5, MAX_LIMIT)}` to look further back",
    ]
    if "added" not in fields:
        lines.append(
            f"Run `plex-axi recent --type {libtype} --fields key,title,added` for each row's date"
        )
    doc["help"] = HelpBlock(lines)
    return doc


def _added_span(rows: list) -> str:
    """When the rows shown arrived, as one line rather than one column per row.

    The list is ordered by this date, so the span says what a per-row column
    would -- how far back the answer reaches -- for the price of one line instead
    of a fifth column on every row, which is what kept the default schema here
    above AXI's four.
    """
    dates = sorted(row["added"] for row in rows if row.get("added"))
    if not dates:
        return ""
    if dates[0] == dates[-1]:
        return dates[0]
    return f"{dates[-1]} back to {dates[0]}"
