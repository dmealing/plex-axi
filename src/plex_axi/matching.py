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

**Everything here is pure, and the module imports nothing of this tool's.** A
string in, a string or a list out: no error class, no output boundary, no
transport, no flag names. The refusals a command raises when one of these says
"there is nothing left to search for" are written where the flag is known, in
:mod:`plex_axi.music`. That is what lets these rules be lifted into a shared
package unchanged, should a second consumer want them.
"""

from __future__ import annotations

import re
import unicodedata

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
