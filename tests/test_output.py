"""The output boundary: TOON on stdout, and nothing that leaks through it."""

from __future__ import annotations

import io

from plex_axi import output
from plex_axi.output import MODE_HUMAN, MODE_JSON, MODE_TOON, HelpBlock


def test_a_document_renders_as_toon_by_default():
    doc = {"count": "1 of 1 total", "tracks": [{"key": 1, "title": "Example Track"}]}
    assert output.render(doc, MODE_TOON) == (
        "count: 1 of 1 total\ntracks[1]{key,title}:\n  1,Example Track"
    )


def test_a_help_block_renders_one_suggestion_per_line():
    """The one deliberate departure from strict TOON: suggestions are command
    lines, and command lines are full of commas."""
    doc = {"help": HelpBlock(["Run `plex-axi genres`", "Run `plex-axi track <key>`"])}
    assert output.render(doc, MODE_TOON) == (
        "help[2]:\n  Run `plex-axi genres`\n  Run `plex-axi track <key>`"
    )


def test_an_empty_help_block_prints_nothing():
    assert output.render({"help": HelpBlock([])}, MODE_TOON) == ""


def test_json_mode_flattens_the_help_block():
    doc = {"help": HelpBlock(["a"])}
    assert output.render(doc, MODE_JSON) == '{\n  "help": [\n    "a"\n  ]\n}'


def test_human_mode_renders_a_table():
    doc = {"tracks": [{"key": 1, "title": "Example Track"}]}
    rendered = output.render(doc, MODE_HUMAN)
    assert "key" in rendered and "Example Track" in rendered


def test_null_and_empty_are_different_answers():
    """ "The server did not say" and "the value is empty" are not the same."""
    doc = {"rows": [{"a": None, "b": ""}]}
    assert output.render(doc, MODE_TOON) == 'rows[1]{a,b}:\n  null,""'


def test_write_passes_everything_through_the_redactor():
    output.register_secret("supersecretvalue")
    stream = io.StringIO()
    output.write({"note": "supersecretvalue"}, MODE_TOON, stream=stream)
    assert "supersecretvalue" not in stream.getvalue()
    assert "<redacted>" in stream.getvalue()


def test_debug_output_is_redacted_too():
    """stderr is not a safe channel just because agents ignore it."""
    output.register_secret("supersecretvalue")
    output.set_debug(True)
    import sys

    captured = io.StringIO()
    original, sys.stderr = sys.stderr, captured
    try:
        output.debug("token supersecretvalue")
    finally:
        sys.stderr = original
    assert "supersecretvalue" not in captured.getvalue()


def test_truncation_reports_what_was_withheld():
    text, hint = output.truncate("x" * 100, 10, "Run with --full")
    assert text.startswith("x" * 10)
    assert "100 chars total" in text
    assert hint == "Run with --full"

    whole, no_hint = output.truncate("short", 10, "Run with --full")
    assert whole == "short" and no_hint == ""


def test_a_short_string_is_never_registered_as_a_secret():
    """Redacting a short literal would corrupt unrelated output."""
    output.reset_secrets()
    output.register_secret("abc")
    assert output.redact("abc def") == "abc def"
