"""M7, revisited: what the playback seam still guarantees, now that there is one.

**Read this before deleting anything here, and read the next two paragraphs
before adding anything.**

This file used to prove something absolute: that ``plex-axi`` could not play
music at all. Not that it refused to, that it *could not* -- no command, no flag,
no code path, and an import graph with no player in it. That proof is gone and it
is not coming back. Playback exists here now, gated on
``PLEX_AXI_ALLOW_PLAYBACK`` and invisible until an operator opens that gate, and
once the code exists the strongest available claim is that it is *gated*, never
that it is *absent*. Nothing in this file can restore the old claim; a test
asserting the absence of a command that ships would have to be deleted the first
time somebody ran it, and a deleted test protects nothing.

**Why the old decision was still right, so that the reversal is not read as one.**
The reasoning was never "playing music is dangerous". It was that a house running
a home-automation system already has something that owns the speakers, and a
second tool that could also start music lets an agent pick the path that bypasses
it -- leaving two systems believing they own the same queue. That is intact for
anyone who has such a system. It is simply irrelevant to somebody who has a Plex
library and nothing else, and for them the tool dead-ended at an identifier. So
the capability is available, off, and -- the part that keeps the original
reasoning working -- *invisible* while it is off, because a capability an agent
cannot see is one it cannot choose wrongly. See ``plex_axi/playback.py``.

What is asserted here instead, and each of these is a real claim:

1. **The client library's account and Sonos surface is never named and never
   imported.** This is the one part that is still absolute, gate open or closed:
   ``plexapi.sonos``, ``PlexSonosClient``, ``sonos_speakers``, ``MyPlexAccount``,
   ``switchUser`` and their relatives appear nowhere in this package's *code*,
   and ``plexapi.sonos`` and ``plexapi.myplex`` are never pulled into the
   process. The tool reaches Sonos, when it is asked to, over one documented
   HTTP endpoint parsed with the standard library -- the same shape
   :mod:`plex_axi.users` uses for ``--user`` -- so the account object, which
   resolves speakers by name and dispatches to them, still never exists here.
2. **No command path touches the client library's player object model.** The
   dangerous entry points are replaced with land mines and the whole CLI surface
   is exercised over them -- *including* `play` and `clients` with the gate open,
   which is a stronger statement than the old sweep could make: the playback
   commands address the server's own HTTP paths, so even they never reach
   ``PlexServer.clients()``, ``createPlayQueue`` or ``myPlexAccount``.
3. **No command or flag is a transport control.** `play` starts something and
   `--client` names where; there is no pause, stop, resume, seek, skip, next,
   previous, volume, mute, room, queue or cast, on any command, and the two
   words the playback commands are allowed are named one by one rather than by
   removing the check.
4. **The gate hides, not merely refuses.** That is
   ``tests/test_playback.py``, which is where the invisibility claim is made.

**The scan reads code, not prose, and that is a change worth understanding.** It
used to read raw lines, which worked only while no module had any reason to
mention a forbidden name. :mod:`plex_axi.cloud` now has every reason to: its
docstring explains, at length, that it does *not* use ``plexapi.sonos`` and why.
A rule that made that paragraph the offence would be answered by deleting the
paragraph, which is the opposite of what it is for. So the scan parses each
module and looks at names, attributes, imports and **string literals** -- the
last so that ``getattr(server, "createPlayQueue")`` is caught as surely as the
attribute would be. Comments and docstrings are the only thing it does not read,
because a comment cannot reach anything.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

import plex_axi
from plex_axi import cli, playback

SOURCE_ROOT = Path(plex_axi.__file__).parent

#: Names that reach a player through the client library. Each is a real, working
#: entry point in the dependency -- not a hypothetical -- and none of them is
#: used by this package, gate open or closed.
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

#: Modules that must never be pulled into the process by importing this package
#: **or by running any command in it**. ``plexapi.sonos`` is the one that matters
#: most: it is the cloud path to a speaker, it is gated only on a subscription
#: feature, and this package reaches Sonos without it.
FORBIDDEN_MODULES = ("plexapi.sonos", "plexapi.myplex", "soco", "pychromecast")

#: The player modules that arrive whatever we do, because ``plexapi.server``
#: imports them itself. They are listed rather than hidden: the invariant they
#: get is "never named, never reached", which the other tests here enforce.
UNAVOIDABLE_MODULES = ("plexapi.client", "plexapi.playqueue")

#: Words that would make a command or a flag a control surface rather than a
#: handoff. Matched as whole words against *names*, never against help prose.
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

#: The two words the playback commands are allowed, named one by one rather than
#: by exempting those commands from the check. `play` is the verb and `client` is
#: where; everything else in :data:`CONTROL_WORDS` is still forbidden on them,
#: which is what "starting playback is all it does" means in code.
PLAYBACK_WORDS = frozenset({"play", "client"})


def _sources():
    return sorted(SOURCE_ROOT.rglob("*.py"))


def _reachable(path: Path) -> list:
    """Every name, attribute, import and string literal in one module's code.

    Docstrings and comments are deliberately absent: a comment cannot reach
    anything, and the modules that explain *why* a dispatch surface is not used
    have to be able to name it. String literals are present because
    ``getattr(x, "playMedia")`` reaches exactly as far as ``x.playMedia`` does.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []

    def add(name, node):
        if name:
            found.append((node.lineno, name))

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            add(node.id, node)
        elif isinstance(node, ast.Attribute):
            add(node.attr, node)
            add(_dotted(node), node)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name, node)
                add(alias.asname, node)
        elif isinstance(node, ast.ImportFrom):
            add(node.module, node)
            for alias in node.names:
                add(alias.name, node)
                add(alias.asname, node)
                if node.module:
                    add(f"{node.module}.{alias.name}", node)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            add(node.value, node)
    return found


def _dotted(node) -> str:
    """``a.b.c`` for an attribute chain rooted in a plain name, else ``""``."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return ""
    parts.append(node.id)
    return ".".join(reversed(parts))


def test_the_package_never_names_a_dispatch_entry_point():
    """Every one of these is a live capability, not a missing one.

    Absolute, and the only claim in this file that still is: it holds whatever
    the gate says, because the gate governs which commands exist and this
    governs what any of them may reach for.
    """
    offences = []
    for path in _sources():
        for line_number, name in _reachable(path):
            if name in FORBIDDEN_NAMES:
                offences.append(f"{path.name}:{line_number}: {name}")
    assert offences == [], "plex-axi reached the playback surface: " + "; ".join(offences)


def test_the_scan_would_notice_a_dispatch_call(tmp_path):
    """The scan is a security control, so it is proved rather than trusted.

    Three shapes, because the previous version of this scan read raw lines and
    would have missed none of them -- and would also have reported the paragraph
    in ``cloud.py`` that explains why the first one is not used. This one has to
    tell those apart, so both halves are asserted: the calls are found and the
    prose is not.
    """
    module = tmp_path / "offender.py"
    module.write_text(
        "\n".join(
            [
                '"""A docstring naming plexapi.sonos and PlexSonosClient and MyPlexAccount."""',
                "# A comment naming createPlayQueue.",
                "import plexapi.sonos",
                "def go(server, account):",
                '    getattr(server, "createPlayQueue")(None)',
                "    return account.sonos_speakers()",
            ]
        ),
        encoding="utf-8",
    )
    found = {name for _line, name in _reachable(module) if name in FORBIDDEN_NAMES}
    assert found == {"plexapi.sonos", "createPlayQueue", "sonos_speakers"}


def test_importing_the_cli_never_pulls_in_a_player():
    """The dispatch modules must not be in the process at all."""
    # Importing the CLI is what a real invocation does; every command module is
    # imported there, so this covers the whole package in one check.
    assert cli is not None
    loaded = set(sys.modules)
    for name in FORBIDDEN_MODULES:
        assert name not in loaded, f"{name} was imported"


def test_playing_for_real_never_pulls_in_a_player(server, cli_run, playing_env):
    """The stronger version of the check above: after a play, not before one.

    An import that only happened on the playback path would pass the check above
    and fail this one, which is the whole point of having both.
    """
    played = cli_run("play", "111", "--client", "Example Client", "--now", env=playing_env)
    assert played.code == 0, played.out
    for name in FORBIDDEN_MODULES:
        assert name not in set(sys.modules), f"{name} was imported by a playback command"


def test_the_player_modules_that_arrive_anyway_are_never_used():
    """`plexapi.server` imports these itself, and that cannot be prevented.

    Saying so out loud matters more than pretending otherwise. A test asserting
    they are absent would have to be deleted the first time someone ran it, and
    a deleted test protects nothing. The invariant they actually get is "never
    named, never reached" -- the code scan above and the run-time check below.
    """
    for name in UNAVOIDABLE_MODULES:
        assert name in sys.modules, f"{name} no longer arrives; tighten this test"
        for path in _sources():
            assert name not in {n for _line, n in _reachable(path)}


@pytest.mark.parametrize("noun", sorted(cli.COMMAND_ORDER))
def test_no_command_or_flag_is_a_control_surface(noun):
    """`--target`, `--speaker`, `--room` and their relatives do not exist here."""
    _assert_no_control_words(noun, allowed=frozenset())


@pytest.mark.parametrize("noun", sorted(cli.PLAYBACK_ORDER))
def test_the_playback_commands_are_a_start_button_and_nothing_more(noun):
    """`play` and `--client` are the whole vocabulary; the rest is still refused.

    Written as an exemption of two named words rather than as a skip, so that
    adding `--volume` or a `pause` subcommand fails here rather than passing
    because the command it was added to happens to be a playback one.
    """
    _assert_no_control_words(noun, allowed=PLAYBACK_WORDS)


def _assert_no_control_words(noun: str, *, allowed: frozenset) -> None:
    command = cli._PLAYBACK_MODULES.get(noun, cli._MODULES.get(noun)).COMMAND_FOR(noun)
    names = [command.name]
    for sub in command.subs:
        names.append(sub.name)
        names.extend(flag.name.lstrip("-") for flag in sub.flags)
        names.extend(arg.strip("<>[]") for arg in sub.args)
    for name in names:
        parts = re.split(r"[-_]", name.lower())
        overlap = (set(parts) & set(CONTROL_WORDS)) - allowed
        assert not overlap, f"`{noun}` declares `{name}`, which names {sorted(overlap)}"


def test_no_command_path_touches_the_client_librarys_player_model(
    server, cli_run, playing_env, monkeypatch
):
    """Land-mine the dangerous entry points, then run everything over them.

    `play` and `clients` are in the sweep, which the old version of this test
    could not do because they did not exist. That they pass is the claim worth
    having: the playback commands address the server's own HTTP paths, so the
    client library's player object model is not on the path of a command that
    actually starts music.
    """
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
        ("clients",),
        ("play", "111", "--client", "Example Client"),
        ("play", "111", "--client", "Example Client", "--now"),
        (),
    ):
        assert cli_run(*argv, env=playing_env).code == 0, argv


def test_the_gate_is_the_only_thing_standing_between_the_two_answers(server, cli_run, plex_env):
    """The same invocation, twice, with one variable changed.

    This is the reversal in one assertion: what used to be a permanent refusal
    is now a decision the operator makes, and nothing else about the invocation
    differs.
    """
    argv = ("play", "111", "--client", "Example Client", "--now")

    closed = cli_run(*argv, env=plex_env)
    assert closed.code == 2
    assert "OUT_OF_SCOPE" in closed
    assert server.played == []

    opened = cli_run(*argv, env={**plex_env, playback.ALLOW_VAR: playback.ALLOW_VALUE})
    assert opened.code == 0, opened.out
    assert "started:" in opened.out
    assert [row["client"] for row in server.played] == ["Example Client"]
