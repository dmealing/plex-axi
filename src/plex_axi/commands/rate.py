"""`plex-axi rate <rating_key> --stars <0-5>` -- the write that pairs with the read.

`--rated-min` has been readable since the first release and every rating this
tool prints is in stars, 0-5. This is the other direction of the same scale: a
rating read out of `search` or `track` can be handed straight back here, and
what comes back is read from the server rather than echoed from the request.

Plex stores 0-10 and a star is two points. That conversion lives in
:mod:`plex_axi.music` and is done once, here as everywhere else, because a tool
that took stars in one command and points in another would be a silent trap --
the kind that looks like it worked and halves every rating it touches.

**A user rating is not library metadata.** It is per-account state, which is why
it is the one write this tool has and why editing titles, artwork or matches
stays out: those change the library for everyone and are a different job with a
different blast radius.
"""

from __future__ import annotations

from .. import writes
from ..argspec import Command, Flag, Sub
from ..errors import UsageError
from ..ids import handoff, validate_rating_key
from ..music import LIBTYPES, POINTS_PER_STAR, parse_stars, stars
from ..output import HelpBlock
from ..plex import translate
from ._common import article

#: Plex's own "no rating", and the value the client library puts in the URL when
#: it is asked to clear one. It is named here rather than passed: the library
#: rejects a negative rating *from a caller* and only sends this when the
#: argument is omitted, so clearing is the absence of a value, and handing this
#: number over would be a client-side refusal that never reaches the server.
UNRATED = -1

COMMAND = Command(
    name="rate",
    summary="Set or clear your rating on one track, album or artist",
    usage="usage: plex-axi rate <rating_key> --stars <0-5> [--write]",
    default_sub="rate",
    access=writes.MUTATING,
    subs=(
        Sub(
            name="rate",
            args=("<rating_key>",),
            flags=(
                Flag("--stars", "<0-5>", note="the same scale every rating here prints in"),
                Flag("--clear", boolean=True, note="remove the rating instead of setting one"),
                Flag(
                    "--write",
                    boolean=True,
                    note="apply it; without this the command shows the change and sends nothing",
                ),
            ),
            summary="Rate one item",
        ),
    ),
    notes=(
        "the rating printed afterwards is read back from the server, not echoed from the request",
        "a rating is per-account state, not library metadata; editing metadata stays out of scope",
        "rating something to the value it already has is a no-op and exits 0",
    ),
    examples=(
        "plex-axi rate 12345 --stars 4",
        "plex-axi rate 12345 --stars 4 --write",
        "plex-axi rate 12345 --clear --write",
    ),
)


def COMMAND_FOR(name: str) -> Command:
    return COMMAND


def run(ctx, name: str, sub: str, parsed):
    key = validate_rating_key(parsed.positionals[0], invocation="plex-axi rate")
    wanted = _wanted(parsed, key)

    # Before the connection, not after it: a refused write must not be a request
    # the server ever hears about.
    writes.require(ctx.environ, action=f"rate {key}")

    server = ctx.server()
    item = _fetch(server, key)
    libtype = getattr(item, "type", "") or "item"
    if libtype not in LIBTYPES:
        raise UsageError(
            f"{key} is {article(libtype)} {libtype} on this server, and plex-axi rates music only",
            help_lines=[
                f"Run `plex-axi search --artist '<name>' --type {LIBTYPES[0]}` to find a music key",
            ],
            code="WRONG_ITEM_TYPE",
        )

    current = stars(getattr(item, "userRating", None))
    doc: dict = {libtype: getattr(item, "title", "") or ""}
    artist = getattr(item, "grandparentTitle", "") or getattr(item, "parentTitle", "") or ""
    if artist and libtype != "artist":
        doc["artist"] = artist

    if current == wanted:
        # AXI 6: the desired state already holds, so this is an outcome, not a
        # failure. Saying so beats writing the same value and calling it a change.
        doc["rating"] = _shown(current)
        doc["applied"] = f"no change: already {_shown(current)}"
        doc["item"] = handoff(server.machineIdentifier, item)
        return doc

    if not parsed.get("write"):
        doc["rating"] = _shown(current)
        doc["rating_after"] = _shown(wanted)
        doc["preview"] = writes.preview_note(_invocation(key, parsed))
        doc["item"] = handoff(server.machineIdentifier, item)
        doc["help"] = HelpBlock(
            [
                f"Run `{_invocation(key, parsed)} --write` to apply it",
                f"Run `plex-axi {libtype} {key}` for the full detail view first",
            ]
        )
        return doc

    try:
        if wanted is None:
            item.rate()  # omitted, not UNRATED -- see the constant
        else:
            item.rate(wanted * POINTS_PER_STAR)
    except Exception as exc:
        raise translate(
            exc,
            what=f"the rating on {libtype} {key}",
            help_lines=[
                "A rating is per-account: a token shared into this server may not carry one",
                f"Run `plex-axi {libtype} {key}` to see what the server holds now",
            ],
        ) from None

    # Read it back rather than reporting the request. The value the server holds
    # is the answer; the value that was sent is only what was asked for.
    written = stars(getattr(_fetch(server, key), "userRating", None))
    doc["rating_before"] = _shown(current)
    doc["rating"] = _shown(written)
    doc["applied"] = (
        f"set to {_shown(wanted)}"
        if written == wanted
        else f"asked for {_shown(wanted)}; the server now reports {_shown(written)}"
    )
    doc["item"] = handoff(server.machineIdentifier, item)
    doc["help"] = HelpBlock(
        [
            f"Run `plex-axi search --rated-min {wanted:g}` for everything at that rating or better"
            if wanted
            else f"Run `plex-axi {libtype} {key}` to confirm",
        ]
    )
    return doc


def _wanted(parsed, key: str):
    """The rating asked for, in stars, or ``None`` for `--clear`."""
    raw = parsed.get("stars")
    clearing = bool(parsed.get("clear"))
    if clearing and raw not in (None, ""):
        raise UsageError(
            "--stars and --clear ask for different things; pass one",
            help_lines=[
                f"Run `plex-axi rate {key} --stars 4 --write` to set a rating",
                f"Run `plex-axi rate {key} --clear --write` to remove one",
            ],
            code="CONFLICTING_FLAGS",
        )
    if clearing:
        return None
    if raw in (None, ""):
        raise UsageError(
            "rate needs a rating to set",
            help_lines=[
                f"Run `plex-axi rate {key} --stars 4 --write`",
                f"Run `plex-axi rate {key} --clear --write` to remove the rating instead",
            ],
            code="MISSING_RATING",
        )
    return parse_stars(raw, flag="--stars")


def _fetch(server, key: str):
    try:
        return server.fetchItem(f"/library/metadata/{key}")
    except Exception as exc:
        raise translate(
            exc,
            what=f"item {key}",
            help_lines=[
                "Run `plex-axi search --track '<title>'` to find this server's rating key",
                "A rating key from another server, or from before a library rebuild, will not "
                "resolve here",
            ],
        ) from None


def _shown(value):
    return "unrated" if value is None else f"{value:g} stars"


def _invocation(key: str, parsed) -> str:
    if parsed.get("clear"):
        return f"plex-axi rate {key} --clear"
    return f"plex-axi rate {key} --stars {parse_stars(parsed.get('stars'), flag='--stars'):g}"
