"""The playback gate: available, off by default, and invisible until it is on.

The first two releases had no play command at all, and said so in the README, in
root help, in the generated skill and in a test suite that proved the capability
was not reachable. That decision was right for the house it was written in --
one where Home Assistant owns dispatch, and a second tool that could also start
music would let an agent pick the path that bypasses it. It is simply irrelevant
to somebody who has a Plex library and nothing else, and for them the tool
dead-ended at an identifier with nothing to do with it.

So playback is here, and it is gated. The gate has **two conjuncts, exactly like
the write gate**, and one extra property the write gate does not have.

1. **:data:`ALLOW_VAR` in the environment is the gate.** Same reasoning as
   :mod:`plex_axi.writes`: what makes an environment variable the right primary
   is *who sets it* -- the operator, once, outside the invocation. A caller
   composing a command line cannot grant itself a permission it was not given.
   A value that is set but is not :data:`ALLOW_VALUE` is refused by name.
2. **:data:`CONFIRM_FLAG` on the invocation is the confirmation.** With the gate
   open and the flag absent, `play` still runs and previews: it resolves the
   item, resolves the target, prints which one it picked and why, and sends no
   playback command. That is where "three clients and you named none of them"
   and "that rating key is a film" are caught, for free, before a speaker in
   somebody's house comes on.

**The extra property: when the gate is closed the commands do not exist.**
Refusing is not enough. If `play` appeared in `--help`, in the home view or in
the generated skill, an agent in a house that *also* runs a home-automation CLI
would see two ways to start music and would sometimes choose the wrong one --
which is the exact failure the original no-playback decision avoided. So
:func:`allowed` is consulted by the dispatcher itself: with the gate closed
`plex-axi play` is an unknown command with the same out-of-scope message it has
always had, root help lists the same commands it always did, and the skill is
byte-for-byte the one this repository commits. A user who has not opted in
cannot tell the capability is there.

**Why this is not the write gate.** Playing is not a write and sharing a switch
with one would be wrong in both directions. A write changes library or account
state that persists and that somebody will read back later; playback changes
what is coming out of a speaker for as long as nobody presses stop. More to the
point, the two gates are opened for different reasons: :data:`writes.ALLOW_VAR`
answers "may this tool change my library", and this one answers "does anything
*else* in this house own the speakers". An operator who wanted `rate` has said
nothing about the second question, and folding them together would mean opening
one silently granted the other -- the coupling this gate exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import AxiError
from .output import register_secret

#: The operator's standing decision. Prefixed like :data:`writes.ALLOW_VAR`,
#: and deliberately a *different* variable -- see the module docstring.
ALLOW_VAR = "PLEX_AXI_ALLOW_PLAYBACK"

#: The one accepted value, matched case-insensitively after stripping.
ALLOW_VALUE = "true"

#: The per-invocation confirmation. Spelled once here so the command, the help
#: renderer and the refusal cannot disagree about it. Not `--play`, which would
#: read as ceremony on a command already called `play`; `--now` says what the
#: absence of the flag means, which is "later, or not at all".
CONFIRM_FLAG = "--now"

#: A plex.tv **account** token, which is a broader credential than the server
#: token in `PLEX_TOKEN` and is not interchangeable with it: a server token gets
#: a flat 401 from plex.tv. Only the Sonos cloud route needs it, and it is an
#: environment variable rather than a flag for exactly the reason `PLEX_TOKEN`
#: is: a credential on a command line leaks into shell history and the process
#: table.
ACCOUNT_TOKEN_VAR = "PLEX_ACCOUNT_TOKEN"

#: The nouns that exist only when the gate is open.
COMMANDS = ("clients", "play")

#: The two routes to a speaker, named in every row and every refusal because
#: they have different failure modes and different consequences. See
#: :mod:`plex_axi.cloud` for what `sonos` costs.
LOCAL = "local"
CLOUD = "sonos"

#: The access level these commands declare. Read-only and mutating were the
#: whole vocabulary while the tool could only read and write the library;
#: starting playback is neither, and describing it as either would be a lie in
#: one direction or the other. :mod:`plex_axi.argspec` merges this into the
#: table `--help` and the generated skill both render from.
DISPATCHING = "dispatching"

ACCESS = {
    DISPATCHING: (
        f"dispatching - starts playback on a client; needs {ALLOW_VAR}={ALLOW_VALUE} in the "
        f"environment, and without {CONFIRM_FLAG} it names the target and sends nothing"
    ),
}


class PlaybackRefused(AxiError):
    """A playback command run against a closed gate.

    Exits 1 rather than 2, for the same reason :class:`writes.WriteRefused`
    does: the invocation was well formed. What is absent is the operator's
    opt-in, which is configuration.

    Reaching this is defence in depth rather than the ordinary path. The
    dispatcher in :mod:`plex_axi.cli` will not route a playback noun at all with
    the gate closed, so a closed gate is an unknown command long before it is a
    refusal. This is the second latch, so that "a refused dispatch reaches the
    server zero times" does not rest on the dispatcher alone.
    """


def gate_value(environ) -> str:
    """The raw value of the gate variable, stripped. Empty when unset."""
    return (environ.get(ALLOW_VAR) or "").strip()


def allowed(environ) -> bool:
    return gate_value(environ).lower() == ALLOW_VALUE


def misconfigured(environ) -> bool:
    """The gate variable is set, and to something that is not :data:`ALLOW_VALUE`.

    Worth telling apart from "not set", and the reason is the one difference
    between this gate and the write gate. Invisibility is owed to somebody who
    has *not* opted in: an agent that cannot see the capability cannot choose it
    wrongly. Somebody who has exported this variable at all already knows the
    capability exists -- they typed its name -- so there is nothing left to
    hide from them, and answering `plex-axi play` with "unknown command" would
    send them hunting for a variable they had already set. They get the same
    refusal-by-name the write gate gives, for the same reason it gives it.
    """
    raw = gate_value(environ)
    return bool(raw) and raw.lower() != ALLOW_VALUE


def state(environ) -> str:
    """A one-line description of the gate, for the home view.

    Only ever printed when the gate is open: with it closed the home view says
    nothing at all, because saying "playback: disabled" would advertise the
    capability to precisely the reader who must not see it.
    """
    raw = gate_value(environ)
    return f"enabled ({ALLOW_VAR}={raw}); `play` still needs {CONFIRM_FLAG} to start anything"


def refusal(environ, *, action: str) -> PlaybackRefused:
    """The one refusal, built in one place.

    Both the dispatcher and the commands have to be able to say this, and they
    have to say it identically: a caller who meets it from one route and then
    from the other must not be given two different accounts of the same
    configuration.
    """
    raw = gate_value(environ)
    detail = f"{ALLOW_VAR} is {raw!r}, not {ALLOW_VALUE!r}" if raw else f"{ALLOW_VAR} is not set"
    return PlaybackRefused(
        f"refusing to {action}: playback is disabled ({detail})",
        help_lines=[
            f"Run `export {ALLOW_VAR}={ALLOW_VALUE}`, then run the command again "
            f"with {CONFIRM_FLAG}",
            "The gate is an environment variable rather than a flag on purpose: it is the "
            "operator's decision, and a caller cannot grant itself one it was not given",
            "Nothing was sent to the server",
        ],
        code="PLAYBACK_DISABLED",
    )


def require(environ, *, action: str) -> None:
    """Refuse ``action`` unless this installation has been opted in.

    Called before the connection is opened, so a refusal costs no request and
    the server never hears about the attempt.
    """
    if gate_value(environ).lower() == ALLOW_VALUE:
        return
    raise refusal(environ, action=action)


def account_token(environ) -> str:
    """The plex.tv account token, registered as a secret before it is returned.

    Empty when unset, which is not an error: the Sonos route is one of two and
    the local one needs nothing but `PLEX_TOKEN`. The callers that do need it
    say which credential is missing rather than surfacing plex.tv's 401.
    """
    token = (environ.get(ACCOUNT_TOKEN_VAR) or "").strip()
    if token:
        # Registered at the moment it is read, exactly like `PLEX_TOKEN` in
        # `config.load` and the per-user token in `users.access_token`.
        register_secret(token)
    return token


# ------------------------------------------------------------------- targets


@dataclass(frozen=True)
class Target:
    """One thing that can be played to, from either route.

    Deliberately **not** the client library's own client object, and
    deliberately carrying no address. A `/clients` element advertises `host`,
    `address` and `port`, all of which are addresses on the operator's own
    network; a Sonos resource advertises `lanIP`. None of them is needed to
    address a target -- the machine identifier is -- and this repository is
    public, so a row shape that carried one would be one careless fixture away
    from committing somebody's network layout.
    """

    title: str
    machine_identifier: str
    product: str
    device: str
    route: str
    capabilities: tuple = ()
    #: The raw element, kept only so the local route can hand it to the client
    #: library rather than reassembling what it already parsed. Never printed.
    element: object = None

    def can_play(self) -> bool:
        return "playback" in self.capabilities

    def row(self) -> dict:
        return {
            "title": self.title,
            "route": self.route,
            "product": self.product,
            "device": self.device,
            "machine_id": self.machine_identifier,
            "capabilities": ",".join(self.capabilities),
        }

    def label(self) -> str:
        return f"{self.title} ({self.route})"


# ------------------------------------------------------------- the two routes

#: The server's own list of clients that have announced themselves to it. This
#: is deliberately **not** ``PlexServer.clients()``: that helper falls back to
#: ``myPlexAccount().devices()`` whenever a client fails to advertise a port,
#: which would pull the account object -- and with it the Sonos dispatch surface
#: -- into a process that has no other reason to hold it. Reading the same path
#: and parsing it here costs nothing and keeps that surface out.
CLIENTS_PATH = "/clients"

#: Where a proxied remote-control command goes. The command is addressed to the
#: *server*, which forwards it to the client named in the
#: ``X-Plex-Target-Client-Identifier`` header. Talking to the client directly
#: would mean opening a second connection to an address on the operator's
#: network; this tool connects to `PLEX_URL` and to nothing else.
PLAY_PATH = "/player/playback/playMedia"

#: The play queue a client is pointed at. One POST, and the id is the only part
#: of the answer anything needs.
PLAYQUEUE_PATH = "/playQueues"

#: Plex's own library provider, required by ``/playQueues`` and by the play
#: command, and the same identifier ``/:/rate`` insists on.
PROVIDER = "com.plexapp.plugins.library"

#: Plex's word for audio in a playback command. The libtype is ``audio``
#: everywhere else in this tool; the remote-control API calls it ``music``, and
#: sending the wrong one is a silent no-op on some clients.
MEDIA_TYPE = "music"

#: The capability a client must advertise for `play` to be willing to address
#: it. A client that offers `timeline` and `navigation` but not this one will
#: accept the command and do nothing.
PLAYBACK_CAPABILITY = "playback"


def survey(server, config, environ) -> dict:
    """Every target this installation can reach, and what was consulted.

    Returns the playable targets, the ones that answered but cannot play, and
    one line per route so an empty answer says *which* routes were asked rather
    than leaving the caller to guess whether the Sonos half ran at all.
    """
    from . import output

    found = _local_targets(server)
    routes = [
        {"route": LOCAL, "detail": f"{len(found)} client(s) known to this server"},
    ]
    token = account_token(environ)
    if token:
        from .cloud import speakers

        cloud = speakers(config, token)
        found = found + cloud
        routes.append(
            {
                "route": CLOUD,
                "detail": f"{len(cloud)} speaker(s) linked to this plex.tv account",
            }
        )
    else:
        routes.append(
            {
                "route": CLOUD,
                "detail": f"not consulted -- {ACCOUNT_TOKEN_VAR} is not set and Plex for "
                "Sonos needs a plex.tv account token, which PLEX_TOKEN is not",
            }
        )
    playable = [target for target in found if target.can_play()]
    hidden = [target for target in found if not target.can_play()]
    output.debug(f"targets: {len(playable)} playable, {len(hidden)} without playback")
    return {"targets": playable, "hidden": hidden, "routes": routes}


def route_lines(found: dict) -> list:
    """The route survey as one line each, for a help block."""
    return [f"{row['route']}: {row['detail']}" for row in found["routes"]]


def _local_targets(server) -> list:
    from .plex import translate

    try:
        data = server.query(CLIENTS_PATH)
    except Exception as exc:
        raise translate(
            exc,
            what="the clients this server can see",
            help_lines=[
                "A Plex client appears here only while it is running and on the same network "
                "as the server",
            ],
        ) from None
    if data is None:
        return []
    return [_local_target(element) for element in data]


def _local_target(element) -> Target:
    """One `/clients` element as a target.

    ``name`` rather than ``title``: a `/clients` entry is a ``<Server>`` element
    and carries the player's name under ``name``, where a ``<Player>`` on a
    session carries neither. Both are read, most-specific first, for the same
    reason ``sessions._device`` reads three attributes -- and the address
    attributes (``host``, ``address``, ``port``) are deliberately not read at
    all, because nothing here needs them and this repository is public.
    """
    capabilities = tuple(
        part.strip()
        for part in (element.get("protocolCapabilities") or "").split(",")
        if part.strip()
    )
    return Target(
        title=element.get("title") or element.get("name") or "",
        machine_identifier=element.get("machineIdentifier") or "",
        product=element.get("product") or "",
        device=element.get("deviceClass") or element.get("platform") or "",
        route=LOCAL,
        capabilities=capabilities,
        element=element,
    )


def resolve(found: dict, wanted, *, flag: str) -> tuple:
    """One target and the reason it was chosen, or a refusal that lists them.

    Exactly matched -- by case-folded title or by machine identifier -- and
    never by substring or nearest neighbour, which is the same discipline
    `playlist` resolution follows and for the same reason: guessing which
    speaker somebody meant is how music starts in the wrong room.
    """
    targets = found["targets"]
    if wanted:
        needle = str(wanted).strip().casefold()
        for target in targets:
            if needle in (
                target.title.strip().casefold(),
                target.machine_identifier.strip().casefold(),
            ):
                return target, f"named by {flag}"
        raise _no_such_target(found, wanted, flag=flag)
    if not targets:
        raise _nothing_to_play_to(found)
    if len(targets) == 1:
        # Defaulting to the only one is a convenience, but a silent default is
        # not: the answer says which target it picked and that it was the only
        # candidate, so a second client appearing later changes the output
        # rather than changing where the music comes out without saying so.
        return targets[0], f"the only target advertising {PLAYBACK_CAPABILITY}"
    raise _ambiguous(found, flag=flag)


def _listing(targets: list) -> str:
    return ", ".join(f"{t.title!r} ({t.route})" for t in targets) or "none"


def _no_such_target(found: dict, wanted, *, flag: str) -> AxiError:
    hidden = found["hidden"]
    lines = [f"targets that can play: {_listing(found['targets'])}"]
    if hidden:
        lines.append(
            f"answered but cannot play: {_listing(hidden)} -- these do not advertise "
            f"{PLAYBACK_CAPABILITY}"
        )
    lines.extend(
        [
            f"{flag} matches a title exactly, case-folded, or a machine_id; "
            "`plex-axi clients` prints both",
            *route_lines(found),
        ]
    )
    return AxiError(
        f"no target called {str(wanted)!r} is available to this server",
        help_lines=lines,
        code="NO_SUCH_TARGET",
    )


def _nothing_to_play_to(found: dict) -> AxiError:
    hidden = found["hidden"]
    lines = route_lines(found)
    if hidden:
        lines.insert(
            0,
            f"answered but cannot play: {_listing(hidden)} -- these do not advertise "
            f"{PLAYBACK_CAPABILITY}",
        )
    lines.extend(
        [
            "A Plex client is only visible while its app is running and on the same network "
            "as the server; open it and run `plex-axi clients` again",
            "Run `plex-axi sessions` to see whether the server thinks anything is playing",
        ]
    )
    return AxiError(
        "this server can see nothing to play to",
        help_lines=lines,
        code="NO_TARGETS",
    )


def _ambiguous(found: dict, *, flag: str) -> AxiError:
    return AxiError(
        f"{len(found['targets'])} targets can play, so {flag} is not optional",
        help_lines=[
            f"targets: {_listing(found['targets'])}",
            f"Run `plex-axi play <rating_key> {flag} '<title>'` with one of those",
            "Run `plex-axi clients` for each one's machine_id, which is unambiguous when two "
            "share a title",
        ],
        code="AMBIGUOUS_TARGET",
    )


# ------------------------------------------------------------------ dispatch

#: The line a preview prints instead of a result, so "would" is never mistaken
#: for "did" -- the same discipline as :data:`writes.PREVIEW_LINE`, and the same
#: sentence, because it is the same promise.
PREVIEW_LINE = "nothing was sent to the server and nothing is playing that was not already"


def preview_note(command: str) -> str:
    return f"{PREVIEW_LINE}; run `{command}` with {CONFIRM_FLAG} to start it"


def play(server, config, target: Target, item, environ) -> str:
    """Start ``item`` on ``target``. Returns a one-line description of what was sent."""
    from . import output

    playqueue = _playqueue(server, item)
    output.debug(f"play queue {playqueue} -> {target.label()}")
    if target.route == CLOUD:
        from .cloud import play as cloud_play

        return cloud_play(server, config, target, item, playqueue, account_token(environ))
    return _local_play(server, config, target, item, playqueue)


def _playqueue(server, item) -> int:
    """Create the play queue and return its id, which is all a client needs.

    Deliberately not the client library's ``createPlayQueue``: that builds a
    whole ``PlayQueue`` object, which indexes its own contents to find the
    selected item and therefore needs every row of a ten-thousand-track playlist
    parsed to hand back a number. The request is the same one; only the id is
    read from it.
    """
    from .plex import translate

    params = {
        "type": _media_type(item),
        "uri": f"server://{server.machineIdentifier}/{PROVIDER}{item.key}",
        "includeChapters": 0,
        "includeRelated": 0,
        "shuffle": 0,
        "repeat": 0,
        "continuous": 0,
    }
    try:
        data = server.query(PLAYQUEUE_PATH, method=server._session.post, params=params)
    except Exception as exc:
        raise translate(
            exc,
            what=f"a play queue for {getattr(item, 'title', '') or item.key!r}",
            help_lines=["Run `plex-axi track <rating_key>` to check the item resolves at all"],
        ) from None
    identifier = None if data is None else data.attrib.get("playQueueID")
    if not identifier:
        raise AxiError(
            "the server accepted the play queue but did not return an id",
            help_lines=["Run the command again with `--debug` for what the server answered"],
            code="NO_PLAY_QUEUE",
        )
    return int(identifier)


def _media_type(item) -> str:
    """Plex's own word for the queue's contents, from the item rather than a guess."""
    return getattr(item, "playlistType", None) or getattr(item, "listType", None) or "audio"


def _local_play(server, config, target: Target, item, playqueue: int) -> str:
    from urllib.parse import urlsplit
    from xml.etree.ElementTree import ParseError

    from .plex import translate

    parts = urlsplit(config.base_url)
    params = {
        "providerIdentifier": PROVIDER,
        "machineIdentifier": server.machineIdentifier,
        "protocol": parts.scheme,
        "address": parts.hostname or "",
        "port": parts.port or "",
        "offset": 0,
        "key": item.key,
        "type": MEDIA_TYPE,
        "containerKey": f"{PLAYQUEUE_PATH}/{playqueue}?window=100&own=1",
        "commandID": 1,
    }
    token = _delegation_token(server)
    if token:
        params["token"] = token
    try:
        server.query(
            PLAY_PATH,
            params=params,
            headers={"X-Plex-Target-Client-Identifier": target.machine_identifier},
        )
    except ParseError:
        # Not a failure. Plexamp, Plex for Android and Plex for Samsung answer a
        # successful playback command with `OK` rather than with XML, and the
        # client library treats exactly that as success for exactly those
        # products. The status code was already checked before the body was
        # parsed, so reaching here means the server said 200.
        pass
    except Exception as exc:
        raise translate(
            exc,
            what=f"the playback command for {target.label()}",
            help_lines=[
                "Run `plex-axi clients` to check the target is still there; a client that has "
                "gone to sleep is still listed by the server for a while",
            ],
        ) from None
    return f"sent to {target.title} over the local network, through the server"


def _delegation_token(server):
    """A short-lived token the client uses to fetch the media, when the server mints one.

    **Optional, and that was learned from a real server rather than assumed.**
    The client library asks for one unconditionally and lets the failure
    propagate, which turns every play into a `403` on a server whose token is
    not a plex.tv account token -- a server that permits unauthenticated access
    on the local network issues exactly such a token, and one answered `403
    Forbidden` here. The command works without it whenever the client is already
    signed in to the same account, which is the ordinary case, so a refusal to
    mint one is noted and stepped over rather than raised.
    """
    from . import output

    try:
        data = server.query("/security/token", params={"type": "delegation", "scope": "all"})
    except Exception as exc:
        output.debug(f"no delegation token ({type(exc).__name__}); playing without one")
        return ""
    token = "" if data is None else (data.attrib.get("token") or "")
    if token:
        # A delegation token is a bearer credential with a short life, and it
        # travels in a URL. Registered before anything can print it.
        register_secret(token)
    return token
