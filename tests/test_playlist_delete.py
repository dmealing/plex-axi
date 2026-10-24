"""`playlist delete`: the write gate, the preview, the smart refusal, the read-back."""

from __future__ import annotations


def _deletes(server):
    return [r for r in server.requests if r.get("method") == "DELETE"]


def test_delete_is_refused_before_the_server_hears_of_it_when_the_gate_is_closed(server, cli_run):
    result = cli_run("playlist", "delete", "Example Playlist", "--write")
    assert result.code != 0
    assert server.requests == []


def test_delete_previews_by_default_and_sends_nothing(server, cli_run, writable_env):
    result = cli_run("playlist", "delete", "Example Playlist", env=writable_env)
    assert result.code == 0
    assert "Example Playlist" in result.out
    assert "holds: 2 items" in result.out
    assert "smart: false" in result.out
    assert "--write" in result.out
    assert server.writes == []
    assert [p["title"] for p in server.playlists].count("Example Playlist") == 1


def test_delete_with_write_removes_the_playlist_and_reads_it_back(server, cli_run, writable_env):
    result = cli_run("playlist", "delete", "Example Playlist", "--write", env=writable_env)
    assert result.code == 0
    assert "applied: deleted" in result.out
    assert [w["method"] for w in server.writes] == ["DELETE"]
    assert all(p["title"] != "Example Playlist" for p in server.playlists)
    # The tracks are library items, not playlist contents.
    assert cli_run("track", "111", env=writable_env).code == 0


def test_delete_by_key_works(server, cli_run, writable_env):
    assert cli_run("playlist", "delete", "501", "--write", env=writable_env).code == 0
    assert all(p["id"] != 501 for p in server.playlists)


def test_a_smart_playlist_is_refused_in_preview_and_apply(server, cli_run, writable_env):
    for argv in (
        ("playlist", "delete", "Example Smart Playlist"),
        ("playlist", "delete", "Example Smart Playlist", "--write"),
    ):
        result = cli_run(*argv, env=writable_env)
        assert result.code == 1
        assert "code: SMART_PLAYLIST" in result.out
    assert server.writes == []


def test_a_playlist_that_is_not_there_hands_back_the_real_ones(server, cli_run, writable_env):
    result = cli_run("playlist", "delete", "Nope", "--write", env=writable_env)
    assert result.code == 1
    assert "NO_SUCH_PLAYLIST" in result.out
    assert server.writes == []


def test_a_film_playlist_is_invisible_to_delete(server, cli_run, writable_env):
    result = cli_run("playlist", "delete", "Example Film Night", "--write", env=writable_env)
    assert result.code == 1
    assert server.writes == []
