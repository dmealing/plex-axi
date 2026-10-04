"""R8: every byte the suite captured, scanned again once the suite has run.

Each invocation was already checked as it ran. This is the second look, over the
whole capture directory at once, with the repository's own leak scanner as well
as the harness's: the credential rules it applies to tracked files are applied
to what the tool printed against a real server.

Only the credential rules. The scanner's other rules -- media paths, private
addresses -- describe things a *repository* must not hold, and the tool prints
some of them on purpose: `track --check-files` prints the file's path because
that is what was asked. The captured output is never committed; what must not be
in it is a credential.

Named so that it sorts last.
"""

from __future__ import annotations

import sys

from .harness import ROOT

CREDENTIAL_RULES = ("plex-token", "jwt", "bearer")


def test_no_captured_output_holds_a_credential(live):
    sys.path.insert(0, str(ROOT / "scripts"))
    import leakcheck

    files = sorted(live.capture.glob("*.txt"))
    assert files, "nothing was captured; run the whole suite, not this module alone"
    found = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for leak in live.leaks(text):
            if leak != "HOST":
                found.append((path.name, leak))
        for finding in leakcheck.scan_text(path.name, text, markers=False):
            if finding.rule.name in CREDENTIAL_RULES:
                found.append((path.name, finding.rule.name))
    assert found == [], found[:20]
    print(f"scanned {len(files)} captured invocations: no credential on either stream")
