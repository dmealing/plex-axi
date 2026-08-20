"""`plex-axi pick` -- "what would I play right now", decided by the server.

`search` answers a question the caller already has words for. `pick` answers the
one they do not: give me something to listen to, matching these constraints, and
do not give me the same thing every time.

**Everything here is a server-side predicate or it is reported as absent.** That
is the whole discipline of this command, and it is not pedantry. A client-side
filter is applied *after* the server has sliced the result set, so it fights
`--limit` exactly as it fights Plex's own `limit`: ask for ten and post-filter
and you get however many of the first ten survive, which is not ten and is not a
random sample of the matches either. So each flag maps to a Plex predicate:

* `--rated-min` to ``track.userRating>`` -- Plex's "is greater than or equals",
  the same operator `search` uses, never the `field__gte` lookalike.
* `--genre` to ``artist.genre``, because a Plex music library tags the artist.
* `--not-played-since` to ``track.lastViewedAt<<=`` with a relative date, ORed
  server-side with ``track.unplayed`` -- see :func:`_add_last_played`.
* `--exclude-live` to ``album.subformat!=Compilation,Live``, which is the shape
  Plex's own popular-tracks query uses.
* the shuffle to ``sort=random``, evaluated by the server over the whole match
  set rather than by shuffling a page that was already chosen.

A server that does not advertise one of those fields does not get a filter
quietly dropped: it gets an ``unapplied`` row naming the flag and the reason, so
the caller can tell "no track matched" from "that constraint never ran".
"""

from __future__ import annotations

from ..argspec import Command, Flag, Sub
from ..errors import AxiError
from ..ids import handoff
from ..music import (
    POINTS_PER_STAR,
    RELATIVE_DATE,
    advertised_sorts,
    available_fields,
    default_fields,
    label_filters,
    offers,
    parse_relative_date,
    parse_stars,
    rows_for,
    run_search,
    with_track_artist,
)
from ..output import HelpBlock
from ..plex import translate
from ._common import count_line, parse_limit, project, select_fields

DEFAULT_LIMIT = 10

#: Plex's own shuffle. Validated against the section's advertised sorts before
#: it is used, because plexapi refuses an unknown sort field outright and a
#: picker that failed rather than returning an unshuffled answer would be worse.
RANDOM_SORT = "random"

#: The subformats Plex tags a pressing with, and the two `--exclude-live` drops.
#: Passed as a list rather than as the comma-joined string Plex's own query
#: uses, so that each name is resolved to the numeric id Plex filters on instead
#: of reaching the URL as text that only matches if the server happens to accept
#: names there.
LIVE_SUBFORMATS = ["Compilation", "Live"]

COMMAND = Command(
    name="pick",
    summary="Choose tracks to play now, filtered and shuffled by the server",
    usage="usage: plex-axi pick [--rated-min <stars>] [--genre <name>] [flags]",
    default_sub="pick",
    subs=(
        Sub(
            name="pick",
            flags=(
                Flag("--rated-min", "<stars>", note="0-5 stars, the scale ratings print in"),
                Flag("--genre", "<name>", note="run `plex-axi genres` for this library's list"),
                Flag(
                    "--not-played-since",
                    "<period>",
                    note="e.g. 30d, 6mon, 2y; never-played tracks count as well",
                ),
                Flag(
                    "--exclude-live",
                    boolean=True,
                    note="drop pressings Plex tags Compilation or Live",
                ),
                Flag("--limit", "<n>", default=DEFAULT_LIMIT, note="how many to pick"),
                Flag("--fields", "<a,b,c>", note="add columns; see `plex-axi search --help`"),
            ),
            summary="Pick tracks to play now",
        ),
    ),
    notes=(
        "every filter is a Plex predicate evaluated server-side; anything this server "
        "does not offer is reported under `unapplied`, never applied client-side",
        "the shuffle is the server's `sort=random` over the whole match set, not a "
        "shuffle of one page",
        "identical titles are collapsed with Plex's own `group=title`, so one song "
        "does not fill the list from three pressings",
        "ratings are stars (0-5) in and out, so a rating in a result can be passed back",
    ),
    examples=(
        "plex-axi pick",
        "plex-axi pick --rated-min 4 --limit 20",
        "plex-axi pick --genre Jazz --not-played-since 30d --exclude-live",
    ),
)


def COMMAND_FOR(name: str) -> Command:
    return COMMAND


def run(ctx, name: str, sub: str, parsed):
    # Everything that can be decided from the arguments alone is decided first,
    # so a malformed flag costs no connection and the message names the flag
    # rather than whatever the server said about the request it never got.
    limit = parse_limit(parsed.get("limit"), default=DEFAULT_LIMIT)
    fields = select_fields(parsed.get("fields"), available_fields("track"), default_fields("track"))
    asked = _validate(parsed)

    section = ctx.section()
    try:
        filters, described, unapplied = _build(section, asked)
        sort, shuffled = _shuffle(section)
    except AxiError:
        raise
    except Exception as exc:
        raise _metadata_error(exc) from None

    result = run_search(
        section,
        libtype="track",
        filters=filters,
        sort=sort,
        limit=limit,
        group=True,
    )

    rows = rows_for("track", result.items)
    described = label_filters(section, described, libtype="track")
    fields = with_track_artist(fields, rows)

    doc: dict = {"count": count_line(len(rows), result.total), "shuffled": shuffled}
    if result.grouped:
        doc["grouped"] = result.grouped
    if described:
        doc["filters"] = described
    if unapplied:
        # Named before the rows, because it changes what the rows mean.
        doc["unapplied"] = unapplied

    if not rows:
        doc["tracks"] = "0 tracks matched every filter"
        doc["help"] = HelpBlock(_empty_steps(asked, unapplied))
        return doc

    doc["tracks"] = project(rows, fields)
    if len(result.items) == 1:
        doc["item"] = handoff(section._server.machineIdentifier, result.items[0])
    doc["help"] = HelpBlock(_next_steps(rows, result, limit))
    return doc


# ------------------------------------------------------------------- filters


def _validate(parsed) -> dict:
    """The flags, checked and converted, with no server in the picture yet."""
    raw_rating = parsed.get("rated_min")
    period = parsed.get("not_played_since")
    return {
        "stars": None if raw_rating in (None, "") else parse_stars(raw_rating, flag="--rated-min"),
        "genre": parsed.get("genre") or None,
        "period": (
            None if period in (None, "") else parse_relative_date(period, flag="--not-played-since")
        ),
        "exclude_live": bool(parsed.get("exclude_live")),
    }


def _build(section, asked) -> tuple:
    """The filter expression, its echo, and every flag this server could not honour.

    ``filters`` holds the predicates that combine with plain AND; ``groups``
    holds the parenthesised ones. They are composed at the end rather than
    merged as they are built, because plexapi refuses a dictionary that mixes a
    boolean key with any other -- so the OR has to be a sibling of the rest,
    inside one ``and``, not a key beside them.
    """
    filters: dict = {}
    groups: list = []
    described: list = []
    unapplied: list = []

    def unavailable(flag: str, field: str):
        unapplied.append(
            {
                "filter": flag,
                "reason": f"this server does not offer {field} as a track filter",
            }
        )

    value = asked["stars"]
    if value is not None:
        points = value * POINTS_PER_STAR
        points = int(points) if float(points).is_integer() else points
        if offers(section, "track.userRating", libtype="track"):
            filters["track.userRating>"] = points
            described.append(
                {
                    "field": "track.userRating",
                    "operator": ">=",
                    "value": f"{points} ({value:g} stars)",
                }
            )
        else:
            unavailable("--rated-min", "track.userRating")

    genre = asked["genre"]
    if genre:
        # On the artist, like everywhere else in this tool: a Plex music library
        # carries genres there and a track-scoped genre filter finds nothing.
        if offers(section, "artist.genre", libtype="track", tag=True):
            filters["artist.genre"] = genre
            described.append({"field": "artist.genre", "operator": "=", "value": genre})
        else:
            unavailable("--genre", "artist.genre")

    if asked["period"] is not None:
        _add_last_played(section, asked["period"], filters, groups, described, unapplied)

    if asked["exclude_live"]:
        if offers(section, "album.subformat", libtype="track", tag=True):
            filters["album.subformat!"] = LIVE_SUBFORMATS
            described.append(
                {
                    "field": "album.subformat",
                    "operator": "is not",
                    "value": ", ".join(LIVE_SUBFORMATS),
                }
            )
        else:
            unavailable("--exclude-live", "album.subformat")

    return _compose(filters, groups), described, unapplied


def _compose(filters: dict, groups: list) -> dict:
    """One filter expression from the plain predicates and the grouped ones."""
    if not groups:
        return filters
    parts = ([filters] if filters else []) + groups
    return parts[0] if len(parts) == 1 else {"and": parts}


def _echo_period(period: str) -> str:
    """The period as the predicate that ran should be read back.

    A relative period is echoed with the sign the client library's normalisation
    puts on the wire -- ``30d`` reaches the server as ``-30d``. An absolute date
    is echoed as itself, because nothing prefixes it and ``-2020-01-01`` is not a
    day anybody asked for.
    """
    return f"-{period}" if RELATIVE_DATE.match(period) else period


def _add_last_played(section, period, filters, groups, described, unapplied) -> None:
    """ "Not played since 30d" has two halves, and the second one is the point.

    A track Plex has never played carries no ``lastViewedAt`` at all, so the
    date predicate alone excludes exactly the tracks that most obviously have
    not been played lately. Plex's ``unplayed`` boolean covers them, and
    plexapi's ``{'or': [...]}` compiles the pair into ``push=1 ... or=1 ...
    pop=1`` -- a real parenthesised OR the server evaluates, not two searches
    merged here.

    When a server offers only one half, that half runs and the missing one is
    reported, because "played more than 30 days ago" and "not played in the last
    30 days" are different answers and the caller has to know which they got.
    """
    has_date = offers(section, "track.lastViewedAt", libtype="track")
    has_unplayed = offers(section, "track.unplayed", libtype="track")

    if has_date and has_unplayed:
        groups.append({"or": [{"track.lastViewedAt<<": period}, {"track.unplayed": True}]})
        described.append(
            {
                "field": "track.lastViewedAt",
                "operator": "is before, or never played",
                "value": _echo_period(period),
            }
        )
        return
    if has_date:
        filters["track.lastViewedAt<<"] = period
        described.append(
            {"field": "track.lastViewedAt", "operator": "is before", "value": _echo_period(period)}
        )
        unapplied.append(
            {
                "filter": "--not-played-since",
                "reason": (
                    "applied as a date only: this server does not offer track.unplayed, "
                    "so tracks it has never played are not included"
                ),
            }
        )
        return
    if has_unplayed:
        filters["track.unplayed"] = True
        described.append({"field": "track.unplayed", "operator": "is", "value": "true"})
        unapplied.append(
            {
                "filter": "--not-played-since",
                "reason": (
                    "narrowed to never-played: this server does not offer "
                    "track.lastViewedAt, so the period was not applied"
                ),
            }
        )
        return
    unapplied.append(
        {
            "filter": "--not-played-since",
            "reason": "this server offers neither track.lastViewedAt nor track.unplayed",
        }
    )


def _metadata_error(exc: Exception):
    """A library that will not describe its filters is a failure, not an absence."""
    return translate(
        exc,
        what="this library's filter metadata",
        help_lines=[
            "`pick` reads the fields this server advertises before it builds a predicate, "
            "so that a filter it cannot honour is reported rather than applied in Python",
            "Run `plex-axi doctor`: a library that has not finished scanning has no filter "
            "metadata yet",
        ],
    )


def _shuffle(section) -> tuple:
    """``sort=random`` when the server advertises it, and the truth when not."""
    if RANDOM_SORT in advertised_sorts(section, "track"):
        return RANDOM_SORT, f"server-side (sort={RANDOM_SORT})"
    return None, (
        "no: this server does not advertise a random sort, so these are in its default order"
    )


# --------------------------------------------------------------------- help


def _next_steps(rows, result, limit) -> list:
    lines = [f"Run `plex-axi track {rows[0]['key']}` for the detail and media id of the first"]
    lines.append(f"Run `plex-axi similar {rows[0]['key']}` for tracks that sound like it")
    if result.total > len(rows):
        lines.append(f"Run the same command again for a different {len(rows)} of {result.total}")
    return lines


def _empty_steps(asked, unapplied) -> list:
    lines = []
    if unapplied:
        lines.append("One filter did not run; see `unapplied` above before widening the others")
    if asked["genre"]:
        lines.append("Run `plex-axi genres` for the genres this library actually uses")
    if asked["stars"] is not None:
        lines.append("Run the same command with a lower `--rated-min`, or without it")
    if asked["period"]:
        lines.append("Run the same command with a shorter `--not-played-since`, e.g. 7d")
    lines.append("Run `plex-axi pick` with no filters to confirm the library answers at all")
    return lines
