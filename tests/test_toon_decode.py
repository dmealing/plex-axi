"""The default output, read back by a decoder this project did not write.

The encoder in `axi_toolkit.toon` is held to the specification's own conformance
fixtures in its own package. This checks it from the other end: the official TOON
decoder is handed every surface's default output and must produce exactly the
document `--json` prints. An encoder and its own tests can agree on a document no
other implementation can read; this is the test that cannot.

The `help[N]:` block is lifted out first -- it is the documented departure from
strict TOON -- and then compared as a list, so the block is held to the count
its own header declares.
"""

from __future__ import annotations

import json

import pytest

from support import ERRORS, READS, toon_doc

#: Every surface that prints TOON. An invocation naming `--json` itself has no
#: default output to decode.
CASES = [*READS, *(argv for argv, _code in ERRORS if "--json" not in argv)]


@pytest.mark.parametrize("argv", CASES, ids=lambda argv: " ".join(argv)[:60] or "home")
def test_default_output_decodes_to_the_json_document(server, cli_run, argv):
    default = cli_run(*argv)
    # `--json` leads, so a flag left without its value cannot swallow it.
    as_json = cli_run("--json", *argv)
    assert default.code == as_json.code
    assert toon_doc(default.out.rstrip("\n")) == json.loads(as_json.out)


def test_a_library_full_of_awkward_text_still_decodes(server, cli_run):
    """Commas, quotes, a newline, a colon, leading space: every one is a TOON edge."""
    tables = server.tables
    tables.add("artist", 700, 'Colon: "Quoted", and a comma')
    tables.add("album", 710, " leading space and trailing ", artist=700)
    tables.add("track", 711, "line one\nline two\ttab", album=710)
    tables.add("track", 712, "true", album=710)
    tables.add("track", 713, "007", album=710)
    tables.add("track", 714, "- dash [3]: {a,b}", album=710)
    for argv in (
        ("search", "--artist", "Colon", "--no-group", "--fields", "key,title,artist,album"),
        ("artist", "700"),
        ("album", "710"),
        ("track", "711"),
        ("recent", "--type", "track", "--limit", "20"),
    ):
        default, as_json = cli_run(*argv), cli_run("--json", *argv)
        assert toon_doc(default.out.rstrip("\n")) == json.loads(as_json.out), argv


def test_the_help_block_holds_exactly_the_lines_its_header_declares(server, cli_run):
    for argv in CASES:
        out = cli_run(*argv).out
        if "help[" not in out:
            continue
        declared = int(out.split("help[", 1)[1].split("]", 1)[0])
        assert len(toon_doc(out.rstrip("\n"))["help"]) == declared, argv
