"""F: the raw escape hatch reads, and only reads.

The state-changing requests are asked against the **stub**, which forwards
nothing: the question is whether the tool would send them at all, and the real
server must never be the one to find out.
"""

from __future__ import annotations

STATE_CHANGING = [
    ("/:/rate", ("--query", "key=1", "--query", "identifier=x", "--query", "rating=6")),
    ("/:/scrobble", ("--query", "key=1")),
    ("/:/unscrobble", ("--query", "key=1")),
    ("/:/timeline", ("--query", "ratingKey=1")),
    ("/library/sections/1/refresh", ()),
    ("/library/sections/1/analyze", ()),
    ("/library/sections/1/emptyTrash", ()),
    ("/library/optimize", ()),
    ("/player/playback/playMedia", ()),
    ("/player/playback/stop", ()),
    ("/playQueues", ("--query", "type=audio")),
    ("/%3A/rate", ("--query", "key=1")),
    ("//:/rate", ("--query", "key=1")),
]


def test_d02_a_state_changing_get_is_never_sent(live, stub):
    """With both gates closed, `api /:/rate ...` used to change a real rating."""
    for path, extra in STATE_CHANGING:
        result = live.run("api", path, *extra, via=stub)
        assert result.code == 2, path
        assert "STATE_CHANGING_PATH" in result.out, path
    assert stub.log == [], [entry["path"] for entry in stub.log]


def test_d02_the_refusal_does_not_depend_on_either_gate(live, stub):
    env = {"PLEX_AXI_ALLOW_WRITES": "true", "PLEX_AXI_ALLOW_PLAYBACK": "true"}
    for path, extra in STATE_CHANGING:
        assert live.run("api", path, *extra, via=stub, env=env).code == 2, path
    assert stub.log == []


def test_only_get_ever_leaves_the_process(run, proxy):
    for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "post", "Delete"):
        for env in ({}, {"PLEX_AXI_ALLOW_WRITES": "true"}):
            assert run("api", method, "/library/sections", env=env).code == 2, method
    assert proxy.log == []
    assert run("api", "GET", "/library/sections").code == 0
    assert proxy.methods == {"GET"}


def test_d04_no_credential_attribute_is_printed(run):
    """`/myplex/account` carries the owner's plex.tv token under `authToken`."""
    # HOST is allowed here and nowhere else: this element is the server
    # describing its own addresses, and `api` renders what the server says.
    for mode in ((), ("--json",), ("--human",), ("--full",), ("--debug",)):
        result = run("api", "/myplex/account", *mode, allow=("HOST",))
        assert result.code == 0, mode
        assert "<redacted>" in result.out
    # The standing checks already failed the run if a credential-named
    # attribute came through unredacted; these paths are held to the same.
    run("api", "/devices", allow=("HOST",))
    run("api", "/security/token", allow=("HOST",))


def test_d19_a_token_in_the_path_is_refused_and_never_sent(run, proxy):
    inline = "abcdefgh" + "12345678"
    for path in ("/identity?X-Plex-" + "Token=" + inline, "/identity?a=1&to" + "ken=" + inline):
        result = run("api", path)
        assert result.code == 2 and "TOKEN_IN_QUERY" in result.out
        assert inline not in result.out + result.err
    assert proxy.log == []


def test_odd_paths_are_usage_errors_or_lookups_and_never_bugs(run):
    for path in (
        "library/sections",
        "/library/../identity",
        "http://plex.example.com:32400/identity",
        "/no/such/path",
        "/library/sections#fragment",
        "/library/sections?type=10",
        "/\u00e9t\u00e9",
        "/a b",
    ):
        result = run("api", path)
        assert "INTERNAL_ERROR" not in result.out, path
    assert run("api", "http://plex.example.com:32400/identity", "--json").json()["help"][0] == (
        "Run `plex-axi api /identity`"
    )


def test_a_path_that_answers_with_bytes_is_not_called_a_refusal(run, catalogue):
    thumbs = [row["thumb"] for row in catalogue.albums if row.get("thumb")]
    if not thumbs:
        return
    result = run("api", thumbs[0])
    assert result.code == 1
    assert "refused" not in result.out
    assert "NOT_XML" in result.out


def test_depth_and_full_are_bounded_and_say_what_they_left_out(run, catalogue):
    path = f"/library/sections/{catalogue.section}/all"
    bounded = run("api", path, "--query", "type=10")
    assert "shown" in bounded.out and "--full" in bounded.out
    assert run("api", path, "--depth", "9").code == 2
