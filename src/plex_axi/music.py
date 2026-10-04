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

**Filters, not keyword arguments (M3).** The rules that turn a flag into a Plex
predicate -- the field map, the operators, the star arithmetic, the dates and
the sorts -- are :mod:`axi_toolkit.plex.filters` now: they take plain values and
so were never this module's to keep. What stays is everything that needs a live
section. :func:`run_search` is where the two meet, and it calls
:func:`~axi_toolkit.plex.filters.assert_server_side` on whatever plexapi did not
recognise, because a predicate applied *after* the server has already sliced the
result set fights the limit instead of narrowing the query and looks like it
worked.

**Both artists (S5).** A track carries the album artist in ``grandparentTitle``
and the performing artist in ``originalTitle``. On a compilation the first is
"Various Artists" for every track on the disc, so a row that reports only that
one is wrong about who is playing.
"""

from __future__ import annotations

from axi_toolkit.plex.filters import (
    BARE_OPERATOR,
    FIELD_MAP,
    LIBTYPES,
    assert_server_side,
    build_filters,
    stars,
)
from axi_toolkit.plex.ids import media_id_for

from . import output
from .errors import AnyAxiError, AxiError, UsageError
from .plex import MUSIC_SECTION_TYPE, translate
from .toolkit import matching
from .toolkit import search as rules
from .toolkit.matching import TEXT_OPERATOR, spellings
from .toolkit.search import PERFORMER_FIELD, TEXT_FLAGS, compose

#: The `MusicSection` method for each libtype. Named explicitly rather than
#: built from the libtype so that grepping for the method finds this table.
SEARCH_METHODS = {
    "track": "searchTracks",
    "album": "searchAlbums",
    "artist": "searchArtists",
}

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


# ----------------------------------------------- filters, once a server is here


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


def sonic_analysis(section):
    """Whether this library's sonic analysis is switched on: True, False or None.

    Read from the library's own ``musicAnalysis`` preference. It used to be
    inferred from the mood vocabulary, on the reasoning that the analysis writes
    moods -- but the metadata agent writes moods too, so a library with the
    analysis off and two hundred moods was reported as analysed while `similar`
    returned nothing for every seed. ``None`` means the server did not say.
    """
    try:
        data = section._server.query(rules.preferences_path(section.key))
    except Exception as exc:
        output.debug(f"library preferences not read ({type(exc).__name__})")
        return None
    return rules.sonic_analysis(data)


# ------------------------------------------------------- the search, planned
#
# `axi_toolkit.plex.filters.build_filters` turns each flag into one predicate.
# What follows is the part that depends on how a *server* reads a title, which
# was measured rather than read off its metadata. The rules themselves are in
# :mod:`plex_axi.toolkit`; what is here is where they meet a command line and a
# connection.

# :data:`PERFORMER_FIELD` is not advertised by the server, so
# :func:`offer_performer` adds it to the section's field table the way the
# client library adds ``group``, and :func:`performer_honoured` checks the rows
# that came back rather than trusting that it ran.


def clean_text(raw, *, flag: str) -> str:
    """One typed value, cleaned, or a refusal naming the flag it came from.

    The rule is :func:`plex_axi.toolkit.matching.clean_text`; this is where it
    meets a command line, because only here is it known which flag to name.
    """
    value = matching.clean_text(raw)
    if not value:
        raise UsageError(
            f"{flag} needs some text to search for, got {str(raw)!r}",
            help_lines=[
                "A comma separates alternatives on the server, so a value that is only "
                "commas and spaces would match every item in the library",
                f"Run the command again with `{flag} '<text>'`",
            ],
            code="EMPTY_VALUE",
        )
    return value


def parse_year(raw) -> str:
    """A release year, checked before the server sees it."""
    value = matching.year(raw)
    if value is None:
        raise UsageError(
            f"--year needs one four-digit year, got {str(raw)!r}",
            help_lines=[
                "Run the command again with `--year 1977`",
                "A range is not a filter this command builds; run one search per year",
            ],
            code="BAD_YEAR",
        )
    return value


class SearchPlan:
    """One search, decided from the arguments alone: no server in the picture."""

    __slots__ = ("described", "filters", "matching", "note", "performer", "texts", "title")

    def __init__(self):
        self.filters: dict = {}
        self.described: list = []
        self.note = ""
        #: What was done to the typed text before it was sent, said in the
        #: result so the echo is not read as the literal request.
        self.matching: list = []
        #: Flag name to cleaned value, for the nearest-title fallback.
        self.texts: dict = {}
        self.title = None
        self.performer = False


class _Values:
    """A parsed invocation with some values replaced, for the shared builder."""

    def __init__(self, parsed, replaced: dict):
        self._parsed = parsed
        self._replaced = replaced

    def get(self, name, default=None):
        if name in self._replaced:
            return self._replaced[name]
        return self._parsed.get(name, default)


def plan_search(parsed, libtype: str, *, performer: bool = True) -> SearchPlan:
    """Turn the flags into a filter expression, static checks first.

    ``performer=False`` builds the same search on the album artist alone, which
    is what a server that does not apply :data:`PERFORMER_FIELD` is given.
    """
    plan = SearchPlan()
    replaced: dict = {}
    for flag in TEXT_FLAGS:
        raw = parsed.get(flag)
        if raw in (None, ""):
            continue
        replaced[flag] = plan.texts[flag] = clean_text(raw, flag=f"--{flag}")
        if plan.texts[flag] != str(raw):
            plan.matching.append(
                f"--{flag} was searched as {plan.texts[flag]!r}: the server reads a comma as "
                "OR and a doubled space as an empty word, so both are taken out"
            )
    year = parsed.get("year")
    if year not in (None, ""):
        replaced["year"] = parse_year(year)
    query = parsed.get("query")
    if query not in (None, ""):
        plan.texts["query"] = clean_text(query, flag="--query")

    filters, plan.described, plan.note = build_filters(_Values(parsed, replaced), libtype)
    groups: list = []
    expanded = False
    for flag in TEXT_FLAGS:
        if flag not in replaced:
            continue
        field = FIELD_MAP[flag](libtype)
        variants = spellings(replaced[flag])
        expanded = expanded or len(variants) > 1
        value = variants if len(variants) > 1 else variants[0]
        row = next(row for row in plan.described if row["field"] == field)
        row["operator"] = TEXT_OPERATOR
        if flag == "artist" and libtype == "track" and performer:
            del filters[field]
            groups.append(rules.artist_or_performer(field, value))
            row["field"] = f"{field} or {PERFORMER_FIELD}"
            plan.performer = True
        else:
            filters[field] = value
    if "query" in plan.texts:
        variants = spellings(plan.texts["query"])
        expanded = expanded or len(variants) > 1
        plan.title = variants if len(variants) > 1 else variants[0]
    if expanded:
        plan.matching.append(
            "typographic spellings of the apostrophes, quotes, hyphens and ellipses typed "
            "were searched as well, because the server does not treat them as the same character"
        )
    plan.filters = compose(filters, groups)
    return plan


def offer_performer(section) -> None:
    """Make :data:`PERFORMER_FIELD` a field the client library will build with.

    The same move the client library makes for ``group`` and ``index``: a field
    the server accepts and does not list is added to the cached field table by
    hand, so the ordinary builder validates it, resolves its operator and puts
    it inside the parentheses. Building that part of the URL here instead would
    be a second filter language to keep in step with the first.
    """
    from plexapi.library import FilteringField

    filter_type = section.getFilterType("track")
    if any(field.key == PERFORMER_FIELD for field in filter_type.fields):
        return
    xml = f'<Field key="{PERFORMER_FIELD}" title="{rules.PERFORMER_TITLE}" type="string"/>'
    filter_type.fields.append(filter_type._manuallyLoadXML(xml, FilteringField))


def performer_honoured(items, typed: str) -> bool:
    """Whether the rows that came back are ones the name could have matched.

    Checked on the answer, like :func:`_verify_grouping`. A server that ignores
    a filter field it does not know returns the *unfiltered* set -- a plausible
    page of the whole library -- and nothing in the request can show that. If
    not one row on the page has the name in its album artist or its performer,
    the field did not run.
    """
    return rules.performer_honoured(
        (
            (getattr(item, "grandparentTitle", "") or "", getattr(item, "originalTitle", "") or "")
            for item in items
        ),
        typed,
    )


NEAREST_SHOWN = rules.NEAREST_SHOWN


def nearest_titles(section, texts: dict) -> list:
    """The closest real titles to each name that matched nothing.

    The per-field filter folds nothing: no accents, no typographic punctuation.
    The server's own free-text search folds both, so it is asked what the caller
    might have meant, and the titles it holds are handed back as the recovery
    set -- exact strings to search on, rather than advice to try a different
    spelling. This never *is* the search: free text is the weak path this tool
    exists to replace, and its answer is offered, not substituted.

    A failure here is swallowed. The search itself succeeded and found nothing;
    a recovery aid that could turn that into an error would be worse than none.
    """
    return rules.nearest_titles(
        lambda path, params: section._server.query(path, params=params),
        texts,
        section_key=section.key,
        on_error=lambda exc: output.debug(f"nearest-title lookup failed ({type(exc).__name__})"),
    )


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


def run_search(
    section,
    *,
    libtype,
    filters=None,
    title=None,
    sort=None,
    limit=20,
    group=False,
    performer=False,
):
    """Execute one section-scoped search and return items plus the exact total.

    ``performer`` says the expression names :data:`PERFORMER_FIELD`, which the
    section has to be told about before the client library will build with it.
    """
    call_filters = dict(filters or {})
    grouped = GROUP_BY_TITLE if group else ""
    if performer:
        try:
            offer_performer(section)
        except Exception as exc:
            raise _filter_error(exc, libtype) from None

    try:
        result = _execute(section, libtype, call_filters, title, sort, limit, grouped)
    except AnyAxiError:
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
    assert_server_side(leftover)

    # The single most useful diagnostic this tool has: the exact predicate,
    # already resolved -- tag names turned into ids, operators normalised,
    # parentheses in place. It is what `--debug` is for, and it is what an
    # `UNKNOWN_OPERATOR` or an unexpectedly empty result needs beside it.
    output.debug(f"search key: {key}")

    total = count_matches(section, key)
    output.debug(f"exact total: {total}")
    method = getattr(section, SEARCH_METHODS[libtype])
    # `maxresults` bounds the fetch client-side after one page; the server-side
    # `limit` parameter is deliberately not used, because it would also cap the
    # `totalSize` the count query reads and turn an exact total into a lie.
    items = method(maxresults=limit, container_size=limit, **kwargs)
    return SearchResult(list(items), total, grouped, key)


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
        # Every comparison in a plex-axi filter is built by this module from a
        # flag, never typed by a caller, so reaching here means the tool asked
        # for something this server does not define. The advice has to say that.
        # It used to name `--rated-min` as "the supported at-least comparison",
        # which was the flag that produced the error -- structurally valid
        # recovery text recommending the command that had just failed.
        return AxiError(
            "this server does not offer that comparison for that field",
            help_lines=[
                f"operators for that field: {operators}" if operators else "",
                "This is a bug in plex-axi: it builds every comparison itself, so one this "
                "server rejects is a wrong assumption about Plex rather than a wrong argument",
                "Report it at https://github.com/dmealing/plex-axi/issues",
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
#: without an artist is not a music result -- it is a title and a number, which
#: is what every prior tool in the landscape returns.
#:
#: **Four columns at most, which is AXI's bar for a default list schema.** Every
#: column is paid once per row, and two of the four are spent on identifiers --
#: ``key`` for this tool's own follow-ups, ``media_id`` for whatever plays it --
#: so the defaults carry exactly one descriptive column beyond the title. The
#: album and the year are one ``--fields`` away; the detail views print both.
#: The one data-driven exception is :func:`with_track_artist`, which adds a
#: column only on the compilation rows where the fourth would be misleading.
#:
#: **``media_id`` is in every default row, and that is the point of the tool.**
#: plex-axi ends at a labelled identifier, so a list view that printed only
#: ``key`` under-delivered on its own premise and cost the caller one detail
#: request per row to finish the job. The ``guid`` stays out of the defaults and
#: in the detail views: it is the durable identifier a human writes down, not
#: the actionable one -- and for a locally-matched item it is not even durable
#: (see :func:`axi_toolkit.plex.ids.stability_note`), so doubling every row's
#: width for it would be a poor trade.
ROW_FIELDS = {
    "track": (
        "key,media_id,title,artist",
        "key,media_id,title,artist,track_artist,album,year,rating,"
        "duration,plays,skips,index,added,guid",
    ),
    # No `tracks` here: an album *row* carries no track count -- only its
    # detail view does -- so the column was null on every real server.
    "album": (
        "key,media_id,title,artist",
        "key,media_id,title,artist,year,rating,added,guid",
    ),
    "artist": (
        "key,media_id,title",
        "key,media_id,title,rating,added,guid",
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


def track_year(item):
    """A track's year, which is its album's: the server sends no other.

    A real track element carries ``parentYear`` and no ``year`` at all, and the
    client library models only ``year`` -- so the value has to be read off the
    element the object was built from. ``year`` is kept as a fallback for a
    server that does send one.
    """
    data = getattr(item, "_data", None)
    raw = rules.track_year(data.attrib) if data is not None else None
    return raw or getattr(item, "parentYear", None) or getattr(item, "year", None)


def track_row(item, machine_identifier: str) -> dict:
    """One track, with both artists and nothing that costs a second request."""
    album_artist = getattr(item, "grandparentTitle", "") or ""
    performer = getattr(item, "originalTitle", "") or ""
    return {
        "key": number(getattr(item, "ratingKey", None)),
        "media_id": media_id_for(machine_identifier, item),
        "title": getattr(item, "title", "") or "",
        "artist": album_artist,
        # Reported separately, never merged: on a compilation the album artist
        # is "Various Artists" for every track, and collapsing the two loses the
        # only field that says who is actually playing.
        "track_artist": rules.track_artist(album_artist, performer),
        "album": getattr(item, "parentTitle", "") or "",
        "year": number(track_year(item)),
        "rating": stars(getattr(item, "userRating", None)),
        "duration": _seconds(getattr(item, "duration", None)),
        "plays": int(getattr(item, "viewCount", 0) or 0),
        "skips": int(getattr(item, "skipCount", 0) or 0),
        "index": number(getattr(item, "index", None)),
        "added": date_only(getattr(item, "addedAt", None)),
        "guid": getattr(item, "guid", "") or "",
    }


def album_row(item, machine_identifier: str) -> dict:
    return {
        "key": number(getattr(item, "ratingKey", None)),
        "media_id": media_id_for(machine_identifier, item),
        "title": getattr(item, "title", "") or "",
        "artist": getattr(item, "parentTitle", "") or "",
        "year": number(getattr(item, "year", None)),
        "rating": stars(getattr(item, "userRating", None)),
        "added": date_only(getattr(item, "addedAt", None)),
        "guid": getattr(item, "guid", "") or "",
    }


def artist_row(item, machine_identifier: str) -> dict:
    return {
        "key": number(getattr(item, "ratingKey", None)),
        "media_id": media_id_for(machine_identifier, item),
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


def rows_for(libtype: str, items, machine_identifier: str) -> list:
    """Rows for one page of results, each carrying its own media id.

    ``machine_identifier`` is a required argument rather than an optional one so
    that a new row-bearing surface cannot quietly ship without the identifier
    this tool exists to hand over. Six of them once did.
    """
    return [ROW_BUILDERS[libtype](item, machine_identifier) for item in items]


def with_track_artist(fields: list, rows: list) -> list:
    """Add ``track_artist`` to the *default* schema exactly when it says something.

    The column earns its tokens when a track's performer differs from its album
    artist, which is the compilation case and the one where reporting only the
    album artist is wrong: every track on a Various Artists disc reports
    "Various Artists" and none of them says who is playing. On an ordinary album
    the two agree, and the column would repeat the artist on every row.

    **Only when the caller did not name the columns.** This once ran
    unconditionally, so `--fields key` could answer with `{key,track_artist}`
    and two runs of the same command could return different schemas depending on
    which rows came back. A caller that names its columns gets those columns;
    the data-dependent extra belongs to the default, which is a suggestion
    rather than a contract. Nor does it qualify a schema that has no ``artist``
    column to qualify, which is what `similar`'s default is.
    """
    if "track_artist" in fields or "artist" not in fields:
        return fields
    if not any(row.get("track_artist") for row in rows):
        return fields
    out = list(fields)
    out.insert(out.index("artist") + 1, "track_artist")
    return out


def tag_titles(tags) -> str:
    """Render a list of Plex media tags as a space-free, comma-joined string."""
    return ", ".join(sorted({getattr(tag, "tag", "") or "" for tag in tags or []} - {""}))
