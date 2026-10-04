"""How a music search is put to a Plex Media Server, and how its answer is read.

The rules here were each measured against a real server rather than read off its
metadata, and each is the part of a search that depends on how a *server*
behaves instead of on what a caller typed:

* **A performer is not an album artist.** A track on a compilation has "Various
  Artists" for an album artist, so a search on the artist's title alone cannot
  find somebody who has no album of their own. :data:`PERFORMER_FIELD` is the
  field that says who is playing; the server honours it and does not advertise
  it, so :func:`performer_honoured` checks the rows that came back.
* **An OR has to be a sibling, not a key.** :func:`compose` builds the one shape
  of filter expression that carries a parenthesised group.
* **The per-field filter folds nothing, and the free-text search does.** So a
  name that matched nothing is put to ``/hubs/search`` for the nearest titles
  the library really holds: :func:`nearest_request`, :func:`nearest_rows` and
  :func:`nearest_titles`.
* **Some values are not where the model says.** A track's year is its album's
  (:func:`track_year`), and whether sonic analysis is on is a library
  preference rather than something the mood list implies
  (:func:`sonic_analysis`).

**Nothing here opens a connection.** A function that needs the server's answer
takes it already fetched -- attributes as a mapping, a document as a parsed
element -- or takes a callable the caller supplies. Nothing is raised to refuse
a value either: a rule that finds nothing usable returns ``None``, ``False`` or
an empty list, and the caller decides what to say.
"""

from __future__ import annotations

from .matching import clean_text, loosely_matches, spellings

#: The names whose value is free text matched against a title.
TEXT_FLAGS = ("artist", "album", "track")

#: Who is playing, as opposed to whose record it is on.
#:
#: **The server does not advertise this field, and it honours it anyway** --
#: measured, the same way the client library's own hand-added fields were. A
#: caller that validates against the advertised table has to add it by hand, and
#: has to check the answer with :func:`performer_honoured`: an unadvertised
#: field is exactly the kind a different build could drop without saying so.
PERFORMER_FIELD = "track.originalTitle"

#: The label the performer field is offered under.
PERFORMER_TITLE = "Track Artist"


def filter_value(raw):
    """One typed value as the server should be sent it, or ``None`` to refuse.

    Cleaned, then expanded to each punctuation spelling a title might hold: a
    string when there is one spelling, a list of alternatives when there are
    several. ``None`` means nothing was left to search for, and the caller must
    not send it -- an empty value matches every item in the library.
    """
    value = clean_text(raw)
    if not value:
        return None
    variants = spellings(value)
    return variants if len(variants) > 1 else variants[0]


def artist_or_performer(artist_field: str, value) -> dict:
    """The parenthesised group that finds a track by either of its artists."""
    return {"or": [{artist_field: value}, {PERFORMER_FIELD: value}]}


def compose(filters: dict, groups: list) -> dict:
    """One filter expression from the plain predicates and the parenthesised ones.

    Composed rather than merged, because the server's filter language -- and the
    client library validating it -- refuses a dictionary that mixes a boolean
    key with any other. So an OR has to be a sibling of the rest, inside one
    ``and``, not a key beside them.
    """
    if not groups:
        return filters
    parts = ([filters] if filters else []) + groups
    return parts[0] if len(parts) == 1 else {"and": parts}


def performer_honoured(rows, typed: str) -> bool:
    """Whether the rows that came back are ones the name could have matched.

    ``rows`` is one entry per track, each the names that track answers to: its
    album artist and its performer. A server that ignores a filter field it does
    not know returns the *unfiltered* set -- a plausible page of the whole
    library -- and nothing in the request can show that. If not one row on the
    page carries the name, the field did not run. An empty page proves nothing
    and is taken as honoured.
    """
    rows = list(rows)
    if not rows:
        return True
    return any(loosely_matches(typed, name or "") for names in rows for name in names)


def track_artist(album_artist, performer) -> str:
    """The performer, when it says something the album artist does not.

    Never merged with the album artist: on a compilation that is "Various
    Artists" for every track, and the performer is the only field that says who
    is actually playing. Empty when the two agree or there is no performer.
    """
    album_artist, performer = album_artist or "", performer or ""
    return performer if performer and performer != album_artist else ""


def playing_artist(album_artist, performer) -> str:
    """The one name to show for what is playing: the performer when there is one."""
    return (performer or "") or (album_artist or "")


def track_year(attributes):
    """A track's year, which is its album's: the server sends no other.

    A real track element carries ``parentYear`` and no ``year`` at all.
    ``attributes`` is the element's own attribute mapping; the result is the raw
    value, or ``None`` when the element carries neither.
    """
    return attributes.get("parentYear") or attributes.get("year") or None


#: The library preference that says whether sonic analysis runs.
ANALYSIS_SETTING = "musicAnalysis"


def preferences_path(section_key) -> str:
    """Where a library section's preferences are read."""
    return f"/library/sections/{section_key}/prefs"


def sonic_analysis(preferences):
    """Whether a library's sonic analysis is switched on: True, False or None.

    ``preferences`` is the parsed answer from :func:`preferences_path`. Read from
    the library's own setting, never inferred from the mood vocabulary: the
    metadata agent writes moods too, so a library with the analysis off and two
    hundred moods looks analysed. ``None`` means the server did not say.
    """
    for setting in preferences.iter("Setting"):
        if setting.attrib.get("id") == ANALYSIS_SETTING:
            return str(setting.attrib.get("value", "")).strip().lower() in ("true", "1")
    return None


# ------------------------------------------------------------ nearest titles

#: Which hub of the server's free-text search answers for each kind of name.
NEAREST_KINDS = {"artist": "artist", "album": "album", "track": "track", "query": "track"}

NEAREST_SHOWN = 3

NEAREST_PATH = "/hubs/search"


def nearest_request(typed: str, section_key, *, shown: int = NEAREST_SHOWN) -> tuple:
    """The path and parameters that ask for the titles nearest ``typed``."""
    return NEAREST_PATH, {"query": typed, "sectionId": section_key, "limit": shown}


def _integer(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def nearest_rows(answer, kind: str, *, shown: int = NEAREST_SHOWN) -> list:
    """The titles of one kind out of a parsed ``/hubs/search`` answer."""
    rows = []
    for hub in answer.iter("Hub"):
        if hub.attrib.get("type") != kind:
            continue
        for child in list(hub)[:shown]:
            rows.append(
                {
                    "type": kind,
                    "key": _integer(child.attrib.get("ratingKey")),
                    "title": child.attrib.get("title", ""),
                    "artist": child.attrib.get("grandparentTitle")
                    or child.attrib.get("parentTitle")
                    or "",
                }
            )
    return rows


def nearest_titles(fetch, texts: dict, *, section_key, on_error=None) -> list:
    """The closest real titles to each name that matched nothing.

    ``texts`` maps a kind of name (a key of :data:`NEAREST_KINDS`) to what was
    typed, and ``fetch(path, params)`` is the caller's own request, returning
    the parsed answer. Each row carries the kind it answers under ``_flag``.

    The titles are a recovery set -- exact strings to search on -- and never the
    search itself: free text is the weak path, and its answer is offered, not
    substituted. A failure of ``fetch`` is therefore swallowed, and handed to
    ``on_error`` if the caller wants to know: the search succeeded and found
    nothing, and an aid that could turn that into an error is worse than none.
    """
    rows = []
    for flag, typed in texts.items():
        kind = NEAREST_KINDS[flag]
        path, params = nearest_request(typed, section_key)
        try:
            answer = fetch(path, params)
        except Exception as exc:
            if on_error is not None:
                on_error(exc)
            continue
        rows.extend({**row, "_flag": flag} for row in nearest_rows(answer, kind))
    return rows
