"""The generated skill: derived from the command table, never hand-edited."""

from __future__ import annotations

from pathlib import Path

from plex_axi import cli, skill

REPO_ROOT = Path(__file__).resolve().parents[1]


def _rendered() -> str:
    specs = cli.command_specs()
    return skill.render([specs[noun] for noun in cli.COMMAND_ORDER])


def test_the_committed_skill_matches_the_command_table():
    """CI runs `plex-axi skill --check`; this is the same assertion, offline."""
    committed = skill.target_path(REPO_ROOT).read_text(encoding="utf-8")
    assert committed == _rendered()


def test_every_command_appears_in_the_skill():
    content = _rendered()
    for noun in cli.COMMAND_ORDER:
        assert f"### `plex-axi {noun}`" in content


def test_the_skill_carries_no_live_state(tmp_path):
    """A skill is static, so anything about one library would be wrong elsewhere.

    Checked with the repository's own leak scanner rather than by listing
    strings: the scanner already knows every shape that identifies a server, a
    network or a collection, and a hand-written list would go stale.
    """
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import leakcheck

    (tmp_path / "SKILL.md").write_text(_rendered(), encoding="utf-8")
    assert leakcheck.scan_paths(["SKILL.md"], root=tmp_path) == []


def test_the_skill_states_what_the_tool_will_not_do():
    content = _rendered()
    assert "never plays anything" in content
    assert "music only" in content
    assert "read-only" in content


def test_the_check_flag_fails_on_a_stale_copy(tmp_path, cli_run):
    stale = tmp_path / "skills" / "plex-axi"
    stale.mkdir(parents=True)
    (stale / "SKILL.md").write_text("out of date\n", encoding="utf-8")
    result = cli_run("skill", "--check", "--root", str(tmp_path), env={})
    assert result.code == 1
    assert "SKILL_STALE" in result


def test_writing_the_skill_needs_no_server_and_no_token(tmp_path, cli_run):
    result = cli_run("skill", "--root", str(tmp_path), env={})
    assert result.code == 0
    assert (tmp_path / "skills" / "plex-axi" / "SKILL.md").exists()
    assert cli_run("skill", "--check", "--root", str(tmp_path), env={}).code == 0
