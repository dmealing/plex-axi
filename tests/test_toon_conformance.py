"""The official TOON conformance fixtures, run against the encoder this tool prints through.

The encoder is `axi_toolkit.toon` and there is no second copy here. This
project used to carry its own, byte-identical with the shared package's and
with the sibling AXI CLI's, and one anchor defect lived in all three because
nothing compared them. So the encoder's behaviour is stated once, in the shared
package's own suite, and the specification's fixtures are vendored once, beside
the encoder they judge (MIT; `axi_toolkit.toon_spec` carries the provenance,
the checksums and the refresh recipe).

What is left here is the claim this repository makes and therefore has to
check: that the encoder it *resolved at install time* scores every published
case. A dependency floor says which releases are allowed, not which one is in
the environment, so the README's strict-encoder claim is asserted against the
installed package rather than inherited from it.

The count is asserted too: a fixture that stopped being collected would
otherwise shrink the score in silence, which is exactly how a partial score
ships.
"""

from __future__ import annotations

import importlib.util

import axi_toolkit.toon
import pytest
from axi_toolkit import toon_spec

from plex_axi import output

#: The encoder every command prints through, read off the output boundary
#: rather than imported beside it, so the suite judges what the tool uses.
encode = output.encode

#: Total encode cases published by the vendored spec version. Enforcing the
#: number is what makes the score a test result instead of a claim in a report.
CASE_COUNT = 179


def test_the_output_boundary_encodes_with_the_shared_encoder():
    assert output.encode is axi_toolkit.toon.encode


def test_this_package_carries_no_encoder_of_its_own():
    """A second copy is the drift this arrangement ends; it must not come back."""
    assert importlib.util.find_spec("plex_axi.toon") is None


def test_the_score_is_every_published_case():
    report = toon_spec.run(encode)
    assert report.failures == [], "\n".join(
        f"{toon_spec.case_id(failure.case)}: expected {failure.case.expected!r},"
        f" got {failure.got!r}"
        for failure in report.failures[:5]
    )
    assert report.score == f"{CASE_COUNT}/{CASE_COUNT}"


@pytest.mark.parametrize("case", toon_spec.cases(), ids=toon_spec.case_id)
def test_encode_matches_the_specification_fixture(case):
    """One test per case, so a failure names the case rather than the suite."""
    detail = f"{case.name} (spec section {case.spec_section or '?'})"
    assert encode(case.input, **toon_spec.encoder_kwargs(case)) == case.expected, detail


def test_the_whole_published_suite_runs():
    """A fixture that stops being collected must fail, not quietly shrink the score."""
    assert len(toon_spec.cases()) == CASE_COUNT


def test_every_vendored_fixture_matches_its_recorded_checksum():
    """A fixture edited to suit the encoder is no longer the specification's opinion."""
    assert toon_spec.digest_mismatches() == []


def test_every_fixture_file_is_an_encode_fixture():
    """Decode fixtures are not vendored; one arriving there would silently not run."""
    assert set(toon_spec.categories()) <= toon_spec.RUNNABLE_CATEGORIES


def test_the_star_and_distance_values_commands_do_emit_are_unchanged():
    """The values this tool's own rows carry, through the encoder it now borrows.

    `filters.stars` yields half-star steps and `similar` rounds a sonic distance
    to four places. Neither lands in a band where the canonical decimal form
    differs from Python's float repr, so this is the one encoder case that is
    about this tool's output rather than about the encoder.
    """
    doc = {"tracks": [{"distance": 0.0001, "rating": 4.5}, {"distance": 0.0, "rating": None}]}
    assert encode(doc) == "tracks[2]{distance,rating}:\n  0.0001,4.5\n  0,null"


def test_a_key_ending_in_a_newline_is_quoted():
    """The defect the dependency floor exists for, asserted on the installed encoder."""
    assert encode({"name\n": 1}) == '"name\\n": 1'
    assert encode({"a": "1\n"}) == 'a: "1\\n"'
