"""The documented developer setup must not be able to break an installed copy.

This tool is normally installed as an isolated user-level tool. An editable
install into whatever interpreter is ambient replaces that installation: it
overwrites the console script in the user's own bin directory with a launcher
bound to the system interpreter, and leaves an editable pointer at the checkout.
Delete the checkout -- the ordinary end of a throwaway one -- and the reader's
own copy of the tool dies with `ModuleNotFoundError`, with nothing to say why.
The second symptom is worse because it is silent: a sibling tool went on working
while pinned two releases behind what was published.

`scripts/dev-setup.sh` is the entry point because a rule that exists only as a
sentence is one somebody eventually skips. This file is the same reasoning
applied to the sentence: the safe command is documented, so a document that
reintroduces the unsafe one fails here rather than at somebody's install.

**It reads what a reader would copy, which is not the same as what a file
says.** In Markdown that is a fenced code block and nothing else, because the
prose beside the block is where the warning lives and it has to be free to name
the thing it forbids -- a guard that made the explanation the offence would be
answered by deleting the explanation. Everywhere else every line counts, since a
shell script has no prose. The same distinction the leak scanner draws when it
refuses to let its own advice contain the shape it reports.

Two allowances, and both are structural rather than a list of files:

- A line naming `.venv/bin/` is the *safe* invocation, not the unsafe one. That
  is the form `ci.yml` has always used, so the workflows pass this guard as they
  stand and are held to it from now on.
- `scripts/dev-setup.sh` is exempt whole, being the one place the command
  belongs. `test_the_entry_point_allowance_is_still_earning_its_place` fails if
  it stops containing the shape, so the exemption cannot outlive its cause.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRY_POINT = "scripts/dev-setup.sh"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
VENV = ".venv"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import leakcheck  # noqa: E402  (the path insert above has to come first)

# Deliberately assembled so this file does not match itself. Writing the shape
# out would need an allowance for the guard, and an allowance nobody can see the
# point of is one somebody widens.
EDITABLE_INSTALL = re.compile(r"pip[\d.]*['\"]?\s+install\s+[^\n]*?(?:-e|--editable)(?![\w-])")

# The by-path form. A `pip` reached out of the checkout's own virtualenv cannot
# touch the user site, which is the whole of what this guard is about.
BY_PATH = VENV + "/bin/"

FENCE = re.compile(r"^\s*```")


def tracked_text_files():
    """Every tracked file this guard can read, as (repo-relative name, text)."""
    names = leakcheck.tracked_files(REPO_ROOT)
    assert names, (
        "`git ls-files` returned nothing, so this guard has no idea what the "
        "repository contains. It fails rather than reporting a clean it cannot "
        "support -- the same rule the leak scanner follows when it cannot reach a "
        "pull request."
    )
    for name in names:
        path = REPO_ROOT / name
        if not path.is_file() or not leakcheck._readable(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        yield name, text


def copyable_lines(name, text):
    """The lines of ``name`` a reader could plausibly copy and run.

    Markdown contributes its fenced code blocks only. Everything else
    contributes every line.
    """
    markdown = name.lower().endswith(".md")
    inside = not markdown
    for number, line in enumerate(text.splitlines(), 1):
        if markdown and FENCE.match(line):
            inside = not inside
            continue
        if inside:
            yield number, line


def unsafe_installs(name, text):
    for number, line in copyable_lines(name, text):
        match = EDITABLE_INSTALL.search(line)
        if match and BY_PATH not in line:
            yield number, match.group(0)


def test_no_document_offers_an_editable_install_into_the_ambient_interpreter():
    found = [
        (name, number, match)
        for name, text in tracked_text_files()
        if name != ENTRY_POINT
        for number, match in unsafe_installs(name, text)
    ]
    assert not found, (
        "A copyable command installs this package into whatever interpreter is "
        "ambient:\n"
        + "\n".join(f"  {name}:{number}: {match!r}" for name, number, match in found)
        + "\n\n"
        f"That replaces the reader's own installation of this tool and breaks it when "
        f"the checkout goes away. Document `{ENTRY_POINT}` instead -- it builds "
        f"`{VENV}` and installs into that -- or, where the command has to be spelled "
        f"out, call pip out of `{BY_PATH}` the way ci.yml does. Prose is free to name "
        "the unsafe command in order to warn about it; only fenced blocks and shell "
        "scripts are read here."
    )


def test_the_entry_point_allowance_is_still_earning_its_place():
    path = REPO_ROOT / ENTRY_POINT
    assert path.is_file(), (
        f"{ENTRY_POINT} is gone. It is the documented setup path, named in the README "
        "and in AGENTS.md; deleting it leaves both pointing at nothing and invites the "
        "unsafe command back."
    )
    text = path.read_text(encoding="utf-8")
    assert EDITABLE_INSTALL.search(text), (
        f"{ENTRY_POINT} is exempt from this guard because it is the one place the "
        "editable install belongs, and it no longer performs one. Either it stopped "
        "being the entry point -- in which case drop the exemption -- or the install "
        "was lost, in which case the documented setup installs nothing."
    )


def test_the_entry_point_is_executable():
    path = REPO_ROOT / ENTRY_POINT
    assert os.access(path, os.X_OK), (
        f"{ENTRY_POINT} is not executable, so the documented `{ENTRY_POINT}` fails "
        "with a permission error on a fresh clone. `chmod +x` it and commit the mode."
    )


def test_the_entry_point_and_ci_build_the_same_virtualenv():
    """One pattern in this repository, not two.

    The workflows were right about this before the documents were, so the script
    matches them rather than the other way round. If the two ever name different
    directories, a contributor's `.venv` is not the one CI proves.

    The workflow is parsed into what GitHub will actually run, not matched as
    text: the comment above the `lint` job discusses the same directory, and
    prose is not a step.
    """
    script = (REPO_ROOT / ENTRY_POINT).read_text(encoding="utf-8")
    declared = re.search(r"^venv=(\S+)$", script, re.MULTILINE)
    assert declared, (
        f"No `venv=<dir>` assignment found in {ENTRY_POINT}. This guard holds that "
        "directory and ci.yml's to one value; teach it the new shape rather than "
        "deleting it."
    )

    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    in_ci = set()
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            run = step.get("run") or ""
            in_ci.update(re.findall(r"python -m venv (?:--clear )?(\S+)", run))
    assert in_ci, (
        f"No `python -m venv <dir>` step found in {CI_WORKFLOW.name}. If the jobs "
        "stopped building a virtualenv, read the comment above the `lint` job before "
        "assuming that is safe."
    )

    assert in_ci == {declared.group(1)} == {VENV}, (
        f"{ENTRY_POINT} builds {declared.group(1)!r} and ci.yml builds "
        f"{sorted(in_ci)!r}. A contributor's virtualenv should be the one CI proves, "
        "and every by-path invocation in the documents is written against "
        f"{VENV!r}. Move all three together or not at all."
    )


def test_both_documents_point_at_the_entry_point():
    for name in ("README.md", "AGENTS.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert ENTRY_POINT in text, (
            f"{name} does not mention {ENTRY_POINT}. It is the documented setup path "
            "for exactly two audiences -- a contributor reads the README, an agent "
            "reads AGENTS.md -- and one of them is now being told to work it out."
        )
