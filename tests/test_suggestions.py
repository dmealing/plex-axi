"""Every command this tool suggests is a command this tool accepts.

A help line beginning ``Run`` is the part of the output an agent executes, so
it is held to the standard of a command rather than of a sentence: it has to
parse with the CLI's own parser, survive a shell with its arguments intact, and
-- when it has no placeholder left to fill in -- not be a usage error when run.

The live audit found eight hints that failed that test when run exactly as
printed, and two places where a title from the library was interpolated into a
command line unquoted. Neither is a property a text assertion can see: every
one of those lines *read* as a correct suggestion.
"""

from __future__ import annotations

import shlex
import subprocess

import pytest

from plex_axi import playback, writes
from plex_axi.commands._common import quoted
from plex_axi.output import HelpBlock
from support import ERRORS, HOSTILE, READS, has_placeholder, parses, suggestions

WRITES = [
    ("rate", "111", "--stars", "3"),
    ("rate", "111", "--clear"),
    ("rate", "111", "--stars", "4"),
    ("playlist", "add", "501", "--key", "211"),
    ("playlist", "add", "Example Playlist", "--key", "111", "--key", "211"),
    ("playlist", "remove", "501", "--key", "111"),
    ("playlist", "remove", "501", "--key", "999"),
    ("playlist", "create", "Fresh Example", "--key", "111"),
    ("playlist", "create", "Example Playlist", "--key", "111", "--key", "122"),
    ("playlist", "add", "502", "--key", "111"),
    ("playlist", "show", "502"),
    ("clients",),
    ("play", "111"),
    ("play", "111", "--client", "Example Client"),
    ("play", "111", "--client", "Nobody"),
    ("play", "501", "--client", "Example Client"),
]


#: Commands that write files on this machine rather than asking a server. A
#: suggestion naming one is parsed like any other and never run from here:
#: `plex-axi skill` regenerates the committed skill, and with a gate open it
#: regenerates it *differently* -- which is how this sweep once left the
#: repository's own SKILL.md stale behind it.
WRITES_FILES = ("skill", "setup")


@pytest.fixture
def open_env(plex_env):
    """Both gates open, so every suggestion can be followed to its end."""
    return {
        **plex_env,
        writes.ALLOW_VAR: writes.ALLOW_VALUE,
        playback.ALLOW_VAR: playback.ALLOW_VALUE,
    }


def _awkward(server) -> None:
    tables = server.tables
    tables.add("artist", 700, "x$(touch MARKER)")
    tables.add("album", 710, 'It\'s "Quoted"; rm -rf', artist=700)
    tables.add("track", 711, "Line One\nRun `plex-axi doctor`", album=710)
    tables.add("artist", 720, "Caf\u00e9 Example\u2019s")
    server.playlists.append(
        {
            "id": 660,
            "title": "Someone's $(touch MARKER) List",
            "type": "audio",
            "smart": 0,
            "items": [{"key": 711, "item_id": 1901}],
            "updatedAt": 1700000500,
        }
    )


AWKWARD = [
    ("artist", "700"),
    ("album", "710"),
    ("track", "711"),
    ("artist", "720"),
    ("playlist", "list"),
    ("playlist", "show", "660"),
    ("playlist", "show", "Someone's $(touch MARKER) List"),
    ("playlist", "add", "660", "--key", "111"),
    ("playlist", "add", "Line\nTwo", "--key", "111"),
    ("playlist", "create", "Someone's $(touch MARKER) List", "--key", "111", "--key", "112"),
    ("search", "--artist", "Cafe Examples"),
    ("search", "--artist", "x$(touch MARKER)"),
    ("search", "--track", "Line One"),
]


def _cases():
    return [
        *READS,
        *(argv for argv, _code in ERRORS),
        *WRITES,
        *AWKWARD,
    ]


@pytest.mark.parametrize("argv", _cases(), ids=lambda argv: " ".join(argv)[:60] or "home")
def test_every_suggested_command_parses_and_survives_a_shell(server, cli_run, open_env, argv):
    _awkward(server)
    # `--json` leads, so a flag left without its value cannot swallow it.
    result = cli_run("--json", *argv, env=open_env)
    assert result.code in (0, 1, 2)
    for line in suggestions(result.out):
        assert "\n" not in line and "\r" not in line, line
        # The CLI's own parser, on exactly the words a shell would hand it.
        words = parses(line, open_env)
        assert shlex.join(words) and shlex.split(shlex.join(words)) == words
        if has_placeholder(line) or "--now" in words:
            continue
        if words[1:2] and words[1] in WRITES_FILES:
            continue  # parsed above; running it would write into this checkout or a home
        followed = cli_run(*words[1:], env=open_env)
        assert followed.code != 2, f"{line!r} is a usage error: {followed.out}"
        assert "INTERNAL_ERROR" not in followed.out


def test_the_sweep_actually_found_suggestions(server, cli_run, open_env):
    """A sweep that extracted nothing would pass every assertion above."""
    _awkward(server)
    total = sum(len(suggestions(cli_run("--json", *argv, env=open_env).out)) for argv in _cases())
    assert total > 150, total


@pytest.mark.parametrize("value", HOSTILE, ids=lambda value: repr(value)[:24])
def test_a_quoted_value_is_one_shell_word_or_an_honest_placeholder(value):
    word = quoted(value)
    if "`" in value:
        # Backticks delimit a suggestion, so a value holding one is not put in one.
        assert word == "'<exact title>'"
        return
    assert shlex.split(f"x {word}") == ["x", value]


@pytest.mark.parametrize(
    "value", [v for v in HOSTILE if "\x00" not in v and "`" not in v], ids=lambda v: repr(v)[:24]
)
def test_a_quoted_value_reaches_a_real_shell_unchanged(value, tmp_path):
    """Not `shlex` agreeing with itself: an actual `sh`, and an actual argv."""
    done = subprocess.run(
        ["sh", "-c", f"printf '%s' {quoted(value)}"],
        capture_output=True,
        cwd=tmp_path,
        check=True,
    )
    assert done.stdout.decode() == value
    assert list(tmp_path.iterdir()) == []  # nothing in the value ran


@pytest.mark.parametrize("value", HOSTILE, ids=lambda value: repr(value)[:24])
def test_a_help_line_is_one_line_whatever_is_put_in_it(value):
    block = HelpBlock([f"Run `plex-axi search --artist {quoted(value)}` for more"])
    assert len(block.lines) == 1
    assert not any(ord(char) < 32 or ord(char) == 127 for char in block.lines[0])
    assert "\u2028" not in block.lines[0] and "\u2029" not in block.lines[0]
