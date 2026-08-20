"""The music surface: section resolution, per-field filters, and result rows.

This module is the product. Three decisions here are the difference between a
music search and a search that merely returns music-shaped rows:

**The section, not the server (M2).** plexapi has two ``search`` methods.
``Library.search`` hits ``/library/all``, validates nothing, and drops unknown
keyword arguments straight into the query string; its own docstring says *"This
is untested but seems to work. Use library section search when you can."*
``MusicSection.search`` carries the whole Plex filter language -- field scoping,
per-type operators, server-side grouping. Everything here goes through the
section, and :func:`resolve_section` is the only place a section is chosen.

**Filters, not keyword arguments (M3).** A numeric predicate written as
``userRating__gte=8`` means three different things depending on how it is
reached: through ``Library.search`` it is emitted verbatim into the URL and
applied nowhere; through ``LibrarySection.search`` it becomes a *client-side*
post-filter applied after ``limit`` has already sliced the results; and only
through ``filters={"userRating>": 8}`` is it a real, server-validated Plex
predicate over the whole set. :func:`build_filters` produces only the third
form, and :func:`_assert_server_side` fails loudly if a client-side filter ever
sneaks back in.

**Both artists (S5).** A track carries the album artist in ``grandparentTitle``
and the performing artist in ``originalTitle``. On a compilation the first is
"Various Artists" for every track on the disc, so a row that reports only that
one is wrong about who is playing.
"""

from __future__ import annotations

import re

from .errors import AxiError, UsageError
from .plex import MUSIC_SECTION_TYPE, translate

#: The three libtypes a music library holds, in the order they are listed.
LIBTYPES = ("track", "album", "artist")

#: The `MusicSection` method for each libtype. Named explicitly rather than
#: built from the libtype so that grepping for the method finds this table.
SEARCH_METHODS = {
    "track": "searchTracks",
    "album": "searchAlbums",
    "artist": "searchArtists",
}

#: Plex stores a user rating as 0-10; a star is two points. Every rating this
#: tool prints and every rating it accepts is in stars, so that a rating read
#: out of one command can be passed straight into `--rated-min` on the next.
POINTS_PER_STAR = 2


def stars(user_rating):
    """A Plex 0-10 user rating as 0-5 stars, or ``None`` when it is unrated.

    Returned as a number rather than a formatted string so the output boundary
    prints it unquoted, and so an unrated item reads as ``null`` rather than as
    an empty cell that could be mistaken for a zero rating.
    """
    if user_rating in (None, ""):
        return None
    value = float(user_rating) / POINTS_PER_STAR
    return int(value) if value.is_integer() else value


# ------------------------------------------------------------------ section


def resolve_section(server, *, wanted: str | None = None):
    """Find the music section once, and say clearly when the choice is ambiguous.

    A music library is a library *of artists*: Plex types the section ``artist``
    and hangs albums and tracks below it. Selecting on the type rather than on a
    name is what stops a video library answering a music query.
    """
    try:
        sections = server.library.sections()
    except Exception as exc:  # plexapi raises its own hierarchy; none of it escapes
        raise translate(exc, what="the library sections") from None

    music = [s for s in sections if getattr(s, "type", "") == MUSIC_SECTION_TYPE]
    if not music:
        others = ", ".join(sorted({f"{s.title} ({s.type})" for s in sections})) or "none"
        raise AxiError(
            "this server has no music library",
            help_lines=[
                f"sections on this server: {others}",
                "plex-axi reads music only; a video library is deliberately out of scope",
            ],
            code="NO_MUSIC_SECTION",
        )

    if wanted:
        for section in music:
            if str(section.key) == str(wanted) or section.title.lower() == wanted.strip().lower():
                return section
        titles = ", ".join(f"{s.title} (key {s.key})" for s in music)
        raise AxiError(
            f"no music library named {wanted!r} on this server",
            help_lines=[
                f"music libraries: {titles}",
                "Pass `--section <title|key>` with one of those, or unset PLEX_SECTION",
            ],
            code="NO_SUCH_SECTION",
        )

    if len(music) > 1:
        titles = ", ".join(f"{s.title} (key {s.key})" for s in music)
        raise AxiError(
            f"this server has {len(music)} music libraries; name the one to search",
            help_lines=[
                f"music libraries: {titles}",
                "Pass `--section <title|key>`, or export PLEX_SECTION to set a default",
            ],
            code="AMBIGUOUS_SECTION",
        )
    return music[0]


# ------------------------------------------------------------------- filters


#: Which Plex field each search flag maps to, per libtype searched.
#:
#: Two of these are scoping decisions rather than translations, and both are
#: load-bearing:
#:
#: * **genre and style resolve against the artist.** In a Plex music library
#:   genres and styles are carried by the artist, not by the track; a
#:   track-scoped genre filter returns nothing on a library tagged the ordinary
#:   way. Scoping to `artist.genre` with `libtype=track` is Plex's own answer --
#:   it returns the tracks of artists in that genre, server-side, in one query.
#: * **mood scopes to whatever was searched.** Unlike genre, Plex's analysis
#:   writes moods at every level, so `--mood` on a track search means the
#:   track's own mood and on an artist search the artist's.
#:
#: Any field may be combined with any libtype: Plex resolves `track.title` on an
#: artist search as "artists having a track by that name", which is a real and
#: useful query rather than an error.
FIELD_MAP = {
    "artist": lambda libtype: "artist.title",
    "album": lambda libtype: "album.title",
    "track": lambda libtype: "track.title",
    "genre": lambda libtype: "artist.genre",
    "style": lambda libtype: "artist.style",
    "mood": lambda libtype: f"{libtype}.mood",
    "year": lambda libtype: "album.year",
}

#: The operator each filter carries on the wire. A field given without a suffix
#: normalises to ``=``, and what ``=`` *means* is a property of the field's
#: type: "contains" on a string, "is" on a tag or an integer. The label printed
#: back is therefore read from the section's own operator table by
#: :func:`label_filters` rather than guessed once for all fields here.
BARE_OPERATOR = "="

#: ``userRating>`` normalises to ``>=`` -- Plex's "is greater than or equals".
#: A symbol needs no per-type resolution, so it is printed as it normalises.
RATING_OPERATOR = ">="


def parse_stars(raw, *, flag: str) -> float:
    try:
        value = float(str(raw))
    except (TypeError, ValueError):
        raise UsageError(
            f"{flag} needs a rating in stars from 0 to 5, got {raw!r}",
            help_lines=[f"Run the command again with `{flag} 4`"],
            code="BAD_RATING",
        ) from None
    if not 0 <= value <= 5:
        raise UsageError(
            f"{flag} is in stars from 0 to 5, got {value:g}",
            help_lines=[
                f"Run the command again with `{flag} 4`",
                "Ratings print in stars too, so a rating read from a result can be passed back",
            ],
            code="BAD_RATING",
        )
    return value


def build_filters(parsed, libtype: str) -> tuple:
    """Turn the per-field flags into Plex filters, and describe what was applied.

    Returns ``(filters, described)`` where ``filters`` is the dictionary handed
    to ``MusicSection.search`` and ``described`` is the rows printed back so the
    caller can see the actual predicate rather than guessing it.
    """
    filters: dict = {}
    described: list = []

    for flag in ("artist", "album", "track", "genre", "mood", "style", "year"):
        value = parsed.get(flag)
        if value in (None, ""):
            continue
        field = FIELD_MAP[flag](libtype)
        filters[field] = value
        described.append({"field": field, "operator": BARE_OPERATOR, "value": value})

    raw_rating = parsed.get("rated_min")
    if raw_rating not in (None, ""):
        value = parse_stars(raw_rating, flag="--rated-min")
        points = value * POINTS_PER_STAR
        points = int(points) if float(points).is_integer() else points
        # `userRating>` is Plex's "is greater than or equals". The lookalike
        # `userRating__gte` is not a Plex operator at all: it survives into the
        # URL untranslated through the weak search path, and becomes a
        # client-side post-filter through the strong one. Neither filters.
        field = f"{libtype}.userRating>"
        filters[field] = points
        described.append(
            {
                "field": f"{libtype}.userRating",
                "operator": RATING_OPERATOR,
                "value": f"{points} ({value:g} stars)",
            }
        )

    return filters, described


def label_filters(section, described: list, *, libtype: str) -> list:
    """Give each echoed filter the operator title the server itself advertises.

    The echo is a promise about the predicate that ran, and ``=`` does not mean
    one thing: "contains" on a string field, "is" on a tag or an integer. A
    single label for all of them invites substrings and synonyms on fields that
    only match an exact value, so the title is read from the section's operator
    table -- the same metadata the search just validated against, already
    fetched and cached by then, so this costs no round trip.
    """
    for row in described:
        if row["operator"] != BARE_OPERATOR:
            continue
        row["operator"] = _operator_title(section, row["field"], libtype=libtype)
    return described


# ------------------------------------------------- what this server will accept
#
# Every one of these reads the section's own filter metadata, which plexapi
# fetches once (`includeMeta=1`) and caches for the life of the section object.
# Asking before building a predicate therefore costs no extra round-trip, and it
# is the difference between a command that degrades with an explanation and one
# that fails with the client library's validation message.


def advertised_fields(section, libtype: str) -> set:
    """The bare field names this server offers as filters for one libtype."""
    return {f.key.rsplit(".", 1)[-1] for f in section.listFields(libtype)}


def advertised_filters(section, libtype: str) -> set:
    """The *tag* filters this server offers, which is a smaller set than the fields.

    A tag predicate needs both: the field, to validate the operator, and the
    filter, because the client library resolves a tag's name to the numeric id
    Plex actually filters on by listing that filter's choices. A field without
    its filter raises during value resolution rather than during validation.
    """
    return {f.filter for f in section.listFilters(libtype)}


def advertised_sorts(section, libtype: str) -> set:
    return {s.key for s in section.listSorts(libtype)}


def offers(section, field: str, *, libtype: str, tag: bool = False) -> bool:
    """Whether ``<scope>.<name>`` is a filter this server will accept.

    Failures are deliberately not swallowed here. "This server does not offer
    that field" and "this server would not say what it offers" are different
    answers, and reporting the second as the first would return an unfiltered
    result set under a note claiming the filter was merely unavailable. The
    caller wraps the whole metadata read and translates it once.
    """
    scope, _, name = field.rpartition(".")
    scope = scope or libtype
    if name not in advertised_fields(section, scope):
        return False
    return not tag or name in advertised_filters(section, scope)


#: A relative date as Plex spells it: a count and a unit. plexapi normalises a
#: bare ``30d`` to ``-30d`` and passes it through, so the tool accepts the form
#: without the sign -- "30d ago" is how a caller says it.
RELATIVE_DATE = re.compile(r"^-?\d+(mon|[smhdwy])$")
ABSOLUTE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_relative_date(raw, *, flag: str) -> str:
    """Validate a relative date before the client library sees it.

    plexapi answers a malformed value with ``BadRequest`` naming its own field
    key, which is a message about the library rather than about the flag that
    was typed.
    """
    value = str(raw).strip()
    if RELATIVE_DATE.match(value):
        # The sign is plexapi's to add: it normalises `30d` to `-30d` and a
        # caller who wrote the minus meant the same thing.
        return value.lstrip("-")
    if ABSOLUTE_DATE.match(value):
        return value
    raise UsageError(
        f"{flag} needs a period like 30d, 6mon or 2y, or a date as YYYY-MM-DD, got {raw!r}",
        help_lines=[
            f"Run the command again with `{flag} 30d`",
            "units: s seconds, m minutes, h hours, d days, w weeks, mon months, y years",
        ],
        code="BAD_PERIOD",
    )


def _operator_title(section, field: str, *, libtype: str) -> str:
    """The title the section gives the ``=`` operator on one field's type.

    The field is found the way the validation finds it: a ``libtype.field``
    scope in the name redirects the lookup to that libtype's advertised fields,
    which is why ``artist.genre`` resolves even when tracks were searched.
    """
    scope, _, name = field.rpartition(".")
    fields = section.listFields(scope or libtype)
    filter_field = next(f for f in fields if f.key.split(".")[-1] == name)
    operators = section.getFieldType(filter_field.type).operators
    return next(operator.title for operator in operators if operator.key == BARE_OPERATOR)


# -------------------------------------------------------------------- search


class SearchResult:
    """One executed search: the items, the exact total, and what was applied."""

    __slots__ = ("grouped", "items", "key", "total")

    def __init__(self, items, total, grouped, key):
        self.items = items
        self.total = total
        self.grouped = grouped
        self.key = key


#: The grouping predicate Plex's own popular-tracks query uses, which collapses
#: one song appearing on an album, a compilation and a live record into one row.
#:
#: It is worth knowing where this field comes from, because it is not where it
#: looks. The server does not advertise `group` in its filter metadata at all;
#: the client library adds it by hand, as a string field titled "SQL Group By
#: Statement", precisely because it works and is not exposed. So the field
#: always validates, on every server, whatever that server's metadata says --
#: and whether the server then *honours* it is the one thing validation cannot
#: tell us. That is why :func:`_verify_grouping` checks the answer instead of
#: trusting the request.
GROUP_BY_TITLE = "title"


def run_search(section, *, libtype, filters=None, title=None, sort=None, limit=20, group=False):
    """Execute one section-scoped search and return items plus the exact total."""
    call_filters = dict(filters or {})
    grouped = GROUP_BY_TITLE if group else ""

    try:
        result = _execute(section, libtype, call_filters, title, sort, limit, grouped)
    except AxiError:
        raise
    except Exception as exc:
        raise _filter_error(exc, libtype) from None
    if grouped:
        result.grouped = _verify_grouping(result.items)
    return result


def _verify_grouping(items) -> str:
    """Report what the server did, not what it was asked to do.

    Asking for grouping and printing "grouped: title" asserts something about
    the answer that only the answer can settle. A server that ignored the
    parameter returns the repeats, and saying it collapsed them would be exactly
    the class of lie this tool is meant to catch elsewhere. It costs one pass
    over rows already in hand.
    """
    titles = [(getattr(item, "title", "") or "").casefold() for item in items]
    if len(set(titles)) != len(titles):
        return f"{GROUP_BY_TITLE} (asked for, but this server returned repeated titles)"
    return GROUP_BY_TITLE


def _execute(section, libtype, filters, title, sort, limit, grouped):
    kwargs: dict = {}
    if title:
        kwargs["title"] = title
    if sort:
        kwargs["sort"] = sort
    if filters:
        kwargs["filters"] = filters
    if grouped:
        # Passed beside the filter expression rather than inside it. `group` is
        # a SQL GROUP BY, not a predicate, and plexapi refuses a boolean key
        # (`and`/`or`) in a filter dictionary that holds anything else -- so a
        # `group` sitting in `filters` would make a parenthesised OR unbuildable
        # and, worse, would land the grouping *inside* the parentheses. Routed
        # through `**kwargs` it is validated by the same field table and emitted
        # as the same `group=title` parameter, outside any group.
        kwargs["group"] = grouped

    # Build the key with plexapi's own builder so the count and the fetch can
    # never describe different queries, and so a client-side filter is caught
    # here rather than silently fighting the limit.
    key, leftover = section._buildSearchKey(libtype=libtype, returnKwargs=True, **kwargs)
    _assert_server_side(leftover)

    total = count_matches(section, key)
    method = getattr(section, SEARCH_METHODS[libtype])
    # `maxresults` bounds the fetch client-side after one page; the server-side
    # `limit` parameter is deliberately not used, because it would also cap the
    # `totalSize` the count query reads and turn an exact total into a lie.
    items = method(maxresults=limit, container_size=limit, **kwargs)
    return SearchResult(list(items), total, grouped, key)


def _assert_server_side(leftover: dict) -> None:
    """Refuse to run a search that plexapi would filter client-side.

    Anything left in ``kwargs`` after ``_buildSearchKey`` is a PlexAPI operator
    rather than a Plex one: plexapi applies it in Python *after* the server has
    already sliced the result set, so it fights the limit instead of narrowing
    the query. It is never what the caller meant, and it looks like it worked.
    """
    if leftover:
        names = ", ".join(sorted(leftover))
        raise AxiError(
            f"refusing to filter on {names} after the server has already answered",
            help_lines=[
                "This is a bug in plex-axi: every filter must be a server-side Plex predicate",
                "Report it at https://github.com/dmealing/plex-axi/issues",
            ],
            code="CLIENT_SIDE_FILTER",
        )


def count_matches(section, key: str) -> int:
    """The exact number of items matching ``key``, for one extra header.

    ``X-Plex-Container-Size: 0`` asks Plex for the container metadata with no
    body, so the total costs a round-trip with no payload rather than a second
    full fetch. A list view that reports only its own page size makes an agent
    paginate to find out how much it is not seeing.
    """
    data = section._server.query(
        key, headers={"X-Plex-Container-Start": "0", "X-Plex-Container-Size": "0"}
    )
    total = data.attrib.get("totalSize")
    if total is None:
        total = data.attrib.get("size")
    try:
        return int(total)
    except (TypeError, ValueError):
        return -1


def _filter_error(exc: Exception, libtype: str):
    """Translate plexapi's filter-validation failures into recoverable errors."""
    text = str(exc)
    if "Unknown filter field" in text:
        fields = _bracketed(text)
        return AxiError(
            f"this server does not offer that filter for a {libtype}",
            help_lines=[
                f"filter fields for {libtype}: {fields}" if fields else "",
                "Run `plex-axi genres` (or `moods`, `styles`) to see the values it does offer",
            ],
            code="UNKNOWN_FILTER_FIELD",
        )
    if "Unknown operator" in text:
        operators = _bracketed(text)
        return AxiError(
            "this server does not offer that comparison for that field",
            help_lines=[
                f"operators for that field: {operators}" if operators else "",
                "Run `plex-axi search --rated-min 4` for the supported at-least comparison",
            ],
            code="UNKNOWN_OPERATOR",
        )
    if "Unknown libtype" in text:
        return UsageError(
            f"this server's music library does not hold {libtype}s",
            help_lines=[f"Run the command again with `--type {LIBTYPES[0]}`"],
            code="UNKNOWN_LIBTYPE",
        )
    if "Unknown sort field" in text:
        # plexapi signals this one as NotFound, not BadRequest: a wrong --sort
        # value is a client-side validation miss, and letting it fall through
        # to the generic NotFound translation would tell the caller their
        # results "were not found on this server" when no request was sent.
        # It is the caller's argument rather than a lookup outcome, so like
        # --fields it exits on the usage side, not the lookup side.
        sorts = _bracketed(text)
        return UsageError(
            f"this server does not offer that sort for a {libtype}",
            help_lines=[
                f"sort fields for {libtype}: {sorts}" if sorts else "",
                "Run the same search with `--sort addedAt:desc` for newest first",
            ],
            code="UNKNOWN_SORT_FIELD",
        )
    return translate(exc, what="the search results")


def _bracketed(text: str) -> str:
    """Pull plexapi's ``[a, b, c]`` tail out of a validation message.

    The tail is the useful half -- it is the server's own list of what it will
    accept -- while the rest of the message names the library that produced it.
    """
    start = text.rfind("[")
    end = text.rfind("]")
    if start < 0 or end < start:
        return ""
    inner = text[start + 1 : end]
    parts = [p.strip().strip("'\"") for p in inner.split(",")]
    parts = [p.rsplit(".", 1)[-1] for p in parts if p]
    return ", ".join(dict.fromkeys(parts))


# ---------------------------------------------------------------------- rows


#: Fields each libtype can produce, and the minimal default schema. A track row
#: without an artist and an album is not a music result -- it is a title and a
#: number, which is what every prior tool in the landscape returns.
ROW_FIELDS = {
    "track": (
        "key,title,artist,album",
        "key,title,artist,track_artist,album,year,rating,duration,plays,skips,index,guid",
    ),
    "album": (
        "key,title,artist,year",
        "key,title,artist,year,rating,tracks,added,guid",
    ),
    "artist": (
        "key,title",
        "key,title,rating,added,guid",
    ),
}


def default_fields(libtype: str) -> list:
    return ROW_FIELDS[libtype][0].split(",")


def available_fields(libtype: str) -> list:
    return ROW_FIELDS[libtype][1].split(",")


def _seconds(milliseconds):
    """A duration in whole seconds, or ``None`` when the server gave none."""
    if not milliseconds:
        return None
    return int(milliseconds) // 1000


def track_row(item) -> dict:
    """One track, with both artists and nothing that costs a second request."""
    album_artist = getattr(item, "grandparentTitle", "") or ""
    performer = getattr(item, "originalTitle", "") or ""
    return {
        "key": number(getattr(item, "ratingKey", None)),
        "title": getattr(item, "title", "") or "",
        "artist": album_artist,
        # Reported separately, never merged: on a compilation the album artist
        # is "Various Artists" for every track, and collapsing the two loses the
        # only field that says who is actually playing.
        "track_artist": performer if performer and performer != album_artist else "",
        "album": getattr(item, "parentTitle", "") or "",
        "year": number(getattr(item, "year", None)),
        "rating": stars(getattr(item, "userRating", None)),
        "duration": _seconds(getattr(item, "duration", None)),
        "plays": int(getattr(item, "viewCount", 0) or 0),
        "skips": int(getattr(item, "skipCount", 0) or 0),
        "index": number(getattr(item, "index", None)),
        "guid": getattr(item, "guid", "") or "",
    }


def album_row(item) -> dict:
    return {
        "key": number(getattr(item, "ratingKey", None)),
        "title": getattr(item, "title", "") or "",
        "artist": getattr(item, "parentTitle", "") or "",
        "year": number(getattr(item, "year", None)),
        "rating": stars(getattr(item, "userRating", None)),
        "tracks": number(getattr(item, "leafCount", None)),
        "added": date_only(getattr(item, "addedAt", None)),
        "guid": getattr(item, "guid", "") or "",
    }


def artist_row(item) -> dict:
    return {
        "key": number(getattr(item, "ratingKey", None)),
        "title": getattr(item, "title", "") or "",
        "rating": stars(getattr(item, "userRating", None)),
        "added": date_only(getattr(item, "addedAt", None)),
        "guid": getattr(item, "guid", "") or "",
    }


def number(value):
    """An integer attribute, or ``None`` when the server did not supply one."""
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


ROW_BUILDERS = {"track": track_row, "album": album_row, "artist": artist_row}


def date_only(value) -> str:
    if not value:
        return ""
    try:
        return value.strftime("%Y-%m-%d")
    except AttributeError:
        return str(value)


def rows_for(libtype: str, items) -> list:
    return [ROW_BUILDERS[libtype](item) for item in items]


def with_track_artist(fields: list, rows: list) -> list:
    """Add ``track_artist`` to the schema exactly when it says something.

    The column earns its tokens when a track's performer differs from its album
    artist, which is the compilation case and the one where reporting only the
    album artist is wrong: every track on a Various Artists disc reports
    "Various Artists" and none of them says who is playing. On an ordinary album
    the two agree, and the column would repeat the artist on every row.
    """
    if "track_artist" in fields:
        return fields
    if not any(row.get("track_artist") for row in rows):
        return fields
    out = list(fields)
    anchor = out.index("artist") + 1 if "artist" in out else len(out)
    out.insert(anchor, "track_artist")
    return out


def tag_titles(tags) -> str:
    """Render a list of Plex media tags as a space-free, comma-joined string."""
    return ", ".join(sorted({getattr(tag, "tag", "") or "" for tag in tags or []} - {""}))
