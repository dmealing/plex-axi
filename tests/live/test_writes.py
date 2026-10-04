"""W: the two real writes, each reversed and each verified against the raw API.

Opt-in twice: the suite itself, and ``PLEX_AXI_LIVE_WRITES=1``. Two targets and
no others:

* **one track's rating.** The test refuses to start unless the track is unrated,
  and restores it in a ``finally`` block. ``PLEX_AXI_LIVE_RATE_KEY`` pins which
  track; without it the first unrated one is used.
* **one playlist the test creates,** under a name no real playlist has. The tool
  cannot delete a playlist, so the cleanup is a raw ``DELETE`` -- armed only
  after checking the title is this run's unique name, the key did not exist
  before the run, and the playlist is not a smart one.

Nothing here plays anything, scans anything, or touches a playlist it did not
create. Every other playlist is compared before and after.
"""

from __future__ import annotations

import os
import time

import pytest

pytestmark = pytest.mark.live_write

WRITES = {"PLEX_AXI_ALLOW_WRITES": "true"}


def _track(live, key):
    return dict(live.raw(f"/library/metadata/{key}")[0].attrib)


def _playlists(live):
    return {
        p.attrib["ratingKey"]: {
            name: p.attrib.get(name) for name in ("title", "leafCount", "updatedAt", "smart")
        }
        for p in live.raw("/playlists", {"playlistType": "audio"})
    }


def test_a_rating_is_set_changed_and_cleared_and_the_track_is_left_as_it_was(
    live, run, proxy, catalogue
):
    pinned = os.environ.get("PLEX_AXI_LIVE_RATE_KEY")
    key = pinned or next(row["ratingKey"] for row in catalogue.tracks if not row.get("userRating"))
    before = _track(live, key)
    if "userRating" in before:
        pytest.skip("the chosen track is rated; this test only touches an unrated one")

    try:
        # Gate closed: refused, and the server never hears about it.
        refused = run("rate", key, "--stars", "3", "--write")
        assert refused.code == 1 and "WRITES_DISABLED" in refused.out
        # D02: the raw path that used to do the same thing with the gate closed.
        bypass = run(
            "api", "/:/rate", "--query", f"key={key}",
            "--query", "identifier=com.plexapp.plugins.library", "--query", "rating=6",
        )  # fmt: skip
        assert bypass.code == 2 and "STATE_CHANGING_PATH" in bypass.out
        assert proxy.log == []
        assert "userRating" not in _track(live, key)

        # Gate open, no --write: a preview, GETs only.
        preview = run("rate", key, "--stars", "3", env=WRITES)
        assert preview.code == 0 and "nothing was sent to the server" in preview.out
        assert proxy.methods == {"GET"}
        assert "userRating" not in _track(live, key)

        # D17: neither of these is a rating, and neither is sent.
        assert run("rate", key, "--stars", "0", "--write", env=WRITES).code == 2
        assert run("rate", key, "--stars", "2.25", "--write", env=WRITES).code == 2
        assert "userRating" not in _track(live, key)

        proxy.allow_writes = True
        done = run("rate", key, "--stars", "3", "--write", env=WRITES)
        assert done.code == 0 and "set to 3 stars" in done.out
        assert float(_track(live, key)["userRating"]) == 6.0

        proxy.log.clear()
        again = run("rate", key, "--stars", "3", "--write", env=WRITES)
        assert again.code == 0 and "no change" in again.out
        assert proxy.methods == {"GET"}, "a no-op sent a write"

        changed = run("rate", key, "--stars", "4.5", "--write", env=WRITES)
        assert changed.code == 0
        assert float(_track(live, key)["userRating"]) == 9.0

        cleared = run("rate", key, "--clear", "--write", env=WRITES)
        assert cleared.code == 0 and "unrated" in cleared.out
        assert proxy.blocked == []
    finally:
        if "userRating" in _track(live, key):
            proxy.allow_writes = True
            run("rate", key, "--clear", "--write", env=WRITES, check=False)
        after = _track(live, key)
        assert "userRating" not in after, "the rating was not restored"
        changed_names = sorted(n for n in set(before) | set(after) if before.get(n) != after.get(n))
        # `lastRatedAt` is the server recording that a rating was ever touched;
        # nothing else may differ.
        assert set(changed_names) <= {"lastRatedAt", "updatedAt"}, changed_names


def test_a_test_playlist_is_created_edited_and_removed_and_no_other_is_touched(
    live, run, proxy, catalogue
):
    name = f"zz-plex-axi-live-test-{int(time.time())}"
    before = _playlists(live)
    assert name not in {entry["title"] for entry in before.values()}
    tracks = [row["ratingKey"] for row in catalogue.tracks[:3]]
    album = catalogue.albums[0]["ratingKey"]

    def items(key):
        return int(live.raw(f"/playlists/{key}/items", start=0, size=0).attrib["totalSize"])

    try:
        preview = run(
            "playlist", "create", name, "--key", tracks[0], "--key", tracks[1], env=WRITES
        )
        assert preview.code == 0 and "nothing was sent to the server" in preview.out
        assert proxy.methods == {"GET"}
        assert _playlists(live) == before

        proxy.allow_writes = True
        created = run(
            "playlist", "create", name, "--key", tracks[0], "--key", tracks[1], "--write",
            "--json", env=WRITES,
        )  # fmt: skip
        assert created.code == 0, created.out
        key = str(created.json()["key"])
        assert key not in before
        assert items(key) == 2
        assert created.json()["applied"] == "created with 2 item(s)"

        added = run("playlist", "add", key, "--key", tracks[2], "--write", "--json", env=WRITES)
        assert added.json()["applied"] == "added 1 item(s)"
        assert items(key) == 3

        proxy.log.clear()
        again = run("playlist", "add", key, "--key", tracks[2], "--write", env=WRITES)
        assert again.code == 0 and "no-op" in again.out
        assert proxy.methods == {"GET"}

        # D10: an album is not a track, and is refused before anything is sent.
        refused = run("playlist", "add", key, "--key", album, "--write", env=WRITES)
        assert refused.code == 1 and "NOT_A_TRACK" in refused.out
        assert proxy.methods == {"GET"}
        assert items(key) == 3

        removed = run(
            "playlist", "remove", key, "--key", tracks[0], "--write", "--json", env=WRITES
        )
        assert removed.json()["applied"] == "removed 1 item(s)"
        assert items(key) == 2

        shown = run("playlist", "show", key, "--json")
        assert shown.json()["count"] == "2 of 2 items"
        assert proxy.blocked == []
    finally:
        ours = {
            key: entry
            for key, entry in _playlists(live).items()
            if entry["title"] == name and key not in before and entry["smart"] != "1"
        }
        assert len(ours) <= 1
        for key in ours:
            live.arm()
            assert live.raw_delete(f"/playlists/{key}") in (200, 204)
        assert _playlists(live) == before, "a playlist this test did not create has changed"
