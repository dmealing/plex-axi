"""`plex-axi setup` -- install the session integration the AXI standard calls primary.

AXI section 7 offers two discovery paths and says a user needs only one: a
SessionStart hook, which gives an agent ambient context in every session, and an
installable skill, which loads on demand and costs nothing per session. This
tool shipped only the second for three releases.

**Why `setup` carries `hooks` and not `skill`, unlike the sibling AXI CLI.**
There, `setup skill` is the only spelling the skill has. Here `plex-axi skill`
already exists, is what CI runs as `plex-axi skill --check`, and is named in the
generated skill and the README. Adding `setup skill` as a second door onto the
same room would give an agent two names for one idea -- the thing this project
refused when it declined to ship `--count` alongside `--limit`, and the
ambiguity the shared-package extraction exists to end. So the choice between the
two paths is *explained* here, in the notes, and the skill keeps its one
spelling. `plex-axi skill` is untouched by this command's existence.

**Why `hooks` declares itself read-only.** It writes files, but not to the Plex
server, and the access vocabulary is about the server: ``mutating`` is defined
as needing ``PLEX_AXI_ALLOW_WRITES`` and previewing without ``--write``, none of
which is true here, so declaring it would put a false sentence in `--help`.
`plex-axi skill` already sets the precedent -- it writes a file too, declares
read-only, and names the file it writes in a note. This does the same, for all
four of them.
"""

from __future__ import annotations

from pathlib import Path

from .. import hooks
from ..argspec import Command, Flag, Sub
from ..output import HelpBlock

COMMAND = Command(
    name="setup",
    summary="Install or repair the session hook that gives an agent ambient context",
    usage="usage: plex-axi setup hooks [--home <path>]",
    subs=(
        Sub(
            name="hooks",
            summary="Install SessionStart hooks for Claude Code, Codex and OpenCode",
            flags=(Flag("--home", "<path>", note="install under a different home directory"),),
        ),
    ),
    notes=(
        "hooks give ambient context every session; the skill loads on demand instead -- "
        "install either, with `plex-axi setup hooks` or `plex-axi skill`",
        "the hook runs `plex-axi context`, which reads the environment and the command table: "
        "no connection, no token, no server address, and it exits 0 on a machine with no server",
        "writes four files under your home directory and nothing on the Plex server: "
        ".claude/settings.json, .codex/hooks.json, .codex/config.toml and "
        ".config/opencode/plugins/",
        "installation is idempotent and repairs the recorded path after a reinstall or a move; "
        "another tool's hooks are left alone and an unmanaged OpenCode plugin is never "
        "overwritten",
    ),
    examples=("plex-axi setup hooks",),
)


def COMMAND_FOR(name: str) -> Command:
    return COMMAND


def run(ctx, name: str, sub: str, parsed):
    home = parsed.get("home")
    report = hooks.install(Path(home) if home else None)
    doc = {"hooks": report["command"], "targets": report["targets"]}
    if report["errors"]:
        doc["errors"] = report["errors"]
        doc["__exit_code__"] = 1
        return doc
    doc["help"] = HelpBlock(
        [
            "Restart your agent session to receive plex-axi ambient context at session start",
            "Run `plex-axi context` to see exactly what that hook will print",
        ]
    )
    return doc
