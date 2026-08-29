"""`plex-axi play <rating_key>` -- the one command that does not end at an identifier.

Every other command in this tool stops at a labelled `media_id` and leaves
dispatch to whatever owns the speakers. That is still the right shape in a house
that has something else doing the owning. It is a dead end in a house that does
not, and this command is the answer to that -- gated, and invisible until the
operator opens the gate. :mod:`plex_axi.playback` carries the reasoning.

What it adds over `api` is what `api` cannot do at all: `api` refuses every
method but GET, so it cannot create the play queue, and a playback command
without one plays nothing. Beyond that it is the two judgements a caller would
otherwise have to make and would get wrong once: which target, resolved
explicitly and never guessed at, and which of the two routes it is on -- because
a Sonos speaker is reached through Plex's cloud and a house watching the local
server will not see the command go out.

**Starting playback is deliberately all it does.** No pause, no stop, no volume,
no next, no queue management. Those are a control surface rather than a handoff,
and the moment this tool has one it is competing with whatever else in the house
already does. Starting playback from a media id is the thing that was missing;
the rest was never missing.
"""

from __future__ import annotations

from axi_toolkit.plex.ids import handoff, validate_rating_key

from .. import playback
from ..argspec import Command, Flag, Sub
from ..errors import UsageError
from ..output import HelpBlock
from ..plex import translate
from ._common import article

#: What Plex will build an audio play queue from. An artist is in because "play
#: everything by this artist" is a real request the server answers the same way;
#: a film is not, and neither is a photo playlist.
PLAYABLE = ("track", "album", "artist", "playlist")

#: The one playlist type this command will start, for the same reason
#: `playlist` only ever lists audio ones.
AUDIO = "audio"

COMMAND = Command(
    name="play",
    summary="Start a track, album, artist or audio playlist on one Plex client",
    usage=f"usage: plex-axi play <rating_key> [--client <title>] [{playback.CONFIRM_FLAG}]",
    default_sub="play",
    access=playback.DISPATCHING,
    subs=(
        Sub(
            name="play",
            args=("<rating_key>",),
            flags=(
                Flag(
                    "--client",
                    "<title-or-machine-id>",
                    note="matched exactly, case-folded; `plex-axi clients` lists both",
                ),
                Flag(
                    playback.CONFIRM_FLAG,
                    boolean=True,
                    note="start it; without this the command names the target and sends nothing",
                ),
            ),
            summary="Play one item on one client",
        ),
    ),
    notes=(
        "the rating key is the one `search`, `pick` and `playlist` print; a guid is refused "
        "with the reason, exactly as everywhere else",
        "a playlist is played as a playlist: `playlist list` prints its rating key beside its "
        "media_id, and either resolves here",
        "the target is never guessed: with several available `--client` is required, and with "
        "exactly one the answer says which it was and that it was the only candidate",
        "starting playback is all this does -- there is no pause, stop, volume, next or queue "
        "command, and there is not going to be one",
        "a `sonos` target is reached through Plex's cloud rather than through this server, so "
        "anything watching the server for a session will lag the command",
        f"this command exists only while {playback.ALLOW_VAR}={playback.ALLOW_VALUE}",
    ),
    examples=(
        "plex-axi clients",
        "plex-axi play 12345",
        "plex-axi play 12345 --client 'Example Client'",
        f"plex-axi play 12345 --client 'Example Client' {playback.CONFIRM_FLAG}",
    ),
)


def COMMAND_FOR(name: str) -> Command:
    return COMMAND


def run(ctx, name: str, sub: str, parsed):
    key = validate_rating_key(parsed.positionals[0], command=("play",))

    # Before the connection, not after it: a refused dispatch must not be a
    # request the server ever hears about. With the gate closed the CLI will not
    # route this noun at all, so this is the second latch rather than the first.
    playback.require(ctx.environ, action=f"play {key}")

    server = ctx.server()
    item = _fetch(server, key)
    kind = _kind(item, key)

    found = playback.survey(server, ctx.config(), ctx.environ)
    target, why = playback.resolve(found, parsed.get("client"), flag="--client")

    doc = {"play": getattr(item, "title", "") or ""}
    artist = getattr(item, "grandparentTitle", "") or getattr(item, "parentTitle", "") or ""
    if artist and kind not in ("artist", "playlist"):
        doc["artist"] = artist
    doc["type"] = kind
    doc["target"] = target.title
    doc["route"] = target.route
    doc["chosen"] = why
    doc["item"] = handoff(server.machineIdentifier, item)

    if not parsed.get(playback.CONFIRM_FLAG.lstrip("-")):
        doc["preview"] = playback.preview_note(_invocation(key, target))
        doc["help"] = HelpBlock(
            [
                f"Run `{_invocation(key, target)} {playback.CONFIRM_FLAG}` to start it",
                *_route_help(target),
            ]
        )
        return doc

    doc["started"] = playback.play(server, ctx.config(), target, item, ctx.environ)
    doc["help"] = HelpBlock(
        [
            "Run `plex-axi sessions` to see whether the server agrees it is playing",
            *_route_help(target),
        ]
    )
    return doc


def _route_help(target) -> list:
    if target.route != playback.CLOUD:
        return []
    from ..cloud import ROUTE_NOTE

    return [ROUTE_NOTE]


def _fetch(server, key: str):
    """One item by rating key, whatever kind it turns out to be.

    A playlist's rating key lives in the same ``/library/metadata`` namespace as
    a track's -- checked against a real server, where
    ``GET /library/metadata/<playlistRatingKey>`` answers 200 with a
    ``<Playlist>`` element -- which is why one lookup covers all four kinds and
    why a playlist's `media_id` is a real one.
    """
    try:
        return server.fetchItem(f"/library/metadata/{key}")
    except Exception as exc:
        raise translate(
            exc,
            what=f"item {key}",
            help_lines=[
                "Run `plex-axi search --track '<title>'` to find this server's rating key",
                "Run `plex-axi playlist list` for a playlist's rating key",
            ],
        ) from None


def _kind(item, key: str) -> str:
    kind = getattr(item, "type", "") or "item"
    if kind == "playlist":
        listed = getattr(item, "playlistType", "") or ""
        if listed != AUDIO:
            raise UsageError(
                f"{key} is {article(listed)} {listed} playlist, and plex-axi plays music only",
                help_lines=[
                    "Run `plex-axi playlist list` for the audio playlists on this server",
                ],
                code="WRONG_ITEM_TYPE",
            )
        return kind
    if kind not in PLAYABLE:
        raise UsageError(
            f"{key} is {article(kind)} {kind} on this server, and plex-axi plays music only",
            help_lines=[
                f"playable kinds: {', '.join(PLAYABLE)}",
                "Run `plex-axi search --artist '<name>'` to find a music rating key",
            ],
            code="WRONG_ITEM_TYPE",
        )
    return kind


def _invocation(key: str, target) -> str:
    return f"plex-axi play {key} --client '{target.title}'"
