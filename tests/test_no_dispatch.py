"""M7: the no-playback rule, enforced in code rather than described in prose.

**Read this before deleting anything here.** The rule is not "plex-axi cannot
play music". The client library it is built on *can*: ``plexapi.sonos`` is a
real module with a real ``PlexSonosClient``, ``MyPlexAccount.sonos_speakers()``
resolves a speaker by name over a live cloud path, and Plex for Sonos is a
current product, not a discontinued one. ``plexapi.client.PlexClient`` will
address a Chromecast running the Plex receiver. Every one of those is one
attribute access away from any code in this package.

So the absence of a play command is a *decision*, and a decision that is only
written down is a decision that lasts until someone reasonable thinks "actually,
the library can already do this". These tests are what makes it hold. If you
find yourself here because one of them failed, the failure is the point: the
seam is that this tool ends at an identifier and something else owns the
speakers, and reaching past it makes two systems believe they own the same
queue.

Three checks, because one is not enough:

1. **Nothing in the package names the dispatch surface.** A source-level scan,
   because an import is only the most obvious way to reach it.
2. **Nothing pulls the dispatch modules into the process.** An import-graph
   check, which catches a reference added through a helper or a plugin.
3. **No command path touches them at run time.** The dangerous entry points are
   replaced with land mines and the whole CLI surface is exercised over them.

The scan is scoped to command names, flag names and identifiers rather than to
prose: a play *count* is a legitimate music field, and a rule that forbade the
substring "play" would forbid describing a library as well as controlling one.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

import plex_axi
from plex_axi import cli

SOURCE_ROOT = Path(plex_axi.__file__).parent

#: Names that reach a player. Each is a real, working entry point in the client
#: library this package depends on -- not a hypothetical.
FORBIDDEN_NAMES = (
    "plexapi.sonos",
    "PlexSonosClient",
    "sonos_speakers",
    "sonos_speaker",
    "PlexClient",
    "playMedia",
    "playQueue",
    "PlayQueue",
    "createPlayQueue",
    "MyPlexAccount",
    "switchUser",
    "myPlexAccount",
)

#: Modules that must never be pulled into the process by importing this package.
#: ``plexapi.sonos`` is the one that matters most: it is the cloud path to a
#: speaker, it is gated only on a subscription feature, and nothing else in this
#: package would ever have a reason to load it.
FORBIDDEN_MODULES = ("plexapi.sonos", "plexapi.myplex", "soco", "pychromecast")

#: The player modules that arrive whatever we do, because ``plexapi.server``
#: imports them itself. They are listed rather than hidden: the invariant they
#: get is "never named, never reached", which the other tests here enforce.
UNAVOIDABLE_MODULES = ("plexapi.client", "plexapi.playqueue")

#: Words that would make a command or a flag a control surface rather than a
#: read. Matched as whole words against *names*, never against help prose.
CONTROL_WORDS = (
    "play",
    "pause",
    "stop",
    "resume",
    "seek",
    "skip",
    "next",
    "previous",
    "volume",
    "mute",
    "speaker",
    "room",
    "area",
    "entity",
    "client",
    "player",
    "target",
    "queue",
    "cast",
    "dispatch",
)


def _sources():
    return sorted(SOURCE_ROOT.rglob("*.py"))


def test_the_package_never_names_a_dispatch_entry_point():
    """Every one of these is a live capability, not a missing one."""
    offences = []
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if "FORBIDDEN_NAMES" in line:
                continue
            for name in FORBIDDEN_NAMES:
                # Word-boundary matching on the right, so `myPlexAccounts` would
                # still be caught but `playback` in a sentence would not.
                if re.search(r"(?<![\w.])" + re.escape(name) + r"\b", line):
                    offences.append(f"{path.name}:{line_number}: {name}")
    assert offences == [], "plex-axi reached the playback surface: " + "; ".join(offences)


def test_importing_the_cli_never_pulls_in_a_player():
    """The dispatch modules must not be in the process at all."""
    # Importing the CLI is what a real invocation does; every command module is
    # imported there, so this covers the whole package in one check.
    assert cli is not None
    loaded = set(sys.modules)
    for name in FORBIDDEN_MODULES:
        assert name not in loaded, f"{name} was imported"


def test_the_player_modules_that_arrive_anyway_are_never_used():
    """`plexapi.server` imports these itself, and that cannot be prevented.

    Saying so out loud matters more than pretending otherwise. A test asserting
    they are absent would have to be deleted the first time someone ran it, and
    a deleted test protects nothing. The invariant they actually get is "never
    named, never reached" -- the source scan above and the run-time check below.
    """
    for name in UNAVOIDABLE_MODULES:
        assert name in sys.modules, f"{name} no longer arrives; tighten this test"
        for path in _sources():
            assert name not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("noun", sorted(cli.COMMAND_ORDER))
def test_no_command_or_flag_is_a_control_surface(noun):
    """`--target`, `--speaker`, `--room` and their relatives do not exist here."""
    command = cli._MODULES[noun].COMMAND_FOR(noun)
    names = [command.name]
    for sub in command.subs:
        names.append(sub.name)
        names.extend(flag.name.lstrip("-") for flag in sub.flags)
        names.extend(arg.strip("<>[]") for arg in sub.args)
    for name in names:
        parts = re.split(r"[-_]", name.lower())
        overlap = set(parts) & set(CONTROL_WORDS)
        assert not overlap, f"`{noun}` declares `{name}`, which names {sorted(overlap)}"


def test_no_command_path_touches_a_player_at_run_time(server, cli_run, monkeypatch):
    """Land-mine the dangerous entry points, then run everything over them."""
    import plexapi.server

    def _mine(name):
        def _explode(*args, **kwargs):
            raise AssertionError(f"a command reached {name}")

        return _explode

    for attribute in ("clients", "client", "myPlexAccount", "createPlayQueue"):
        if hasattr(plexapi.server.PlexServer, attribute):
            monkeypatch.setattr(
                plexapi.server.PlexServer, attribute, _mine(attribute), raising=False
            )

    for argv in (
        ("search", "--artist", "Example Artist"),
        ("search", "--genre", "Jazz", "--type", "album"),
        ("genres",),
        ("moods",),
        ("styles",),
        ("track", "111", "--check-files"),
        ("album", "110"),
        ("artist", "100"),
        ("similar", "111"),
        ("recent",),
        ("sessions",),
        ("api", "/"),
        ("doctor",),
        (),
    ):
        assert cli_run(*argv).code == 0, argv
