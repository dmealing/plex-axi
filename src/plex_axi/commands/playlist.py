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

Resolution is by rating key, or by exact title, case-folded -- and nothing else.
No stripping of the word "playlist", no substring matching, no nearest
neighbour: on a miss the command hands back every audio playlist on the server,
key and title, and lets the caller choose. The key is there because a title is
not always typeable: real ones carry emoji and typographic apostrophes, and a
listing that printed no other handle made those playlists a shell-quoting
exercise before they were a Plex question.
"""

from __future__ import annotations

from axi_toolkit.plex.ids import media_id_for

from .. import writes
from ..argspec import Command, Flag, Sub
from ..errors import AxiError, UsageError
from ..music import available_fields, default_fields, rows_for, with_track_artist
from ..output import HelpBlock
from ..plex import translate
from ..toolkit import ids
from ._common import (
    KeyRef,
    article,
    fields_flag,
    more_hint,
    parse_key,
    parse_limit,
    project,
    quoted,
    select_fields,
)

#: The one playlist type this tool will look at. Passed on every listing, which
#: is the guard the rest of the landscape leaves out.
AUDIO = "audio"

DEFAULT_LIMIT = 100
DEFAULT_ITEM_LIMIT = 50

#: The `--limit` ceilings of the two list views. `parse_limit` refuses past them
#: and the reveal hints quote them, so both read the same number.
MAX_LIMIT = 1000
MAX_ITEM_LIMIT = 500

_KEY_FLAG = Flag(
    "--key",
    "<rating_key>",
    repeat=True,
    note="a track's rating key or media_id, from `search` or `pick`; repeat for several",
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
            flags=(
                Flag("--limit", "<n>", default=DEFAULT_LIMIT),
                Flag("--fields", "<a,b,c>", note="replaces the default columns"),
            ),
            summary="List the audio playlists",
        ),
        Sub(
            name="show",
            args=("<title-or-key>",),
            flags=(
                Flag("--limit", "<n>", default=DEFAULT_ITEM_LIMIT),
                Flag("--fields", "<a,b,c>", note="replaces the default columns"),
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
            args=("<title-or-key>",),
            flags=(_KEY_FLAG, _WRITE_FLAG),
            summary="Add tracks to an existing playlist",
            access=writes.MUTATING,
        ),
        Sub(
            name="remove",
            args=("<title-or-key>",),
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
        "repeating one of these writes is safe: when the playlist already holds "
        "everything a `create` or `add` names, or none of what a `remove` names, the "
        "command answers `already: … (no-op)` and exits 0 rather than failing",
        "a playlist is named by its `key` or `media_id` from `playlist list`, or by its "
        "exact case-folded title; on a miss the real keys and titles are handed back",
        "`--key` takes tracks: an album's or an artist's key is refused with the search "
        "that lists its tracks, rather than added as one item that is not a song",
        "`items` in a listing (`--fields key,title,items`) is the count the server "
        "declares, which for a smart playlist is cached; `playlist show` reports what it "
        "actually holds",
        f"listing columns: {', '.join(available_fields('playlist'))}",
        "nothing here plays a playlist: both `list` and `show` print the playlist's own "
        "media_id, and `show` prints one per track as well",
    ),
    examples=(
        "plex-axi playlist",
        "plex-axi playlist show 'Example Playlist'",
        "plex-axi playlist show 501",
        "plex-axi playlist add 'Example Playlist' --key 12345 --key 12346",
        "plex-axi playlist create 'Example Playlist' --key 12345 --write",
    ),
)


def COMMAND_FOR(name: str) -> Command:
    return COMMAND


def run(ctx, name: str, sub: str, parsed):
    if sub in ("create", "add", "remove"):
        title = parsed.positionals[0]
        if sub == "create" and not title.strip():
            raise UsageError(
                "a playlist needs a title, and this one is empty",
                help_lines=[
                    "Run `plex-axi playlist create '<title>' --key <rating_key>` to preview one"
                ],
                code="EMPTY_TITLE",
            )
        refs = _keys(parsed, sub, title)
        # Before the connection: a refused write is not a request the server
        # ever hears about.
        writes.require(ctx.environ, action=f"{sub} {title!r}")
        server = ctx.server()
        keys = list(dict.fromkeys(ref.confirm(server) for ref in refs))
        return _MUTATORS[sub](ctx, title, keys, parsed)
    return {"list": _list, "show": _show}[sub](ctx, parsed)


# ---------------------------------------------------------------------- reads


def _list(ctx, parsed):
    limit = parse_limit(parsed.get("limit"), default=DEFAULT_LIMIT, maximum=MAX_LIMIT)
    chosen = parsed.get("fields")
    # ``smart`` is the default's fourth column because it decides what a caller
    # can do next -- a smart playlist cannot be added to -- where ``items`` is a
    # count the server caches and gets wrong (see below), so it is asked for by
    # name.
    fields = select_fields(chosen, available_fields("playlist"), default_fields("playlist"))
    server = ctx.server()
    playlists = _audio_playlists(server)
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

    rows = [_playlist_row(p, server.machineIdentifier) for p in shown]
    doc["playlists"] = project(rows, fields)
    if "items" in fields:
        # `items` is the count the *server* declares, and on a smart playlist it
        # is a cached figure that drifts from what the saved search currently
        # returns -- seen on a real server as a declared 0 against 81 actual
        # items, and off by one even on a static list. Fetching the truth costs
        # one request per playlist; saying which number this is costs one line.
        doc["note"] = (
            "items is the count this server declares; a smart playlist's is cached and "
            "`playlist show` may return a different number, which is the real one"
        )
    help_lines = [
        f"Run `plex-axi playlist show {shown[0].ratingKey}` for one playlist's tracks",
        "Run `plex-axi playlist add '<title>' --key <rating_key>` to preview an addition",
    ]
    if len(shown) < len(playlists):
        carried = fields_flag(chosen)
        help_lines.append(
            more_hint(f"plex-axi playlist list{carried}", len(playlists), MAX_LIMIT, "playlists")
        )
    doc["help"] = HelpBlock(help_lines)
    return doc


def _show(ctx, parsed):
    title = parsed.positionals[0]
    limit = parse_limit(parsed.get("limit"), default=DEFAULT_ITEM_LIMIT, maximum=MAX_ITEM_LIMIT)
    server = ctx.server()
    playlist = _resolve(server, title)
    # One page, and the total from the container. Fetching the whole playlist to
    # print fifty rows of it cost four seconds on a ten-thousand-item list; the
    # server counts for the price of a header.
    items, total = _page(server, playlist, limit)

    tracks = [item for item in items if getattr(item, "type", "") == "track"]
    rows = rows_for("track", tracks, server.machineIdentifier)
    chosen = parsed.get("fields")
    fields = select_fields(chosen, available_fields("track"), default_fields("track"))
    if not chosen:
        fields = with_track_artist(fields, rows)

    doc = {
        "playlist": playlist.title,
        "key": int(playlist.ratingKey),
        # The playlist's own handoff id, not any track's: this is the one a
        # caller wants when they mean "play this whole playlist", and the track
        # rows below carry their own for the case where they mean one song.
        "media_id": media_id_for(server.machineIdentifier, playlist),
        "count": f"{len(rows)} of {total} items",
        "smart": bool(playlist.smart),
    }
    declared = getattr(playlist, "leafCount", None)
    if declared is not None and int(declared) != total:
        # The two commands must not contradict each other in silence. `playlist
        # list` prints the declared count because that is all a listing has;
        # here the real contents are in hand, so the disagreement is named.
        doc["declared"] = (
            f"this server declares {int(declared)} items; the {total} above are what "
            "it actually returned"
        )
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
        lines = ["Run `plex-axi search --track '<title>'` to find rating keys"]
        if not playlist.smart:
            lines.insert(
                0,
                f"Run `plex-axi playlist add {int(playlist.ratingKey)} --key <rating_key>` to "
                "preview adding a track",
            )
        doc["help"] = HelpBlock(lines)
        return doc

    doc["tracks"] = project(rows, fields)
    if len(tracks) != len(items):
        # Counted, not detailed: a non-track item in an audio playlist is not
        # something a music tool should be rendering rows for.
        doc["other"] = f"{len(items) - len(tracks)} item(s) that are not tracks"
    help_lines = [
        f"Run `plex-axi track {rows[0]['key']}` for one track's tags, analysis version "
        "and file details",
    ]
    if not playlist.smart:
        # Not offered on a smart playlist: its contents are a saved search, and
        # the command this line names would be refused.
        help_lines.append(
            f"Run `plex-axi playlist remove {int(playlist.ratingKey)} --key {rows[0]['key']}` "
            "to preview removing one"
        )
    if len(items) < total:
        carried = fields_flag(chosen)
        help_lines.append(
            more_hint(
                f"plex-axi playlist show {int(playlist.ratingKey)}{carried}",
                total,
                MAX_ITEM_LIMIT,
                "items",
            )
        )
    doc["help"] = HelpBlock(help_lines)
    return doc


# --------------------------------------------------------------------- writes


def _create(ctx, title, keys, parsed):
    server = ctx.server()
    existing = _find(_audio_playlists(server), title)
    if existing is not None:
        held = _items(existing) if not existing.smart else []
        missing = _not_held(held, keys)
        if not existing.smart and not missing:
            # The state a repeated create asks for already holds: an ordinary
            # playlist by that name containing every requested item. Confirmed
            # and exit 0, rather than refused, so a retried command converges
            # instead of failing on its own earlier success.
            return _no_op(
                existing,
                held,
                f"already exists and holds all {len(keys)} requested item(s) (no-op)",
            )
        lines = []
        if not existing.smart:
            key_flags = " ".join(f"--key {key}" for key in missing)
            lines.append(
                f"Run `plex-axi playlist add {int(existing.ratingKey)} {key_flags} --write` to "
                "add the missing items to it"
            )
        lines.append(f"Run `plex-axi playlist show {int(existing.ratingKey)}` to see what it holds")
        raise AxiError(
            f"an audio playlist called {existing.title!r} already exists on this server",
            help_lines=lines,
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
    held = len(_items(created))
    doc["key"] = int(created.ratingKey)
    doc["holds"] = f"{held} items"
    # What the server holds, read back -- not the size of the request.
    doc["applied"] = _applied("created with", held, len(items))
    doc["help"] = HelpBlock([f"Run `plex-axi playlist show {int(created.ratingKey)}` to confirm"])
    return doc


def _add(ctx, title, keys, parsed):
    server = ctx.server()
    playlist = _resolve(server, title)
    _refuse_smart(playlist, action="add items to")
    held = _items(playlist)
    missing = _not_held(held, keys)
    if not missing:
        return _no_op(playlist, held, f"already holds all {len(keys)} requested item(s) (no-op)")
    items = _fetch_items(server, missing)

    doc = {"playlist": playlist.title, "smart": False, "holds": f"{len(held)} items"}
    if len(missing) < len(keys):
        # Only what is not already there is added, and the rest is named: an
        # addition repeated after a partial success converges on one copy of
        # each item instead of doubling the ones that landed the first time.
        doc["already_held"] = [int(key) for key in keys if key not in missing]
    if not parsed.get("write"):
        doc["would_add"] = _item_rows(items)
        doc["preview"] = writes.preview_note(_invocation("add", title, keys))
        doc["help"] = HelpBlock([f"Run `{_invocation('add', title, keys)} --write` to apply it"])
        return doc

    try:
        playlist.addItems(items)
    except Exception as exc:
        raise _write_error(exc, action="add items to", title=playlist.title, keys=keys) from None

    after = len(_items(_by_key(server, playlist)))
    doc["holds"] = f"{after} items"
    # The difference the server reports, not the size of the request: an item
    # the server declined to add used to be counted as added.
    doc["applied"] = _applied("added", after - len(held), len(items))
    doc["help"] = HelpBlock([f"Run `plex-axi playlist show {int(playlist.ratingKey)}` to confirm"])
    return doc


def _remove(ctx, title, keys, parsed):
    server = ctx.server()
    playlist = _resolve(server, title)
    _refuse_smart(playlist, action="remove items from")
    held = _items(playlist)
    wanted = {str(key) for key in keys}
    going, repeated = _memberships(held, wanted)
    absent = _not_held(held, keys)
    if not going:
        # Nothing named is in the playlist, which is the state a removal asks
        # for: a repeated removal confirms it rather than failing on its own
        # earlier success. The note keeps the one thing the old refusal said
        # that is still worth saying, for the key that was never there at all.
        doc = _no_op(playlist, held, f"holds none of the {len(keys)} named item(s) (no-op)")
        doc["note"] = "a rating key is local to this server and moves when an item is re-matched"
        return doc

    doc = {"playlist": playlist.title, "smart": False, "holds": f"{len(held)} items"}
    if absent:
        doc["already_absent"] = [int(key) for key in absent]
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

    after = len(_items(_by_key(server, playlist)))
    doc["holds"] = f"{after} items"
    doc["applied"] = _applied("removed", len(held) - after, len(going))
    doc["help"] = HelpBlock([f"Run `plex-axi playlist show {int(playlist.ratingKey)}` to confirm"])
    return doc


_MUTATORS = {"create": _create, "add": _add, "remove": _remove}


# -------------------------------------------------------------------- helpers


def _applied(verb: str, happened: int, asked: int) -> str:
    """What changed, measured, with the request beside it when the two differ."""
    if happened == asked:
        return f"{verb} {happened} item(s)"
    return f"{verb} {happened} item(s); {asked} were asked for, so check what the playlist holds"


def _by_key(server, playlist):
    """The same playlist again, fresh, found by the key rather than by its title."""
    wanted = str(playlist.ratingKey)
    for candidate in _audio_playlists(server):
        if str(candidate.ratingKey) == wanted:
            return candidate
    raise _missing(playlist.title, [])


def _page(server, playlist, limit: int) -> tuple:
    """The first ``limit`` items of a playlist, and how many it holds in all."""
    path = f"/playlists/{int(playlist.ratingKey)}/items"
    try:
        counted = server.query(
            path, headers={"X-Plex-Container-Start": "0", "X-Plex-Container-Size": "0"}
        )
        items = list(
            server.fetchItems(path, container_start=0, container_size=limit, maxresults=limit)
        )
    except Exception as exc:
        raise translate(exc, what=f"the contents of {playlist.title!r}") from None
    total = counted.attrib.get("totalSize")
    if total is None:
        total = counted.attrib.get("size")
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = len(items)
    return items, max(total, len(items))


def _not_held(held: list, keys: list) -> list:
    """The requested keys the playlist does not hold, in the order they were asked for."""
    present = {str(getattr(item, "ratingKey", "")) for item in held}
    return [key for key in keys if str(key) not in present]


def _no_op(playlist, held: list, already: str) -> dict:
    """The answer to a write whose desired state already holds: exit 0, nothing sent."""
    return {
        "playlist": playlist.title,
        "smart": bool(playlist.smart),
        "holds": f"{len(held)} items",
        "already": already,
    }


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
    """One playlist by rating key or by exact, case-folded title.

    The rating key is accepted because `playlist list` prints it and a title
    cannot always be typed: on a real server they contain emoji and typographic
    apostrophes. It is tried first and only when the argument is all digits, so
    a playlist actually called "2024" is still reachable by name.
    """
    playlists = _audio_playlists(server)
    wanted = str(title).strip()
    media = ids.parse_reference(wanted)
    if media.kind == ids.MEDIA_ID:
        # The `media_id` a listing prints beside the key, accepted back.
        KeyRef(media.key, media.machine, wanted).confirm(server)
        wanted = media.key
    if wanted.isascii() and wanted.isdigit():
        for playlist in playlists:
            if str(playlist.ratingKey) == wanted:
                return playlist
    found = _find(playlists, title)
    if found is not None:
        return found
    raise _missing(title, playlists)


def _missing(title: str, playlists: list) -> AxiError:
    listing = ", ".join(f"{p.ratingKey} {p.title!r}" for p in playlists) or "none"
    return AxiError(
        f"no audio playlist called {title!r} on this server",
        help_lines=[
            f"audio playlists (key and title): {listing}",
            "Titles match exactly; pass one of those, or the key beside it, rather than a "
            "description of it",
            f"Run `plex-axi playlist create {quoted(title)} --key <rating_key> --write` to make it",
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
    # The caller's own words after the tool name, which is what a `run`
    # recovery is: the name in front of them is the renderer's to supply. The
    # `--key` is one of those words -- a recovery that ended at the title put
    # the corrected key where a positional argument goes, and was refused.
    command = ("playlist", sub, quoted(title), "--key")
    refs = [parse_key(value, command=command) for value in raw]
    if not refs:
        raise UsageError(
            f"`playlist {sub}` needs at least one --key",
            help_lines=[
                f"Run `plex-axi playlist {sub} {quoted(title)} --key <rating_key>`",
                "Run `plex-axi search --artist '<name>'` to find rating keys",
            ],
            code="MISSING_KEY",
        )
    # Deduplicated by the caller, once each key's server has been confirmed:
    # asking twice for the same key is a typo, not a request to hold the same
    # track twice.
    return refs


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
    for key, item in zip(keys, items):
        kind = getattr(item, "type", "") or "item"
        if kind in ("album", "artist"):
            # Plex accepts an album into an audio playlist as *one item that is
            # not a song*, which is never what "add this album" meant, and the
            # write used to be reported as an addition the server did not make.
            flag = "--album" if kind == "album" else "--artist"
            raise AxiError(
                f"{key} is {article(kind)} {kind}, and `--key` takes tracks",
                help_lines=[
                    f"Run `plex-axi search {flag} {quoted(getattr(item, 'title', '') or '<title>')}"
                    f" --no-group` for the keys of its tracks",
                ],
                code="NOT_A_TRACK",
            )
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


def _playlist_row(playlist, machine_identifier: str) -> dict:
    """One playlist row: addressable by this tool, and by whatever plays music.

    Two identifiers, because they answer different questions. The `key` is how
    *this tool* names a playlist -- a title could only be passed by typing it
    exactly, and real ones carry emoji, typographic apostrophes and leading
    spaces, all of which have to survive a shell first.

    The `media_id` is the handoff, and **a playlist has one exactly like a track
    does**. A playlist's rating key lives in the same `/library/metadata`
    namespace: fetching it returns the playlist, which is precisely what a
    consumer does when it parses `plex://<machineIdentifier>/<ratingKey>`.
    Without it, playing a whole playlist meant assembling that string by hand --
    the hand-assembly the six-forms rule exists to prevent, in the one case
    where the caller most obviously wants the container rather than a row of it.
    """
    return {
        "key": int(playlist.ratingKey),
        "media_id": media_id_for(machine_identifier, playlist),
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
            f"Run `plex-axi playlist show {quoted(title)}` to see what the search currently returns",
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
        help_lines=[
            f"Run `plex-axi playlist show {quoted(title)}` to see what the server holds now"
        ],
    )


def _invocation(sub: str, title: str, keys: list) -> str:
    flags = " ".join(f"--key {key}" for key in keys)
    return f"plex-axi playlist {sub} {quoted(title)} {flags}".strip()
