"""Helpers shared by the command modules."""

from __future__ import annotations

from ..errors import UsageError
from ..music import LIBTYPES

#: Preview length for long free-text values (a summary, a review) before
#: `--full` is needed.
PREVIEW_CHARS = 800


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
