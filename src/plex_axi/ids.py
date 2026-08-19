"""The handoff: which `plex://` string is safe to print, and which is a bug.

``plex-axi`` ends at an identifier. It never plays anything, so the identifier
*is* the product of every command, and there are five strings in circulation
that all look like one:

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
===================================  ==========================  ==============

The last two are the trap: they are the same *shape* in two different
namespaces, one of which is a legitimate Plex identifier that plexapi hands out
under the attribute name ``guid``. Fed to a media player as a content id, one
resolves to a server that does not exist and the other crashes it.

So this module builds exactly one content id -- the first form -- and every
command labels it ``media_id``. The ``guid`` is printed too, under
its own label, because it is the only identifier that survives a re-match: a
``ratingKey`` is a row number in one server's database and moves when the
library is rebuilt. :func:`stability_note` is what says so wherever a human
might copy one into a configuration file.
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

STABILITY_NOTE = (
    "rating_key is local to this server and changes when an item is re-matched or the "
    "library is rebuilt; guid is the identifier that survives, so keep them together"
)


def stability_note() -> str:
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


def handoff(machine_identifier: str, item, *, hint: str = "") -> dict:
    """The labelled identifier block every item-producing command prints.

    The labels are vendor-neutral on purpose: this tool ships to anyone with a
    Plex library, and naming one particular consumer in the default output would
    be wrong for everybody else. ``hint`` carries the "play this with ..." line
    only when the operator has configured one -- see :func:`handoff_hint`.
    """
    rating_key = getattr(item, "ratingKey", None)
    guid = getattr(item, "guid", "") or ""
    block = {
        "media_id": media_content_id(machine_identifier, rating_key),
        "rating_key": int(rating_key),
        "guid": guid,
        "note": STABILITY_NOTE,
    }
    if hint:
        block["play_with"] = hint
    return block


#: Where an operator declares the command that plays a media id in *their*
#: house. It is configuration rather than a hardcoded line because plex-axi has
#: no idea what owns the speakers where it is installed, and a suggestion that
#: names the wrong consumer is worse than none: an agent will run it.
HINT_VAR = "PLEX_AXI_PLAY_HINT"

#: Placeholders a hint template may carry. Anything else is left alone, so a
#: template with a typo prints as written rather than failing the command.
_HINT_FIELDS = ("media_id", "rating_key", "guid")


def handoff_hint(environ, block: dict) -> str:
    """Render the operator's configured play command, or nothing at all.

    An unset variable yields an empty string and the field is omitted entirely.
    That is the deliberate default: nothing in plex-axi's own output assumes
    what will play the id it just produced.
    """
    template = (environ or {}).get(HINT_VAR, "")
    if not template.strip():
        return ""
    rendered = template
    for field in _HINT_FIELDS:
        rendered = rendered.replace("{" + field + "}", str(block.get(field, "")))
    return rendered
