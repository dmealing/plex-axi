"""Session-end capture: what a session did with this tool, for the next one's context.

AXI section 7 asks for *lifecycle capture* as well as ambient context: a
session-end hook records what happened, so the session-start document gets
richer over time instead of saying the same thing forever. `plex-axi setup hooks`
installs `plex-axi context end` as Claude Code's ``SessionEnd`` hook, and
`plex-axi context` reads back what it recorded for the directory it runs in.

**What is recorded is deliberately thin, and the thinness is the design.** One
record per session: the directory, the date, and how many times each command
ran -- ``search x3, playlist add x1`` -- with a count of the invocations that
carried ``--write`` or ``--now``. Never an argument. Arguments are where artist
and album names live, and where a token typed on a command line would be; the
record is read back into an agent's context on every later session, which is a
wider surface than the terminal the command was typed in. Command names say
what the last session was doing without saying anything about the library.

**It reads the transcript the agent hands it and nothing else.** The hook's
payload names the transcript file; the commands are the shell commands the
agent issued through its tools, found by their ``tool_use`` shape rather than
by searching the prose -- a session that merely *discussed* `plex-axi search`
did not run it. Nothing here opens a connection, and every failure -- no
payload, an unreadable transcript, an unwritable state directory -- records
nothing and says so, because a hook that failed would be reported to the user
as their session failing to close.

**Only Claude Code gets the hook.** Codex's hook events stop at ``Stop``, which
fires per turn rather than per session, and OpenCode's plugin events have no
session-end event either; installing this against a per-turn event would
re-read the whole transcript on every reply.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shlex
from pathlib import Path

from .hooks import write_atomic

#: How many sessions the state file remembers, across every directory.
KEEP = 50

#: Flags whose presence means an invocation changed something rather than
#: previewing it: the write gate's confirmation and the playback gate's.
APPLYING_FLAGS = ("--write", "--now")

#: Global flags that ask about the tool rather than use it.
_PROBES = {"--version", "-v", "-V", "--help", "-h"}

#: Where an invocation of this tool starts inside a shell command line: in
#: command position -- the start of a line, or after ``;``, ``&``, ``|``, ``(``
#: or ``$(`` -- optionally behind environment assignments, a launcher such as
#: ``env`` or ``time``, and a path. Command position is the point: ``grep
#: plex-axi notes.md`` and a commit message that mentions the tool name it
#: without running it. A backtick is deliberately not an operator here: in an
#: agent's commands it is far more often Markdown quoting a command inside a
#: string than a shell substitution running one.
_INVOCATION = re.compile(
    r"(?:^|[;&|(]|\$\()[ \t]*"
    r"(?:(?:[A-Za-z_][A-Za-z0-9_]*=\S*|env|time|exec|command|nohup)[ \t]+)*"
    r"(?:[^\s;&|()`'\"]*/)?plex-axi(?=\s|$|[;&|)])",
    re.M,
)

#: Where that invocation ends: the next shell operator or line break.
_END = re.compile(r"\|\||&&|[;|&\n)]")

#: A here-document's body, which is data the command reads rather than more
#: commands: a script or a document written through one names the tool on every
#: other line without running it once.
_HEREDOC = re.compile(r"<<-?[ \t]*(['\"]?)(\w+)\1[^\n]*\n.*?^[ \t]*\2[ \t]*$", re.S | re.M)


def state_path(environ=None) -> Path:
    """The state file, under ``$XDG_STATE_HOME`` when it is set."""
    environ = os.environ if environ is None else environ
    root = environ.get("XDG_STATE_HOME") or os.environ.get("XDG_STATE_HOME")
    base = Path(root) if root else Path.home() / ".local" / "state"
    return base / "plex-axi" / "sessions.json"


def invocations(command: str, nouns: dict) -> list:
    """Every invocation of this tool in one shell command line, as ``(label, applied)``.

    ``nouns`` maps each command name to its subcommand names, so a label is the
    command and, where it has them, the subcommand -- and never an argument.
    """
    found = []
    command = _HEREDOC.sub("", command)
    for match in _INVOCATION.finditer(command):
        rest = command[match.end() :]
        end = _END.search(rest)
        segment = rest[: end.start()] if end else rest
        try:
            words = shlex.split(segment)
        except ValueError:
            words = segment.split()
        label = _label(words, nouns)
        if label:
            found.append((label, any(flag in words for flag in APPLYING_FLAGS)))
    return found


def _label(words: list, nouns: dict) -> str:
    """The command and subcommand, ``home`` for a bare run, or ``""`` if neither.

    A command this installation does not have -- a typo, or a playback command
    with the gate closed -- is not counted rather than counted as something it
    was not, and nor is a version or help probe, which used nothing.
    """
    for index, word in enumerate(words):
        if word in nouns:
            following = words[index + 1] if index + 1 < len(words) else ""
            return f"{word} {following}" if following in nouns[word] else word
    if any(not word.startswith("-") for word in words) or set(words) & _PROBES:
        return ""
    return "home"


def _shell_commands(transcript: Path):
    """Each shell command the agent issued through a tool, in order."""
    with transcript.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            yield from _tool_commands(entry)


def _tool_commands(node):
    if isinstance(node, dict):
        given = node.get("input")
        if node.get("type") == "tool_use" and isinstance(given, dict):
            command = given.get("command")
            if isinstance(command, str):
                yield command
        for value in node.values():
            yield from _tool_commands(value)
    elif isinstance(node, list):
        for value in node:
            yield from _tool_commands(value)


def summarise(transcript: Path, nouns: dict) -> dict:
    """Count each command label and the invocations that applied something."""
    counts: dict = {}
    applied = 0
    for command in _shell_commands(transcript):
        for label, did_apply in invocations(command, nouns):
            counts[label] = counts.get(label, 0) + 1
            applied += did_apply
    return {"commands": counts, "applied": applied}


def record(payload: dict, nouns: dict, environ=None, *, today: str | None = None) -> dict:
    """Record one ended session from a hook payload.

    Returns the document the hook prints: what was recorded, and when it is
    nothing, the reason.
    """
    transcript = payload.get("transcript_path")
    if not isinstance(transcript, str) or not transcript:
        return _nothing("the hook payload names no transcript")
    try:
        summary = summarise(Path(transcript), nouns)
    except OSError as exc:
        return _nothing(f"the transcript could not be read ({type(exc).__name__})")
    total = sum(summary["commands"].values())
    if not total:
        return _nothing("this session ran no plex-axi command")

    path = state_path(environ)
    entry = {
        "session": str(payload.get("session_id") or ""),
        "cwd": str(payload.get("cwd") or os.getcwd()),
        "ended": today or datetime.date.today().isoformat(),
        **summary,
    }
    try:
        sessions = [
            s for s in _load(path) if not entry["session"] or s.get("session") != entry["session"]
        ]
        sessions.append(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, json.dumps(sessions[-KEEP:], indent=2) + "\n")
    except OSError as exc:
        return _nothing(f"the state file could not be written ({type(exc).__name__})")
    return {"recorded": f"{total} plex-axi command(s) from this session"}


def _nothing(reason: str) -> dict:
    return {"recorded": "nothing", "reason": reason}


def _load(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [entry for entry in data if isinstance(entry, dict)] if isinstance(data, list) else []


def last_session(cwd: str, environ=None) -> str:
    """The most recent recorded session in this directory, as one line, or ``""``.

    Directory-scoped, as AXI asks of ambient context: a session in another
    project used the tool for something else, and saying so here would be noise.
    """
    for entry in reversed(_load(state_path(environ))):
        if entry.get("cwd") != cwd or not isinstance(entry.get("commands"), dict):
            continue
        ranked = sorted(entry["commands"].items(), key=lambda item: (-item[1], item[0]))
        used = ", ".join(f"{label} x{count}" for label, count in ranked)
        applied = entry.get("applied") or 0
        tail = f"; {applied} applied with --write or --now" if applied else "; nothing applied"
        return f"{entry.get('ended', '?')}: {used}{tail}"
    return ""
