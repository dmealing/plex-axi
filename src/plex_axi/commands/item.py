"""`plex-axi track|album|artist <key>` -- one item, in full.

Three nouns, one implementation, because a detail view differs only in which
libtype it will accept and which relations it reports.

Two fields here exist nowhere else in the Plex tooling landscape and are the
reason the command earns its place beside the raw `api` escape hatch:

* **``analysis``** -- Plex's ``musicAnalysisVersion``. A track that has not been
  analysed has no moods and cannot be a seed for `similar`, and until you can
  see the version there is no way to tell that apart from "this track is not
  similar to anything".
* **``--check-files``** -- ``accessible`` and ``exists`` on the media part. Both
  are empty on an ordinary fetch, because the client library sends
  ``checkFiles: 0`` by default, so reading them needs a second round-trip that
  makes the server stat the file. That cost is why it is a flag and not a
  default -- and why, when the flag is off, this view says *not checked* rather
  than reporting the empty value as "not accessible". A diagnostic that answers
  a question it did not ask is worse than one that declines to.
"""

from __future__ import annotations

from ..argspec import Command, Flag, Sub
from ..errors import UsageError
from ..ids import handoff, validate_rating_key
from ..music import date_only, stars, tag_titles
from ..output import HelpBlock, truncate
from ..plex import translate
from ._common import PREVIEW_CHARS

#: What each noun accepts, and the sibling command that lists them.
NOUNS = ("track", "album", "artist")


def _command(name: str) -> Command:
    flags = [Flag("--full", boolean=True, note="print the whole summary instead of a preview")]
    notes = [
        "rating is in stars (0-5), the same scale as `search --rated-min`",
        "rating_key is local to this server; guid is the identifier that survives a re-match",
        "read-only: this command cannot change anything on the server",
    ]
    if name == "track":
        flags.insert(
            0,
            Flag(
                "--check-files",
                boolean=True,
                note=(
                    "ask the server to stat the file; costs a second request, "
                    "so without it availability reads 'not checked', never 'missing'"
                ),
            ),
        )
        notes.insert(0, "analysis is Plex's musicAnalysisVersion; 0 means `similar` has no seed")
    return Command(
        name=name,
        summary=f"Show one {name} in full, with its media id",
        usage=f"usage: plex-axi {name} <rating_key> [flags]",
        default_sub=name,
        subs=(
            Sub(
                name=name,
                args=("<rating_key>",),
                flags=tuple(flags),
                summary=f"Show one {name}",
            ),
        ),
        notes=tuple(notes),
        examples=(
            f"plex-axi {name} 12345",
            f"plex-axi search --artist 'Example Artist' --type {name}",
        ),
    )


_COMMANDS = {name: _command(name) for name in NOUNS}

COMMAND = _COMMANDS["track"]


def COMMAND_FOR(name: str) -> Command:
    return _COMMANDS[name]


def run(ctx, name: str, sub: str, parsed):
    key = validate_rating_key(parsed.positionals[0], invocation=f"plex-axi {name}")
    server = ctx.server()
    try:
        item = server.fetchItem(f"/library/metadata/{key}")
    except Exception as exc:
        raise translate(
            exc,
            what=f"{name} {key}",
            help_lines=[
                f"Run `plex-axi search --{name} '<title>'` to find this server's rating key",
                "A rating key from another server, or from before a library rebuild, will not "
                "resolve here",
            ],
        ) from None

    found = getattr(item, "type", "") or "item"
    if found != name:
        raise UsageError(
            f"{key} is a {found} on this server, not a {name}",
            help_lines=[
                f"Run `plex-axi {found} {key}` instead"
                if found in NOUNS
                else f"Run `plex-axi search --type {name}` to find a {name}",
            ],
            code="WRONG_ITEM_TYPE",
        )

    doc = _BUILDERS[name](item, parsed)

    doc["item"] = handoff(server.machineIdentifier, item)

    help_lines = _next_steps(name, item)
    if help_lines:
        doc["help"] = HelpBlock(help_lines)
    return doc


# ------------------------------------------------------------------ builders


def _summary(item, parsed) -> tuple:
    text = (getattr(item, "summary", "") or "").strip()
    if not text:
        return "", ""
    if parsed.get("full"):
        return text, ""
    return truncate(text, PREVIEW_CHARS, "Run the same command with `--full` for the whole summary")


def _tags(item) -> dict:
    """The tag columns, omitted when the library carries none of that kind."""
    out = {}
    for label, attribute in (("genres", "genres"), ("moods", "moods"), ("styles", "styles")):
        value = tag_titles(getattr(item, attribute, None))
        if value:
            out[label] = value
    return out


def _track(item, parsed) -> dict:
    album_artist = getattr(item, "grandparentTitle", "") or ""
    performer = getattr(item, "originalTitle", "") or ""
    doc = {
        "track": getattr(item, "title", "") or "",
        "artist": album_artist,
    }
    if performer and performer != album_artist:
        # Never merged with `artist`: on a compilation the album artist is
        # "Various Artists" for every track, and this is the only field that
        # says who is actually playing.
        doc["track_artist"] = performer
    doc.update(
        {
            "album": getattr(item, "parentTitle", "") or "",
            "year": getattr(item, "year", "") or "",
            "index": getattr(item, "index", "") or "",
            "duration": _duration(getattr(item, "duration", None)),
            "rating": stars(getattr(item, "userRating", None)) or "unrated",
            "plays": getattr(item, "viewCount", 0) or 0,
            "skips": getattr(item, "skipCount", 0) or 0,
            "last_played": date_only(getattr(item, "lastViewedAt", None)) or "never",
            "added": date_only(getattr(item, "addedAt", None)),
            "analysis": _analysis(item),
        }
    )
    doc.update(_tags(item))
    doc["media"] = _media(item, parsed)
    summary, hint = _summary(item, parsed)
    if summary:
        doc["summary"] = summary
        if hint:
            doc["truncated"] = hint
    return doc


def _album(item, parsed) -> dict:
    doc = {
        "album": getattr(item, "title", "") or "",
        "artist": getattr(item, "parentTitle", "") or "",
        "year": getattr(item, "year", "") or "",
        "tracks": getattr(item, "leafCount", "") or "",
        "rating": stars(getattr(item, "userRating", None)) or "unrated",
        "plays": getattr(item, "viewCount", 0) or 0,
        "last_played": date_only(getattr(item, "lastViewedAt", None)) or "never",
        "added": date_only(getattr(item, "addedAt", None)),
        "studio": getattr(item, "studio", "") or "",
    }
    doc.update(_tags(item))
    summary, hint = _summary(item, parsed)
    if summary:
        doc["summary"] = summary
        if hint:
            doc["truncated"] = hint
    return doc


def _artist(item, parsed) -> dict:
    doc = {
        "artist": getattr(item, "title", "") or "",
        "albums": getattr(item, "childCount", "") or "",
        "tracks": getattr(item, "leafCount", "") or "",
        "rating": stars(getattr(item, "userRating", None)) or "unrated",
        "plays": getattr(item, "viewCount", 0) or 0,
        "last_played": date_only(getattr(item, "lastViewedAt", None)) or "never",
        "added": date_only(getattr(item, "addedAt", None)),
    }
    doc.update(_tags(item))
    summary, hint = _summary(item, parsed)
    if summary:
        doc["summary"] = summary
        if hint:
            doc["truncated"] = hint
    return doc


_BUILDERS = {"track": _track, "album": _album, "artist": _artist}


def _analysis(item):
    """Plex's music analysis version, and what a zero means.

    A zero is not a small number here: it means the track was never analysed, so
    it has no moods and `similar` has no seed to work from. Printing a bare 0
    would leave that indistinguishable from a version number.
    """
    version = getattr(item, "musicAnalysisVersion", None)
    if version in (None, ""):
        return "not reported by this server"
    if int(version) <= 0:
        return "0 (not analysed: no moods, and `similar` has no seed)"
    return int(version)


def _duration(milliseconds) -> str:
    if not milliseconds:
        return ""
    total = int(milliseconds) // 1000
    return f"{total // 60}:{total % 60:02d}"


# --------------------------------------------------------------------- media


def _media(item, parsed) -> dict:
    """The playability facts, and an honest account of which were checked."""
    parts = [part for media in (getattr(item, "media", None) or []) for part in (media.parts or [])]
    if not parts:
        return {"files": 0, "availability": "no media part on this item"}

    checked = bool(parts and parsed.get("check_files"))
    if parsed.get("check_files"):
        try:
            item.reload(checkFiles=True)
            parts = [part for media in (item.media or []) for part in (media.parts or [])] or parts
        except Exception:
            checked = False

    part = parts[0]
    doc = {
        "files": len(parts),
        "container": getattr(part, "container", "") or "",
        "bitrate": _bitrate(item),
        "size": getattr(part, "size", "") or "",
    }
    if not parsed.get("check_files"):
        # The empty value is not evidence of absence: the client library sends
        # `checkFiles: 0`, so the server never looked. Saying "not accessible"
        # here would be a different untruth from the one it is avoiding.
        doc["availability"] = "not checked (run with --check-files)"
        return doc
    if not checked:
        doc["availability"] = "the server did not answer the file check"
        return doc

    accessible = getattr(part, "accessible", None)
    exists = getattr(part, "exists", None)
    doc["availability"] = _availability(accessible, exists)
    doc["file"] = getattr(part, "file", "") or ""
    return doc


def _availability(accessible, exists) -> str:
    if exists is False:
        return "missing: the server cannot find the file"
    if accessible is False:
        return "present but not readable by the server (check permissions)"
    if accessible and exists:
        return "readable by the server"
    return "the server checked but reported neither accessible nor exists"


def _bitrate(item) -> str:
    for media in getattr(item, "media", None) or []:
        if getattr(media, "bitrate", None):
            return f"{media.bitrate} kbps"
    return ""


def _next_steps(name: str, item) -> list:
    key = getattr(item, "ratingKey", "")
    lines = []
    if name == "track":
        lines.append(f"Run `plex-axi similar {key}` for sonically similar tracks")
        parent = getattr(item, "parentRatingKey", None)
        if parent:
            lines.append(f"Run `plex-axi album {parent}` for the album this is on")
        grandparent = getattr(item, "grandparentRatingKey", None)
        if grandparent:
            lines.append(f"Run `plex-axi artist {grandparent}` for the album artist")
    elif name == "album":
        parent = getattr(item, "parentRatingKey", None)
        if parent:
            lines.append(f"Run `plex-axi artist {parent}` for the artist")
        title = getattr(item, "title", "")
        if title:
            lines.append(f'Run `plex-axi search --album "{title}"` for its tracks')
    else:
        title = getattr(item, "title", "")
        if title:
            lines.append(f'Run `plex-axi search --artist "{title}" --type album` for its albums')
            lines.append(f'Run `plex-axi search --artist "{title}" --rated-min 4` for the best')
    return lines
