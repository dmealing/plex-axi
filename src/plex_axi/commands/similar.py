"""`plex-axi similar <key>` -- Plex's own sonic analysis, exposed.

Plex analyses every track it can and can answer "what sounds like this" from
that analysis, with a numeric distance for each answer. Nothing in the Plex
tooling landscape exposes it: not a CLI, not an MCP server, not a wrapper. It is
"more like this" with no language model in the loop and no free-text guessing --
the server already knows.

The ``distance`` column is the reason this is a command rather than a curiosity.
Without it a caller cannot tell a close match from the tail of the list, and the
server's own default cut-off (0.25) is invisible.

A track that has not been analysed is not similar to nothing: it is unanswerable.
The empty state says which of the two happened, because `track <key>` reports
``analysis`` and this command reads it before blaming the library.
"""

from __future__ import annotations

from ..argspec import Command, Flag, Sub
from ..errors import UsageError
from ..ids import validate_rating_key
from ..music import available_fields, default_fields, rows_for, with_track_artist
from ..output import HelpBlock
from ..plex import translate
from ._common import article, parse_limit, project, select_fields

DEFAULT_LIMIT = 20

COMMAND = Command(
    name="similar",
    summary="List tracks Plex's analysis finds sonically similar, with distances",
    usage="usage: plex-axi similar <rating_key> [flags]",
    default_sub="similar",
    subs=(
        Sub(
            name="similar",
            args=("<rating_key>",),
            flags=(
                Flag("--limit", "<n>", default=DEFAULT_LIMIT),
                Flag(
                    "--max-distance",
                    "<0.0-1.0>",
                    note="smaller is closer; the server's own default is 0.25",
                ),
                Flag("--fields", "<a,b,c>", note="replaces the default columns"),
            ),
            summary="Find sonically similar tracks",
        ),
    ),
    notes=(
        "distance is the server's own sonic distance: 0 is identical, larger is further away",
        "a seed with no `analysis` version has not been analysed and can return nothing at all",
    ),
    examples=(
        "plex-axi similar 12345",
        "plex-axi similar 12345 --max-distance 0.1 --limit 5",
    ),
)


def COMMAND_FOR(name: str) -> Command:
    return COMMAND


def run(ctx, name: str, sub: str, parsed):
    key = validate_rating_key(parsed.positionals[0], invocation="plex-axi similar")
    limit = parse_limit(parsed.get("limit"), default=DEFAULT_LIMIT)
    max_distance = _parse_distance(parsed.get("max_distance"))

    server = ctx.server()
    try:
        seed = server.fetchItem(f"/library/metadata/{key}")
    except Exception as exc:
        raise translate(
            exc,
            what=f"track {key}",
            help_lines=["Run `plex-axi search --track '<title>'` to find a rating key"],
        ) from None

    found = getattr(seed, "type", "") or "item"
    if found != "track":
        raise UsageError(
            f"{key} is {article(found)} {found}, and sonic similarity is per track",
            help_lines=[
                "Run `plex-axi search --artist '<name>' --type track` to find a track key",
            ],
            code="WRONG_ITEM_TYPE",
        )

    try:
        items = seed.sonicallySimilar(limit=limit, maxDistance=max_distance)
    except Exception as exc:
        raise translate(
            exc,
            what="the sonic neighbours of that track",
            help_lines=[
                f"Run `plex-axi track {key}` to check its `analysis` version first",
                "Sonic analysis is a server-side feature; an unanalysed library has no neighbours",
            ],
        ) from None

    rows = rows_for("track", list(items), server.machineIdentifier)
    distances = [_distance(item) for item in items]
    for row, distance in zip(rows, distances):
        row["distance"] = distance

    chosen = parsed.get("fields")
    fields = select_fields(
        chosen,
        [*available_fields("track"), "distance"],
        ["distance", *default_fields("track")],
    )
    if not chosen:
        fields = with_track_artist(fields, rows)

    doc = {
        "seed": f"{seed.title} - {getattr(seed, 'grandparentTitle', '') or ''}".strip(" -"),
        "count": f"{len(rows)} returned",
    }
    if max_distance is not None:
        doc["max_distance"] = f"{max_distance:g}"

    if not rows:
        doc["tracks"] = "0 sonically similar tracks"
        doc["help"] = HelpBlock(
            [
                # `track` never prints a bare `0` here: an unanalysed item reads
                # "0 (not analysed: ...)" and one the server said nothing about
                # reads "not reported by this server". Advice naming a value the
                # tool cannot emit sends the reader looking for something that
                # is not there.
                f"Run `plex-axi track {key}` and read `analysis`: a version number means it "
                "was analysed, anything else means this seed has nothing to work from",
                "Run the same command with a larger `--max-distance` to widen the search",
            ]
        )
        return doc

    doc["tracks"] = project(rows, fields)
    doc["help"] = HelpBlock(
        [
            "Run `plex-axi track <key>` for a result's tags, analysis version and file details",
            "distance is the server's own measure; sort order is the server's, closest first",
        ]
    )
    return doc


def _distance(item):
    value = getattr(item, "distance", None)
    if value in (None, ""):
        # The attribute is absent when the server answered without one, which is
        # different from a distance of zero and must not be reported as one.
        return None
    return round(float(value), 4)


def _parse_distance(raw):
    if raw in (None, ""):
        return None
    try:
        value = float(str(raw))
    except ValueError:
        raise UsageError(
            f"--max-distance needs a number between 0 and 1, got {raw!r}",
            help_lines=["Run the command again with `--max-distance 0.25`"],
            code="BAD_DISTANCE",
        ) from None
    if not 0 <= value <= 1:
        raise UsageError(
            f"--max-distance is between 0 and 1, got {value:g}",
            help_lines=["Run the command again with `--max-distance 0.25`"],
            code="BAD_DISTANCE",
        )
    return value
