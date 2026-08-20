"""The identifier boundary: which `plex://` string may be printed, and which never.

Two of the five `plex://` forms in circulation break a consumer, and one of them
raises inside it rather than failing a lookup. This is where that is prevented,
so these tests assert on the strings the tool emits as much as on the ones it
refuses.
"""

from __future__ import annotations

import re

import pytest

from conftest import MACHINE_ID
from plex_axi.errors import UsageError
from plex_axi.ids import media_content_id, validate_rating_key

#: The form that must never leave this tool: a rating key wearing the guid
#: namespace. A consumer parses the namespace as a server name, looks for a
#: server called "track", and fails -- and the sibling form, a real 24-hex guid
#: in the same position, raises rather than failing. A guid is all-hex and 24
#: characters; a rating key is a short run of digits, which is what this matches.
_FORBIDDEN = re.compile(r"plex://(artist|album|track)/\d{1,12}(?![0-9a-f])")


def test_the_content_id_names_the_server_as_well_as_the_item():
    """M5: the canonical form, not the one a consumer calls legacy."""
    assert media_content_id(MACHINE_ID, 311) == f"plex://{MACHINE_ID}/311"


def test_a_content_id_is_never_built_from_a_guid():
    """The `plex://track/<hex>` form raises inside a consumer rather than failing."""
    with pytest.raises(ValueError):
        media_content_id(MACHINE_ID, "0000000000000000000000a1")


def test_a_content_id_needs_the_machine_identifier():
    with pytest.raises(ValueError):
        media_content_id("", 311)


@pytest.mark.parametrize(
    "value",
    [
        "plex://track/a1b2c3d4e5f60718293a0100",
        "plex://0f0f0f0f/311",
        "plex://311",
        "not-a-key",
        "",
        "12a",
    ],
)
def test_only_a_decimal_rating_key_is_accepted(value):
    with pytest.raises(UsageError):
        validate_rating_key(value, invocation="plex-axi track")


def test_a_guid_is_rejected_by_name_rather_than_crashing():
    """§ the collision is real: a guid is a legitimate Plex identifier."""
    with pytest.raises(UsageError) as caught:
        validate_rating_key("plex://track/a1b2c3d4e5f60718293a0100", invocation="plex-axi track")
    assert caught.value.code == "GUID_NOT_RATING_KEY"
    assert "guid" in caught.value.message


def test_a_media_id_is_rejected_with_the_field_that_carries_the_number():
    with pytest.raises(UsageError) as caught:
        validate_rating_key("plex://abc/311", invocation="plex-axi track")
    assert caught.value.code == "MEDIA_ID_NOT_RATING_KEY"


def test_the_search_output_labels_the_id_and_carries_the_guid(server, cli_run):
    """M5/M6: three labelled fields, and the note that the key can move."""
    result = cli_run("search", "--track", "Guest Track")
    assert result.code == 0
    assert result.line("media_id:").endswith(f'"plex://{MACHINE_ID}/311"')
    assert result.line("rating_key:") == "rating_key: 311"
    guid = result.line("guid:").split(": ", 1)[1].strip('"')
    assert re.fullmatch(r"plex://track/[0-9a-f]{24}", guid)
    assert "changes when an item is re-matched" in result


def test_no_command_ever_emits_a_rating_key_in_the_guid_namespace(server, cli_run, writable_env):
    """M5: the form that resolves to a server called "track" and fails there.

    Swept over every command that names an item, including the two that write:
    a mutation response identifies what it changed, and that is exactly where an
    identifier gets copied into a configuration file.
    """
    for argv in (
        ("search", "--track", "Guest Track"),
        ("pick",),
        ("track", "311"),
        ("album", "310"),
        ("artist", "300"),
        ("similar", "111"),
        ("recent",),
        ("sessions",),
        ("playlist",),
        ("playlist", "show", "Example Playlist"),
        ("rate", "311", "--stars", "3"),
        ("rate", "311", "--stars", "3", "--write"),
        ("playlist", "add", "Example Playlist", "--key", "311"),
    ):
        result = cli_run(*argv, env=writable_env)
        assert result.code == 0, argv
        for line in result.out.splitlines():
            assert not _FORBIDDEN.search(line.strip().strip('"')), (argv, line)


def test_a_mutation_hands_back_the_same_four_labelled_fields(server, cli_run, writable_env):
    """A write is the response most likely to be pasted somewhere permanent.

    `rating_key` moves when an item is re-matched, so the `guid` and the note
    travel with it here for the same reason they do everywhere else.
    """
    result = cli_run("rate", "111", "--stars", "5", "--write", env=writable_env)
    assert result.code == 0
    assert list(_block(result.out, "item:")) == ["media_id", "rating_key", "guid", "note"]


def test_the_handoff_block_is_identifiers_and_nothing_else(server, cli_run):
    """plex-axi prints identifiers and stops.

    The block names no consumer and suggests no command to play the id with,
    because anything it could suggest would have to come from the caller in the
    first place -- and echoing that back tells them nothing they did not know.
    """
    result = cli_run("track", "111")
    assert result.code == 0
    block = _block(result.out, "item:")
    assert list(block) == ["media_id", "rating_key", "guid", "note"]


def _block(out: str, header: str) -> dict:
    """The indented `key: value` lines under one header, in order."""
    fields = {}
    inside = False
    for line in out.splitlines():
        if line.rstrip() == header:
            inside = True
            continue
        if inside:
            if not line.startswith("  "):
                break
            key, _, value = line.strip().partition(": ")
            fields[key] = value.strip('"')
    return fields
