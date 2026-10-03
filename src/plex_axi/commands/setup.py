"""`plex-axi setup` -- install the session integration the AXI standard calls primary.

AXI section 7 offers two discovery paths and says a user needs only one: a
SessionStart hook, which gives an agent ambient context in every session, and an
installable skill, which loads on demand and costs nothing per session. This
tool shipped only the second for three releases.

**Why `setup` carries `hooks` and not `skill`, unlike the sibling AXI CLI.**
There, `setup skill` is the only spelling the skill has. Here `plex-axi skill`
already exists, is what `scripts/ci-local.sh` runs as `plex-axi skill --check`,
and is named in the
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

_HOME_FLAG = Flag("--home", "<path>", note="act under a different home directory")

COMMAND = Command(
    name="setup",
    summary="Install, check or remove the session hooks that give an agent ambient context",
    usage="usage: plex-axi setup <hooks|status|remove> [--home <path>]",
    subs=(
        Sub(
            name="hooks",
            summary="Install or repair session hooks for Claude Code, Codex and OpenCode",
            flags=(_HOME_FLAG,),
        ),
        Sub(
            name="status",
            summary="Report whether each session hook is installed and current; writes nothing",
            flags=(_HOME_FLAG,),
        ),
        Sub(
            name="remove",
            summary="Remove every session hook this tool installed, and nothing else",
            flags=(_HOME_FLAG,),
        ),
    ),
    notes=(
        "hooks give ambient context every session; the skill loads on demand instead -- "
        "install either, with `plex-axi setup hooks` or `plex-axi skill`",
        "the session-start hook runs `plex-axi context`, which reads the environment, the "
        "command table and the local session record: no connection, no token, no server "
        "address, and it exits 0 on a machine with no server",
        "Claude Code also gets a session-end hook, `plex-axi context end`, which records which "
        "plex-axi commands the session ran -- names and counts, never arguments -- so the next "
        "session's context in that directory can say so; Codex and OpenCode have no "
        "session-end event to run it from",
        "writes four files under your home directory and nothing on the Plex server: "
        ".claude/settings.json, .codex/hooks.json, .codex/config.toml and "
        ".config/opencode/plugins/",
        "installation is idempotent and repairs the recorded path after a reinstall or a move; "
        "another tool's hooks are left alone and an unmanaged OpenCode plugin is never "
        "overwritten",
        "`remove` takes out only the entries this tool marked as its own, and leaves Codex's "
        "`[features] hooks = true` on because other tools' Codex hooks depend on it",
    ),
    examples=("plex-axi setup hooks", "plex-axi setup status", "plex-axi setup remove"),
)


def COMMAND_FOR(name: str) -> Command:
    return COMMAND


def run(ctx, name: str, sub: str, parsed):
    home = parsed.get("home")
    home = Path(home) if home else None
    if sub == "status":
        return _status(home)
    if sub == "remove":
        return _remove(home)
    report = hooks.install(home)
    doc = {"hooks": report["command"], "targets": report["targets"]}
    if report["errors"]:
        doc["errors"] = report["errors"]
        doc["__exit_code__"] = 1
        return doc
    doc["help"] = HelpBlock(
        [
            "Restart your agent session to receive plex-axi ambient context at session start",
            "Run `plex-axi context` to see exactly what that hook will print",
            "Run `plex-axi setup status` to check the hooks later",
        ]
    )
    return doc


def _status(home):
    report = hooks.status(home)
    doc = {"hooks": report["command"], "targets": report["targets"]}
    if report["errors"]:
        doc["errors"] = report["errors"]
    # A read, so it exits 0 whatever it finds: "not installed" is an answer.
    states = {target["status"] for target in report["targets"]}
    if states - {"installed"}:
        doc["help"] = HelpBlock(
            ["Run `plex-axi setup hooks` to install the missing hooks and repair stale ones"]
        )
    else:
        doc["help"] = HelpBlock(["Run `plex-axi setup remove` to uninstall them"])
    return doc


def _remove(home):
    report = hooks.remove(home)
    doc = {"targets": report["targets"]}
    if report["errors"]:
        doc["errors"] = report["errors"]
        doc["__exit_code__"] = 1
        return doc
    # Idempotent: a second removal reports every target `absent` and exits 0,
    # because the state it asks for already holds.
    doc["help"] = HelpBlock(["Run `plex-axi setup hooks` to install them again"])
    return doc
