"""`plex-axi playlist list|show|create|add|remove` -- audio playlists, and their two traps.

Every playlist tool in the Plex landscape omits the same two guards, and both
of them are one line in the client library:

* **``PlexServer.playlists()`` returns every playlist on the server** -- film
  playlists, photo playlists, the lot -- unless ``playlistType='audio'`` is
  passed. A music tool that lists all of them is answering a different question,
  and an agent that then adds a track to one of them meets the next trap.
* **``addItems`` raises ``BadRequest`` twice, for different reasons.** On a
  *smart* playlist, because a smart playlist's contents are a saved search and
  cannot be added to at all. On *mixed media types*, because Plex will not hold
  a film and a song in one list. The message that comes back names the client
  library and its own attribute; :func:`_write_error` turns each into a sentence
  saying which of the two happened and what to do instead.

Both are translated rather than surfaced, because the difference matters: one
means "pick a different playlist", the other means "pick different items", and a
raw ``BadRequest`` says neither.

Resolution is by exact title, case-folded, and nothing else. No stripping of the
word "playlist", no substring matching, no nearest neighbour: on a miss the
command hands back every audio playlist on the server and lets the caller choose.
"""

from __future__ import annotations

from .. import writes
from ..argspec import Command, Flag, Sub
from ..errors import AxiError, UsageError
from ..ids import validate_rating_key
from ..music import available_fields, default_fields, rows_for, with_track_artist
from ..output import HelpBlock
from ..plex import translate
from ._common import parse_limit, project, select_fields

#: The one playlist type this tool will look at. Passed on every listing, which
#: is the guard the rest of the landscape leaves out.
AUDIO = "audio"

DEFAULT_LIMIT = 100
DEFAULT_ITEM_LIMIT = 50

_KEY_FLAG = Flag(
    "--key",
    "<rating_key>",
    repeat=True,
    note="a track's rating key, from `search` or `pick`; repeat for several",
)
_WRITE_FLAG = Flag(
    "--write",
    boolean=True,
    note="apply it; without this the command shows what would change and sends nothing",
)

COMMAND = Command(
    name="playlist",
    summary="List, inspect and edit the audio playlists on this server",
    usage="usage: plex-axi playlist <list|show|create|add|remove> [<title>] [flags]",
    default_sub="list",
    subs=(
        Sub(
            name="list",
            flags=(Flag("--limit", "<n>", default=DEFAULT_LIMIT),),
            summary="List the audio playlists",
        ),
        Sub(
            name="show",
            args=("<title>",),
            flags=(
                Flag("--limit", "<n>", default=DEFAULT_ITEM_LIMIT),
                Flag("--fields", "<a,b,c>"),
            ),
            summary="Show one playlist's tracks",
        ),
        Sub(
            name="create",
            args=("<title>",),
            flags=(_KEY_FLAG, _WRITE_FLAG),
            summary="Create an audio playlist from rating keys",
            access=writes.MUTATING,
        ),
        Sub(
            name="add",
            args=("<title>",),
            flags=(_KEY_FLAG, _WRITE_FLAG),
            summary="Add tracks to an existing playlist",
            access=writes.MUTATING,
        ),
        Sub(
            name="remove",
            args=("<title>",),
            flags=(_KEY_FLAG, _WRITE_FLAG),
            summary="Remove tracks from a playlist",
            access=writes.MUTATING,
        ),
    ),
    notes=(
        "only audio playlists are listed or edited; video and photo playlists on the "
        "same server are deliberately invisible here",
        "a smart playlist's contents are a saved search and cannot be edited by adding "
        "items; the command says so rather than letting the server refuse",
        "titles match exactly, case-folded; on a miss the real titles are handed back",
        "nothing here plays a playlist: `show` prints the tracks and their media ids",
    ),
    examples=(
        "plex-axi playlist",
        "plex-axi playlist show 'Example Playlist'",
        "plex-axi playlist add 'Example Playlist' --key 12345 --key 12346",
        "plex-axi playlist create 'Example Playlist' --key 12345 --write",
    ),
)


def COMMAND_FOR(name: str) -> Command:
    return COMMAND


def run(ctx, name: str, sub: str, parsed):
    if sub in ("create", "add", "remove"):
        title = parsed.positionals[0]
        keys = _keys(parsed, sub, title)
        # Before the connection: a refused write is not a request the server
        # ever hears about.
        writes.require(ctx.environ, action=f"{sub} {title!r}")
        return _MUTATORS[sub](ctx, title, keys, parsed)
    return {"list": _list, "show": _show}[sub](ctx, parsed)


# ---------------------------------------------------------------------- reads


def _list(ctx, parsed):
    limit = parse_limit(parsed.get("limit"), default=DEFAULT_LIMIT, maximum=1000)
    playlists = _audio_playlists(ctx.server())
    shown = playlists[:limit]

    doc = {"count": f"{len(shown)} of {len(playlists)} audio playlists"}
    if not playlists:
        doc["playlists"] = "0 audio playlists on this server"
        doc["help"] = HelpBlock(
            [
                "Run `plex-axi playlist create '<title>' --key <rating_key> --write` to make one",
                "Run `plex-axi search --artist '<name>'` to find rating keys",
            ]
        )
        return doc

    doc["playlists"] = [_playlist_row(p) for p in shown]
    doc["help"] = HelpBlock(
        [
            f"Run `plex-axi playlist show '{shown[0].title}'` for one playlist's tracks",
            "Run `plex-axi playlist add '<title>' --key <rating_key>` to preview an addition",
        ]
    )
    return doc


def _show(ctx, parsed):
    title = parsed.positionals[0]
    limit = parse_limit(parsed.get("limit"), default=DEFAULT_ITEM_LIMIT)
    server = ctx.server()
    playlist = _resolve(server, title)
    items = _items(playlist)

    tracks = [item for item in items if getattr(item, "type", "") == "track"]
    rows = rows_for("track", tracks[:limit])
    fields = select_fields(parsed.get("fields"), available_fields("track"), default_fields("track"))
    fields = with_track_artist(fields, rows)

    doc = {
        "playlist": playlist.title,
        "count": f"{len(rows)} of {len(items)} items",
        "smart": bool(playlist.smart),
    }
    if not items:
        doc["tracks"] = "0 items in this playlist"
        return doc

    if not rows:
        # Items but no tracks is a real state, not a contradiction: every music
        # libtype reports listType 'audio', so Plex will hold albums and artists
        # in an audio playlist. The zero is the answer, the `other` line says
        # what the playlist does hold, and the suggestions cannot quote a track
        # key because there is none in the list.
        doc["tracks"] = "0 tracks in this playlist"
        doc["other"] = f"{len(items)} item(s) that are not tracks"
        doc["help"] = HelpBlock(
            [
                f"Run `plex-axi playlist add '{playlist.title}' --key <rating_key>` to preview "
                "adding a track",
                "Run `plex-axi search --track '<title>'` to find rating keys",
            ]
        )
        return doc

    doc["tracks"] = project(rows, fields)
    if len(tracks) != len(items):
        # Counted, not detailed: a non-track item in an audio playlist is not
        # something a music tool should be rendering rows for.
        doc["other"] = f"{len(items) - len(tracks)} item(s) that are not tracks"
    doc["help"] = HelpBlock(
        [
            f"Run `plex-axi track {rows[0]['key']}` for one track's detail and its media id",
            f"Run `plex-axi playlist remove '{playlist.title}' --key {rows[0]['key']}` to preview "
            "removing one",
        ]
    )
    return doc


# --------------------------------------------------------------------- writes


def _create(ctx, title, keys, parsed):
    server = ctx.server()
    existing = _find(_audio_playlists(server), title)
    if existing is not None:
        raise AxiError(
            f"an audio playlist called {existing.title!r} already exists on this server",
            help_lines=[
                f"Run `plex-axi playlist add '{existing.title}' "
                f"--key {keys[0]} --write` to add to it",
                f"Run `plex-axi playlist show '{existing.title}'` to see what it holds",
            ],
            code="PLAYLIST_EXISTS",
        )

    items = _fetch_items(server, keys)
    doc = {"playlist": title, "smart": False}
    if not parsed.get("write"):
        doc["would_hold"] = _item_rows(items)
        doc["preview"] = writes.preview_note(_invocation("create", title, keys))
        doc["help"] = HelpBlock(
            [f"Run `{_invocation('create', title, keys)} --write` to create it"]
        )
        return doc

    from plexapi.playlist import Playlist

    try:
        created = Playlist.create(server, title, items=items)
    except Exception as exc:
        raise _write_error(exc, action="create", title=title, keys=keys) from None

    doc["playlist"] = created.title
    doc["type"] = created.playlistType
    doc["holds"] = f"{len(_items(created))} items"
    doc["applied"] = f"created with {len(items)} item(s)"
    doc["help"] = HelpBlock([f"Run `plex-axi playlist show '{created.title}'` to confirm"])
    return doc


def _add(ctx, title, keys, parsed):
    server = ctx.server()
    playlist = _resolve(server, title)
    _refuse_smart(playlist, action="add items to")
    items = _fetch_items(server, keys)

    doc = {"playlist": playlist.title, "smart": False, "holds": f"{len(_items(playlist))} items"}
    if not parsed.get("write"):
        doc["would_add"] = _item_rows(items)
        doc["preview"] = writes.preview_note(_invocation("add", title, keys))
        doc["help"] = HelpBlock([f"Run `{_invocation('add', title, keys)} --write` to apply it"])
        return doc

    try:
        playlist.addItems(items)
    except Exception as exc:
        raise _write_error(exc, action="add items to", title=playlist.title, keys=keys) from None

    doc["holds"] = f"{len(_items(_resolve(server, playlist.title)))} items"
    doc["applied"] = f"added {len(items)} item(s)"
    doc["help"] = HelpBlock([f"Run `plex-axi playlist show '{playlist.title}'` to confirm"])
    return doc


def _remove(ctx, title, keys, parsed):
    server = ctx.server()
    playlist = _resolve(server, title)
    _refuse_smart(playlist, action="remove items from")
    held = _items(playlist)
    wanted = {str(key) for key in keys}
    going, repeated = _memberships(held, wanted)
    absent = sorted(wanted - {str(getattr(item, "ratingKey", "")) for item in held})

    if absent:
        raise AxiError(
            f"{', '.join(absent)} is not in {playlist.title!r}"
            if len(absent) == 1
            else f"{', '.join(absent)} are not in {playlist.title!r}",
            help_lines=[
                f"Run `plex-axi playlist show '{playlist.title}'` for the keys it does hold",
                "A rating key is local to this server and moves when an item is re-matched",
            ],
            code="NOT_IN_PLAYLIST",
        )

    doc = {"playlist": playlist.title, "smart": False, "holds": f"{len(held)} items"}
    if repeated:
        # One removal per key, and said out loud. A playlist may hold the same
        # track twice; deleting every membership from one `--key` would remove
        # more than the caller named, and the client library resolves a track to
        # its *first* membership anyway, so the second delete would fail on an
        # id that no longer exists and report the playlist as missing.
        listed = ", ".join(repeated)
        doc["note"] = f"{listed} appears more than once; one copy of each is removed"
    if not parsed.get("write"):
        doc["would_remove"] = _item_rows(going)
        doc["preview"] = writes.preview_note(_invocation("remove", title, keys))
        doc["help"] = HelpBlock([f"Run `{_invocation('remove', title, keys)} --write` to apply it"])
        return doc

    try:
        playlist.removeItems(going)
    except Exception as exc:
        raise _write_error(
            exc, action="remove items from", title=playlist.title, keys=keys
        ) from None

    doc["holds"] = f"{len(_items(_resolve(server, playlist.title)))} items"
    doc["applied"] = f"removed {len(going)} item(s)"
    doc["help"] = HelpBlock([f"Run `plex-axi playlist show '{playlist.title}'` to confirm"])
    return doc


_MUTATORS = {"create": _create, "add": _add, "remove": _remove}


# -------------------------------------------------------------------- helpers


def _memberships(held: list, wanted: set) -> tuple:
    """The first membership of each wanted key, and the keys held more than once."""
    going, seen, repeated = [], set(), []
    for item in held:
        key = str(getattr(item, "ratingKey", ""))
        if key not in wanted:
            continue
        if key in seen:
            if key not in repeated:
                repeated.append(key)
            continue
        seen.add(key)
        going.append(item)
    return going, repeated


def _audio_playlists(server) -> list:
    """Every audio playlist, and only those.

    ``playlistType`` is the guard: without it this returns the server's film and
    photo playlists too, and the first thing a caller would do with one of those
    is meet the mixed-media-type refusal.
    """
    try:
        return list(server.playlists(playlistType=AUDIO))
    except Exception as exc:
        raise translate(exc, what="the audio playlists") from None


def _find(playlists: list, title: str):
    wanted = str(title).strip().casefold()
    for playlist in playlists:
        if (playlist.title or "").strip().casefold() == wanted:
            return playlist
    return None


def _resolve(server, title: str):
    """One playlist by exact, case-folded title, or the real list to choose from."""
    playlists = _audio_playlists(server)
    found = _find(playlists, title)
    if found is not None:
        return found
    titles = ", ".join(repr(p.title) for p in playlists) or "none"
    raise AxiError(
        f"no audio playlist called {title!r} on this server",
        help_lines=[
            f"audio playlists: {titles}",
            "Titles match exactly; pass one of those rather than a description of it",
            f"Run `plex-axi playlist create '{title}' --key <rating_key> --write` to make it",
        ],
        code="NO_SUCH_PLAYLIST",
    )


def _items(playlist) -> list:
    try:
        return list(playlist.items())
    except Exception as exc:
        raise translate(exc, what=f"the contents of {playlist.title!r}") from None


def _keys(parsed, sub: str, title: str) -> list:
    raw = parsed.get("key", []) or []
    keys = [
        validate_rating_key(value, invocation=f"plex-axi playlist {sub} '{title}'") for value in raw
    ]
    if not keys:
        raise UsageError(
            f"`playlist {sub}` needs at least one --key",
            help_lines=[
                f"Run `plex-axi playlist {sub} '{title}' --key <rating_key>`",
                "Run `plex-axi search --artist '<name>'` to find rating keys",
            ],
            code="MISSING_KEY",
        )
    # Deduplicated in order: asking twice for the same key is a typo, not a
    # request to hold the same track twice.
    return list(dict.fromkeys(keys))


def _fetch_items(server, keys: list) -> list:
    items = []
    for key in keys:
        try:
            items.append(server.fetchItem(f"/library/metadata/{key}"))
        except Exception as exc:
            raise translate(
                exc,
                what=f"item {key}",
                help_lines=[
                    "Run `plex-axi search --track '<title>'` to find this server's rating key",
                ],
            ) from None
    return items


def _item_rows(items: list) -> list:
    """A compact row per item, whatever type it turned out to be.

    The type is a column rather than an assumption: it is the field that
    explains the mixed-media refusal when one of these is not music.
    """
    return [
        {
            "key": int(getattr(item, "ratingKey", 0) or 0),
            "type": getattr(item, "type", "") or "",
            "title": getattr(item, "title", "") or "",
            "artist": getattr(item, "grandparentTitle", "")
            or getattr(item, "parentTitle", "")
            or "",
        }
        for item in items
    ]


def _playlist_row(playlist) -> dict:
    return {
        "title": playlist.title or "",
        "items": playlist.leafCount,
        "smart": bool(playlist.smart),
        "updated": _date(getattr(playlist, "updatedAt", None)),
    }


def _date(value) -> str:
    try:
        return value.strftime("%Y-%m-%d")
    except AttributeError:
        return ""


def _refuse_smart(playlist, *, action: str) -> None:
    """Refuse before the write, so a preview never promises what cannot happen."""
    if playlist.smart:
        raise _smart_error(playlist.title, action=action)


def _smart_error(title: str, *, action: str) -> AxiError:
    return AxiError(
        f"cannot {action} {title!r}: it is a smart playlist",
        help_lines=[
            "A smart playlist's contents are a saved search that Plex re-runs; its items are "
            "a result, not a list, and adding to it is not something the server offers",
            f"Run `plex-axi playlist show '{title}'` to see what the search currently returns",
            "Run `plex-axi playlist create '<title>' --key <rating_key> --write` for an "
            "ordinary playlist you can edit",
        ],
        code="SMART_PLAYLIST",
    )


def _write_error(exc: Exception, *, action: str, title: str, keys: list):
    """Name which of the two known refusals happened, and never echo the library.

    Both arrive as the same exception type carrying the same shape of message,
    and the difference is the whole point: one means pick a different playlist,
    the other means pick different items.
    """
    text = str(exc)
    if "smart playlist" in text:
        return _smart_error(title, action=action)
    if "mix media types" in text:
        return AxiError(
            f"cannot {action} {title!r}: those items are not all the same kind of media",
            help_lines=[
                "Plex holds one media type per playlist, and an audio playlist takes music only",
                f"Run `plex-axi track <key>` on each of {', '.join(keys)} to see which is not music",
                "A rating key from a film or photo library resolves here but cannot go in",
            ],
            code="MIXED_MEDIA_TYPES",
        )
    return translate(
        exc,
        what=f"the playlist {title!r}",
        help_lines=[f"Run `plex-axi playlist show '{title}'` to see what the server holds now"],
    )


def _invocation(sub: str, title: str, keys: list) -> str:
    flags = " ".join(f"--key {key}" for key in keys)
    return f"plex-axi playlist {sub} '{title}' {flags}".strip()
