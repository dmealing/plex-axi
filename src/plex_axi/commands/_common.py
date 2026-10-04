"""Helpers shared by the command modules."""

from __future__ import annotations

import shlex

from axi_toolkit.plex.filters import LIBTYPES
from axi_toolkit.plex.ids import validate_rating_key

from ..errors import AxiError, UsageError
from ..toolkit import ids

#: Preview length for long free-text values (a summary, a review) before
#: `--full` is needed.
PREVIEW_CHARS = 800


def quoted(value) -> str:
    """One value as a shell word, for a command line this tool prints.

    Every suggestion is something an agent pastes into a shell, and the values
    interpolated into one come from tags -- which come from files, which come
    from anywhere. A title in double quotes runs its `$(...)`; a title in single
    quotes breaks on its own apostrophe. `shlex.quote` is the one spelling that
    survives both, and the output boundary strips control characters besides.

    One character survives neither: a backtick. A suggestion is delimited by
    backticks, so a value containing one ends the command early for anybody
    reading it out of the line, whatever the shell would have made of it. Such a
    value is replaced by a placeholder -- a suggestion that says "fill this in"
    is honest where one that reads as complete and is not would be run.
    """
    text = str(value)
    if "`" in text:
        return "'<exact title>'"
    return shlex.quote(text)


class KeyRef:
    """A rating key, and the server the caller said it belongs to, if they said."""

    __slots__ = ("key", "machine", "raw")

    def __init__(self, key: str, machine: str | None, raw: str) -> None:
        self.key = key
        self.machine = machine
        self.raw = raw

    def confirm(self, server) -> str:
        """The key, once the server it names is known to be this one.

        A media id is `plex://<machineIdentifier>/<ratingKey>`, and a rating key
        is a row number in *one* server's database -- so the same number on
        another server is a different item. The identifier cannot be checked
        until a connection exists, which is why this is a second step.
        """
        if not ids.same_server(self.machine, server.machineIdentifier):
            raise AxiError(
                f"{self.raw!r} is a media id for a different server",
                help_lines=[
                    "A rating key is a row number on one server, so that number names "
                    "something else here",
                    "Run `plex-axi search --track '<title>'` to find the item on this server",
                ],
                code="MEDIA_ID_OTHER_SERVER",
            )
        return self.key


def parse_key(raw, *, command) -> KeyRef:
    """Accept what this tool prints as an identifier, and refuse what only looks like one.

    Every row carries a ``key`` and a ``media_id``, and both come back here: a
    command that printed an identifier and then refused it cost the caller a
    call to learn which of the two it wanted. ``command`` is the caller's own
    words after the tool name, flags included, so a recovery line repeats the
    whole invocation rather than the half before the key.

    Which spelling a string is, is :func:`plex_axi.toolkit.ids.parse_reference`;
    this is where that judgement becomes a refusal naming the command.
    """
    ref = ids.parse_reference(raw)
    if ref.kind == ids.NON_ASCII_DIGITS:
        # Not a rating key the server will resolve, so it is refused here rather
        # than sent and reported as not found.
        raise UsageError(
            f"a rating key is written in ASCII digits, got {ref.raw!r}",
            help_lines=[f"Run `plex-axi {' '.join(command)} {ref.key}`"],
            code="BAD_RATING_KEY",
        )
    if ref.kind in (ids.MEDIA_ID, ids.LEGACY_MEDIA_ID):
        return KeyRef(ref.key, ref.machine, ref.raw)
    return KeyRef(validate_rating_key(ref.raw, command=tuple(command)), None, ref.raw)


def parse_limit(raw, *, default: int, maximum: int = 500) -> int:
    if raw is None:
        return default
    try:
        value = int(str(raw))
    except ValueError:
        raise UsageError(
            f"--limit needs a whole number, got {raw!r}",
            help_lines=[f"Run the command again with `--limit {default}`"],
            code="BAD_LIMIT",
        ) from None
    if value < 1:
        raise UsageError(
            f"--limit must be at least 1, got {value}",
            help_lines=[f"Run the command again with `--limit {default}`"],
            code="BAD_LIMIT",
        )
    if value > maximum:
        raise UsageError(
            f"--limit is capped at {maximum}, got {value}",
            help_lines=[
                f"Run the command again with `--limit {maximum}`",
                "Narrow the search instead; a list an agent cannot read is not a result",
            ],
            code="BAD_LIMIT",
        )
    return value


def parse_libtype(raw, *, default: str = "track") -> str:
    if raw in (None, ""):
        return default
    value = str(raw).strip().lower().rstrip("s") or default
    if value not in LIBTYPES:
        raise UsageError(
            f"--type must be one of {', '.join(LIBTYPES)}, got {raw!r}",
            help_lines=[f"Run the command again with `--type {default}`"],
            code="BAD_TYPE",
        )
    return value


def more_hint(command: str, total: int, cap: int, noun: str) -> str:
    """The follow-up that reveals the rest of a list cut short by ``--limit``.

    ``cap`` is the command's own ``--limit`` ceiling: a hint past it would be
    advice to run something the command refuses.
    """
    if total <= cap:
        return f"Run `{command} --limit {total}` for all {total} {noun}"
    return f"Run `{command} --limit {cap}` for the first {cap} of {total} {noun}"


def fields_flag(chosen) -> str:
    """The caller's own ``--fields`` value, quoted, for a follow-up that repeats it.

    A reveal hint that drops the named columns would suggest a different answer
    than the one the caller was just shown.
    """
    return f" --fields {shlex.quote(chosen)}" if chosen else ""


def select_fields(raw, available: list, default: list) -> list:
    """Resolve ``--fields`` against the fields a view can actually produce."""
    if not raw:
        return list(default)
    wanted = [part.strip() for part in str(raw).split(",") if part.strip()]
    if not wanted:
        return list(default)
    unknown = [name for name in wanted if name not in available]
    if unknown:
        raise UsageError(
            f"unknown field{'s' if len(unknown) > 1 else ''}: {', '.join(unknown)}",
            help_lines=[f"available fields: {', '.join(available)}"],
            code="UNKNOWN_FIELD",
        )
    return wanted


def project(rows: list, fields: list) -> list:
    """Reduce rows to the requested fields, preserving field order.

    A field a row does not carry becomes ``None`` rather than an empty string,
    so the output boundary renders it as null: "the server did not say" and "the
    value is empty" are different answers.
    """
    return [{name: row.get(name) for name in fields} for row in rows]


def article(word: str) -> str:
    """``a`` or ``an``, for a noun the server named rather than one we chose.

    Every libtype and item type in this tool is interpolated into a sentence
    somewhere, and two of the three begin with a vowel -- so a fixed "a" wrote
    "a album" and "a artist" in the errors most likely to be read closely.
    """
    return "an" if word[:1].lower() in "aeiou" else "a"


def plural(count: int, singular: str, many: str = "") -> str:
    word = singular if count == 1 else (many or f"{singular}s")
    return f"{count} {word}"


def count_line(shown: int, total: int) -> str:
    """The ``count:`` value for a list view.

    Reports the page against the exact match total, so an agent never has to
    paginate to find out how much it is not seeing. ``-1`` means the server
    declined to report a total, which is said plainly rather than guessed.
    """
    if total < 0:
        return f"{shown} shown (this server did not report a total)"
    return f"{shown} of {total} total"


def describe_filters(described: list) -> str:
    """A one-line echo of the applied filters, for an empty state."""
    return " ".join(f'{row["field"]} {row["operator"]} "{row["value"]}"' for row in described)


def parse_pairs(pairs: list, *, flag: str) -> dict:
    """Turn repeated ``--flag key=value`` tokens into a dict."""
    out: dict = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise UsageError(
                f"{flag} needs key=value, got {pair!r}",
                help_lines=[f"Run the command again with `{flag} type=10`"],
                code="BAD_PAIR",
            )
        out[key.strip()] = value
    return out
