"""B, C: every read command, in every mode, against the real library."""

from __future__ import annotations

import json

import pytest

from support import budget_for, toon_doc

MODES = ((), ("--json",), ("--human",))


@pytest.fixture(scope="module")
def forms(catalogue):
    """One invocation per read surface, built from keys this server really has."""
    track = catalogue.tracks[len(catalogue.tracks) // 2]
    album = catalogue.albums[len(catalogue.albums) // 2]
    artist = catalogue.artists[len(catalogue.artists) // 2]
    out = [
        (),
        ("search", "--artist", artist["title"].replace(",", " ")),
        ("search", "--track", track["title"].replace(",", " ")),
        ("search", "--album", album["title"].replace(",", " "), "--type", "album"),
        ("search", "--rated-min", "4", "--limit", "5"),
        ("search", "--year", str(album.get("year") or 2000), "--type", "album", "--limit", "5"),
        ("pick",),
        ("pick", "--rated-min", "3", "--limit", "3"),
        ("pick", "--not-played-since", "30d", "--exclude-live", "--limit", "5"),
        ("genres",),
        ("moods",),
        ("styles",),
        ("track", track["ratingKey"]),
        ("track", track["ratingKey"], "--check-files"),
        ("album", album["ratingKey"]),
        ("artist", artist["ratingKey"]),
        ("similar", track["ratingKey"]),
        ("recent",),
        ("recent", "--type", "track", "--limit", "5"),
        ("playlist",),
        ("sessions",),
        ("api", "/"),
        ("api", "/library/sections"),
        ("doctor",),
        ("context",),
    ]
    plain = [p for p in catalogue.playlists if p.get("smart") != "1"]
    if plain:
        out.append(("playlist", "show", plain[0]["ratingKey"], "--limit", "5"))
    return out


def test_every_read_succeeds_in_every_mode_and_only_reads(run, proxy, forms):
    for argv in forms:
        for mode in MODES:
            result = run(*argv, *mode)
            assert result.code == 0, (argv, mode, result.out[:300])
    assert proxy.methods <= {"GET"}
    assert proxy.blocked == []
    assert not any(entry["token_in_query"] for entry in proxy.log)
    assert all(entry["token_header"] for entry in proxy.log)


def test_default_output_decodes_to_the_json_document(run, forms):
    """An independent decoder, on real titles: commas, quotes, non-ASCII and all."""
    shuffled = {"pick"}
    for argv in forms:
        if argv and argv[0] in shuffled:
            continue
        default, as_json = run(*argv), run(*argv, "--json")
        assert toon_doc(default.out.rstrip("\n")) == json.loads(as_json.out), argv


def test_each_command_stays_inside_its_request_budget(run, proxy, forms):
    for argv in forms:
        proxy.reset()
        result = run(*argv)
        empty = "0 of 0 total" in result.out
        assert len(proxy.log) <= budget_for(argv, empty=empty), (argv, proxy.paths)


def test_fields_is_authoritative_and_refuses_what_it_does_not_know(run, catalogue):
    track = catalogue.tracks[0]["title"].replace(",", " ")
    for fields in ("key", "key,title", "key,title,artist,album,year,rating,added"):
        result = run("search", "--track", track, "--fields", fields, "--json")
        rows = result.json().get("tracks")
        if isinstance(rows, list):
            assert all(list(row) == fields.split(",") for row in rows), fields
    refused = run("search", "--track", track, "--fields", "nosuch")
    assert refused.code == 2 and "available fields" in refused.out


def test_limit_bounds_the_rows_and_the_total_is_never_smaller(run):
    for limit in ("1", "5", "50"):
        result = run("search", "--rated-min", "0.5", "--limit", limit, "--json")
        doc = result.json()
        shown, total = (int(part) for part in doc["count"].split(" total")[0].split(" of "))
        assert shown <= int(limit) and shown <= total
        rows = doc.get("tracks")
        assert not isinstance(rows, list) or len(rows) == shown
    for bad in ("0", "-1", "x", "1.5", "501"):
        assert run("search", "--rated-min", "4", "--limit", bad).code == 2, bad


def test_a_repeat_run_is_byte_identical(run, forms):
    for argv in forms:
        if argv and argv[0] == "pick":
            continue  # the server shuffles; that is the point of the command
        first, second = run(*argv), run(*argv)
        if argv and argv[0] == "sessions":
            continue  # somebody may press play between the two
        assert first.out == second.out, argv
