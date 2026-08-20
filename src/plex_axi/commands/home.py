"""The no-argument view: live state first, help second.

An agent that runs the bare command should learn what this library *is* -- which
server, which music section, how big, whether the analysis has run, what arrived
recently, whether anything is playing -- and be able to act on the next line. A
usage screen would cost it a second call to find that out.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from ..argspec import Command, Sub
from ..config import missing_env_vars, setup_help
from ..errors import AxiError
from ..music import date_only
from ..output import HelpBlock
from ._common import plural

DESCRIPTION = (
    "Structured, per-field music search and diagnosis against a Plex Media Server. "
    "Prefer this over raw curl or a free-text search for anything about a music library."
)

COMMAND = Command(
    name="home",
    summary="Show this music library at a glance",
    usage="usage: plex-axi",
    default_sub="home",
    subs=(Sub(name="home", summary="Show the server, the library and what is happening"),),
    examples=("plex-axi",),
)


def COMMAND_FOR(name: str) -> Command:
    return COMMAND


RECENT_SHOWN = 3


def executable_path() -> str:
    """The absolute path of this executable, with the home directory collapsed."""
    candidate = Path(sys.argv[0]).expanduser()
    try:
        resolved = candidate.resolve()
    except OSError:  # pragma: no cover - unresolvable argv[0] is not worth failing on
        resolved = candidate
    if not resolved.exists():
        resolved = Path(sys.executable).resolve()
    text = str(resolved)
    home = os.path.expanduser("~")
    if home and text.startswith(home):
        return "~" + text[len(home) :]
    return text


def run(ctx, name: str, sub: str, parsed):
    doc = {"bin": executable_path(), "description": DESCRIPTION}
    missing = missing_env_vars(ctx.environ)
    if missing:
        doc["error"] = f"{' and '.join(missing)} not set in the environment"
        doc["help"] = HelpBlock(setup_help())
        doc["__exit_code__"] = 1
        return doc

    config = ctx.config()
    doc["url"] = config.base_url

    try:
        server = ctx.server()
        section = ctx.section()
    except AxiError as exc:
        doc["error"] = exc.message
        doc["help"] = HelpBlock([*exc.help_lines, "Run `plex-axi doctor` to see which check fails"])
        doc["__exit_code__"] = 1
        return doc

    doc["server"] = f"{server.friendlyName} (Plex Media Server {server.version})"
    doc["library"] = f"{section.title} (key {section.key})"
    doc["holds"] = _counts(section)
    doc["analysis"] = _analysis(section)

    recent = _recent(section)
    if recent:
        doc["recent"] = recent
    doc["playing"] = _playing(server)

    doc["help"] = HelpBlock(
        [
            "Run `plex-axi search --artist '<name>' --track '<title>'` to search field by field",
            "Run `plex-axi genres` (or `moods`, `styles`) for the values this library will accept",
            "Run `plex-axi track <key>` for one item's detail and its media id",
            "Run `plex-axi doctor` when something looks wrong",
        ]
    )
    return doc


def _counts(section) -> str:
    parts = []
    for libtype, label in (("artist", "artists"), ("album", "albums"), ("track", "tracks")):
        try:
            total = section.totalViewSize(libtype=libtype, includeCollections=False)
        except Exception:
            total = None
        parts.append(f"{total} {label}" if total is not None else f"? {label}")
    return ", ".join(parts)


def _analysis(section) -> str:
    """How much of Plex's own music analysis this library has.

    The honest cheap measure is how many mood tags exist at all: Plex writes
    moods from the analysis, so an empty vocabulary means it has not run and
    `similar` will have nothing to work from. This is deliberately not phrased
    as a percentage, because the exact per-track coverage is not something the
    server will report in one request and an estimate would read as one.
    """
    try:
        moods = section.listFilterChoices("mood", libtype="track")
    except Exception:
        return "not reported by this server"
    if not moods:
        return "0 track moods: the sonic analysis has not run, so `similar` has no seeds"
    return f"{len(moods)} track moods in use (written by Plex's sonic analysis)"


def _recent(section) -> list:
    try:
        albums = list(section.recentlyAddedAlbums(maxresults=RECENT_SHOWN))
    except Exception:
        return []
    return [
        {
            "key": int(album.ratingKey),
            "album": album.title or "",
            "artist": getattr(album, "parentTitle", "") or "",
            "added": date_only(getattr(album, "addedAt", None)),
        }
        for album in albums
    ]


def _playing(server) -> str:
    try:
        sessions = list(server.sessions())
    except Exception:
        return "not reported by this server"
    music = sum(1 for s in sessions if getattr(s, "type", "") == "track")
    if not sessions:
        return "nothing"
    return (
        f"{plural(music, 'music stream')} of {plural(len(sessions), 'stream')} "
        "(run `plex-axi sessions`)"
    )
