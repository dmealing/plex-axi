"""S9: `--user`, the one flag here that leaves the local network.

Two facts have to survive: it is admin-only, and it needs plex.tv. Both are in
`--help`, and -- the part that actually matters -- both are in the failure, so a
non-admin or a plex.tv outage arrives as a sentence rather than as a 401 from
somewhere the caller was not aware their command had gone.

There is still no network here. plex.tv is answered by the same double as the
server, routed on the hostname, which is what lets "plex.tv is down but the
library is fine" be a case rather than a hypothetical.
"""

from __future__ import annotations

import pytest

from conftest import SHARED_USERNAME, TOKEN, USER_TOKEN, FakePlex, FakeSession


@pytest.fixture
def user_server(monkeypatch):
    def _build(**kwargs):
        fake = FakePlex(**kwargs)
        from plex_axi import plex

        monkeypatch.setattr(plex, "build_session", lambda **kw: FakeSession(fake))
        return fake

    return _build


def _tokens(server):
    return [record["headers"].get("X-Plex-Token") for record in server.requests]


def test_reading_as_another_account_costs_one_plex_tv_round_trip(user_server, cli_run):
    """Not three, which is what the client library's own user switch costs.

    The sharing record already carries the username, the user id *and* the
    access token for this machine, so the account object and the user lookup it
    would otherwise need are both avoidable.
    """
    fake = user_server()
    result = cli_run("--user", SHARED_USERNAME, "search", "--track", "Example Track")
    assert result.code == 0
    assert len(fake.plex_tv_requests) == 1
    assert fake.plex_tv_requests[0]["path"].endswith("/shared_servers")


def test_the_library_is_then_read_with_that_users_token(user_server, cli_run):
    """The point of the flag: ratings and playlists are per account."""
    fake = user_server()
    assert cli_run("--user", SHARED_USERNAME, "search", "--track", "Example Track").code == 0
    tokens = _tokens(fake)
    assert TOKEN in tokens, "the admin connection is what reports the machine identifier"
    assert USER_TOKEN in tokens, "and everything after it is the named account's"


def test_a_user_token_never_reaches_stdout_or_stderr(user_server, cli_run):
    """It arrived from outside this process's configuration, so it is registered
    as a secret the moment it is read rather than trusted not to be printed."""
    fake = user_server()
    result = cli_run("--user", SHARED_USERNAME, "--debug", "search", "--track", "Example Track")
    assert result.code == 0
    assert USER_TOKEN not in result.out
    assert USER_TOKEN not in result.err
    assert fake is not None


def test_a_non_admin_token_is_told_that_the_flag_is_admin_only(user_server, cli_run):
    """Not a bare 401 from a host the caller did not know was involved."""
    fake = user_server(plex_tv_status=401)
    result = cli_run("--user", SHARED_USERNAME, "search", "--track", "Example Track")
    assert result.code == 1
    assert "NOT_SERVER_OWNER" in result
    assert "admin-only" in result
    assert fake.writes == []


def test_plex_tv_being_unreachable_says_that_and_nothing_else(user_server, cli_run):
    """Everything else in this tool works with the cloud down, and says so here."""
    fake = user_server(plex_tv_unreachable=True)
    result = cli_run("--user", SHARED_USERNAME, "search", "--track", "Example Track")
    assert result.code == 1
    assert "PLEX_TV_UNREACHABLE" in result
    assert "plex.tv" in result
    assert "without `--user`" in result
    assert fake.plex_tv_requests == []


def test_an_unknown_user_is_answered_with_the_accounts_that_do_exist(user_server, cli_run):
    fake = user_server()
    result = cli_run("--user", "nobody", "search", "--track", "Example Track")
    assert result.code == 1
    assert "NO_SUCH_USER" in result
    assert SHARED_USERNAME in result
    assert fake.requests, "the admin connection was still made"


def test_a_server_shared_with_nobody_says_so_rather_than_listing_nothing(user_server, cli_run):
    fake = user_server(shared_users=[])
    result = cli_run("--user", SHARED_USERNAME, "search", "--track", "Example Track")
    assert result.code == 1
    assert "not shared with any other Plex account" in result
    assert fake is not None


def test_a_user_can_be_named_by_email_or_by_id(user_server, cli_run):
    from conftest import SHARED_EMAIL, SHARED_USER_ID

    for name in (SHARED_EMAIL, SHARED_USER_ID, SHARED_USERNAME.upper()):
        fake = user_server()
        assert cli_run("--user", name, "search", "--track", "Example Track").code == 0, name
        assert USER_TOKEN in _tokens(fake), name


def test_the_flag_needs_a_value(server, cli_run):
    result = cli_run("--user", "search", "--track", "Example Track")
    # `search` is swallowed as the value, so the invocation is left with no
    # command at all -- which is a usage error either way, and never a silent
    # read as the wrong account.
    assert result.code != 0


def test_the_flag_rejects_an_empty_name_before_connecting(server, cli_run):
    result = cli_run("--user", "  ", "search", "--track", "Example Track")
    assert result.code == 2
    assert "BAD_USER" in result
    assert server.requests == []


def test_root_help_states_both_facts(server, cli_run):
    result = cli_run("--help")
    assert result.code == 0
    assert "--user" in result
    assert "admin only" in result
    assert "plex.tv" in result


def test_a_write_as_another_user_still_needs_the_gate(user_server, cli_run):
    """`--user` chooses whose ratings are read; it does not open anything."""
    fake = user_server()
    result = cli_run("--user", SHARED_USERNAME, "rate", "111", "--stars", "5", "--write")
    assert result.code == 1
    assert "WRITES_DISABLED" in result
    assert fake.requests == []
    assert fake.plex_tv_requests == []


def test_a_rating_written_as_another_user_is_that_users_rating(user_server, cli_run, writable_env):
    """Per-account is the whole reason this flag exists, so the double models it."""
    fake = user_server()
    written = cli_run(
        "--user", SHARED_USERNAME, "rate", "111", "--stars", "1", "--write", env=writable_env
    )
    assert written.code == 0
    assert written.line("rating:") == "rating: 1 stars"

    theirs = cli_run("--user", SHARED_USERNAME, "track", "111", env=writable_env)
    assert theirs.line("rating:") == "rating: 1"

    mine = cli_run("track", "111", env=writable_env)
    assert mine.line("rating:") == "rating: 4"
    assert fake is not None
