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

from axi_toolkit.plex.filters import parse_sort
from axi_toolkit.plex.ids import handoff

from ..argspec import Command, Flag, Sub
from ..music import (
    available_fields,
    default_fields,
    label_filters,
    nearest_titles,
    performer_honoured,
    plan_search,
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
    quoted,
    select_fields,
)

DEFAULT_LIMIT = 20

_FLAGS = (
    Flag(
        "--artist",
        "<name>",
        note="album artist, searched on artist.title; on a track search the track's own "
        "performer matches as well, which is how a compilation track is found",
    ),
    Flag("--album", "<title>", note="searched on album.title"),
    Flag(
        "--track",
        "<title>",
        note="searched on track.title, which on this field also matches the performer",
    ),
    Flag("--genre", "<name>", note="searched on artist.genre; run `plex-axi genres` for the list"),
    Flag("--mood", "<name>", note="run `plex-axi moods` for the list"),
    Flag("--style", "<name>", note="run `plex-axi styles` for the list"),
    Flag("--year", "<year>", note="the album's release year, four digits"),
    Flag(
        "--rated-min",
        "<stars>",
        note=(
            "0-5 stars, the scale ratings print in; 0 is the bottom of the scale "
            "and filters nothing, so `--rated-min 0.5` is what asks for the rated ones"
        ),
    ),
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
    Flag(
        "--fields",
        "<a,b,c>",
        note="replaces the default columns; run --help for the list per type",
    ),
    Flag(
        "--sort",
        "<field:dir>",
        note="e.g. addedAt:desc, titleSort, userRating:desc; the direction is asc or desc",
    ),
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
    subs=(Sub(name="search", flags=_FLAGS, summary="Run one structured search", needs_flags=True),),
    notes=(
        "each flag is searched on its own Plex field; that is the whole point of this tool",
        "a name matches by word: each word typed must begin a word of the title, in the "
        "order typed, so `exa tra` finds `Example Track` and `xample` finds nothing",
        "apostrophes, quotes, hyphens and ellipses are searched in their typographic "
        "spellings too; a comma in a value is dropped, because the server reads it as OR",
        "accents are not folded by the server: when a name matches nothing, the nearest "
        "real titles are listed under `nearest` to search on exactly",
        "ratings are stars (0-5) in and out, so a rating in a result can be passed to --rated-min",
        "dates (`added`) are in this machine's local time zone, not the server's and not UTC",
        f"track fields: {', '.join(available_fields('track'))}",
        f"album fields: {', '.join(available_fields('album'))}",
        f"artist fields: {', '.join(available_fields('artist'))}",
        "identical track titles are collapsed with Plex's own `group=title`; --no-group shows each",
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
    plan = plan_search(parsed, libtype)
    sort = parse_sort(parsed.get("sort"))
    chosen = parsed.get("fields")
    fields = select_fields(chosen, available_fields(libtype), default_fields(libtype))

    if not plan.filters and not plan.title:
        return _nothing_asked(libtype, plan.note)

    section = ctx.section()
    result = _search(section, plan, libtype, sort, limit, parsed)
    if plan.performer and not performer_honoured(result.items, plan.texts["artist"]):
        # The rows do not carry the name anywhere, so the unadvertised field did
        # not run and the page is an unfiltered one. Ask again on the album
        # artist alone, and say that is what happened.
        plan = plan_search(parsed, libtype, performer=False)
        result = _search(section, plan, libtype, sort, limit, parsed)
        plan.matching.append(
            "this server did not apply the track's performer, so --artist matched the "
            "album artist only"
        )

    rows = rows_for(libtype, result.items, section._server.machineIdentifier)
    described = label_filters(section, plan.described, libtype=libtype)
    if libtype == "track" and not chosen:
        fields = with_track_artist(fields, rows)

    doc: dict = {"count": count_line(len(rows), result.total)}
    if result.grouped:
        doc["grouped"] = result.grouped
    if "query" in plan.texts:
        doc["query"] = plan.texts["query"]
    if described:
        doc["filters"] = described
    if plan.matching:
        doc["matching"] = plan.matching
    if plan.note:
        # A flag that was accepted and deliberately applied nothing has to say
        # so where the result is, not only in `--help`.
        doc["note"] = plan.note

    if not rows:
        return _empty(doc, section, libtype, described, plan)

    doc[f"{libtype}s"] = project(rows, fields)
    doc.update(_handoff_block(section, result.items))
    doc["help"] = HelpBlock(_next_steps(libtype, rows, result, limit))
    return doc


def _search(section, plan, libtype, sort, limit, parsed):
    return run_search(
        section,
        libtype=libtype,
        filters=plan.filters,
        title=plan.title,
        sort=sort,
        limit=limit,
        # Grouping collapses one song appearing on an album, a compilation and a
        # live record into one row. It only means anything for tracks.
        group=libtype == "track" and not parsed.get("no_group"),
        performer=plan.performer,
    )


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
        # Not "and its media id": every row above carries one. Advice that
        # sends a caller to fetch what they already have is the same defect as
        # advice naming a value the tool never prints.
        lines.append(
            f"Run `plex-axi {libtype} <key>` for what a row omits: when it was last "
            "played, its tags, and the durable guid"
        )
    if libtype == "track":
        lines.append(f"Run `plex-axi similar {key}` for sonically similar tracks with distances")
    if result.total > len(rows):
        lines.append(f"Run the same search with `--limit {min(result.total, limit * 5)}` for more")
    if result.grouped == "title":
        lines.append("Run the same search with `--no-group` to see every pressing of each title")
    return lines


def _nothing_asked(libtype: str, note: str = ""):
    return {
        "error": "search needs at least one field to search on",
        "code": "NO_FILTERS",
        "help": HelpBlock(
            [
                # First, when it applies: the caller *did* pass a flag, and
                # being told they passed none without being told why theirs did
                # not count is the kind of error that gets retried verbatim.
                note,
                "Run `plex-axi search --artist '<name>'` to search by artist",
                "Run `plex-axi search --artist '<name>' --track '<title>'` to combine fields",
                f"Run `plex-axi search --genre '<genre>' --type {libtype}` after `plex-axi genres`",
            ]
        ),
        "__exit_code__": 2,
    }


def _empty(doc: dict, section, libtype: str, described: list, plan):
    """A definitive zero, naming exactly what matched nothing.

    An empty result is an answer, not a failure: exit 0. What makes it usable is
    saying which predicate was applied and handing back strings the server will
    actually accept, so the next attempt is informed rather than a guess with
    different spelling.

    The recovery used to be two hints that pointed at each other -- "run the
    same search with --type artist" and, from there, "with --type track" -- so a
    name typed in ASCII against a title with a typographic apostrophe looped
    between two zeros and read as "not in the library". The nearest real titles
    are fetched instead, from the one search on the server that folds accents
    and punctuation.
    """
    applied = describe_filters(described)
    query = plan.texts.get("query")
    if query:
        applied = f'{applied} title ~ "{query}"'.strip()
    doc[f"{libtype}s"] = f"0 {libtype}s matched {applied}" if applied else f"0 {libtype}s"

    nearest = nearest_titles(section, plan.texts) if plan.texts else []
    lines = []
    if nearest:
        doc["nearest"] = [
            {name: row[name] for name in ("type", "key", "title", "artist")} for row in nearest
        ]
        seen = set()
        for row in nearest:
            flag = row["_flag"]
            if flag in seen:
                continue
            seen.add(flag)
            option = "--track" if flag == "query" else f"--{flag}"
            lines.append(
                f"Run `plex-axi search {option} {quoted(row['title'])} --type {libtype}` to "
                f"search on the nearest {row['type']} title this library holds"
            )
    elif plan.texts:
        lines.append(
            "Nothing close to that text in this library's own free-text search either; "
            "check the spelling, or search on fewer words"
        )
    if any(row["field"].endswith("genre") for row in described):
        lines.append("Run `plex-axi genres` for the genres this library actually uses")
    if any(row["field"].endswith("mood") for row in described):
        lines.append("Run `plex-axi moods` for the moods this library actually uses")
    if any(row["field"].endswith("style") for row in described):
        lines.append("Run `plex-axi styles` for the styles this library actually uses")
    if len(described) > 1:
        lines.append("Drop one flag at a time: every flag narrows the query independently")
    if "artist" in plan.texts and libtype == "track":
        lines.append(
            "--artist on a track search matches the album artist or the track's performer; "
            "a name that is neither is not in this library under that spelling"
        )
    if libtype != "track":
        lines.append(f"Run the same search with `--type track` instead of `--type {libtype}`")
    doc["help"] = HelpBlock(lines)
    return doc
