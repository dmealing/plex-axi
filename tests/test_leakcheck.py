"""The public-repository guard.

The scanner is the control that keeps library-specific data out of this
repository, so it is tested adversarially: every rule against the shape it
claims, every rule against content that must NOT trip it, and the evasions that
a line-by-line scanner misses.

Nothing dirty is ever committed. Address shapes are assembled from fragments at
run time (the condensed pass deliberately does not join digits, so a fragmented
address is invisible to it), and credentials are built at run time -- a JWT by
actually base64-encoding a payload, a Plex token by joining fragments -- so no
literal of either shape exists in this file at all.
"""

from __future__ import annotations

import subprocess
import sys
import urllib.parse
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import leakcheck

REPO_ROOT = Path(__file__).resolve().parents[1]
JWT = leakcheck.synthetic_jwt()
HEAD, PAYLOAD, SIGNATURE = JWT.split(".")
PLEX_TOKEN = leakcheck.synthetic_plex_token()


#: One realistic leak per rule. The name is the rule that must fire.
DIRTY = {
    "plex-token": "url ?X-Plex-Token=" + PLEX_TOKEN,
    "jwt": f"token: {JWT}",
    "bearer": "header " + "Bearer " + "aa11bb22cc33dd44ee55",
    "plex-direct-host": "url https://"
    + "10-0-0-5"
    + ".0123456789abcdef0123456789abcdef"
    + ".plex.direct:32400",
    "machine-identifier": "machineIdentifier=" + "fedcba9876543210fedcba9876543210fedcba98",
    "media-path": "file "
    + "/sr"
    + "v/media/Some Artist/Some Album/03 A Song.flac",  # leakcheck: allow=media-path
    "private-ip": "host " + "192." + "168.1.10",
    "cgnat-ip": "peer " + "100." + "101.102.103",
    "link-local-ip": "addr " + "169." + "254.10.20",
    "private-ipv6": "addr " + "fd12" + ":3456:789a::1",
    "lan-hostname": "url http://" + "plexserver" + ".local:32400",
    "mac-address": "mac " + "a4:c1" + ":38:9f:2b:7e",
    "home-path": "path " + "/ho" + "me/" + "someone" + "/notes",
    "personal-email": "mail " + "noreply" + "@" + "realcompany.co.uk",
}

#: Content this project legitimately contains, or that reads like a leak but is
#: not. A guard that fires on these gets ignored, which is its own failure mode.
CLEAN = [
    "host 127.0.0.1:32400",
    "bind 0.0.0.0 for the test double",
    "host 8.8.8.8",
    "host 172.15.0.1",
    "host 172.32.0.1",
    "host 100.63.255.1",
    "host 100.128.0.1",
    "url http://plex.example.com:32400",
    "artist Example Artist, album Example Album",
    "mail you@example.com",
    "mail noreply@anything.example",
    "curl -H 'Authorization: Bearer <token>'",
    'curl -H "X-Plex-Token: $PLEX_TOKEN"',
    "export PLEX_TOKEN=<a Plex access token>",
    "PLEX_TOKEN is read from the environment",
    "A Plex token is a 20-character bearer credential for the whole library",
    "the plex token belongs in an environment variable and nowhere else",
    "a bearer of good news arrives",
    "relative path src/plex_axi/cli.py",
    "the module is scripts/leakcheck.py",
    "version 2026.1.0 released",
    "python 3.9, 3.10, 3.12 supported",
    "line-length = 100",
    "timeout 30.5 seconds",
    "coverage rose from 51.5 to 90.2 percent",
    "the git empty tree is 4b825dc642cb6eb9a060e54bf8d69288fbee4904",
    "ff02::1 is the all-nodes multicast group",
    "fdfd is hex, not an address",
    "settings.local.json is ignored",
    "Path.home() resolves the home directory",
    "from .commands.home import DESCRIPTION",
    "a timestamp like 12:34:56 is not a MAC",
    "plex://track/a1b2c3d4e5f60718293c0111 is a catalogue guid",
]


def rule_names(findings):
    return sorted({finding.rule.name for finding in findings})


@pytest.mark.parametrize(("rule", "content"), sorted(DIRTY.items()))
def test_every_rule_detects_its_shape(rule, content):
    assert rule in rule_names(leakcheck.scan_text("f.txt", content + "\n"))


def test_every_declared_rule_is_covered_by_this_suite():
    """A rule added without a test would otherwise look proven."""
    assert sorted(DIRTY) == sorted(rule.name for rule in leakcheck.RULES)


@pytest.mark.parametrize("content", CLEAN)
def test_legitimate_content_does_not_trip_the_scanner(content):
    assert leakcheck.scan_text("f.txt", content + "\n") == []


# --------------------------------------------------------------- evasions


def test_a_token_split_across_lines_is_caught():
    """A line pass cannot see this; the condensed pass is why it exists."""
    source = f'JWT = (\n    "{HEAD}."\n    "{PAYLOAD}."\n    "{SIGNATURE}"\n)\n'
    findings = leakcheck.scan_text("f.py", source)
    assert "jwt" in rule_names(findings)
    assert any(finding.pass_name == "joined" for finding in findings)


def test_a_token_joined_by_concatenation_is_caught():
    source = f'T = "{HEAD}" + "." + "{PAYLOAD}" + "." + "{SIGNATURE}"\n'
    assert "jwt" in rule_names(leakcheck.scan_text("f.py", source))


def test_a_token_continued_over_a_backslash_is_caught():
    source = f"token: {HEAD}.{PAYLOAD}.\\\n{SIGNATURE}\n"
    assert "jwt" in rule_names(leakcheck.scan_text("f.txt", source))


def test_a_percent_encoded_token_is_caught():
    source = f"u={HEAD}%2E{PAYLOAD}%2E{SIGNATURE}\n"
    assert "jwt" in rule_names(leakcheck.scan_text("f.txt", source))


def test_a_finding_is_reported_once_even_when_both_passes_see_it():
    findings = leakcheck.scan_text("f.txt", f"token: {JWT}\n")
    assert len(findings) == 1


def test_a_plex_token_split_across_lines_is_caught():
    """The shape that matters most here: a bearer credential for a whole library."""
    source = f'PLEX_TOKEN = (\n    "{PLEX_TOKEN[:8]}"\n    "{PLEX_TOKEN[8:]}"\n)\n'
    findings = leakcheck.scan_text("f.py", source)
    assert "plex-token" in rule_names(findings)
    assert any(finding.pass_name == "joined" for finding in findings)


def test_a_media_path_with_spaces_is_caught():
    """Real music paths are full of spaces; a scanner that stopped at one would
    only ever match the last word, which never starts with a slash."""
    # The marker has to sit on the physical line the shape lands on, and the
    # formatter will move a trailing comment if it wraps the expression -- so
    # this literal stays short enough to be left alone.
    dirty = "file /mn" + "t/x/An Artist/An Album/07 A Song.mp3"  # leakcheck: allow=media-path
    assert "media-path" in rule_names(leakcheck.scan_text("f.txt", dirty + "\n"))


# ----------------------------------------------------------- allow marker


def test_the_allow_marker_exempts_only_the_rule_it_names():
    dirty = "host " + "192." + "168.1.10" + " and " + "100." + "101.102.103"
    assert rule_names(leakcheck.scan_text("f.txt", dirty + "\n")) == ["cgnat-ip", "private-ip"]

    scoped = f"{dirty}  # {leakcheck.ALLOW_PREFIX}private-ip\n"
    assert rule_names(leakcheck.scan_text("f.txt", scoped)) == ["cgnat-ip"]


def test_the_allow_marker_accepts_several_named_rules():
    dirty = "host " + "192." + "168.1.10" + " and " + "100." + "101.102.103"
    scoped = f"{dirty}  # {leakcheck.ALLOW_PREFIX}private-ip,cgnat-ip\n"
    assert leakcheck.scan_text("f.txt", scoped) == []


def test_an_unscoped_marker_exempts_nothing():
    """A blanket marker would switch off rules nobody was thinking about."""
    dirty = "host " + "192." + "168.1.10" + "  # leakcheck: allow\n"
    assert rule_names(leakcheck.scan_text("f.txt", dirty)) == ["private-ip"]


def test_the_allow_marker_also_applies_to_the_condensed_pass():
    source = f"token: {JWT}  # {leakcheck.ALLOW_PREFIX}jwt\n"
    assert leakcheck.scan_text("f.txt", source) == []


# -------------------------------------------------------- path allowances
#
# The marker is a comment, so a JSON file cannot carry one. PATH_ALLOWANCES is
# how vendored data that must stay byte-for-byte is exempted instead, and these
# tests hold it to the same scope the marker has -- including the part that only
# shows up at the entry points, where a mode that named the same file differently
# would apply an exemption the others do not.


ALLOWED_PATH = "tests/fixtures/toon-spec/encode/primitives.json"
LOST_MESSAGE_PATH = "tests/fixtures/commit-messages/41bcb73.txt"
HIJACKED_MESSAGE_PATH = "tests/fixtures/commit-messages/b1f9bb18.txt"
TWO_SHAPES = "path " + "/ho" + "me/" + "someone" + "/notes and " + "192." + "168.1.10"


def test_a_path_allowance_exempts_only_the_rule_it_names():
    assert rule_names(leakcheck.scan_text(ALLOWED_PATH, TWO_SHAPES + "\n")) == ["private-ip"]


def test_a_path_allowance_exempts_no_other_file():
    findings = leakcheck.scan_text("src/plex_axi/toon.py", TWO_SHAPES + "\n")
    assert rule_names(findings) == ["home-path", "private-ip"]


def test_an_allowance_matches_only_the_exact_path_it_names():
    """A path that merely ends with an allowed one -- a shadowing directory, a
    suffixed twin, a scan rooted elsewhere -- is a different file, and exempting
    it would grant the entry every directory it is ever copied into."""
    assert leakcheck.path_allowances(ALLOWED_PATH) == frozenset({"home-path"})
    assert leakcheck.path_allowances(f"attic/{ALLOWED_PATH}") == frozenset()
    assert leakcheck.path_allowances(f"/scan/root/{ALLOWED_PATH}") == frozenset()
    assert leakcheck.path_allowances(f"{ALLOWED_PATH}.bak") == frozenset()


#: The exact shapes each exempted file still trips with the allowances switched
#: off, so a refreshed fixture that changes one -- or grows a second -- fails the
#: suite instead of quietly widening what the entry covers. Assembled from
#: fragments like DIRTY, so this file stays clean under its own scanner.
EXPECTED_SHAPES = {
    ALLOWED_PATH: frozenset({"C:" + "\\\\" + "Users" + "\\\\" + "path"}),
    LOST_MESSAGE_PATH: frozenset({"noreply" + "@" + "anthropic" + ".com"}),
    HIJACKED_MESSAGE_PATH: frozenset({"noreply" + "@" + "anthropic" + ".com"}),
}


def test_every_expected_shape_entry_names_a_live_allowance():
    assert sorted(EXPECTED_SHAPES) == sorted(leakcheck.PATH_ALLOWANCES)


@pytest.mark.parametrize("path", sorted(leakcheck.PATH_ALLOWANCES))
def test_every_path_allowance_is_still_earning_its_place(path, monkeypatch):
    """Stale is as bad as blanket: an exemption outlives what it was granted for.

    Scanning the real file with allowances switched off must fire exactly the
    rules the entry names -- no fewer, or the entry is dead and should go; no
    more, or it is covering something nobody agreed to -- and exactly the shapes
    recorded beside it, so a vendored refresh cannot change what is exempted
    without the change being visible here.
    """
    allowed = leakcheck.PATH_ALLOWANCES[path]
    assert allowed <= set(leakcheck.RULES_BY_NAME), "allowance names an undeclared rule"
    expected = EXPECTED_SHAPES[path]
    target = REPO_ROOT / path
    assert target.is_file(), "allowance names a file that is no longer here"

    monkeypatch.setattr(leakcheck, "PATH_ALLOWANCES", {})
    findings = leakcheck.scan_text(path, target.read_text(encoding="utf-8"))
    assert rule_names(findings) == sorted(allowed)
    assert {finding.matched for finding in findings} == expected


# ------------------------------------- the allowance at every entry point
#
# One file, one name, whatever found it. An exemption matched exactly is only
# as good as the agreement between the modes about what to match: a mode that
# handed over an absolute name would stop honouring it, and one that matched a
# trailing fragment would honour it for a decoy the entry never named.


#: The decoy: the same exempted content, one directory deeper, under a path that
#: ends with the allowed one. Trailing-match logic reads this as exempt.
DECOY_PATH = f"attic/{ALLOWED_PATH}"
EXEMPT_SHAPE = sorted(EXPECTED_SHAPES[ALLOWED_PATH])[0]


def _allowance_repo(tmp_path, *hooks):
    """A repository carrying the exempted file and a decoy that shadows it."""
    repo = _hook_repo(tmp_path, *hooks)
    for name in (ALLOWED_PATH, DECOY_PATH):
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f'{{"input": "{EXEMPT_SHAPE}"}}\n', encoding="utf-8")
    return repo


def _reported(capsys):
    return {
        line.strip().split(",")[0]
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("  ") and ",home-path," in line
    }


def _assert_exactly_the_decoy(exit_code, capsys):
    """The named file is exempt; the one that merely ends with it is not."""
    assert exit_code == 1
    assert _reported(capsys) == {DECOY_PATH}


def test_the_allowance_holds_for_the_tracked_files_scan(tmp_path, capsys):
    repo = _allowance_repo(tmp_path)
    _git(repo, "add", "-A")
    _assert_exactly_the_decoy(leakcheck.main(["--root", str(repo)]), capsys)


def test_the_allowance_holds_for_the_pre_commit_hook(tmp_path):
    """The hook's own spelling: --staged, with an absolute --root."""
    repo = _allowance_repo(tmp_path, "pre-commit")
    _git(repo, "add", "-A")
    blocked = _git(repo, "commit", "-m", "vendor fixtures", check=False)
    output = (blocked.stdout + blocked.stderr).decode("utf-8", "replace")
    assert blocked.returncode != 0
    assert f"  {DECOY_PATH},1,home-path," in output
    assert f"  {ALLOWED_PATH},1,home-path," not in output


def test_the_allowance_holds_for_explicit_paths_under_a_root(tmp_path, capsys):
    repo = _allowance_repo(tmp_path)
    _assert_exactly_the_decoy(leakcheck.main(["--root", str(repo), "tests", "attic"]), capsys)


def test_the_allowance_holds_for_an_absolute_target_at_the_default_root(
    tmp_path, capsys, monkeypatch
):
    """`leakcheck.py "$PWD"` names the same files as `leakcheck.py .` does.

    Two spellings of one scan, and the exemption has to survive both: an
    absolute target against the default root is the mode where a name is most
    easily reported in a form the table cannot match.
    """
    repo = _allowance_repo(tmp_path)
    monkeypatch.chdir(repo)
    _assert_exactly_the_decoy(leakcheck.main([str(repo)]), capsys)


def test_a_file_outside_the_root_keeps_its_name_and_no_exemption(tmp_path, capsys):
    """The allowance is this repository's, so it cannot follow the shape elsewhere."""
    repo = _allowance_repo(tmp_path)
    assert leakcheck.main([str(repo / ALLOWED_PATH)]) == 1
    assert _reported(capsys) == {str(repo / ALLOWED_PATH)}


def test_the_allowance_holds_for_the_walk_fallback(tmp_path, capsys, monkeypatch):
    """The path taken when git cannot answer: no index, just os.walk."""
    repo = _allowance_repo(tmp_path)
    monkeypatch.setattr(leakcheck, "tracked_files", lambda root: None)
    _assert_exactly_the_decoy(leakcheck.main(["--root", str(repo)]), capsys)


# ------------------------------------------------------------------ email


def test_an_allowlisted_local_part_no_longer_bypasses_the_domain_check():
    """`noreply@` on a real domain still identifies a real organisation."""
    dirty = "mail " + "noreply" + "@" + "realcompany.co.uk"
    assert rule_names(leakcheck.scan_text("f.txt", dirty + "\n")) == ["personal-email"]


# ------------------------------------------------------------- interfaces


def test_scanning_a_dirty_tree_exits_non_zero(tmp_path, capsys):
    fixture = leakcheck.dirty_fixture()
    for name, content in fixture.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    exit_code = leakcheck.main(["--root", str(tmp_path), *sorted(fixture)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "help:" in out


def test_the_self_test_confirms_every_rule_still_fires(capsys):
    assert leakcheck.main(["--demo"]) == 0
    out = capsys.readouterr().out
    assert "every rule fired" in out
    for rule in leakcheck.RULES:
        assert rule.name in out


def test_the_rules_listing_names_every_rule(capsys):
    assert leakcheck.main(["--rules"]) == 0
    out = capsys.readouterr().out
    for rule in leakcheck.RULES:
        assert rule.name in out


def test_this_repository_is_clean(capsys):
    assert leakcheck.main(["--root", str(REPO_ROOT)]) == 0
    assert "0 findings" in capsys.readouterr().out


def test_binary_files_are_skipped(tmp_path):
    dirty = ("192." + "168.1.1").encode()
    (tmp_path / "image.png").write_bytes(b"\x89PNG" + dirty)
    assert leakcheck.scan_paths(["image.png"], root=tmp_path) == []


def test_a_commit_message_is_scanned(tmp_path, capsys):
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("fix: tested against " + "192." + "168.1.10" + "\n", encoding="utf-8")
    assert leakcheck.main(["--commit-msg", str(message)]) == 1
    assert "private-ip" in capsys.readouterr().out


def test_commit_message_comment_lines_are_ignored(tmp_path):
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("fix: something\n# host " + "192." + "168.1.10" + "\n", encoding="utf-8")
    assert leakcheck.main(["--commit-msg", str(message)]) == 0


# ------------------------------------------------------------------ hooks


def _hook_repo(tmp_path, *hooks):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / ".githooks").mkdir()
    # Both scripts, because `commit-msg` runs both: a repository missing one
    # would block every commit under `set -e` and look like the scanner firing.
    for script in ("leakcheck.py", "commitcheck.py"):
        (repo / "scripts" / script).write_text(
            (REPO_ROOT / "scripts" / script).read_text(encoding="utf-8"), encoding="utf-8"
        )
    for name in hooks:
        target = repo / ".githooks" / name
        target.write_text(
            (REPO_ROOT / ".githooks" / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
        target.chmod(0o755)
    for args in (
        ("init", "-q", "."),
        ("config", "user.email", "you@example.com"),
        ("config", "user.name", "Test"),
        ("config", "core.hooksPath", ".githooks"),
    ):
        subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True)
    return repo


def _git(repo, *args, check=True):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, check=check)


def test_the_pre_commit_hook_blocks_a_dirty_commit(tmp_path):
    repo = _hook_repo(tmp_path, "pre-commit")
    (repo / "clean.txt").write_text("nothing to see\n", encoding="utf-8")
    _git(repo, "add", "-A")
    assert _git(repo, "commit", "-m", "clean").returncode == 0

    (repo / "dirty.txt").write_text("host " + "192." + "168.1.10" + "\n", encoding="utf-8")
    _git(repo, "add", "dirty.txt")
    blocked = _git(repo, "commit", "-m", "dirty", check=False)
    assert blocked.returncode != 0
    assert b"private-ip" in blocked.stdout + blocked.stderr


def test_the_pre_commit_hook_scans_the_very_first_commit(tmp_path):
    """A repository with no HEAD yet has nothing to diff against."""
    repo = _hook_repo(tmp_path, "pre-commit")
    (repo / "first.txt").write_text("host " + "10." + "1.2.3" + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    blocked = _git(repo, "commit", "-m", "first", check=False)
    assert blocked.returncode != 0
    assert b"private-ip" in blocked.stdout + blocked.stderr


def test_the_commit_msg_hook_blocks_a_dirty_message(tmp_path):
    """File content and the commit message are separate channels."""
    repo = _hook_repo(tmp_path, "pre-commit", "commit-msg")
    (repo / "clean.txt").write_text("nothing to see\n", encoding="utf-8")
    _git(repo, "add", "-A")
    dirty = "test: tested on " + "192." + "168.1.10"
    blocked = _git(repo, "commit", "-m", dirty, check=False)
    assert blocked.returncode != 0
    assert b"private-ip" in blocked.stdout + blocked.stderr

    # Conventional, because the same hook now also refuses a message
    # release-please cannot parse. See tests/test_commit_message.py.
    assert _git(repo, "commit", "-m", "test: tested on a local instance").returncode == 0


def test_identity_trailers_do_not_block_a_commit(tmp_path):
    """Git records author and committer addresses anyway; blocking these
    would stop ordinary attribution without preventing any leak."""
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text(
        "fix: something\n\nCo-Authored-By: Someone <someone@example.org>\n"
        "Signed-off-by: Other <" + "other" + "@" + "realcompany.co.uk" + ">\n",
        encoding="utf-8",
    )
    assert leakcheck.main(["--commit-msg", str(message)]) == 0


def test_an_address_in_the_message_body_is_still_caught(tmp_path):
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text(
        "fix: reported by " + "firstname.lastname" + "@" + "realcompany.co.uk" + "\n",
        encoding="utf-8",
    )
    assert leakcheck.main(["--commit-msg", str(message)]) == 1


def test_a_trailer_is_only_exempt_from_the_email_rule(tmp_path):
    """The exemption is about attribution, not a way to smuggle anything else."""
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text(
        "fix: x\n\nCo-Authored-By: host " + "192." + "168.1.10" + "\n", encoding="utf-8"
    )
    assert leakcheck.main(["--commit-msg", str(message)]) == 1


# ------------------------------------------------------- the pull request
#
# The third surface. A title and a body are published the moment they are
# written, are in no checkout and pass under no hook, so neither the tracked-file
# scan nor `--commit-msg` has ever seen one. The pipeline's document step writes
# into the body -- it embeds an evidence script and pastes captured pytest
# output, and both carry absolute paths: a `WORKTREE = ` assignment naming the
# checkout it ran from, and a pytest header's `rootdir:` line. That has published
# a home directory three times across two repositories in one day, with every
# check green each time.
#
# Nothing dirty is written here either: the shapes are assembled from fragments,
# exactly as DIRTY above is.


HOME = "/ho" + "me/" + "someone"

#: This repository's own case, rebuilt: the document step embedded a script that
#: assigns the worktree it ran from, and published the assignment.
LEAKY_BODY = (
    "## Evidence\n\n"
    "Reproduce the before/after yourself:\n\n"
    "```sh\n"
    f'WORKTREE = "{HOME}/checkout/plex-axi"\n'
    "python3 scripts/leakcheck.py --pull-request 7\n"
    "```\n"
)

#: The sibling's case, and the same mechanism from the other end: captured tool
#: output pasted in whole, header included.
LEAKY_CAPTURE_BODY = (
    "## Evidence\n\n"
    "<details>\n<summary>pytest -q</summary>\n\n"
    "```\n"
    "platform linux -- Python 3.12.0, pytest-8.0.0, pluggy-1.5.0\n"
    f"rootdir: {HOME}/checkout/plex-axi\n"
    "collected 900 items\n"
    "```\n\n</details>\n"
)

LEAKY_TITLE = "fix(ci): run the suite from " + HOME + "/checkout"

#: An ordinary pull request: prose, a fenced block, repository-relative paths, a
#: documentation host, synthetic library content, an attribution trailer. A guard
#: that fires on this is one people learn to route around, which is the failure
#: mode that ends guards.
CLEAN_TITLE = "fix(toon): keep decimal form inside the canonical range"
CLEAN_BODY = (
    "## Intent\n\n"
    "`src/plex_axi/toon.py` formats through `Decimal(repr(value))` inside the range,\n"
    "and `tests/test_toon_conformance.py` covers it.\n\n"
    "```\n"
    "rootdir: /github/workspace\n"
    "collected 900 items\n"
    "```\n\n"
    "Checked against http://plex.example.com:32400 with `Example Artist` /\n"
    "`Example Album`, and against the double on 127.0.0.1:32400.\n\n"
    "Co-authored-by: Someone <someone@example.org>\n"
)


class _Transport:
    """A stand-in for the GitHub reader, so no test needs a network or a token."""

    def __init__(self, *, token="t0ken", slug="example/repo", data=None, error=None):
        self._token = token
        self._slug = slug
        self._data = {"title": "", "body": ""} if data is None else data
        self._error = error

    def github_token(self):
        return self._token

    def repo_slug(self, root="."):
        return self._slug

    def pull_request(self, number, *, slug, token, api_url=None):
        if self._error is not None:
            raise self._error
        return self._data


def _transport(monkeypatch, **kwargs):
    transport = _Transport(**kwargs)
    monkeypatch.setattr(leakcheck, "_github_transport", lambda: transport)
    return transport


@pytest.mark.parametrize(
    ("body", "anchor"),
    [(LEAKY_BODY, "WORKTREE"), (LEAKY_CAPTURE_BODY, "rootdir:")],
    ids=["embedded-evidence-script", "pasted-tool-output"],
)
def test_the_pull_request_body_that_shipped_today_is_caught(body, anchor):
    """Both shapes the document step publishes, caught by the home-path rule.

    The first is this repository's own occurrence: an evidence script embedded in
    the body, assigning the checkout it ran from. The second is the sibling's:
    captured tool output pasted in whole, header included.
    """
    findings = leakcheck.scan_pull_request((("title", "fix(ci): a subject"), ("body", body)))
    assert rule_names(findings) == ["home-path"]
    (finding,) = findings
    assert finding.path == "pull request body"
    assert body.splitlines()[finding.line_number - 1].startswith(anchor)
    assert finding.column is not None


def test_a_leak_in_the_title_is_caught_too():
    """The title is published in every listing, every notification and every
    merge subject; it is as public as the body and is scanned as one."""
    findings = leakcheck.scan_pull_request(
        (("title", LEAKY_TITLE), ("body", "## Intent\n\nordinary prose.\n"))
    )
    assert rule_names(findings) == ["home-path"]
    assert findings[0].path == "pull request title"


def test_every_field_github_publishes_is_scanned():
    """Both fields, in one call, so a leak in either fails the check."""
    findings = leakcheck.scan_pull_request((("title", LEAKY_TITLE), ("body", LEAKY_BODY)))
    assert sorted(f.path for f in findings) == [
        f"pull request {field}" for field in sorted(leakcheck.PULL_REQUEST_FIELDS)
    ]


def test_every_location_of_one_repeated_value_is_reported():
    """One value on nine lines is nine places to edit.

    The report used to deduplicate by value across the whole artefact, so a
    header pasted nine times by a capture step was named once. A fixer who
    scrubbed exactly what the report named published the other eight, and the
    re-run then named the next one -- convergent, but one round per occurrence,
    which in practice means a partial fix and a green check. A sweep of two
    repositories found eight leaking bodies, one of them with six matches.
    """
    body = "".join(f"DIR:  {HOME}/checkout/run-{n}\n" for n in range(1, 10))
    findings = leakcheck.scan_pull_request((("title", "fix: x"), ("body", body)))
    assert [f.line_number for f in findings] == list(range(1, 10))
    assert {f.rule.name for f in findings} == {"home-path"}
    # One value, nine locations: the matched text is identical every time, which
    # is exactly what the old key deduplicated on.
    assert len({f.matched for f in findings}) == 1
    assert all(f.column is not None for f in findings)


def test_the_report_lists_every_location_of_a_repeated_value(monkeypatch, capsys):
    """The count in the header is the number of places to edit, not the number
    of distinct values -- and still without printing any of them."""
    body = "".join(f"DIR:  {HOME}/checkout/run-{n}\n" for n in range(1, 7))
    _transport(monkeypatch, data={"title": "fix: x", "body": body})
    assert leakcheck.main(["--pull-request", "7"]) == 1
    out = capsys.readouterr().out
    assert "leakcheck[6]" in out
    for n in range(1, 7):
        assert f"body,{n},7,home-path,line" in out
    assert HOME not in out


def test_a_repeated_value_in_a_file_is_reported_at_every_line():
    """The reasoning is not special to a pull request: a file with one secret on
    four lines is four edits, and the rule set is shared across surfaces."""
    text = "".join(f"source {HOME}/.env  # {n}\n" for n in range(1, 5))
    findings = leakcheck.scan_text("f.sh", text)
    assert [f.line_number for f in findings] == [1, 2, 3, 4]


def test_two_passes_seeing_one_location_still_report_it_once():
    """The half of the old key that was right, kept.

    Deduplicating by value existed to stop the line pass and the condensed pass
    reporting one leak twice. They agree on the line -- the condensed pass
    attributes a match to the line its region starts on -- so keeping the line
    in the key preserves that, and because the line pass runs first the survivor
    is the one carrying an offset.
    """
    split = f'T = (\n    "{HEAD}."\n    "{PAYLOAD}."\n    "{SIGNATURE}"\n)\nwhole = "{JWT}"\n'
    findings = [f for f in leakcheck.scan_text("f.py", split) if f.rule.name == "jwt"]
    # Two locations: the value assembled across lines 2-4 (the condensed pass
    # attributes it to line 2, where the first fragment is), and the whole one
    # on line 6. Not four, and not one.
    assert sorted(f.line_number for f in findings) == [2, 6]
    by_line = {f.line_number: f for f in findings}
    assert by_line[2].pass_name == "joined" and by_line[2].column is None
    assert by_line[6].pass_name == "line" and by_line[6].column is not None


def test_an_ordinary_pull_request_is_left_alone():
    assert leakcheck.scan_pull_request((("title", CLEAN_TITLE), ("body", CLEAN_BODY))) == []


def test_the_check_that_already_read_this_body_reports_it_clean():
    """The hole, stated as a test rather than as a claim.

    Before this scan existed the body was not unread -- `commitcheck
    --pull-request` fetched it on every pull request, in the very same job. It
    read it for a different question (does release-please parse what a merge
    hands it) and answered that question correctly, which is why every check was
    green while an absolute path sat in the body. The rules were never the
    problem; the reach was.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import commitcheck

    problems, faults = commitcheck.check_pull_request(
        "fix(ci): a subject", 12, LEAKY_BODY, engine="python"
    )
    assert (problems, faults) == ([], [])
    assert (
        leakcheck.scan_pull_request((("title", "fix(ci): a subject"), ("body", LEAKY_BODY))) != []
    )


def test_a_pull_request_cannot_exempt_itself_with_a_marker():
    """A file's `allow=` marker is committed, diffed and reviewed. The same text
    in a body is an off-switch anyone can add after every check has run, on the
    one artefact whose editability is why this surface needs a guard."""
    marked = f'WORKTREE = "{HOME}/checkout"  {leakcheck.ALLOW_PREFIX}home-path\n'
    assert rule_names(leakcheck.scan_pull_request((("title", "t"), ("body", marked)))) == [
        "home-path"
    ]
    # The same line in a file still exempts itself, so this is a policy about the
    # surface and not a change to the marker.
    assert leakcheck.scan_text("f.txt", marked) == []


def test_an_attribution_trailer_does_not_fail_a_pull_request():
    """GitHub's squash box offers the body as the commit message, so a trailer
    is as routine there as in one -- and is exempt from the address rule only."""
    trailer = "Co-authored-by: Someone <" + "someone" + "@" + "realcompany.co.uk" + ">\n"
    assert leakcheck.scan_pull_request((("title", "fix: x"), ("body", trailer))) == []
    smuggled = "Co-authored-by: host " + "192." + "168.1.10" + "\n"
    assert rule_names(leakcheck.scan_pull_request((("title", "fix: x"), ("body", smuggled)))) == [
        "private-ip"
    ]


def test_the_report_says_where_without_republishing_it(monkeypatch, capsys):
    """A pull request check runs on a public log. Printing the excerpt would
    republish the leak to a wider audience than the pull request page itself."""
    _transport(monkeypatch, data={"title": LEAKY_TITLE, "body": LEAKY_BODY})
    assert leakcheck.main(["--pull-request", "7"]) == 1
    out = capsys.readouterr().out
    assert HOME not in out
    assert "checkout" not in out
    assert "home-path" in out
    assert "field,line,offset,rule,pass" in out
    # Derived, not transcribed: the point of the line number is that it locates
    # the leak in the artefact, which a hand-counted constant stops doing the
    # moment the fixture gains a line.
    leaking = 1 + next(
        n for n, line in enumerate(LEAKY_BODY.splitlines()) if line.startswith("WORKTREE")
    )
    assert "title,1," in out and f"body,{leaking}," in out
    assert "example/repo#7" in out


def test_a_clean_pull_request_exits_zero(monkeypatch, capsys):
    _transport(monkeypatch, data={"title": CLEAN_TITLE, "body": CLEAN_BODY})
    assert leakcheck.main(["--pull-request", "7"]) == 0
    assert "0 findings" in capsys.readouterr().out


@pytest.mark.parametrize(
    "kwargs",
    [
        {"token": None},
        {"slug": None},
        {"error": RuntimeError("503 Service Unavailable")},
        {"data": "not a pull request"},
    ],
    ids=["no-token", "no-repository", "github-unavailable", "unreadable-answer"],
)
def test_a_pull_request_that_cannot_be_read_fails_the_check(monkeypatch, capsys, kwargs):
    """Fail closed. Reporting `0 findings` for something it never saw would turn
    an unknown into an assurance, which is worse than not running at all."""
    _transport(monkeypatch, **kwargs)
    assert leakcheck.main(["--pull-request", "7"]) == 1
    out = " ".join(capsys.readouterr().out.split())
    assert "cannot read the pull request" in out
    assert "Refusing to report a verdict it cannot support." in out


def test_a_broken_transport_fails_the_check(monkeypatch, capsys):
    def explode():
        raise leakcheck.PullRequestUnavailable("cannot load the GitHub reader")

    monkeypatch.setattr(leakcheck, "_github_transport", explode)
    assert leakcheck.main(["--pull-request", "7"]) == 1
    assert "cannot read the pull request" in capsys.readouterr().out


def test_a_scanner_with_no_rules_refuses_rather_than_passing(monkeypatch, capsys):
    """The other half of failing closed: an empty rule set finds nothing, and
    `0 findings` from a scanner that loaded nothing reads exactly like success."""
    _transport(monkeypatch, data={"title": LEAKY_TITLE, "body": LEAKY_BODY})
    monkeypatch.setattr(leakcheck, "RULES", [])
    assert leakcheck.main(["--pull-request", "7"]) == 1
    assert "no rules loaded" in capsys.readouterr().out


def test_the_self_test_covers_the_pull_request_surface(monkeypatch, capsys):
    """`--demo` runs in CI before the real scan. A scanner that stopped reaching
    the pull request must fail there rather than reporting nothing to report."""
    assert leakcheck.run_demo() == 0
    assert "pull request" in capsys.readouterr().out
    monkeypatch.setattr(leakcheck, "scan_pull_request", lambda fields: [])
    assert leakcheck.run_demo() == 1
    assert "missed a field" in capsys.readouterr().out


def test_the_demo_fixtures_are_the_shapes_they_claim():
    assert rule_names(leakcheck.scan_pull_request(leakcheck.dirty_pull_request())) == ["home-path"]
    assert leakcheck.scan_pull_request(leakcheck.clean_pull_request()) == []


def test_the_self_test_output_passes_the_pull_request_scan(capsys):
    """The demo's output is published twice over: it runs in a public CI log as
    the first step of this check, and the pipeline pastes it into pull request
    bodies as evidence. Printing the sample values to prove the rules fire made
    that output leak-shaped by construction -- and the pasted evidence then
    failed `--pull-request` on the sibling's own pull request, the guard catching
    its own self-test. The proof is the exit code and the per-rule lines; the
    values are the leak."""
    assert leakcheck.run_demo() == 0
    out = capsys.readouterr().out
    assert leakcheck.scan_pull_request((("title", "self-test evidence"), ("body", out))) == []


def test_an_empty_pull_request_argument_is_a_refusal_not_a_files_scan(monkeypatch, capsys):
    """A wrapper passing an empty variable is asking about no pull request.
    Falling through to the tracked-file scan would exit green having never
    fetched the artefact -- the false assurance this check exists to end."""
    _transport(monkeypatch, data=[])
    assert leakcheck.main(["--pull-request", ""]) == 1
    out = capsys.readouterr().out
    assert "cannot read the pull request" in out
    assert "tracked files" not in out


def test_an_offset_is_not_printed_when_it_would_not_locate_the_match(monkeypatch, capsys):
    """The offset must index the artefact as written or not be printed at all.

    A leak that surfaces only in the percent-decoded view of a line, or in the
    condensed pass, has no offset into anything the reader can open. Printing
    one anyway sends the one person who can fix it to a position where nothing
    is -- and the pass column still says which view caught it.
    """
    encoded = "cfg=" + urllib.parse.quote(HOME + "/checkout", safe="")
    _transport(monkeypatch, data={"title": "fix(ci): cfg", "body": encoded + "\n"})
    assert leakcheck.main(["--pull-request", "7"]) == 1
    out = capsys.readouterr().out
    assert "body,1,-,home-path,decoded" in out
    assert HOME not in out

    split = f"t: {HEAD}.\n{PAYLOAD}.{SIGNATURE}\n"
    _transport(monkeypatch, data={"title": "fix: x", "body": split})
    assert leakcheck.main(["--pull-request", "7"]) == 1
    out = capsys.readouterr().out
    assert "body,1,-,jwt,joined" in out
    assert PLEX_TOKEN not in out and HEAD not in out


class _NoGitTransport(_Transport):
    def repo_slug(self, root="."):
        raise FileNotFoundError("No such file or directory: 'git'")


def test_a_transport_that_cannot_resolve_the_repository_refuses(monkeypatch, capsys):
    """`repo_slug` shells out to git with no guard of its own, so a machine
    without one must get the structured refusal, not a raw traceback."""
    monkeypatch.setattr(leakcheck, "_github_transport", lambda: _NoGitTransport())
    assert leakcheck.main(["--pull-request", "7"]) == 1
    out = capsys.readouterr().out
    assert "cannot read the pull request" in out
    assert "could not resolve a token or repository" in out


def test_the_hygiene_workflow_runs_this_where_it_can_block():
    """A guard that cannot fail the check is documentation.

    `edited` is the trigger that matters: the document step writes the evidence
    into the body *after* the pull request is opened, so a check that fired only
    on `opened` and `synchronize` would pass the empty original body and never
    see what replaced it. This repository already carried `edited` for the
    release-please body check; the leak scan rides the same trigger, and this
    test is what stops either guard losing it.

    The workflow is parsed into what GitHub will actually run, not matched as
    text: a commented-out step line or prose that mentions a flag is invisible
    here, and a reformat of the trigger list is not a change of behaviour.
    """
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "hygiene.yml").read_text(encoding="utf-8")
    )
    trigger = workflow.get("on") or workflow.get(True) or {}
    types = (trigger.get("pull_request") or {}).get("types") or []
    if isinstance(types, str):
        types = [types]
    assert "edited" in types

    scanning = []
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            words = (step.get("run") or "").split()
            if any(word.endswith("leakcheck.py") for word in words) and "--pull-request" in words:
                assert "github.event.pull_request.number" in words
                grants = job["permissions"] if "permissions" in job else workflow.get("permissions")
                assert (grants or {}).get("pull-requests") == "read"
                scanning.append(step)
    assert scanning, "no step runs the pull request scan"
