"""`plex-axi search` -- the structured, per-field music search.

This is the command the tool exists for. Every published Plex CLI, MCP server
and agent wrapper takes a single free-text ``query`` string and hands it to the
server as one blob, which is why "an artist and a song title" reliably returns
nothing: the two values are searched as one. Here each value is a flag, each
flag is a Plex field, and the whole predicate is evaluated by Plex.

``--query`` exists for the case where the caller genuinely has one unstructured
string and nothing else. Its help says plainly that it is the weak path, because
an agent that reaches for it when it knows the artist has thrown away the thing
that makes the search work.
"""

from __future__ import annotations

from ..argspec import Command, Flag, Sub
from ..ids import handoff
from ..music import (
    available_fields,
    build_filters,
    default_fields,
    rows_for,
    run_search,
    with_track_artist,
)
from ..output import HelpBlock
from ._common import (
    count_line,
    describe_filters,
    parse_libtype,
    parse_limit,
    project,
    select_fields,
)

DEFAULT_LIMIT = 20

_FLAGS = (
    Flag("--artist", "<name>", note="album artist, searched on artist.title"),
    Flag("--album", "<title>", note="searched on album.title"),
    Flag("--track", "<title>", note="searched on track.title"),
    Flag("--genre", "<name>", note="searched on artist.genre; run `plex-axi genres` for the list"),
    Flag("--mood", "<name>", note="run `plex-axi moods` for the list"),
    Flag("--style", "<name>", note="run `plex-axi styles` for the list"),
    Flag("--year", "<year>", note="the album's release year"),
    Flag("--rated-min", "<stars>", note="0-5 stars, the scale ratings print in"),
    Flag(
        "--query",
        "<text>",
        note=(
            "THE WEAK PATH: one unstructured string matched against the title only. "
            "If you know the artist or the album, use --artist/--album instead -- "
            "a combined string is why every other Plex tool misses"
        ),
    ),
    Flag("--type", "<track|album|artist>", default="track", note="what to return"),
    Flag("--limit", "<n>", default=DEFAULT_LIMIT),
    Flag("--fields", "<a,b,c>", note="add columns; run --help for the list per type"),
    Flag("--sort", "<field:dir>", note="e.g. addedAt:desc, titleSort, userRating:desc"),
    Flag(
        "--no-group",
        boolean=True,
        note="show every pressing; by default identical titles are collapsed server-side",
    ),
)

COMMAND = Command(
    name="search",
    summary="Search the music library field by field, server-side",
    usage="usage: plex-axi search [--artist <name>] [--track <title>] [flags]",
    default_sub="search",
    subs=(Sub(name="search", flags=_FLAGS, summary="Run one structured search"),),
    notes=(
        "each flag is searched on its own Plex field; that is the whole point of this tool",
        "ratings are stars (0-5) in and out, so a rating in a result can be passed to --rated-min",
        f"track fields: {', '.join(available_fields('track'))}",
        f"album fields: {', '.join(available_fields('album'))}",
        f"artist fields: {', '.join(available_fields('artist'))}",
        "identical track titles are collapsed with Plex's own `group=title`; --no-group shows each",
        "read-only: this command cannot change anything on the server",
    ),
    examples=(
        "plex-axi search --artist 'Example Artist' --track 'Example Track'",
        "plex-axi search --genre Jazz --rated-min 4 --limit 10",
        "plex-axi search --artist 'Example Artist' --type album",
        "plex-axi search --mood mellow --sort userRating:desc --fields key,title,artist,rating",
    ),
)


def COMMAND_FOR(name: str) -> Command:
    return COMMAND


def run(ctx, name: str, sub: str, parsed):
    libtype = parse_libtype(parsed.get("type"))
    limit = parse_limit(parsed.get("limit"), default=DEFAULT_LIMIT)
    filters, described = build_filters(parsed, libtype)
    query = parsed.get("query")
    fields = select_fields(parsed.get("fields"), available_fields(libtype), default_fields(libtype))

    if not filters and not query:
        return _nothing_asked(libtype)

    section = ctx.section()
    result = run_search(
        section,
        libtype=libtype,
        filters=filters,
        title=query,
        sort=parsed.get("sort"),
        limit=limit,
        # Grouping collapses one song appearing on an album, a compilation and a
        # live record into one row. It only means anything for tracks.
        group=libtype == "track" and not parsed.get("no_group"),
    )

    rows = rows_for(libtype, result.items)
    if libtype == "track":
        fields = with_track_artist(fields, rows)

    doc: dict = {"count": count_line(len(rows), result.total)}
    if result.grouped:
        doc["grouped"] = result.grouped
    if query:
        doc["query"] = query
    if described:
        doc["filters"] = described

    if not rows:
        return _empty(doc, libtype, described, query)

    doc[f"{libtype}s"] = project(rows, fields)
    doc.update(_handoff_block(section, result.items))
    doc["help"] = HelpBlock(_next_steps(libtype, rows, result, limit))
    return doc


def _handoff_block(section, items) -> dict:
    """The labelled identifier for the first result, when there is exactly one.

    A single match is the case where the caller is about to use the id, so the
    block is worth its tokens there and noise on a list of twenty.
    """
    if len(items) != 1:
        return {}
    return {"item": handoff(section._server.machineIdentifier, items[0])}


def _next_steps(libtype, rows, result, limit) -> list:
    lines = []
    key = rows[0]["key"] if len(rows) == 1 else "<key>"
    if len(rows) == 1:
        lines.append(f"Run `plex-axi {libtype} {key}` for the full detail view")
    else:
        lines.append(f"Run `plex-axi {libtype} <key>` for one item's detail and its media id")
    if libtype == "track":
        lines.append(f"Run `plex-axi similar {key}` for sonically similar tracks with distances")
    if result.total > len(rows):
        lines.append(f"Run the same search with `--limit {min(result.total, limit * 5)}` for more")
    if result.grouped == "title":
        lines.append("Run the same search with `--no-group` to see every pressing of each title")
    return lines


def _nothing_asked(libtype: str):
    return {
        "error": "search needs at least one field to search on",
        "code": "NO_FILTERS",
        "help": HelpBlock(
            [
                "Run `plex-axi search --artist '<name>'` to search by artist",
                "Run `plex-axi search --artist '<name>' --track '<title>'` to combine fields",
                f"Run `plex-axi search --genre '<genre>' --type {libtype}` after `plex-axi genres`",
            ]
        ),
        "__exit_code__": 2,
    }


def _empty(doc: dict, libtype: str, described: list, query):
    """A definitive zero, naming exactly what matched nothing.

    An empty result is an answer, not a failure: exit 0. What makes it usable is
    saying which predicate was applied and handing back the vocabulary the
    server will actually accept, so the next attempt is informed rather than a
    guess with different spelling.
    """
    applied = describe_filters(described)
    if query:
        applied = f'{applied} title~"{query}"'.strip()
    doc[f"{libtype}s"] = f"0 {libtype}s matched {applied}" if applied else f"0 {libtype}s"
    lines = []
    if any(row["field"].endswith("genre") for row in described):
        lines.append("Run `plex-axi genres` for the genres this library actually uses")
    if any(row["field"].endswith("mood") for row in described):
        lines.append("Run `plex-axi moods` for the moods this library actually uses")
    if any(row["field"].endswith("style") for row in described):
        lines.append("Run `plex-axi styles` for the styles this library actually uses")
    if len(described) > 1:
        lines.append("Drop one flag at a time: every flag narrows the query independently")
    if libtype != "track":
        lines.append(f"Run the same search with `--type track` instead of `--type {libtype}`")
    else:
        lines.append("Run the same search with `--type artist` to check the artist exists at all")
    doc["help"] = HelpBlock(lines)
    return doc
