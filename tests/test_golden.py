"""Golden output: every help, error and refusal text, byte for byte.

The text an agent reads when something is wrong is this tool's interface in the
moment that matters, and it is the text least covered by assertions: a test
that checks for a code and a keyword passes whatever the sentence around them
turned into. A byte comparison of 324 invocations was done once by hand, when
the shared package was adopted, and then thrown away. This is that comparison,
kept.

One file per invocation under ``tests/golden/``. A change to any of these texts
shows up in review as a diff of the text itself, which is the point: wording is
reviewed as wording.

To accept a deliberate change::

    PLEX_AXI_UPDATE_GOLDEN=1 .venv/bin/pytest tests/test_golden.py

and commit the files it rewrote. Nothing here is a success path with rows in
it: those depend on the fixture library and are asserted where they belong.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import pytest

from conftest import TOKEN
from plex_axi import cli, playback, writes
from support import ERRORS

GOLDEN = Path(__file__).resolve().parent / "golden"
UPDATE = bool(os.environ.get("PLEX_AXI_UPDATE_GOLDEN"))

CONFIGURED = {"PLEX_URL": "http://plex.example.com:32400", "PLEX_TOKEN": TOKEN}
WRITABLE = {**CONFIGURED, writes.ALLOW_VAR: writes.ALLOW_VALUE}
PLAYING = {**CONFIGURED, playback.ALLOW_VAR: playback.ALLOW_VALUE}

#: The environments a case runs in, by the name its file carries.
ENVIRONMENTS = {
    "default": CONFIGURED,
    "writable": WRITABLE,
    "playing": PLAYING,
    "unconfigured": {},
    "url-only": {"PLEX_URL": "http://plex.example.com:32400"},
    "bad-url": {"PLEX_URL": "ftp://plex.example.com", "PLEX_TOKEN": CONFIGURED["PLEX_TOKEN"]},
    "bad-token": {"PLEX_URL": CONFIGURED["PLEX_URL"], "PLEX_TOKEN": "two words"},
    "writes-misset": {**CONFIGURED, writes.ALLOW_VAR: "yes"},
    "playback-misset": {**CONFIGURED, playback.ALLOW_VAR: "yes"},
}


def _cases() -> list:
    cases = [("default", ("--help",))]
    cases += [("default", (name, "--help")) for name in cli.command_order()]
    cases += [("playing", ("--help",))]
    cases += [("playing", (name, "--help")) for name in playback.COMMANDS]
    cases += [("default", argv) for argv, _code in ERRORS if "--json" not in argv]
    cases += [
        # The gates, closed and mis-set, with and without the confirming flag.
        ("default", ("rate", "111", "--stars", "4", "--write")),
        ("default", ("playlist", "create", "Fresh Example", "--key", "111", "--write")),
        ("default", ("playlist", "remove", "501", "--key", "111")),
        ("writes-misset", ("rate", "111", "--stars", "4")),
        ("playback-misset", ("play", "111")),
        ("playback-misset", ("clients",)),
        ("default", ("clients",)),
        ("default", ("pause",)),
        ("playing", ("pause",)),
        ("playing", ("play", "900")),
        ("playing", ("play", "111", "--client", "Nobody")),
        # Refusals that need the gate open to be reached.
        ("writable", ("rate", "900", "--stars", "4")),
        ("writable", ("playlist", "add", "502", "--key", "111")),
        ("writable", ("playlist", "add", "501", "--key", "110")),
        ("writable", ("playlist", "add", "501", "--key", "900", "--write")),
        ("writable", ("playlist", "create", "Example Playlist", "--key", "111", "--key", "122")),
        ("writable", ("playlist", "add", "No Such Playlist", "--key", "111")),
        # Configuration.
        ("unconfigured", ("search", "--artist", "x")),
        ("unconfigured", ("doctor",)),
        ("url-only", ("search", "--artist", "x")),
        ("bad-url", ("search", "--artist", "x")),
        ("bad-token", ("search", "--artist", "x")),
        # Identifiers.
        ("default", ("track", "plex://" + "ab" * 20 + "/111")),
        ("default", ("track", "\uff11\uff11\uff11")),
    ]
    return cases


def _slug(environment: str, argv: tuple) -> str:
    """A readable file name, and a digest of the exact arguments to keep it unique.

    `search help` and `search --help` are different invocations and read the
    same once punctuation is dropped, so the name alone cannot tell them apart.
    """
    words = "-".join(argv) or "home"
    words = re.sub(r"[^A-Za-z0-9]+", "-", words.encode("ascii", "replace").decode()).strip("-")
    digest = hashlib.sha256("\0".join(argv).encode()).hexdigest()[:8]
    return f"{environment}--{words[:60]}--{digest}"


CASES = _cases()


def _render(environment: str, argv: tuple, cli_run) -> str:
    result = cli_run(*argv, env=ENVIRONMENTS[environment])
    assert result.err == "", result.err
    command = " ".join(
        ["plex-axi", *(repr(word) if " " in word or not word else word for word in argv)]
    )
    return f"$ {command}\nenvironment: {environment}\nexit: {result.code}\n\n{result.out}"


@pytest.mark.parametrize(
    ("environment", "argv"), CASES, ids=[_slug(env, argv) for env, argv in CASES]
)
def test_the_text_is_the_text_that_was_reviewed(server, cli_run, environment, argv):
    path = GOLDEN / f"{_slug(environment, argv)}.txt"
    rendered = _render(environment, argv, cli_run)
    if UPDATE:
        path.write_text(rendered, encoding="utf-8")
        return
    assert path.exists(), f"no golden file; run with PLEX_AXI_UPDATE_GOLDEN=1 to record {path.name}"
    assert rendered == path.read_text(encoding="utf-8")


def test_every_golden_file_belongs_to_a_case():
    """A file whose case was removed pins nothing, and reads as coverage."""
    expected = {f"{_slug(env, argv)}.txt" for env, argv in CASES}
    assert len(expected) == len(CASES), "two cases share one file name"
    if UPDATE:
        for stale in {path.name for path in GOLDEN.glob("*.txt")} - expected:
            (GOLDEN / stale).unlink()
        return
    assert {path.name for path in GOLDEN.glob("*.txt")} == expected


def test_no_golden_text_is_an_internal_error():
    for path in sorted(GOLDEN.glob("*.txt")):
        assert "INTERNAL_ERROR" not in path.read_text(encoding="utf-8"), path.name
