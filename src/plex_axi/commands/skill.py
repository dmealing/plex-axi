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
        "the skill describes the commands *this installation* has, so a gated command that "
        "is enabled here is described and one that is not is absent entirely",
        "needs no server and no token: it reads the command table, not the library",
    ),
    examples=("plex-axi skill", "plex-axi skill --check"),
)


def COMMAND_FOR(name: str) -> Command:
    return COMMAND


def run(ctx, name: str, sub: str, parsed):
    from .. import playback
    from ..cli import command_order, command_specs

    order = command_order(ctx.environ)
    specs = command_specs(ctx.environ)
    # Each noun appears once, in dispatch order; two nouns sharing a module do
    # not share a Command, so this is the same list the root help prints -- and,
    # like the root help, it is the list *this installation* has.
    commands = [specs[noun] for noun in order]
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
    doc = {
        "skill": str(path),
        "status": "unchanged" if unchanged else ("updated" if existed else "created"),
        "bytes": len(content.encode("utf-8")),
    }
    if playback.allowed(ctx.environ):
        # Said out loud, because it is the one way this generated file can end
        # up describing the author's shell rather than the project. The
        # repository's own copy is generated with the gate closed, and CI's
        # `--check` runs with it closed too, so a copy written here and
        # committed will fail that check rather than ship.
        doc["scope"] = (
            f"this installation: {playback.ALLOW_VAR}={playback.ALLOW_VALUE}, so the playback "
            "commands are described; the copy committed to this repository is not"
        )
    doc["help"] = HelpBlock(["Run `plex-axi skill --check` in CI to catch a stale copy"])
    return doc
