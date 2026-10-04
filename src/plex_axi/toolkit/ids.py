"""Which strings name an item on a Plex Media Server, read from a caller's hand.

A caller holds an identifier in one of three spellings, and a fourth that only
looks like one:

* ``plex://<machineIdentifier>/<ratingKey>`` -- the media id, which names the
  server as well as the row;
* ``plex://<ratingKey>`` -- the same without the server, from older
  integrations;
* the rating key alone;
* a number written in digits that are not ASCII, which ``str.isdigit`` and
  ``\\d`` both accept and no server resolves.

:func:`parse_reference` says which one a string is. It refuses nothing: a string
that is none of them comes back as :data:`UNRECOGNISED`, for the caller to judge.

A rating key is a row number in *one* server's database, so the same number on
another server is a different item. :func:`same_server` is that check, made once
a connection exists and the server's own identifier is known.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The media id. The server half is a machine identifier -- hexadecimal -- which
#: is what keeps ``plex://track/12345`` (a tool's internal id) out of this
#: pattern: ``track`` is not hex.
_MEDIA_ID = re.compile(r"^plex://([0-9A-Fa-f]{8,})/([0-9]+)$")

#: The rating key alone, behind the scheme.
_LEGACY_MEDIA_ID = re.compile(r"^plex://([0-9]+)$")

_RATING_KEY = re.compile(r"^[0-9]+$")

MEDIA_ID = "media-id"
LEGACY_MEDIA_ID = "legacy-media-id"
RATING_KEY = "rating-key"
#: Digits, but not ASCII ones: not a key a server will resolve.
NON_ASCII_DIGITS = "non-ascii-digits"
UNRECOGNISED = "unrecognised"


@dataclass(frozen=True)
class Reference:
    """One identifier, taken apart.

    ``key`` is the rating key in ASCII digits, or ``None`` when ``kind`` is
    :data:`UNRECOGNISED`. For :data:`NON_ASCII_DIGITS` it is the number that was
    meant, so the caller can offer it back. ``machine`` is set only for a media
    id that names its server.
    """

    kind: str
    key: str | None
    machine: str | None
    raw: str

    @property
    def usable(self) -> bool:
        return self.kind in (MEDIA_ID, LEGACY_MEDIA_ID, RATING_KEY)


def parse_reference(raw) -> Reference:
    """Take apart whatever a caller offered as an item's identifier."""
    value = str(raw).strip()
    if value.isdigit() and not value.isascii():
        try:
            key = str(int(value))
        except ValueError:
            key = None
        return Reference(NON_ASCII_DIGITS, key, None, value)
    match = _MEDIA_ID.match(value)
    if match:
        return Reference(MEDIA_ID, match.group(2), match.group(1), value)
    match = _LEGACY_MEDIA_ID.match(value)
    if match:
        return Reference(LEGACY_MEDIA_ID, match.group(1), None, value)
    if _RATING_KEY.match(value):
        return Reference(RATING_KEY, value, None, value)
    return Reference(UNRECOGNISED, None, None, value)


def same_server(machine, server_machine) -> bool:
    """Whether an identifier naming ``machine`` belongs to the server in hand.

    An identifier that names no server is taken at its word.
    """
    return not machine or str(machine).lower() == str(server_machine).lower()
