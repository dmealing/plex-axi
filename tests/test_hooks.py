"""The session integration: what it installs, and what the thing it installs may do.

Two halves, and the second is the one that is this project's rather than the
sibling's.

**Installation** is the sibling AXI CLI's contract, and is asserted the same way:
every default target gets a hook, a repeat install is a silent no-op, a moved
executable is repaired rather than duplicated, another tool's hooks survive
untouched, and an OpenCode plugin this tool did not write is never overwritten.

**The document the hook prints** is the half that had to be designed here. A
SessionStart hook runs on every session, on every machine that has the package,
before anybody has decided to use the tool -- so the sibling's answer, which is
to run its no-argument view, is not available: this tool's home view needs a
token, opens a connection and prints the server's address. So the hook runs
`plex-axi context`, and the claims that make that safe are asserted here rather
than described in a docstring:

- it reaches the server **zero times**, asserted on ``server.requests`` rather
  than on an exit code, for the same reason ``tests/test_writes.py`` does;
- it exits 0 and reports no error with **no environment at all**;
- it prints neither the base URL nor the token, on stdout or stderr, when both
  are set;
- and the command the installer actually records is the one all of that is true
  of, which is the join between the two halves and the test worth having.
"""

from __future__ import annotations

import json
import shlex

import pytest

from conftest import TOKEN
from plex_axi import cli, hooks, playback, writes

EXECUTABLE = "plex-axi"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def commands_in(settings) -> list:
    return [
        hook["command"] for group in settings["hooks"]["SessionStart"] for hook in group["hooks"]
    ]


# ------------------------------------------------------------- installation


def test_install_creates_hooks_for_every_default_target(tmp_path):
    """AXI 7: Claude Code, Codex and OpenCode by default, not one favoured agent."""
    report = hooks.install(tmp_path, command=EXECUTABLE)
    assert report["errors"] == []
    assert {target["target"] for target in report["targets"]} == {
        "claude-code",
        "codex",
        "codex-features",
        "opencode",
    }
    assert all(target["status"] == "installed" for target in report["targets"])

    claude = read(tmp_path / ".claude" / "settings.json")
    assert claude["hooks"]["SessionStart"][0]["hooks"][0] == {
        "type": "command",
        "command": "plex-axi context",
        "timeout": hooks.DEFAULT_TIMEOUT_SECONDS,
    }
    assert (tmp_path / ".codex" / "hooks.json").exists()
    assert "hooks = true" in (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert (tmp_path / ".config" / "opencode" / "plugins" / "axi-plex-axi.js").exists()


def test_the_installed_hook_runs_the_context_command_not_the_home_view(tmp_path):
    """The divergence from the sibling, asserted rather than commented.

    The no-argument view is live state: it needs a token, opens a connection and
    prints the server's address. A hook that ran it would fail on every machine
    that has the package and no server, and would put an address into an agent's
    context on every machine that has one.
    """
    report = hooks.install(tmp_path, command=EXECUTABLE)
    assert report["command"] == f"{EXECUTABLE} {hooks.CONTEXT_COMMAND}"
    assert report["command"] != EXECUTABLE, "a bare executable would run the home view"


def test_repeat_installs_with_the_same_path_are_no_ops(tmp_path):
    hooks.install(tmp_path, command=EXECUTABLE)
    second = hooks.install(tmp_path, command=EXECUTABLE)
    assert all(target["status"] == "current" for target in second["targets"])


def test_a_changed_executable_path_is_repaired_not_duplicated(tmp_path):
    hooks.install(tmp_path, command="/old/bin/plex-axi")
    hooks.install(tmp_path, command="/new/bin/plex-axi")
    settings = read(tmp_path / ".claude" / "settings.json")
    assert commands_in(settings) == ["/new/bin/plex-axi context"]


def test_other_tools_hooks_and_unrelated_settings_are_left_alone(tmp_path):
    """These are the user's own global settings; this tool owns one entry in them."""
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"matcher": "", "hooks": [{"type": "command", "command": "other-tool"}]}
                    ]
                },
                "unrelated": True,
            }
        ),
        encoding="utf-8",
    )
    hooks.install(tmp_path, command=EXECUTABLE)
    data = read(settings)
    assert "other-tool" in commands_in(data)
    assert "plex-axi context" in commands_in(data)
    assert data["unrelated"] is True


def test_a_legacy_lowercase_hook_entry_is_cleaned_up(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"hooks": {"session_start": [{"type": "command", "command": "plex-axi"}]}}),
        encoding="utf-8",
    )
    hooks.install(tmp_path, command=EXECUTABLE)
    data = read(settings)
    assert "session_start" not in data["hooks"]
    assert commands_in(data) == ["plex-axi context"]


def test_an_unmanaged_opencode_plugin_is_never_overwritten(tmp_path):
    plugin = tmp_path / ".config" / "opencode" / "plugins" / "axi-plex-axi.js"
    plugin.parent.mkdir(parents=True)
    plugin.write_text("// hand written\n", encoding="utf-8")
    report = hooks.install(tmp_path, command=EXECUTABLE)
    assert plugin.read_text(encoding="utf-8") == "// hand written\n"
    assert any("refusing to overwrite" in error for error in report["errors"])


def test_the_opencode_plugin_carries_a_managed_marker_and_the_context_argument(tmp_path):
    """It spawns without a shell, so the argument travels beside the path, not in it."""
    source = hooks.opencode_plugin_source(EXECUTABLE, hooks.DEFAULT_TIMEOUT_SECONDS)
    assert hooks.OPENCODE_MANAGED_PREFIX in source
    assert f'const executable = "{EXECUTABLE}"' in source
    assert f'const args = ["{hooks.CONTEXT_COMMAND}"]' in source


def test_a_path_with_a_space_survives_being_joined_with_the_argument():
    """The sibling's command is one token and needs no quoting; this one is not."""
    line = hooks.hook_command("/opt/an example/bin/plex-axi")
    assert shlex.split(line) == ["/opt/an example/bin/plex-axi", hooks.CONTEXT_COMMAND]


def test_codex_features_flag_is_added_without_disturbing_other_sections():
    updated, changed = hooks.compute_codex_config_update('[model]\nname = "example"\n')
    assert changed
    assert "[model]" in updated and 'name = "example"' in updated
    assert "[features]" in updated and "hooks = true" in updated


def test_codex_features_flag_already_true_is_a_no_op():
    content = "[features]\nhooks = true\n"
    assert hooks.compute_codex_config_update(content) == (content, False)


def test_codex_features_flag_set_to_false_is_flipped():
    updated, changed = hooks.compute_codex_config_update("[features]\nhooks = false\n")
    assert changed and "hooks = true" in updated


def test_codex_features_is_inserted_into_an_existing_features_table():
    updated, changed = hooks.compute_codex_config_update(
        "[features]\nother = 1\n\n[model]\nx = 2\n"
    )
    assert changed
    assert updated.index("hooks = true") < updated.index("[model]")


def test_portable_command_prefers_a_path_entry_resolving_to_this_executable(tmp_path):
    binary = tmp_path / "plex-axi"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    assert hooks.portable_command(str(binary), [str(tmp_path)]) == "plex-axi"


def test_portable_command_falls_back_to_the_absolute_path(tmp_path):
    """Never a bare name PATH does not resolve here: the hook would run a different binary."""
    binary = tmp_path / "plex-axi"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    assert hooks.portable_command(str(binary), []) == str(binary)


# ----------------------------------------------------------- `setup hooks`


def test_setup_hooks_succeeds_and_says_what_to_do_next(cli_run, tmp_path):
    result = cli_run("setup", "hooks", "--home", str(tmp_path))
    assert result.code == 0
    assert "claude-code,installed" in result
    assert "Restart your agent session" in result


def test_setup_hooks_reports_a_failure_with_a_non_zero_exit(cli_run, tmp_path):
    plugin = tmp_path / ".config" / "opencode" / "plugins" / "axi-plex-axi.js"
    plugin.parent.mkdir(parents=True)
    plugin.write_text("// hand written\n", encoding="utf-8")
    result = cli_run("setup", "hooks", "--home", str(tmp_path))
    assert result.code == 1
    assert "refusing to overwrite" in result


def test_setup_hooks_never_reaches_the_plex_server(server, cli_run, tmp_path):
    """It configures this machine. Nothing about it is a question for the library."""
    assert cli_run("setup", "hooks", "--home", str(tmp_path)).code == 0
    assert server.requests == []


def test_setup_help_explains_the_choice_between_the_two_paths(cli_run):
    """AXI 7 offers two discovery paths and says a user needs one; help has to say which."""
    result = cli_run("setup", "--help")
    assert result.code == 0
    assert "hooks give ambient context every session" in result
    assert "the skill loads on demand instead" in result
    assert "plex-axi skill" in result


def test_setup_does_not_grow_a_second_spelling_of_the_skill(cli_run):
    """One name for one idea: `plex-axi skill` stays the only way to write the skill."""
    assert cli.command_specs()["setup"].find("skill") is None
    assert cli_run("setup", "skill").code == 2


# -------------------------------------------------- the document it prints


def test_the_context_command_reaches_the_server_zero_times(server, cli_run):
    """The claim that makes it safe at session start, asserted where it can fail.

    Not the exit code: a version that connected and then printed the same
    document would pass on that and would be paying a round-trip -- and reading
    a credential -- at the start of every session on the machine.
    """
    assert cli_run("context").code == 0
    assert server.requests == []
    assert server.writes == []


def test_the_context_command_is_clean_and_useful_with_no_environment_at_all(cli_run):
    """A machine that has the package and no Plex server is the ordinary case."""
    result = cli_run("context", env={})
    assert result.code == 0
    assert "error:" not in result.out
    assert "NOT_CONFIGURED" not in result
    assert result.err == ""
    # It still orients: the nouns, the search rule, and how to become configured.
    for noun in cli.COMMAND_ORDER:
        assert noun in result
    assert "one flag per field" in result
    assert "Set PLEX_URL" in result


def test_the_context_command_names_which_variables_are_set_and_never_their_values(cli_run):
    """Hook output lands in an agent's context and is logged: a wider surface, not a narrower one."""
    result = cli_run("context")
    assert result.code == 0
    assert "PLEX_URL and PLEX_TOKEN are set" in result
    for leak in ("plex.example.com", "32400", TOKEN):
        assert leak not in result.out, f"the ambient document printed {leak!r}"
        assert leak not in result.err


def test_a_url_carrying_credentials_is_not_printed_either(cli_run):
    """The one shape where the address itself is a secret."""
    env = {
        "PLEX_URL": "http://someone:hunter2000@plex.example.com:32400",
        "PLEX_TOKEN": TOKEN,
    }
    result = cli_run("context", env=env)
    assert result.code == 0
    for leak in ("someone", "hunter2000", "plex.example.com"):
        assert leak not in result.out and leak not in result.err


def test_the_context_command_says_where_this_tool_ends(cli_run):
    """The single most load-bearing line: an agent has to know what to do with a media id."""
    result = cli_run("context")
    assert "plex://<machine-id>/<rating-key>" in result
    assert "leaves dispatch to whatever owns the speakers" in result


def test_the_context_command_reports_the_write_gate(cli_run, writable_env):
    """An agent that cannot see a closed gate plans writes it will never be allowed to make."""
    assert writes.state({}) in cli_run("context").out
    assert writes.state(writable_env) in cli_run("context", env=writable_env).out


def test_the_context_command_is_gate_aware_about_playback(cli_run, playing_env):
    """Closed, it says the tool ends at a media id; open, that sentence would be false."""
    closed = cli_run("context").out
    assert playback.ALLOW_VAR not in closed
    assert "clients" not in closed
    opened = cli_run("context", env=playing_env).out
    assert playback.ALLOW_VAR in opened
    assert "starting is the whole of it" in opened
    assert "Run `plex-axi clients`" in opened


#: What one session's ambient context may cost. AXI 7: this loads on *every*
#: session, so the budget is asserted rather than intended -- a line added
#: without thinking about the cost fails here rather than being paid forever by
#: everybody who installed the hook. Roughly 1.4 KB today; the ceiling leaves
#: room for one more fact, not for a manual.
CONTEXT_BUDGET_BYTES = 2048


@pytest.mark.parametrize("env", ["configured", "unconfigured"])
def test_the_ambient_document_stays_within_its_token_budget(cli_run, plex_env, env):
    result = cli_run("context", env=plex_env if env == "configured" else {})
    size = len(result.out.encode("utf-8"))
    assert size < CONTEXT_BUDGET_BYTES, f"{env} ambient context is {size} bytes"


def test_the_context_command_needs_no_subcommand_and_takes_no_arguments(cli_run):
    assert cli_run("context").code == 0
    assert cli_run("context", "extra").code == 2
