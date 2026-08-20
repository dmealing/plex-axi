"""`plex-axi skill` -- write, or verify, the installable Agent Skill.

The skill is generated from the CLI's own command table rather than hand-written,
so it cannot describe a flag that does not exist. `--check` is what CI runs: it
fails when the committed copy no longer matches the commands, which is the only
way a static document stays true to a moving one.
"""

from __future__ import annotations

from pathlib import Path

from ..argspec import Command, Flag, Sub
from ..errors import AxiError
from ..output import HelpBlock
from ..skill import SKILL_RELATIVE_PATH, render, target_path

COMMAND = Command(
    name="skill",
    summary="Write or verify the generated Agent Skill for this CLI",
    usage="usage: plex-axi skill [--check] [--root <dir>]",
    default_sub="skill",
    subs=(
        Sub(
            name="skill",
            flags=(
                Flag("--check", boolean=True, note="fail if the committed copy is stale"),
                Flag("--root", "<dir>", default=".", note="repository root"),
            ),
            summary="Generate the skill from the command table",
        ),
    ),
    notes=(
        f"writes {SKILL_RELATIVE_PATH}; never hand-edit that file, it is generated",
        "needs no server and no token: it reads the command table, not the library",
    ),
    examples=("plex-axi skill", "plex-axi skill --check"),
)


def COMMAND_FOR(name: str) -> Command:
    return COMMAND


def run(ctx, name: str, sub: str, parsed):
    from ..cli import COMMAND_ORDER, command_specs

    specs = command_specs()
    # Each noun appears once, in dispatch order; two nouns sharing a module do
    # not share a Command, so this is the same list the root help prints.
    commands = [specs[noun] for noun in COMMAND_ORDER]
    content = render(commands)
    path = target_path(Path(parsed.get("root") or "."))

    if parsed.get("check"):
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current == content:
            return {"skill": str(path), "status": "current"}
        raise AxiError(
            f"{path} does not match the command table",
            help_lines=[
                "Run `plex-axi skill` and commit the result",
                "The file is generated; edit the commands, not the skill",
            ],
            code="SKILL_STALE",
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    unchanged = existed and path.read_text(encoding="utf-8") == content
    if not unchanged:
        path.write_text(content, encoding="utf-8")
    return {
        "skill": str(path),
        "status": "unchanged" if unchanged else ("updated" if existed else "created"),
        "bytes": len(content.encode("utf-8")),
        "help": HelpBlock(["Run `plex-axi skill --check` in CI to catch a stale copy"]),
    }
