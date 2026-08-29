"""`plex-axi genres` / `moods` / `styles` -- the library's own vocabulary.

Three nouns, one implementation: each is ``listFilterChoices`` on a different
Plex filter field. They exist for two reasons.

The first is that a filter value is only useful if the server recognises it, and
no other Plex tool exposes the list. "jazz" and "Jazz" and "Vocal Jazz" are
different tags on a real library, and guessing between them is the difference
between twelve results and none.

The second is recovery. A search that matched nothing hands these commands back
by name, so the next attempt is made from the server's own list rather than from
a synonym. That is deliberately where the resolution happens: this tool never
guesses which tag a caller meant by stripping words or matching substrings --
it surfaces the real set and lets the caller choose.
"""

from __future__ import annotations

from axi_toolkit.plex.filters import LIBTYPES

from ..argspec import Command, Flag, Sub
from ..errors import UsageError
from ..output import HelpBlock
from ..plex import translate
from ._common import article, parse_libtype, parse_limit

#: Which Plex filter field each noun reads, and the libtype it is carried on.
#:
#: genre and style sit on the artist in a music library; mood is written by
#: Plex's own analysis at every level, so it takes the libtype asked for.
FIELDS = {
    "genres": ("genre", "artist"),
    "styles": ("style", "artist"),
    "moods": ("mood", None),
}

DEFAULT_LIMIT = 300


def _command(name: str) -> Command:
    field, fixed = FIELDS[name]
    flags = [Flag("--limit", "<n>", default=DEFAULT_LIMIT)]
    notes = [
        f"the values this library will accept for `search --{field}`, read from the server",
    ]
    if fixed:
        notes.insert(
            1,
            f"{name} are carried on the {fixed} in a Plex music library, not on the track",
        )
    else:
        flags.insert(0, Flag("--type", "<track|album|artist>", default="track"))
        notes.insert(1, "moods are written at every level; --type chooses which set to list")
    return Command(
        name=name,
        summary=f"List the {name} this library uses",
        usage=f"usage: plex-axi {name} [flags]",
        default_sub=name,
        subs=(Sub(name=name, flags=tuple(flags), summary=f"List every {field}"),),
        notes=tuple(notes),
        examples=(f"plex-axi {name}", f"plex-axi search --{field} '<value>'"),
    )


_COMMANDS = {name: _command(name) for name in FIELDS}

COMMAND = _COMMANDS["genres"]


def COMMAND_FOR(name: str) -> Command:
    return _COMMANDS[name]


def run(ctx, name: str, sub: str, parsed):
    field, fixed = FIELDS[name]
    libtype = fixed or parse_libtype(parsed.get("type"))
    limit = parse_limit(parsed.get("limit"), default=DEFAULT_LIMIT, maximum=2000)
    section = ctx.section()

    try:
        choices = section.listFilterChoices(field, libtype=libtype)
    except Exception as exc:  # translated below; nothing from the client library escapes
        raise _no_such_field(exc, name, field, libtype) from None

    titles = sorted({(choice.title or "").strip() for choice in choices} - {""})
    shown = titles[:limit]

    doc = {
        "count": f"{len(shown)} of {len(titles)} total",
        "field": f"{libtype}.{field}",
    }
    if not titles:
        doc[name] = f"0 {name} on this library"
        doc["help"] = HelpBlock(
            [
                f"This library has no {field} tags; Plex writes them when it matches an item",
                "Run `plex-axi doctor` to confirm the library is scanned and analysed",
            ]
        )
        return doc

    doc[name] = shown
    help_lines = [f"Run `plex-axi search --{field} '{shown[0]}'` to search on one of these"]
    if len(titles) > len(shown):
        help_lines.append(f"Run `plex-axi {name} --limit {len(titles)}` for all {len(titles)}")
    help_lines.append("Values are exact: pass one of these strings, not a synonym for it")
    doc["help"] = HelpBlock(help_lines)
    return doc


def _no_such_field(exc: Exception, name: str, field: str, libtype: str):
    if "Unknown filter field" in str(exc):
        return UsageError(
            f"this library does not tag {libtype}s with {article(field)} {field}",
            help_lines=[
                f"Run `plex-axi {name} --type artist` if this library tags artists instead"
                if libtype != "artist"
                else "",
                f"available types: {', '.join(LIBTYPES)}",
            ],
            code="NO_SUCH_FILTER_FIELD",
        )
    return translate(exc, what=f"the {name} list")
