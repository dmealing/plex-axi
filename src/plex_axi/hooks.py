"""Session-lifecycle integration: the discovery path the AXI standard calls primary.

AXI section 7 makes a SessionStart hook the primary way an agent finds a tool and
the installable skill the secondary one. This tool shipped only the skill for
three releases, so an agent that had never been told about ``plex-axi`` had no
way to learn it existed until somebody named it.

Ported from the sibling AXI CLI's session-hook contract so the two install the
same way: a ``SessionStart`` hook for Claude Code and Codex, and a managed
ambient-context plugin for OpenCode. Installation happens only from
`plex-axi setup hooks`, never as a side effect of an ordinary command.

**The one deliberate divergence, and it is the reason this module exists rather
than being a copy.** The sibling's hook runs its bare executable, whose
no-argument view is *live state* -- it connects, reads, and prints what is there.
That is the right answer for the tool it was written for and the wrong one here,
for three separate reasons, any one of which would be enough:

- **It would need credentials.** A hook runs at the start of every session,
  before anybody has decided to use the tool. ``plex-axi`` with no ``PLEX_URL``
  reports ``NOT_CONFIGURED`` and exits 1, so on every machine that has the
  package and no server the hook would open each session with a failure.
- **It would touch the network.** The home view opens a connection and issues
  several requests -- the section, three item counts, the mood vocabulary, the
  recently-added albums, the sessions. Paying that on every session start, for a
  tool the session may never use, is not a cost a hook may impose.
- **It would print a host address.** The home view prints ``url:``, and this
  repository's whole discipline is that a server's address is a thing you do not
  write down. Hook output lands in an agent's context and is routinely logged
  and transcribed, which makes it a wider surface than a terminal, not a
  narrower one.

So the hook runs :data:`CONTEXT_COMMAND` instead -- `plex-axi context`, which
reads the environment and the command table and nothing else. It never opens a
connection, never needs a token, prints no address, and exits 0 whether or not
this machine has a Plex server at all. See :mod:`plex_axi.commands.context`.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

MARKER = "plex-axi"
BINARY_NAMES = ("plex-axi",)

#: The subcommand a session hook runs. Not the bare executable: see the module
#: docstring for why the no-argument home view cannot be what a hook prints.
CONTEXT_COMMAND = "context"

DEFAULT_TIMEOUT_SECONDS = 10
OPENCODE_MANAGED_PREFIX = "plex-axi managed opencode plugin:"


def write_atomic(path: Path, text: str) -> None:
    """Replace a file's contents in one step.

    These are the user's own global agent settings; a partial write during a
    crash would leave them with a truncated, unparseable file.
    """
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def portable_command(exec_path: str, path_entries: list | None = None) -> str:
    """Prefer a bare binary name when PATH resolves it to this same executable.

    A global install stays portable across machines; anything else falls back to
    the absolute path so the hook can never invoke a different binary.
    """
    try:
        resolved = Path(exec_path).resolve()
    except OSError:
        return exec_path
    if not resolved.is_file():
        return exec_path

    entries = path_entries
    if entries is None:
        entries = [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    for name in BINARY_NAMES:
        for directory in entries:
            candidate = Path(directory) / name
            try:
                if candidate.is_file() and candidate.resolve() == resolved:
                    return name
            except OSError:
                continue
    return exec_path


def current_executable() -> str:
    """The executable a hook should invoke to reach this installation."""
    argv0 = sys.argv[0] or ""
    which = shutil.which(BINARY_NAMES[0])
    exec_path = argv0
    if argv0 and Path(argv0).exists():
        exec_path = str(Path(argv0).resolve())
    elif which:
        exec_path = str(Path(which).resolve())
    return portable_command(exec_path)


def hook_command(executable: str) -> str:
    """The whole command line a JSON hook entry records.

    Quoted, which the sibling's is not and does not need to be: its command is a
    single token, so a path containing a space survives being written into a
    field the agent hands to a shell. This one carries an argument after the
    path, so an unquoted space would split the executable in two.
    """
    return f"{shlex.quote(executable)} {CONTEXT_COMMAND}"


# ------------------------------------------------------------- JSON settings


def _is_managed(hook) -> bool:
    return isinstance(hook, dict) and MARKER in str(hook.get("command", ""))


def compute_hook_update(settings: dict, command: str, timeout: int) -> tuple:
    """Return ``(settings, changed)`` with this tool's SessionStart hook current.

    Repeat installs with an unchanged path are silent no-ops; a changed path is
    repaired in place rather than duplicated.
    """
    updated = json.loads(json.dumps(settings)) if settings else {}
    changed = False

    hooks = updated.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        updated["hooks"] = hooks
        changed = True

    legacy = hooks.get("session_start")
    if isinstance(legacy, list):
        kept = [hook for hook in legacy if not _is_managed(hook)]
        if len(kept) != len(legacy):
            changed = True
            if kept:
                hooks["session_start"] = kept
            else:
                hooks.pop("session_start", None)

    groups = hooks.get("SessionStart")
    if not isinstance(groups, list):
        groups = []
        hooks["SessionStart"] = groups
        changed = True

    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            continue
        for hook in group["hooks"]:
            if not _is_managed(hook):
                continue
            correct = (
                hook.get("command") == command
                and hook.get("type") == "command"
                and hook.get("timeout") == timeout
            )
            if correct and not changed:
                return settings, False
            hook["command"] = command
            hook["type"] = "command"
            hook["timeout"] = timeout
            return updated, True

    groups.append(
        {"matcher": "", "hooks": [{"type": "command", "command": command, "timeout": timeout}]}
    )
    return updated, True


def compute_codex_config_update(content: str) -> tuple:
    """Ensure Codex has ``[features] hooks = true`` without disturbing the rest."""
    newline = "\r\n" if "\r\n" in content else "\n"
    if not content.strip():
        return f"[features]{newline}hooks = true{newline}", True

    lines = content.split("\n")
    lines = [line.rstrip("\r") for line in lines]
    in_features = False
    saw_features = False

    for index, line in enumerate(lines):
        section = re.match(r"^\s*(\[{1,2})([^\]]+)(\]{1,2})\s*(?:#.*)?$", line)
        if section:
            opener, name, closer = section.group(1), section.group(2).strip(), section.group(3)
            if len(opener) != len(closer):
                continue
            if in_features:
                lines.insert(index, "hooks = true")
                return newline.join(lines), True
            in_features = name == "features"
            saw_features = saw_features or in_features
            continue
        if not in_features:
            continue
        flag = re.match(r"^\s*hooks\s*=\s*(true|false)\s*(?:#.*)?$", line)
        if not flag:
            continue
        if flag.group(1) == "true":
            return content, False
        lines[index] = line.replace("false", "true", 1)
        return newline.join(lines), True

    if saw_features:
        suffix = "" if content.endswith(newline) else newline
        return f"{content}{suffix}hooks = true{newline}", True
    separator = newline if content.endswith(newline) else newline * 2
    return f"{content}{separator}[features]{newline}hooks = true{newline}", True


# ------------------------------------------------------------------ OpenCode


def opencode_plugin_source(executable: str, timeout: int) -> str:
    """The managed OpenCode plugin, which injects the same document as ambient system context.

    The executable and its argument are passed as separate values rather than as
    the joined command line the JSON hooks record: this spawns without a shell,
    so a joined string would be looked up as one filename.
    """
    header = f"{OPENCODE_MANAGED_PREFIX} {MARKER}"
    return f"""// {header}
// Generated by `plex-axi setup hooks`. Remove the managed marker above before editing.
import {{ spawn }} from "node:child_process";

const executable = {json.dumps(executable)};
const args = {json.dumps([CONTEXT_COMMAND])};
const marker = {json.dumps(MARKER)};
const ambientHeader = {json.dumps(f"## AXI ambient context: {MARKER}")};
const timeoutMs = {timeout * 1000};

function runContext(cwd) {{
  return new Promise((resolve) => {{
    const child = spawn(executable, args, {{
      cwd: cwd && cwd.length > 0 ? cwd : process.cwd(),
      env: process.env,
      shell: false,
      stdio: ["ignore", "pipe", "pipe"],
    }});
    let stdout = "";
    let stderr = "";
    let settled = false;
    const timer = setTimeout(() => {{
      if (settled) return;
      settled = true;
      child.kill("SIGTERM");
      resolve("error: " + marker + " ambient context timed out after " + timeoutMs + "ms");
    }}, timeoutMs);
    child.stdout?.setEncoding("utf-8");
    child.stderr?.setEncoding("utf-8");
    child.stdout?.on("data", (chunk) => {{ stdout += chunk; }});
    child.stderr?.on("data", (chunk) => {{ stderr += chunk; }});
    child.on("error", (error) => {{
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve("error: " + marker + " ambient context failed: " + error.message);
    }});
    child.on("close", (code) => {{
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (code === 0) {{ resolve(stdout.trim()); return; }}
      resolve((stderr || stdout || marker + " exited with code " + code).trim());
    }});
  }});
}}

export const PlexAxiAmbientContextPlugin = async ({{ directory }}) => {{
  const sessionCache = new Map();
  return {{
    "experimental.chat.system.transform": async (input, output) => {{
      const sessionID = input.sessionID ?? "__global__";
      let context = sessionCache.get(sessionID);
      if (context === undefined) {{
        context = await runContext(directory);
        sessionCache.set(sessionID, context);
      }}
      if (context.length === 0) return;
      output.system.push(ambientHeader + "\\n" + context);
    }},
  }};
}};
"""


# ------------------------------------------------------------------- install


def install(
    home: Path | None = None,
    *,
    command: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """Install or repair every session integration. Returns a per-target report.

    ``command`` names the *executable*; the argument that makes it print the
    ambient context is this module's to add, so a caller cannot install a hook
    that runs the connecting home view by mistake.
    """
    home = Path(home) if home else Path.home()
    executable = command or current_executable()
    line = hook_command(executable)
    report: dict = {"command": line, "targets": [], "errors": []}

    for label, path in (
        ("claude-code", home / ".claude" / "settings.json"),
        ("codex", home / ".codex" / "hooks.json"),
    ):
        report["targets"].append(_install_json_hook(label, path, line, timeout, report))

    report["targets"].append(_install_codex_features(home / ".codex" / "config.toml", report))
    report["targets"].append(
        _install_opencode(
            home / ".config" / "opencode" / "plugins" / f"axi-{MARKER}.js",
            executable,
            timeout,
            report,
        )
    )
    return report


def _install_json_hook(label: str, path: Path, command: str, timeout: int, report: dict) -> dict:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(current, dict):
            current = {}
        updated, changed = compute_hook_update(current, command, timeout)
        if changed:
            write_atomic(path, json.dumps(updated, indent=2) + "\n")
        return {"target": label, "status": "installed" if changed else "current"}
    except (OSError, json.JSONDecodeError) as exc:
        report["errors"].append(f"{path}: {exc}")
        return {"target": label, "status": "failed"}


def _install_codex_features(path: Path, report: dict) -> dict:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        updated, changed = compute_codex_config_update(current)
        if changed:
            write_atomic(path, updated)
        return {"target": "codex-features", "status": "installed" if changed else "current"}
    except OSError as exc:
        report["errors"].append(f"{path}: {exc}")
        return {"target": "codex-features", "status": "failed"}


def _install_opencode(path: Path, executable: str, timeout: int, report: dict) -> dict:
    managed = f"{OPENCODE_MANAGED_PREFIX} {MARKER}"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current is not None and managed not in current:
            report["errors"].append(f"{path}: refusing to overwrite an unmanaged plugin")
            return {"target": "opencode", "status": "skipped"}
        source = opencode_plugin_source(executable, timeout)
        if current == source:
            return {"target": "opencode", "status": "current"}
        write_atomic(path, source)
        return {"target": "opencode", "status": "installed"}
    except OSError as exc:
        report["errors"].append(f"{path}: {exc}")
        return {"target": "opencode", "status": "failed"}
