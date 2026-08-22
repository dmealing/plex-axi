"""The handoff: which `plex://` string is safe to print, and which is a bug.

``plex-axi`` ends at an identifier: out of the box it plays nothing, so the
identifier *is* the product of every command -- ``play``, which exists only
where the operator has opened the playback gate, is the one exception. There
are six strings in circulation that all look like one:

===================================  ==========================  ==============
Form                                 Produced by                 Consumable?
===================================  ==========================  ==============
``plex://<machineIdentifier>/<key>`` a media browser             **yes** - the
                                                                 canonical form
``plex://<key>``                     older integrations          yes, but the
                                                                 consumer calls
                                                                 it legacy
``plex://{<json>}``                  play-queue dispatch         yes, matched
                                                                 before parsing
``plex://track/<ratingKey>``         a tool's internal id        **no** - reads
                                                                 as server
                                                                 ``"track"``
``plex://track/<24-hex>``            plexapi's own ``guid``      **no** - raises
                                                                 ``ValueError``
                                                                 in the consumer
``local://<ratingKey>``              Plex, for an item it        n/a - a guid,
                                     never matched               and not a
                                                                 durable one
===================================  ==========================  ==============

Forms four and five are the trap: they are the same *shape* in two different
namespaces, one of which is a legitimate Plex identifier that plexapi hands out
under the attribute name ``guid``. Fed to a media player as a content id, one
resolves to a server that does not exist and the other crashes it.

So this module builds exactly one content id -- the first form -- and every
command labels it ``media_id``. The ``guid`` is printed too, under its own
label, because it is *usually* the only identifier that survives a re-match: a
``ratingKey`` is a row number in one server's database and moves when the
library is rebuilt.

**Form six is why "usually".** An item Plex never matched to its catalogue
carries ``local://<ratingKey>`` -- the rating key with a scheme in front of it,
so it moves exactly when the rating key moves. Roughly one track in seven on an
ordinary library is one of these. :func:`stability_note` reads the scheme and
says which of the two situations the caller is in, because "keep the guid, it
survives" is advice that is false for those items and is at its most dangerous
precisely when someone is pasting one into a configuration file.
"""

from __future__ import annotations

import re

from .errors import UsageError

#: A rating key is a decimal integer. Validating the shape before building a URL
#: turns the guid/rating-key collision from an uncaught ``ValueError`` deep in a
#: consumer into a message naming both identifier shapes.
_RATING_KEY = re.compile(r"^\d+$")

#: A Plex guid for a music item: a namespace and a 24-character hex id.
_GUID = re.compile(r"^plex://(artist|album|track)/[0-9a-f]{24}$")

#: Form six. Plex hands this out for an item it never matched to its catalogue,
#: and it is the rating key with a scheme in front of it -- so it is a guid that
#: is not durable, which is the one combination the note must not get wrong.
_LOCAL_GUID = re.compile(r"^local://\d+$")

STABILITY_NOTE = (
    "rating_key is local to this server and changes when an item is re-matched or the "
    "library is rebuilt; guid is the identifier that survives, so keep them together"
)

#: What to say instead when the guid is form six. The rating key still moves;
#: what has changed is that the guid moves with it, so there is nothing here to
#: write down -- and saying so is more useful than a durability promise that
#: happens to be false.
LOCAL_STABILITY_NOTE = (
    "rating_key is local to this server and changes when an item is re-matched or the "
    "library is rebuilt; this item's guid is local:// plus that same rating key, so it "
    "changes with it -- match this one by artist and title, not by either identifier"
)


def stability_note(guid=None) -> str:
    """The durability note for one item, chosen by its guid's scheme.

    Called with no argument it gives the ordinary note, which is what every
    caller wanted before form six turned up.
    """
    if guid and _LOCAL_GUID.match(str(guid).strip()):
        return LOCAL_STABILITY_NOTE
    return STABILITY_NOTE


def validate_rating_key(raw: str, *, invocation: str) -> str:
    """Accept a rating key, and reject anything that only looks like one."""
    value = str(raw).strip()
    if _RATING_KEY.match(value):
        return value
    if _GUID.match(value):
        raise UsageError(
            f"{value!r} is a guid, not a rating key",
            help_lines=[
                "A guid names an item in Plex's catalogue; a rating key names a row on this server",
                "Run `plex-axi search --track '<title>'` to get this server's rating key",
            ],
            code="GUID_NOT_RATING_KEY",
        )
    if _LOCAL_GUID.match(value):
        # The one case where the answer is sitting inside the argument: a
        # `local://` guid *is* the rating key, so naming the number is a
        # complete recovery rather than a direction to go and look one up.
        raise UsageError(
            f"{value!r} is a guid, not a rating key",
            help_lines=[
                "Plex gives an item it never matched a `local://` guid, which is this "
                "server's rating key with a scheme in front of it",
                f"Run `{invocation} {value[len('local://') :]}`",
            ],
            code="GUID_NOT_RATING_KEY",
        )
    if value.startswith("plex://"):
        raise UsageError(
            f"{value!r} is a media id, not a rating key",
            help_lines=[
                "Pass the number after the last slash, which is what `rating_key:` reports",
                f"Run `{invocation} <rating_key>`",
            ],
            code="MEDIA_ID_NOT_RATING_KEY",
        )
    raise UsageError(
        f"a rating key is a number, got {value!r}",
        help_lines=[
            f"Run `{invocation} <rating_key>`",
            "Run `plex-axi search --artist '<name>'` to find one",
        ],
        code="BAD_RATING_KEY",
    )


def media_content_id(machine_identifier: str, rating_key) -> str:
    """Build the one `plex://` form a media player accepts unambiguously.

    ``plex://<machineIdentifier>/<ratingKey>`` names the server as well as the
    item. The shorter ``plex://<ratingKey>`` resolves only against a consumer's
    default server and is explicitly the legacy branch there; this tool knows the
    machine identifier for free, so there is no reason to emit the weaker one.
    """
    key = str(rating_key).strip()
    if not _RATING_KEY.match(key):
        # Unreachable through the CLI, which validates first. Kept because the
        # failure it prevents -- an unlabelled `plex://track/<hex>` reaching a
        # consumer -- is an uncaught crash rather than a wrong answer.
        raise ValueError("a media content id can only be built from a numeric rating key")
    if not machine_identifier:
        raise ValueError("a media content id needs the server's machineIdentifier")
    return f"plex://{machine_identifier}/{key}"


def media_id_for(machine_identifier: str, item):
    """The media id for one row, or ``None`` when it cannot be built truthfully.

    A list row is not an error path: an item the server described without a
    usable rating key must render as a null cell, not abort the command and not
    -- which is the failure this whole module exists to prevent -- fall back to
    some other ``plex://`` string that happens to be to hand.
    """
    key = str(getattr(item, "ratingKey", "") or "").strip()
    if not machine_identifier or not _RATING_KEY.match(key):
        return None
    return media_content_id(machine_identifier, key)


def handoff(machine_identifier: str, item) -> dict:
    """The labelled identifier block every item-producing command prints.

    Four fields, and nothing about what will consume them. The labels are
    vendor-neutral because this tool ships to anyone with a Plex library, and
    the output stops at the identifier because a suggestion about what plays it
    could only be assembled from something the caller told us -- which is
    information they already had. plex-axi prints identifiers and stops;
    ``play``, which exists only where the operator has opened the playback
    gate, prints this block and then starts the item (see the module docstring).
    """
    rating_key = getattr(item, "ratingKey", None)
    guid = getattr(item, "guid", "") or ""
    return {
        "media_id": media_content_id(machine_identifier, rating_key),
        "rating_key": int(rating_key),
        "guid": guid,
        # Four fields, and the fourth is the only one whose *text* depends on
        # the third: a `local://` guid is not durable, and a note promising it
        # is would be at its most wrong exactly where it is most likely to be
        # believed.
        "note": stability_note(guid),
    }
