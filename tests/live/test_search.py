"""S, Q: the search against the raw catalogue, including the three sweeps.

The sweeps are the re-check the search-behaviour changes owe a real server:
names typed in ASCII against typographic titles, names typed without accents,
titles containing a comma, and performers who appear only on compilations. Every
sample is chosen from the live catalogue by *shape* at run time, so no real name
is written into this repository and none is printed on failure -- a failing
sample is reported by its rating key.
"""

from __future__ import annotations

import re
import unicodedata

TYPOGRAPHIC = re.compile("[\u2018\u2019\u201c\u201d\u2010\u2013\u2026]")
TO_ASCII = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2010": "-",
    "\u2013": "-",
    "\u2026": "...",
}

SAMPLE = 24


def ascii_typed(title: str) -> str:
    return "".join(TO_ASCII.get(char, char) for char in title)


def unaccented(title: str) -> str:
    decomposed = unicodedata.normalize("NFKD", title)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _keys(doc, plural):
    rows = doc.get(plural)
    return {str(row["key"]) for row in rows} if isinstance(rows, list) else set()


def _found(run, flag, libtype, typed, key) -> bool:
    """Whether typing ``typed`` finds ``key``: in the rows, or the nearest titles."""
    doc = run("search", flag, typed, "--type", libtype, "--limit", "100", "--no-group", "--json")
    assert doc.code == 0, key
    return str(key) in _keys(doc.json(), f"{libtype}s")


def test_d01_ascii_punctuation_finds_typographic_titles(run, catalogue):
    """23 of 24 such artists were not found before; the measured fix recovers most."""
    report = {}
    for libtype, rows, flag in (
        ("artist", catalogue.artists, "--artist"),
        ("album", catalogue.albums, "--album"),
        ("track", catalogue.tracks, "--track"),
    ):
        sample = catalogue.sample(
            rows, lambda row: TYPOGRAPHIC.search(row.get("title", "")), SAMPLE
        )
        if not sample:
            continue
        hits = [
            row["ratingKey"]
            for row in sample
            if _found(run, flag, libtype, ascii_typed(row["title"]), row["ratingKey"])
        ]
        report[libtype] = (len(hits), len(sample))
        missed = sorted({row["ratingKey"] for row in sample} - set(hits))
        assert len(hits) >= 0.8 * len(sample), (libtype, report[libtype], "missed keys", missed)
    assert report, "this library has no typographic titles to test with"
    print("D01 typographic sweep:", report)


def test_d01_an_unaccented_name_is_answered_with_the_real_title(run, catalogue):
    """The filter folds no accents, so the recovery is the nearest-title list."""
    sample = catalogue.sample(
        catalogue.artists,
        lambda row: (
            unaccented(row.get("title", "")) != row.get("title", "")
            and not TYPOGRAPHIC.search(row.get("title", ""))
        ),
        16,
    )
    if not sample:
        return
    recovered = []
    for row in sample:
        result = run("search", "--artist", unaccented(row["title"]), "--type", "artist", "--json")
        doc = result.json()
        in_rows = str(row["ratingKey"]) in _keys(doc, "artists")
        in_nearest = any(str(n["key"]) == row["ratingKey"] for n in doc.get("nearest", []))
        if in_rows or in_nearest:
            recovered.append(row["ratingKey"])
        assert "check the artist exists at all" not in result.out
    missed = sorted({row["ratingKey"] for row in sample} - set(recovered))
    print("D01 accent sweep:", (len(recovered), len(sample)))
    assert len(recovered) >= 0.75 * len(sample), ("missed keys", missed)


def test_d03_a_title_with_a_comma_finds_that_track(run, catalogue):
    sample = catalogue.sample(catalogue.tracks, lambda row: "," in row.get("title", ""), 40)
    sizes = []
    for row in sample:
        result = run("search", "--track", row["title"], "--limit", "100", "--no-group", "--json")
        doc = result.json()
        assert str(row["ratingKey"]) in _keys(doc, "tracks"), row["ratingKey"]
        sizes.append(len(doc["tracks"]))
    if sizes:
        sizes.sort()
        print("D03 comma sweep: median rows", sizes[len(sizes) // 2], "worst", sizes[-1])
        assert sizes[len(sizes) // 2] <= 3


def test_d03_a_trailing_comma_matches_nothing_rather_than_everything(run, catalogue):
    result = run("search", "--track", "Zzzqqqxx,", "--json")
    assert result.json()["count"].startswith("0 of 0")
    assert run("search", "--track", " , ,").code == 2


def test_d06_a_compilation_only_performer_is_found_by_artist(run, catalogue):
    album_artists = {row.get("title", "").casefold() for row in catalogue.artists}
    owners = {row.get("parentTitle", "").casefold() for row in catalogue.albums}
    sample = catalogue.sample(
        catalogue.tracks,
        lambda row: (
            row.get("originalTitle")
            and row["originalTitle"] != row.get("grandparentTitle")
            and row["originalTitle"].casefold() not in owners
            and row["originalTitle"].casefold() not in album_artists
            and "," not in row["originalTitle"]
        ),
        15,
    )
    found = [
        row["ratingKey"]
        for row in sample
        if _found(run, "--artist", "track", row["originalTitle"], row["ratingKey"])
    ]
    print("D06 performer sweep:", (len(found), len(sample)))
    missed = sorted({row["ratingKey"] for row in sample} - set(found))
    assert len(found) >= 0.9 * len(sample), ("missed keys", missed)


def test_d07_a_tracks_year_is_its_albums(run, catalogue):
    sample = catalogue.sample(catalogue.tracks, lambda row: row.get("parentYear"), 40)
    assert sample
    for row in sample:
        detail = run("track", row["ratingKey"], "--json").json()
        assert str(detail["year"]) == row["parentYear"], row["ratingKey"]


def test_totals_are_exact_against_the_raw_api(run, catalogue):
    home = run("--json").json()
    counts = [int(part.split()[0]) for part in home["holds"].split(", ")]
    assert counts == [len(catalogue.artists), len(catalogue.albums), len(catalogue.tracks)]
    for stars in (0.5, 1, 2, 3, 4, 5):
        threshold = int(stars * 2) - 1
        expected = catalogue.total({"type": 10, "track.userRating>>": threshold, "group": "title"})
        doc = run("search", "--rated-min", f"{stars:g}", "--limit", "1", "--json").json()
        assert int(doc["count"].split(" of ")[1].split()[0]) == expected, stars


def test_an_artists_album_and_track_counts_are_real(run, catalogue):
    """An artist element carries neither count; both were empty on a real server."""
    sample = catalogue.sample(catalogue.artists, lambda row: True, 8)
    for row in sample:
        doc = run("artist", row["ratingKey"], "--json").json()
        albums = [a for a in catalogue.albums if a.get("parentRatingKey") == row["ratingKey"]]
        assert doc["albums"] == len(albums), row["ratingKey"]
        tracks = [t for t in catalogue.tracks if t.get("grandparentRatingKey") == row["ratingKey"]]
        assert doc["tracks"] == len(tracks), row["ratingKey"]


def test_the_home_view_does_not_credit_the_analysis_with_the_moods(run, live, catalogue):
    """D12: read from the library's own preference, compared with the raw one."""
    prefs = live.raw(f"/library/sections/{catalogue.section}/prefs")
    switch = {s.attrib["id"]: s.attrib.get("value") for s in prefs}.get("musicAnalysis")
    line = run().line("analysis:")
    assert ("is on" in line) == (switch == "true"), line
    assert "written by" not in line
    doctor = run("doctor")
    assert doctor.code == 0
    assert ("sonic analysis,ok" in doctor.out) == (switch == "true")
