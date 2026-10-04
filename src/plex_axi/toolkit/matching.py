"""How a typed name is made to match a title the server holds.

Three things about Plex's title filter were measured against a real server and
none of them is what the filter's own label -- "contains" -- says:

* **A comma is an OR.** The server splits a filter value on commas into
  alternatives, and an empty alternative matches everything, so a title with a
  comma in it returned unrelated rows and a value *ending* in one returned the
  whole library.
* **It matches word prefixes, in order.** Each word typed has to begin a word of
  the title, and in the order typed. ``oser`` does not find a title containing
  it; ``exa tra`` finds "Example Track". A doubled space is an empty word, and
  an empty word matches nothing.
* **Nothing is folded.** An ASCII apostrophe does not match the typographic one
  most catalogue titles carry, and an unaccented letter does not match its
  accented form. Roughly one track in sixteen on an ordinary library carries
  typographic punctuation, so a name typed the way anybody types it missed.

So a typed value is cleaned (:func:`clean_text`), sent in each punctuation
spelling it could have (:func:`spellings`) -- using the comma-OR above, on
purpose this time -- and, when that still finds nothing, the server's own
free-text search is asked for the nearest titles, because that one *does* fold
both.

**Everything here is pure, and the module imports nothing but the standard
library.** A string in, a string or a list out: no error class, no output
boundary, no transport, no flag names. A function that finds "there is nothing
left to search for" says so in its return value, and the caller decides how to
refuse.

Two more judgements are made on names the server has *already* handed back,
because the word-prefix match above returns more than was meant:

* :func:`resolve_name` picks one of several held names for a typed one, and
  never by position: a tie after folding, or no match at all, comes back as the
  candidates rather than as the first of them.
* :func:`exact_matches` keeps the rows whose name *is* the typed one, for a name
  that is also a word inside somebody else's -- which the server's filter
  cannot tell apart.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: What the server's ``=`` on a title actually does, printed where its own label
#: would have said "contains". The echo is a promise about the predicate that
#: ran; a caller told "contains" tries a substring and concludes the item is
#: not in the library.
TEXT_OPERATOR = "has words beginning"

#: ASCII punctuation and the typographic character a catalogue title usually
#: carries in its place.
_APOSTROPHE = "\u2019"
_OPEN_QUOTE, _CLOSE_QUOTE = "\u201c", "\u201d"
_ELLIPSIS = "\u2026"
_HYPHEN, _EN_DASH = "\u2010", "\u2013"

#: The reverse direction: a typographic character pasted from somewhere, against
#: a library tagged in ASCII.
_TO_ASCII = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2010": "-",
    "\u2011": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2026": "...",
}

#: How many spellings one value may expand to. Each is an alternative in the
#: URL, and four covers every combination the measured library needed.
MAX_SPELLINGS = 4

_SPACE = re.compile(r"\s+")


def clean_text(raw) -> str:
    """One typed value, with the two things the server misreads taken out.

    The comma is replaced by a space rather than removed, so ``Last, First``
    still presents both words to the word-prefix match. Whitespace is collapsed
    because a doubled space is an empty word to the server, and stripped because
    a leading one is too.

    Returns ``""`` when nothing is left, which the caller must refuse rather
    than send: an empty value is an empty alternative, and that matches every
    item in the library.
    """
    return _SPACE.sub(" ", str(raw).replace(",", " ")).strip()


def _typographic(value: str, hyphen: str) -> str:
    out = value.replace("...", _ELLIPSIS).replace("'", _APOSTROPHE).replace("-", hyphen)
    opening = True
    chars = []
    for char in out:
        if char == '"':
            chars.append(_OPEN_QUOTE if opening else _CLOSE_QUOTE)
            opening = not opening
        else:
            chars.append(char)
    return "".join(chars)


def to_ascii(value: str) -> str:
    """Typographic punctuation as the ASCII a keyboard produces."""
    return "".join(_TO_ASCII.get(char, char) for char in value)


def spellings(value: str) -> list:
    """The value as typed, then each punctuation spelling a title might hold.

    As typed is always first, so the echo and the hints name what the caller
    wrote. A value with no punctuation in it expands to itself alone and costs
    nothing.
    """
    candidates = [
        value,
        _typographic(value, _HYPHEN),
        _typographic(value, _EN_DASH),
        to_ascii(value),
    ]
    return list(dict.fromkeys(candidates))[:MAX_SPELLINGS]


def fold(value: str) -> str:
    """A name reduced to what two spellings of it have in common.

    Accents dropped, typographic punctuation made ASCII, case folded and
    everything that is not a letter or a digit turned into a space. Used only to
    *check* an answer the server gave, never to filter one.
    """
    decomposed = unicodedata.normalize("NFKD", to_ascii(str(value)))
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _SPACE.sub(" ", re.sub(r"[^\w]+", " ", plain.casefold())).strip()


def loosely_matches(typed: str, held: str) -> bool:
    """Whether every word typed begins a word of ``held``, after folding both."""
    words = fold(held).split()
    return all(any(word.startswith(part) for word in words) for part in fold(typed).split())


_YEAR = re.compile(r"^[0-9]{4}$")


def year(raw):
    """A release year as four ASCII digits, or ``None`` when it is not one.

    The server answers a malformed year with a bare refusal -- no field named,
    nothing to try next -- so the shape is checked before it is sent. ASCII
    only: ``\\d`` and ``str.isdigit`` both accept digits from other scripts.
    """
    value = str(raw).strip()
    return value if _YEAR.match(value) else None


# ------------------------------------------------- choosing among held names

#: One held name is the typed one.
RESOLVED = "resolved"
#: More than one held name folds to the typed one, and nothing tells them apart.
AMBIGUOUS = "ambiguous"
#: No held name is the typed one; the candidates are the near misses.
MISSING = "missing"
#: Nothing was typed, once cleaned.
EMPTY_NAME = "empty"


@dataclass(frozen=True)
class Resolution:
    """What one typed name resolved to among the names a server holds.

    ``match`` is set only when ``status`` is :data:`RESOLVED`. Otherwise
    ``candidates`` carries what the caller should offer back -- the tied
    entries, or the near misses -- in the order they were given.
    """

    status: str
    match: object = None
    candidates: tuple = ()

    @property
    def resolved(self) -> bool:
        return self.status == RESOLVED


def same_name(typed, held) -> bool:
    """Whether two spellings are one name, after folding both.

    Equality, not the word-prefix match: ``Example`` is not ``Example Band``.
    Two empty names are not the same name.
    """
    folded = fold(typed)
    return bool(folded) and folded == fold(held)


def exact_matches(rows, typed, *, names=None) -> list:
    """The rows whose name is ``typed``, out of rows a looser match returned.

    The server's filter matches word prefixes, so a name that is a word inside
    another artist's name returns both artists' rows. ``names`` reads the names
    a row answers to -- one string or several, e.g. a track's album artist and
    its performer -- and defaults to the row itself.
    """
    kept = []
    for row in rows:
        held = names(row) if names else row
        if isinstance(held, str):
            held = (held,)
        if any(same_name(typed, name) for name in held or ()):
            kept.append(row)
    return kept


def resolve_name(typed, candidates, *, name=None) -> Resolution:
    """Choose the candidate ``typed`` names, or say why none was chosen.

    Tried in order: the string exactly as typed, then equality after folding.
    Either settles it only when exactly one candidate qualifies. A tie is
    :data:`AMBIGUOUS` and a miss is :data:`MISSING`, and both hand back
    candidates -- the tied entries, or the ones ``typed`` loosely matches --
    because the first entry of a list is an accident of the server's sort, not
    an answer. ``name`` reads a candidate's name and defaults to the candidate.
    """
    read = name or (lambda candidate: candidate)
    entries = [(candidate, str(read(candidate) or "")) for candidate in candidates]
    wanted = clean_text(typed)
    if not fold(wanted):
        return Resolution(EMPTY_NAME)
    for same in (
        lambda held: held == wanted or held == str(typed),
        lambda held: same_name(wanted, held),
    ):
        hits = [candidate for candidate, held in entries if same(held)]
        if len(hits) == 1:
            return Resolution(RESOLVED, hits[0], (hits[0],))
        if hits:
            return Resolution(AMBIGUOUS, None, tuple(hits))
    near = tuple(candidate for candidate, held in entries if loosely_matches(wanted, held))
    return Resolution(MISSING, None, near)
