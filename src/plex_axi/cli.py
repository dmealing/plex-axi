"""Entry point: global flags, dispatch, help, and the single error boundary."""

from __future__ import annotations

import os
import sys

from . import __version__, output, playback, writes
from . import config as config_module
from .argspec import GLOBAL_FLAGS, VALUE_GLOBALS, Command, parse, render_command_help
from .commands import api as api_command
from .commands import clients as clients_command
from .commands import doctor as doctor_command
from .commands import genres as genres_command
from .commands import home as home_command
from .commands import item as item_command
from .commands import pick as pick_command
from .commands import play as play_command
from .commands import playlist as playlist_command
from .commands import rate as rate_command
from .commands import recent as recent_command
from .commands import search as search_command
from .commands import sessions as sessions_command
from .commands import similar as similar_command
from .commands import skill as skill_command
from .errors import EXIT_ERROR, EXIT_OK, AxiError, UsageError
from .output import MODE_HUMAN, MODE_JSON, MODE_TOON, HelpBlock

#: Dispatch order, which is also the order `--help` and the skill list them in.
#: It follows the order the commands are useful in: find something, widen the
#: vocabulary when nothing matched, look at one item, then the diagnostics.
COMMAND_ORDER = (
    "search",
    "pick",
    "genres",
    "moods",
    "styles",
    "track",
    "album",
    "artist",
    "similar",
    "recent",
    "playlist",
    "rate",
    "sessions",
    "api",
    "doctor",
    "skill",
)

#: The nouns that exist only while the playback gate is open, appended to
#: :data:`COMMAND_ORDER` when it is. They are a separate tuple rather than a
#: flag on each entry because *every* surface that lists commands has to be able
#: to leave them out entirely: help, the home view, the generated skill and the
#: dispatcher all read the order, and a gate that only refused to run them would
#: still have shown an agent that a second way to play music exists. See
#: :mod:`plex_axi.playback`.
PLAYBACK_ORDER = playback.COMMANDS

_MODULES = {
    "search": search_command,
    "genres": genres_command,
    "moods": genres_command,
    "styles": genres_command,
    "track": item_command,
    "album": item_command,
    "artist": item_command,
    "similar": similar_command,
    "recent": recent_command,
    "pick": pick_command,
    "playlist": playlist_command,
    "rate": rate_command,
    "sessions": sessions_command,
    "api": api_command,
    "doctor": doctor_command,
    "skill": skill_command,
    "home": home_command,
}

_PLAYBACK_MODULES = {
    "clients": clients_command,
    "play": play_command,
}

#: Commands an agent might reach for under a different noun. The video nouns are
#: here so that a wrong guess is answered with the reason rather than a bare
#: "unknown command": this tool is music-only on purpose.
_ALIASES = {
    "tracks": "track",
    "albums": "album",
    "artists": "artist",
    "songs": "track",
    "song": "track",
    "find": "search",
    "query": "search",
    "genre": "genres",
    "mood": "moods",
    "style": "styles",
    "health": "doctor",
    "status": "doctor",
    "now": "sessions",
    "playing": "sessions",
    "sonic": "similar",
    "related": "similar",
    "playlists": "playlist",
    "shuffle": "pick",
    "random": "pick",
    "suggest": "pick",
}

#: Nouns that belong to the half of Plex this tool deliberately does not model.
_OUT_OF_SCOPE = {
    "movie": "movies",
    "movies": "movies",
    "show": "shows",
    "shows": "shows",
    "episode": "episodes",
    "episodes": "episodes",
    "watchlist": "the watchlist",
    "scan": "server administration",
    "refresh": "server administration",
    "edit": "metadata editing",
}

#: The playback vocabulary, out of scope while the gate is closed and answered
#: with exactly the message it has always been answered with. With the gate open
#: the two that became commands are removed from this table and the rest keep
#: their refusal, because transport control is still out of scope: `play` starts
#: something, and nothing here stops it again.
_PLAYBACK_OUT_OF_SCOPE = {
    "play": "playback",
    "pause": "playback",
    "stop": "playback",
    "next": "playback",
    "volume": "playback",
    "client": "clients and speakers",
    "clients": "clients and speakers",
    "speaker": "clients and speakers",
    "speakers": "clients and speakers",
    "player": "clients and speakers",
    "room": "clients and speakers",
}

#: What an agent might type for a playback noun once the gate is open. Empty
#: while it is closed, so a wrong guess is answered by the out-of-scope table
#: above and learns nothing about a capability this installation has not opted
#: into.
_PLAYBACK_ALIASES = {
    "speaker": "clients",
    "speakers": "clients",
    "player": "clients",
    "players": "clients",
    "client": "clients",
    "target": "clients",
    "targets": "clients",
    "playback": "play",
    "start": "play",
}


def _out_of_scope(environ) -> dict:
    table = dict(_OUT_OF_SCOPE)
    for name, area in _PLAYBACK_OUT_OF_SCOPE.items():
        if name not in command_order(environ):
            table[name] = area
    return table


def _aliases(environ) -> dict:
    if environ is not None and playback.allowed(environ):
        return {**_ALIASES, **_PLAYBACK_ALIASES}
    return dict(_ALIASES)


def command_order(environ=None) -> tuple:
    """The nouns this installation has, in dispatch order.

    ``None`` means the base set -- the commands every installation has -- which
    is what the committed skill is generated from and what the tests that pin
    the public surface read.
    """
    if environ is not None and playback.allowed(environ):
        return COMMAND_ORDER + PLAYBACK_ORDER
    return COMMAND_ORDER


def modules(environ=None) -> dict:
    if environ is not None and playback.allowed(environ):
        return {**_MODULES, **_PLAYBACK_MODULES}
    return dict(_MODULES)


def command_specs(environ=None) -> dict:
    return {name: module.COMMAND_FOR(name) for name, module in modules(environ).items()}


class Context:
    """Per-invocation state: configuration, the connection, and output mode."""

    def __init__(
        self,
        environ,
        *,
        mode: str = MODE_TOON,
        timeout: float | None = None,
        section: str | None = None,
        user: str | None = None,
    ) -> None:
        self.environ = environ
        self.mode = mode
        self.timeout = timeout
        self.section_name = section
        self.user = user
        self._config = None
        self._server = None
        self._section = None

    def config(self):
        if self._config is None:
            self._config = config_module.load(self.environ, timeout=self.timeout)
            # Registered before any request runs, so a token can never appear in
            # an error message or a debug line.
            output.register_secret(self._config.token)
        return self._config

    def server(self):
        """Connect once. Every command in one invocation shares the connection.

        With ``--user`` that costs a second connection and one plex.tv
        round-trip: the admin connection is what reports the machine identifier
        the sharing record is keyed on, and the second is authenticated as the
        named account so that every per-account value -- ratings, playlists --
        is theirs rather than the owner's.
        """
        if self._server is None:
            from .plex import connect

            server = connect(self.config())
            if self.user:
                from .users import connect_as

                server = connect_as(server, self.config(), self.user)
            self._server = server
        return self._server

    def section(self):
        """Resolve the music section once and cache it for this invocation."""
        if self._section is None:
            from .music import resolve_section
            from .plex import SECTION_VAR

            wanted = self.section_name or self.environ.get(SECTION_VAR) or None
            self._section = resolve_section(self.server(), wanted=wanted)
        return self._section


# ----------------------------------------------------------------- help text


def render_root_help(environ=None) -> str:
    """The root reference for *this* installation.

    Gate-aware, and that is the point rather than a refinement: with the
    playback gate closed this renders exactly what it rendered before playback
    existed -- the same commands, the same environment block, the same closing
    note that the tool ends at a media id. An agent reading it cannot tell the
    capability is there. See :mod:`plex_axi.playback`.
    """
    order = command_order(environ)
    specs = command_specs(environ)
    names = ", ".join(order)
    playing = playback.allowed(environ) if environ is not None else False

    env_lines = [
        "  PLEX_URL - the server's local address, e.g. http://plex.example.com:32400",
        "  PLEX_TOKEN - a Plex access token; there is deliberately no --token flag",
        "  PLEX_SECTION - default music library, when a server has more than one",
        f"  {writes.ALLOW_VAR} - set to {writes.ALLOW_VALUE} to allow `playlist` and `rate` to"
        " write; unset, they refuse",
    ]
    if playing:
        env_lines.extend(
            [
                f"  {playback.ALLOW_VAR} - set to {playback.ALLOW_VALUE}, which is why `clients`"
                " and `play` exist here",
                f"  {playback.ACCOUNT_TOKEN_VAR} - a plex.tv *account* token, needed only to"
                " reach Sonos speakers",
            ]
        )

    flag_lines = [
        "  --human (readable output), --json (raw JSON output), --timeout <seconds> (default 30),",
        "  --section <title|key> (which music library),",
        "  --debug (on stderr: the connection, every request path and query, the exact",
        "    filter expression built, and the type of any error),",
        "  --user <plex-user> (read as another account: admin only, and the one flag here",
        "    that needs a plex.tv round-trip), --help, -v/--version",
    ]

    lines = [
        "usage: plex-axi [command] [subcommand] [args] [flags]",
        f"description: {home_command.DESCRIPTION}",
        f"commands[{len(order) + 1}]:",
        f"  (none)=home, {names}",
        "flags[8]:",
        *flag_lines,
        f"env[{len(env_lines)}]:",
        *env_lines,
        f"summaries[{len(order)}]:",
    ]
    width = max(len(name) for name in order)
    lines.extend(f"  {name.ljust(width)}  {specs[name].summary}" for name in order)
    lines.extend(
        [
            "note:",
            "  plex-axi reads and diagnoses a music library, and can change two things in it:",
            "  a rating and a playlist. Both are refused unless "
            f"{writes.ALLOW_VAR}={writes.ALLOW_VALUE}",
            "  is exported, and each still needs --write on the invocation; without --write",
            "  they show the change and send nothing. Every other command only reads, and",
            "  `api` refuses every method but GET. Each command's --help says which it is.",
            "note:",
        ]
    )
    if playing:
        lines.extend(
            [
                f"  Playback is enabled here ({playback.ALLOW_VAR}={playback.ALLOW_VALUE}), so"
                " `clients` and `play`",
                f"  exist. `play` still needs {playback.CONFIRM_FLAG}; without it, it names the"
                " target and sends",
                "  nothing. Starting playback is all it does: no pause, stop, volume, next or",
                f"  queue. A `{playback.CLOUD}` target is reached through Plex's cloud rather"
                " than through this",
                "  server, so anything else watching this server for a session will lag the",
                "  command. Video is out of scope by a separate decision.",
            ]
        )
    else:
        lines.extend(
            [
                "  It has no play command and no concept of a speaker: it ends at a labelled media",
                "  id and leaves dispatch to whatever owns the speakers. Video is out of scope by",
                "  the same decision.",
            ]
        )
    lines.append("examples:")
    lines.extend(
        [
            "  plex-axi",
            "  plex-axi search --artist 'Example Artist' --track 'Example Track'",
            "  plex-axi search --genre Jazz --rated-min 4 --limit 10",
            "  plex-axi pick --rated-min 4 --not-played-since 30d",
            "  plex-axi genres",
            "  plex-axi track 12345",
            "  plex-axi similar 12345",
            "  plex-axi playlist show 'Example Playlist'",
            "  plex-axi doctor",
        ]
    )
    if playing:
        lines.extend(
            [
                "  plex-axi clients",
                f"  plex-axi play 12345 --client 'Example Client' {playback.CONFIRM_FLAG}",
            ]
        )
    return "\n".join(lines)


# ------------------------------------------------------------------ dispatch


#: Global flags that take no value, derived from the single declaration in
#: argspec so the two cannot drift apart.
_VALUELESS_GLOBALS = tuple(flag for flag in GLOBAL_FLAGS if flag not in VALUE_GLOBALS)


def _help_requested(command: Command, argv: list) -> bool:
    """Whether ``--help`` appears as a flag rather than as a flag's value.

    `search --track --help` must search for the literal string, not print help.
    Scanning raw argv cannot tell the two apart, so this walks the tokens and
    skips the value of any flag the command declares as taking one.
    """
    value_flags = {flag.name for sub in command.subs for flag in sub.flags if flag.takes_value}
    index = 0
    while index < len(argv):
        token = argv[index]
        index += 1
        name, has_inline, _ = token.partition("=")
        if name in ("--help", "-h") and not has_inline:
            return True
        if name in value_flags and not has_inline:
            index += 1  # skip the value, whatever it looks like
        elif name in VALUE_GLOBALS and not has_inline:
            index += 1
    return False


def _prescan_mode(argv: list) -> str:
    """Decide the output mode from the whole invocation, before parsing.

    An agent that appends `--json` and pipes the result to a parser needs the
    machine-readable form most when the invocation is wrong, so the mode has to
    be known before any usage error can be raised -- including for a flag that
    appears after the subcommand.
    """
    seen: dict = {}
    for token in argv:
        name = token.partition("=")[0]
        if name in ("--json", "--human"):
            seen[name.lstrip("-")] = True
    return _mode(seen)


def _split_globals(argv: list) -> tuple:
    """Pull global flags off the front of the invocation, before the command."""
    globals_: dict = {}
    index = 0
    while index < len(argv):
        token = argv[index]
        if not token.startswith("-") or token == "-":
            break
        name, sep, inline = token.partition("=")
        if name in VALUE_GLOBALS:
            key = name.lstrip("-")
            index += 1
            if sep:
                globals_[key] = inline
            elif index < len(argv):
                globals_[key] = argv[index]
                index += 1
            else:
                globals_[key] = _MISSING_VALUE
            continue
        if name in _VALUELESS_GLOBALS:
            globals_[name.lstrip("-")] = True
            index += 1
            continue
        break
    return globals_, argv[index:]


#: Sentinel for a value-taking global given without a value, so it errors rather
#: than being silently swallowed the way an unvalidated global would be.
_MISSING_VALUE = object()


def _resolve_timeout(raw) -> float | None:
    if raw is None:
        return None
    if raw is _MISSING_VALUE:
        raise UsageError(
            "--timeout needs a value",
            help_lines=["Run `plex-axi --timeout 60 <command>`"],
            code="BAD_TIMEOUT",
        )
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise UsageError(
            f"--timeout needs a number of seconds, got {raw!r}",
            help_lines=["Run `plex-axi --timeout 60 <command>`"],
            code="BAD_TIMEOUT",
        ) from None
    if value <= 0:
        raise UsageError(
            f"--timeout must be greater than 0, got {value:g}",
            help_lines=["Run `plex-axi --timeout 60 <command>`"],
            code="BAD_TIMEOUT",
        )
    return value


def _resolve_user(raw) -> str | None:
    if raw is None:
        return None
    if raw is _MISSING_VALUE:
        raise UsageError(
            "--user needs a Plex username",
            help_lines=[
                "Run `plex-axi --user '<plex-username>' <command>`",
                "`--user` is admin-only and needs a plex.tv round-trip; every other flag here "
                "works against the local server alone",
            ],
            code="BAD_USER",
        )
    value = str(raw).strip()
    if not value:
        raise UsageError(
            "--user needs a Plex username",
            help_lines=["Run `plex-axi --user '<plex-username>' <command>`"],
            code="BAD_USER",
        )
    return value


def _resolve_section(raw) -> str | None:
    if raw is None:
        return None
    if raw is _MISSING_VALUE:
        raise UsageError(
            "--section needs a value",
            help_lines=[
                "Run `plex-axi --section 'Example Music' <command>`",
                "Run `plex-axi doctor` to see the music libraries this server has",
            ],
            code="BAD_SECTION",
        )
    return str(raw)


def _mode(globals_: dict) -> str:
    if globals_.get("json"):
        return MODE_JSON
    if globals_.get("human"):
        return MODE_HUMAN
    return MODE_TOON


def _wants_version(globals_: dict) -> bool:
    return bool(globals_.get("version") or globals_.get("v") or globals_.get("V"))


def _unknown_command(name: str, environ=None):
    lowered = name.lower()
    order = command_order(environ)
    if lowered in playback.COMMANDS and environ is not None and playback.misconfigured(environ):
        # Set, but not to the one value that opens it. There is nothing left to
        # hide from somebody who has exported this variable, so they are told
        # what is wrong with it rather than told the command does not exist.
        return playback.refusal(environ, action=f"run `{name}`")
    area = _out_of_scope(environ).get(lowered)
    if area:
        return UsageError(
            f"plex-axi has no `{name}` command: {area} are deliberately out of scope",
            help_lines=[
                _out_of_scope_reason(environ),
                f"commands: {', '.join(order)}",
            ],
            code="OUT_OF_SCOPE",
        )
    suggestion = _aliases(environ).get(lowered)
    if suggestion:
        return UsageError(
            f"unknown command: {name}; use `{suggestion}` instead",
            help_lines=[f"Run `plex-axi {suggestion} --help` for its flags"],
            code="UNKNOWN_COMMAND",
        )
    return UsageError(
        f"unknown command: {name}",
        help_lines=[
            f"commands: {', '.join(order)}",
            "Run `plex-axi --help` for the full reference",
        ],
        code="UNKNOWN_COMMAND",
    )


def _out_of_scope_reason(environ) -> str:
    """Why the refused noun is refused, which is not the same sentence twice.

    With the gate closed this is the sentence it has always been. With it open
    the tool *does* dispatch, so repeating that sentence would be false for
    `pause` and `volume` -- which are still refused, for the different and
    narrower reason that this tool starts playback and does not control it.
    """
    if environ is not None and playback.allowed(environ):
        return (
            "`play` starts something on a client and that is all it does; pausing, stopping "
            "and volume belong to whatever the client already answers to"
        )
    return "This tool reads a music library and stops at a media id; it never dispatches playback"


def _pick_sub(command: Command, argv: list) -> tuple:
    if argv and not argv[0].startswith("-"):
        sub = command.find(argv[0])
        if sub is not None:
            return sub, argv[1:]
        raise_unknown = _unknown_sub(command, argv[0])
        if raise_unknown is not None:
            raise raise_unknown
    if command.default_sub:
        sub = command.find(command.default_sub)
        if sub is not None:
            return sub, argv
    raise UsageError(
        f"`{command.name}` needs a subcommand",
        help_lines=[
            f"subcommands: {', '.join(s.name for s in command.subs)}",
            f"Run `plex-axi {command.name} --help` for the full reference",
        ],
        code="MISSING_SUBCOMMAND",
    )


def _unknown_sub(command: Command, token: str):
    """A word where a subcommand belongs, when it cannot be anything else.

    Only fires when the command has more than one subcommand *and* its default
    takes no positional arguments -- so the token cannot be a legitimate
    argument that merely looks like a name. `plex-axi track 12345` is not this;
    `plex-axi playlist nosuchsub` is.

    Without it the token fell through to the default subcommand and was rejected
    as an excess positional: "unexpected argument 'nosuchsub' for `playlist
    list`", which names a subcommand the caller did not type, blames the
    argument rather than the name, and never lists the five that would have
    worked -- the one thing needed to recover.
    """
    if len(command.subs) < 2 or not command.default_sub:
        return None
    default = command.find(command.default_sub)
    if default is None or default.args:
        return None
    return UsageError(
        f"unknown subcommand {token!r} for `{command.name}`",
        help_lines=[
            f"subcommands: {', '.join(sub.signature() for sub in command.subs)}",
            f"Run `plex-axi {command.name} {command.default_sub}` for the default one",
            f"Run `plex-axi {command.name} --help` for what each takes",
        ],
        code="UNKNOWN_SUBCOMMAND",
    )


def _error_document(exc: AxiError) -> dict:
    doc: dict = {"error": exc.message}
    if exc.code:
        doc["code"] = exc.code
    if exc.help_lines:
        doc["help"] = HelpBlock([line for line in exc.help_lines if line])
    return doc


def main(argv: list | None = None, *, environ=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if environ is None else environ

    globals_, rest = _split_globals(argv)
    # Pre-scan so a usage error is reported in the mode the caller asked for,
    # then refine once the leading globals are known.
    mode = _prescan_mode(argv)
    if "--debug" in argv:
        output.set_debug(True)

    try:
        if _wants_version(globals_):
            output.write({"tool": "plex-axi", "version": __version__}, mode)
            return EXIT_OK

        # The command table this installation has, resolved once. With the
        # playback gate closed it is the base table and `plex-axi play` is an
        # unknown command -- not a refused one, which would advertise the very
        # thing the gate hides.
        available = modules(environ)

        if not rest:
            if globals_.get("help") or globals_.get("h"):
                output.write_text(render_root_help(environ))
                return EXIT_OK
            command, name, sub_name, sub_argv = home_command.COMMAND, "home", "home", []
        else:
            name = rest[0]
            module = available.get(name)
            if module is None or name == "home":
                raise _unknown_command(name, environ)
            command = module.COMMAND_FOR(name)
            if globals_.get("help") or globals_.get("h") or _help_requested(command, rest[1:]):
                output.write_text(render_command_help(command))
                return EXIT_OK
            sub, sub_argv = _pick_sub(command, rest[1:])
            sub_name = sub.name

        if command is home_command.COMMAND:
            from .argspec import Parsed

            parsed = Parsed()
            module = home_command
        else:
            parsed = parse(sub, sub_argv, command=command)
            module = available[name]
            globals_.update(parsed.globals)
            mode = _mode(globals_)
            if _wants_version(globals_):
                output.write({"tool": "plex-axi", "version": __version__}, mode)
                return EXIT_OK

        if globals_.get("debug"):
            output.set_debug(True)

        ctx = Context(
            environ,
            mode=mode,
            timeout=_resolve_timeout(globals_.get("timeout")),
            section=_resolve_section(globals_.get("section")),
            user=_resolve_user(globals_.get("user")),
        )
        output.debug(f"command={name} sub={sub_name} mode={mode}")
        doc = module.run(ctx, name, sub_name, parsed)
    except AxiError as exc:
        # The diagnostic for a *handled* error, which is the error a caller is
        # most likely to be debugging -- and the one `--debug` said nothing
        # about until now. The type is the useful half: it says which boundary
        # produced the refusal, which the message deliberately does not.
        # The type and the code, not a traceback. A handled error already knows
        # where it came from; what `--debug` adds is which boundary refused and
        # -- from `plex.translate` on the way here -- what the library actually
        # said before the message was replaced. A stack for every NOT_FOUND
        # would bury that.
        output.debug(f"{type(exc).__name__} {exc.code or ''} exit={exc.exit_code}".rstrip())
        output.write(_error_document(exc), mode)
        return exc.exit_code
    except KeyboardInterrupt:  # pragma: no cover - interactive interruption
        output.write({"error": "interrupted"}, mode)
        return EXIT_ERROR
    except Exception as exc:
        # Without this, an unexpected exception prints a raw traceback on
        # stderr, bypassing redaction entirely and leaving stdout empty. Both
        # halves matter: the documented contract is that errors arrive on
        # stdout in the same structured shape, and that a credential can never
        # escape. Anything reaching here is a bug, so name it as one -- and name
        # it as *this tool's* bug, never as the client library's.
        output.write(
            {
                "error": f"internal error: {type(exc).__name__}",
                "code": "INTERNAL_ERROR",
                "help": HelpBlock(
                    [
                        "This is a bug in plex-axi; the command did not complete",
                        "Re-run with `--debug` for a diagnostic trace on stderr",
                        "Report it at https://github.com/dmealing/plex-axi/issues",
                    ]
                ),
            },
            mode,
        )
        output.debug_exception(exc)
        return EXIT_ERROR

    exit_code = EXIT_OK
    if isinstance(doc, dict) and "__exit_code__" in doc:
        doc = dict(doc)
        exit_code = doc.pop("__exit_code__")
    output.write(doc, mode)
    return exit_code
