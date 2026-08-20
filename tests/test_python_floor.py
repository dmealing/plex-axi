"""The declared Python floor and the tested Python floor must not drift apart.

`requires-python` is published metadata: it is what an index consults to refuse
an install, and it is the one claim in this project that no amount of passing
tests can verify, because the interpreter that would have failed is the one the
tests were never run on. The CI matrix is what actually proves it. When the two
disagree the claim is unbacked in exactly the direction that hurts — `>=3.9`
survived a `PlexAPI>=4.18` bump that had quietly raised the real floor to 3.10,
and the only thing that noticed was an install attempt on 3.9.

That is why this reads two files rather than trusting either. The failure is not
"these numbers differ"; it is "the package claims support it never installed".

Neither file is parsed with a library, deliberately. `tomllib` arrived in 3.11
and this project's floor is 3.10; PyYAML is not a dependency and adding one to
read four characters would be worse than the regex. Both values live on a single
line, and a shape this guard cannot read fails loudly rather than quietly
passing — see the assertions in the two readers below.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _version(text: str) -> tuple[int, int]:
    major, minor = text.split(".")
    return int(major), int(minor)


def _format(version: tuple[int, int]) -> str:
    return "{}.{}".format(*version)


def declared_floor() -> tuple[int, int]:
    """The lower bound of `requires-python` in `pyproject.toml`."""
    text = PYPROJECT.read_text(encoding="utf-8")
    found = re.search(r'^requires-python\s*=\s*"[^"]*>=\s*(\d+\.\d+)', text, re.MULTILINE)
    assert found, (
        f'No `requires-python = ">=X.Y"` line found in {PYPROJECT.name}. Either the '
        "floor was deleted -- put it back, an unbounded package installs on "
        "interpreters it was never built for -- or it was rewritten in a form this "
        "guard cannot read, in which case teach `declared_floor` the new shape."
    )
    return _version(found.group(1))


def matrix_versions() -> list[tuple[int, int]]:
    """Every interpreter the `test` job in `ci.yml` actually installs and runs on."""
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    found = re.search(r"^\s*python-version:\s*\[([^\]]*)\]\s*$", text, re.MULTILINE)
    assert found, (
        f"No inline `python-version: [...]` matrix list found in {CI_WORKFLOW.name}. If "
        "the matrix was rewritten as a YAML block list, teach `matrix_versions` that "
        "shape rather than deleting this guard: an unread matrix is how the floor "
        "drifts unnoticed."
    )
    versions = [_version(v) for v in re.findall(r'"(\d+\.\d+)"', found.group(1))]
    assert versions, f"The `python-version` matrix in {CI_WORKFLOW.name} is empty."
    return versions


def classifier_versions() -> list[tuple[int, int]]:
    """The `Programming Language :: Python :: X.Y` classifiers in `pyproject.toml`.

    The bare `:: 3` classifier carries no minor version and is not one of these.
    """
    text = PYPROJECT.read_text(encoding="utf-8")
    return [_version(v) for v in re.findall(r"Programming Language :: Python :: (\d+\.\d+)", text)]


def test_declared_floor_matches_the_lowest_tested_version():
    declared = declared_floor()
    lowest = min(matrix_versions())
    assert declared == lowest, (
        f'pyproject.toml declares `requires-python = ">={_format(declared)}"` but the '
        f"lowest interpreter in the ci.yml test matrix is {_format(lowest)}. One of the "
        "two is wrong, and the published one is the one that reaches users.\n"
        "\n"
        f"To raise the floor to {_format(lowest)}: set `requires-python` in "
        "pyproject.toml, drop the retired versions from the ci.yml matrix, and drop "
        "their `Programming Language :: Python :: X.Y` classifiers. Do all three.\n"
        "\n"
        f"To support {_format(declared)} again: add it back to the ci.yml matrix and "
        "its classifier, then let the matrix prove it installs. A dependency may "
        "already forbid it -- plexapi 4.18.0 requires >=3.10, which is what retired "
        "3.9 here -- and the install is the only thing that will tell you."
    )


def test_classifiers_state_exactly_the_tested_versions():
    classifiers = classifier_versions()
    tested = sorted(matrix_versions())
    assert sorted(classifiers) == tested, (
        f"pyproject.toml claims support for {[_format(v) for v in sorted(classifiers)]} "
        f"but ci.yml tests {[_format(v) for v in tested]}. Classifiers are the "
        "human-readable half of the same promise `requires-python` makes to an index; "
        "a version listed here and tested nowhere is a claim with nothing behind it, "
        "and a version tested here and listed nowhere hides work already being done.\n"
        "\n"
        "Add or remove `Programming Language :: Python :: X.Y` lines in pyproject.toml "
        "so the set matches the matrix exactly. Leave the bare "
        "`Programming Language :: Python :: 3` alone -- it carries no minor version "
        "and this guard does not count it."
    )
