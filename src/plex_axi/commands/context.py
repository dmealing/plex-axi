"""`plex-axi context` -- the ambient document a SessionStart hook puts in front of an agent.

This is what `plex-axi setup hooks` installs, and everything about it follows
from *when* it runs: at the start of every session, on every machine that has
the package, before anybody has decided to use the tool.

**Four constraints, and each one rules something out.**

- **No connection and no credential.** An agent whose machine has never been
  pointed at a Plex server must still get a clean, useful document and exit 0.
  So this reads the environment and the command table, and nothing else --
  which is why it cannot be the no-argument home view, whose whole value is the
  live state it fetches.
- **No address and no token.** Hook output lands in an agent's context and is
  routinely logged and transcribed, which is a wider surface than a terminal
  rather than a narrower one. So `config:` reports *whether* the two variables
  are set and never what they hold; the home view is where a caller who has
  asked for it gets the URL.
- **Ruthlessly small.** AXI section 7: this loads on every session, so it
  carries enough to orient and act and no more. Three rules of thumb rather than
  the skill's twelve, and the nouns as a list rather than a summary each.
- **Gate-aware, like every other surface that describes this tool.** The
  commands are :func:`plex_axi.cli.command_order`'s, so a closed playback gate
  is invisible here as it is everywhere else, and the sentence about where the
  tool ends is chosen rather than fixed -- it would be false with the gate open.
  See :mod:`plex_axi.playback`.
"""

from __future__ import annotations

from .. import playback, writes
from ..argspec import Command, Sub
from ..config import describe_environment, missing_env_vars, setup_help
from ..output import HelpBlock
from .home import DESCRIPTION, executable_path

COMMAND = Command(
    name="context",
    summary="Print the ambient context a session hook puts in front of an agent",
    usage="usage: plex-axi context",
    default_sub="context",
    subs=(
        Sub(
            name="context",
            summary="Describe this installation without connecting to it",
        ),
    ),
    notes=(
        "this is the document `plex-axi setup hooks` installs a SessionStart hook to print",
        "it reads the environment and the command table only: no connection, no token, no "
        "server address, and it exits 0 whether or not this machine has a Plex server",
        "for the live library -- the server, its size, what arrived recently and what is "
        "playing -- run `plex-axi` with no arguments instead",
    ),
    examples=("plex-axi context",),
)


def COMMAND_FOR(name: str) -> Command:
    return COMMAND


#: How to search, which is the one thing that distinguishes this tool from every
#: other way of asking a Plex server a question.
SEARCH_RULE = (
    "one flag per field -- --artist, --album, --track, --genre, --mood, --style, --year, "
    "--rated-min -- because Plex matches them separately; --query searches one unstructured "
    "string and is the fallback, not the default"
)

#: Where the tool stops. The single most load-bearing line here, and the reason
#: it is chosen rather than written: with the playback gate open the first
#: sentence is no longer true, and a document that said it anyway would be
#: describing a different installation from the one it is running on.
HANDOFF_RULE = (
    "every row carries one, spelled plex://<machine-id>/<rating-key>, and that is where this "
    "tool ends: it leaves dispatch to whatever owns the speakers"
)
PLAYING_HANDOFF_RULE = (
    "every row carries one, spelled plex://<machine-id>/<rating-key>; this installation can "
    "also start one on a target this server lists, and starting is the whole of it"
)

#: The Plex-specific trap that makes a correctly-spelled search return nothing.
VOCABULARY_RULE = (
    "--genre and --style match the artist, --mood the type being searched; run `plex-axi "
    "genres` (or `moods`, `styles`) for the exact strings this server will accept"
)


def run(ctx, name: str, sub: str, parsed):
    from ..cli import command_order

    environ = ctx.environ
    playing = playback.allowed(environ)
    missing = missing_env_vars(environ)

    doc = {
        "bin": executable_path(),
        "description": DESCRIPTION,
        "config": _config(environ, missing),
        # The same one-liner the home view prints, from the same function. An
        # agent that reads "disabled" here does not plan a rating it cannot
        # write, and does not read the refusal as a broken installation.
        "writes": writes.state(environ),
    }
    if playing:
        doc["playback"] = playback.state(environ)
    doc["search"] = SEARCH_RULE
    doc["media_id"] = PLAYING_HANDOFF_RULE if playing else HANDOFF_RULE
    doc["vocabulary"] = VOCABULARY_RULE
    doc["commands"] = list(command_order(environ))
    doc["help"] = HelpBlock(_help(missing, playing))
    return doc


def _config(environ, missing: list) -> str:
    """Which variables are set -- never what they hold.

    Named from :func:`plex_axi.config.describe_environment` rather than from the
    primary spellings, so an installation configured through one of the accepted
    aliases is told the name of the variable it actually set.

    Reported as an ordinary fact rather than as an error even when both are
    absent, because a hook that opened a session with a failure would be
    reporting the machine's ordinary state as a fault.
    """
    if missing:
        return f"{' and '.join(missing)} not set, so no command here can reach a server yet"
    described = describe_environment(environ)
    return f"{described['url_var']} and {described['token_var']} are set"


def _help(missing: list, playing: bool) -> list:
    if missing:
        # Leading with the home view would be advice to run something that
        # cannot work yet. What this reader needs is the two exports.
        return [*setup_help(), "Run `plex-axi --help` for the whole command reference"]
    return [
        "Run `plex-axi` for this library at a glance: the server, its size, what arrived "
        "recently and what is playing",
        "Run `plex-axi search --artist '<name>' --track '<title>'` to search field by field",
        # Only where the gate is open, and for the same reason the home view
        # adds it there: the line above has just said this installation can
        # start something, and an agent that read that with no way to find a
        # target would have to discover one from a refusal.
        *(["Run `plex-axi clients` for what this server can start music on"] if playing else []),
        "Run `plex-axi <command> --help` for its flags, or `plex-axi --help` for all of them",
    ]
