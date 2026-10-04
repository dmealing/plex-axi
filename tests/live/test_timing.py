"""M: how long a command takes, and whether a long playlist costs more than a short one."""

from __future__ import annotations

import statistics

from support import REQUEST_BUDGET


def _median(run, *argv, runs=5):
    return statistics.median(run(*argv).seconds for _ in range(runs))


def test_the_common_commands_answer_quickly(run, catalogue):
    track = catalogue.tracks[0]["ratingKey"]
    for argv in (
        ("--version",),
        ("context",),
        ("doctor",),
        ("search", "--rated-min", "4", "--limit", "5"),
        ("pick",),
        ("genres",),
        ("track", track),
        ("recent",),
        ("playlist",),
        ("sessions",),
    ):
        assert _median(run, *argv) < 2.0, argv


def test_d20_the_longest_playlist_costs_one_page(run, proxy, catalogue):
    """4.3 seconds on a ten-thousand-item smart playlist, whatever `--limit` said."""
    if not catalogue.playlists:
        return
    longest = max(catalogue.playlists, key=lambda p: int(p.get("leafCount") or 0))
    proxy.reset()
    result = run("playlist", "show", longest["ratingKey"], "--limit", "5")
    assert result.code == 0
    assert len(proxy.log) <= REQUEST_BUDGET["playlist"], proxy.paths
    assert result.seconds < 2.0, f"{result.seconds:.2f}s for {longest.get('leafCount')} items"


def test_parallel_runs_answer_what_serial_runs_do(live, proxy, catalogue):
    import concurrent.futures

    track = catalogue.tracks[0]["ratingKey"]
    argvs = [("track", track), ("genres",), ("playlist",), ("doctor",)] * 3
    serial = [live.run(*argv, via=proxy).out for argv in argvs]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        parallel = list(pool.map(lambda argv: live.run(*argv, via=proxy).out, argvs))
    assert parallel == serial
