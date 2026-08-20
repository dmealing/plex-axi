"""Generate the installable Agent Skill from the CLI's own declarations.

The skill is the low-overhead discovery path: it loads on demand instead of on
every session, and works in agents without hook support. Generating it from the
same command table the CLI dispatches on keeps the two from drifting, and
`plex-axi skill --check` fails when the committed copy is stale.

Live state is deliberately excluded. A skill is static, so anything about a
particular library -- its genres, its size, its section name -- would be wrong
for every other reader and stale for the one it was written from.
"""

from __future__ import annotations

from pathlib import Path

from . import writes
from .argspec import render_access
from .commands.home import DESCRIPTION

SKILL_NAME = "plex-axi"
SKILL_RELATIVE_PATH = Path("skills") / SKILL_NAME / "SKILL.md"

FRONTMATTER_DESCRIPTION = (
    "Search and diagnose a Plex music library through the plex-axi CLI - structured "
    "per-field search on artist, album, track, genre, mood, style, year and rating; "
    "the library's own genre/mood/style vocabulary; track, album and artist detail "
    "including file availability; and sonically similar tracks. It can also set a "
    "rating and edit an audio playlist, but only when the operator has enabled writes. "
    "Use whenever a task touches a Plex music library: finding a recording, checking why "
    "a search found nothing, or resolving a title to a media id. It never plays anything."
)


def _fence(lines) -> str:
    return "\n".join(["```sh", *lines, "```"])


def render(commands) -> str:
    """Render SKILL.md from the live command table."""
    sections = [
        "---",
        f"name: {SKILL_NAME}",
        f"description: {FRONTMATTER_DESCRIPTION}",
        "---",
        "",
        f"# {SKILL_NAME}",
        "",
        DESCRIPTION,
        "",
        "## Configuration",
        "",
        "Both values come from the environment. There is no `--token` flag and no credential",
        "file: a token on a command line leaks into shell history and the process table, and a",
        "Plex token is a bearer credential for the whole library.",
        "",
        _fence(
            [
                "export PLEX_URL=http://plex.example.com:32400   # the server on the local network",
                "export PLEX_TOKEN=<a Plex access token>",
                "export PLEX_SECTION='Example Music'             # only if there is more than one",
                f"export {writes.ALLOW_VAR}={writes.ALLOW_VALUE}"
                "        # only to allow `rate` and `playlist` to write",
            ]
        ),
        "",
        "Point `PLEX_URL` at the server itself rather than at plex.tv, so the tool keeps",
        "working when plex.tv is down and no invocation pays a cloud round-trip.",
        "Run `plex-axi doctor` to confirm; it exits non-zero when any check fails.",
        "",
        "## Running without a global install",
        "",
        _fence(
            [
                "uvx plex-axi search --artist 'Example Artist'",
                "pipx run plex-axi genres",
            ]
        ),
        "",
        "## Output",
        "",
        "Commands print TOON on stdout and exit non-zero on failure. Add `--human` for a",
        "readable table, or `--json` for raw JSON. Errors are structured on stdout too, and",
        "carry the command that fixes them.",
        "",
        "## What this tool does not do",
        "",
        "- **It never plays anything.** There is no play command and no concept of a speaker,",
        "  room or player. Every command ends at a labelled `media_id`, and dispatch belongs to",
        "  whatever owns the speakers.",
        "- **It is music only.** No films, shows, episodes or watchlist. The rest of the Plex",
        "  tooling landscape is video-shaped; this is the half nothing else covers.",
        "- **It reads unless it is told twice that it may write.** Only `rate` and",
        f"  `playlist create|add|remove` change anything. They refuse unless `{writes.ALLOW_VAR}`",
        f"  is `{writes.ALLOW_VALUE}` in the environment, and even then they preview the change and",
        "  send nothing until `--write` is passed. Every other command reads, and `api` refuses",
        "  every method but GET rather than documenting that it should not be used for them.",
        "",
        "## Commands",
        "",
    ]

    for command in commands:
        if command.name == "home":
            continue
        sections.append(f"### `plex-axi {command.name}`")
        sections.append("")
        sections.append(command.summary + ".")
        sections.append("")
        # The same access block `--help` prints, from the same declaration, so a
        # reader of the skill and a reader of the help cannot be told different
        # things about whether a command can change the library.
        sections.extend(
            f"- **{line.strip()}**" if index == 0 else f"  - {line.strip()}"
            for index, line in enumerate(_access_bullets(command))
        )
        sections.append("")
        if command.examples:
            sections.append(_fence(list(command.examples)))
            sections.append("")
        for note in command.notes:
            sections.append(f"- {note}")
        if command.notes:
            sections.append("")

    sections.extend(
        [
            "## Rules of thumb",
            "",
            "- **Use a flag per field.** `--artist 'X' --track 'Y'` searches two Plex fields;",
            "  `--query 'X Y'` searches one string and is why other Plex tools miss. `--query`",
            "  exists for the case where there genuinely is only one unstructured string.",
            "- **Ratings are stars, 0-5, in both directions.** A rating printed in a result can",
            "  be passed straight to `--rated-min`.",
            "- **Genres and styles live on the artist**, not on the track. `plex-axi genres`",
            "  prints the exact strings the server will accept; pass one of those, not a synonym.",
            "- **A zero result is an answer.** It names the filters that matched nothing and the",
            "  command that lists the real vocabulary. Drop one flag at a time to find the",
            "  one that was wrong.",
            "- **`rating_key` is local to one server and moves.** It changes when an item is",
            "  re-matched or the library is rebuilt, so keep the `guid` beside it anywhere the",
            "  value is written down.",
            "- **A track with `analysis: 0` has never been analysed**, so `similar` has nothing",
            "  to work from and its empty answer is not a statement about the library.",
            "- **A mutating command run without `--write` is safe and useful.** It prints what",
            "  would change and sends nothing, which is how to check a playlist edit before",
            "  making it -- and how a smart playlist is caught before the server refuses.",
            "- Every command supports `--help`, which is the authoritative reference for its flags.",
            "",
        ]
    )
    return "\n".join(sections).rstrip() + "\n"


def _access_bullets(command) -> list:
    """The `access:` lines from the command declaration, without the header."""
    lines = render_access(command)
    return list(lines[1:]) or ["access unstated"]


def target_path(root: Path) -> Path:
    return Path(root) / SKILL_RELATIVE_PATH
