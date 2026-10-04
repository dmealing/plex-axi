"""The rules a Plex Media Server makes a music client learn, as a library.

``plex_axi.toolkit`` is the supported import surface of this distribution for a
program that talks to the same server through its own code. Everything in it was
measured against a real server, and all of it is pure:

* **Plain values in, plain values out.** Strings, mappings, lists and parsed
  documents; no server object, no session, no client library.
* **Errors as data.** Nothing here raises to refuse a value. A name that cannot
  be resolved comes back as a :class:`Resolution` carrying the candidates; a
  value with nothing left in it comes back empty or as ``None``.
* **No connection, no output.** A function that needs an answer from the server
  takes it already fetched, or takes a callable the caller supplies.
* **Synchronous.** An asynchronous caller runs these in a thread.

The four modules are importable on their own -- :mod:`~plex_axi.toolkit.matching`,
:mod:`~plex_axi.toolkit.search`, :mod:`~plex_axi.toolkit.shapes` and
:mod:`~plex_axi.toolkit.ids` -- and the names below are the same objects,
gathered. The surface is new and may grow; a name listed in ``__all__`` is not
removed or changed in meaning without a release note saying so.
"""

from __future__ import annotations

from . import ids, matching, search, shapes
from .ids import (
    LEGACY_MEDIA_ID,
    MEDIA_ID,
    NON_ASCII_DIGITS,
    RATING_KEY,
    UNRECOGNISED,
    Reference,
    parse_reference,
    same_server,
)
from .matching import (
    AMBIGUOUS,
    EMPTY_NAME,
    MAX_SPELLINGS,
    MISSING,
    RESOLVED,
    TEXT_OPERATOR,
    Resolution,
    clean_text,
    exact_matches,
    fold,
    loosely_matches,
    resolve_name,
    same_name,
    spellings,
    to_ascii,
    year,
)
from .search import (
    ANALYSIS_SETTING,
    NEAREST_KINDS,
    NEAREST_PATH,
    NEAREST_SHOWN,
    PERFORMER_FIELD,
    PERFORMER_TITLE,
    TEXT_FLAGS,
    artist_or_performer,
    compose,
    filter_value,
    nearest_request,
    nearest_rows,
    nearest_titles,
    performer_honoured,
    playing_artist,
    preferences_path,
    sonic_analysis,
    track_artist,
    track_year,
)
from .shapes import (
    ACTION_ENDINGS,
    ACTION_PREFIXES,
    EMPTY,
    FOREIGN,
    UNPARSEABLE,
    acts_on_get,
    answer_kind,
    has_dot_segments,
    is_credential_name,
    is_foreign_root,
    is_server_fault,
    normalise_path,
    parsed_fault,
)

__all__ = [
    "ACTION_ENDINGS",
    "ACTION_PREFIXES",
    "AMBIGUOUS",
    "ANALYSIS_SETTING",
    "EMPTY",
    "EMPTY_NAME",
    "FOREIGN",
    "LEGACY_MEDIA_ID",
    "MAX_SPELLINGS",
    "MEDIA_ID",
    "MISSING",
    "NEAREST_KINDS",
    "NEAREST_PATH",
    "NEAREST_SHOWN",
    "NON_ASCII_DIGITS",
    "PERFORMER_FIELD",
    "PERFORMER_TITLE",
    "RATING_KEY",
    "RESOLVED",
    "TEXT_FLAGS",
    "TEXT_OPERATOR",
    "UNPARSEABLE",
    "UNRECOGNISED",
    "Reference",
    "Resolution",
    "acts_on_get",
    "answer_kind",
    "artist_or_performer",
    "clean_text",
    "compose",
    "exact_matches",
    "filter_value",
    "fold",
    "has_dot_segments",
    "ids",
    "is_credential_name",
    "is_foreign_root",
    "is_server_fault",
    "loosely_matches",
    "matching",
    "nearest_request",
    "nearest_rows",
    "nearest_titles",
    "normalise_path",
    "parse_reference",
    "parsed_fault",
    "performer_honoured",
    "playing_artist",
    "preferences_path",
    "resolve_name",
    "same_name",
    "same_server",
    "search",
    "shapes",
    "sonic_analysis",
    "spellings",
    "to_ascii",
    "track_artist",
    "track_year",
    "year",
]
