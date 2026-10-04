#!/usr/bin/env python3
"""Capture the *shape* of a real Plex Media Server's answers: names, never content.

The test double in ``tests/conftest.py`` is only worth anything while it answers
like Plex. Every table in it that describes what the server says -- the
operators, the advertised fields and sorts, the attributes on an element -- was
supposed to be transcribed from a real server rather than written from memory,
and nothing checked that it still was. A track's ``year`` attribute was invented
there, the tool read it, and a track's year was empty on every real server while
every test passed.

This script reads a real server and writes down what it found as **names only**:
element names, attribute names, field keys and their types, operator keys and
their titles, sort keys. No attribute *value* that came from the library is
recorded -- no title, no path, no identifier, no address -- so the result can be
committed to a public repository. ``tests/test_shape_contract.py`` then holds the
double to it, offline.

Usage::

    scripts/shape-capture.py                 # print the capture
    scripts/shape-capture.py --write         # refresh tests/fixtures/plex-shape/capture.json
    scripts/shape-capture.py --check         # exit 1 if a fresh capture differs from the file

It needs ``PLEX_URL`` and ``PLEX_TOKEN`` in the environment, sends GET requests
only, and uses the standard library alone. Run ``scripts/leakcheck.py`` after
``--write``; the capture is tracked, so the ordinary scan covers it.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
from pathlib import Path

CAPTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "plex-shape" / "capture.json"

#: How many rows of each list are read to union their attribute names. An
#: attribute a server sends only on a rated or a played item is on a minority of
#: rows, so one row is not a sample.
SAMPLE = 400
DETAILS = 12

#: Words to ask the free-text search for, until each music hub has answered.
HUB_PROBES = ("love", "the", "live", "best", "blue")

#: The search type codes for a music library's three libtypes.
TYPE_CODES = {"artist": 8, "album": 9, "track": 10}


class Server:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def get(self, path: str, params=None, *, start=None, size=None):
        """One GET, parsed. ``None`` when the server has nothing at that path."""
        query = urllib.parse.urlencode(params or {}, doseq=True)
        headers = {"X-Plex-Token": self.token, "Accept": "application/xml"}
        if size is not None:
            headers["X-Plex-Container-Start"] = str(start or 0)
            headers["X-Plex-Container-Size"] = str(size)
        request = urllib.request.Request(
            self.base_url + path + (f"?{query}" if query else ""), headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read()
        except urllib.error.HTTPError:
            return None
        return ElementTree.fromstring(body) if body.strip() else None


def names(elements) -> list:
    """The union of the attribute names on ``elements``, sorted."""
    found: set = set()
    for element in elements:
        found.update(element.attrib)
    return sorted(found)


def children(elements) -> list:
    found: set = set()
    for element in elements:
        found.update(child.tag for child in element)
    return sorted(found)


def capture(server: Server) -> dict:
    root = server.get("/")
    if root is None or "machineIdentifier" not in root.attrib:
        raise SystemExit("shape-capture: PLEX_URL did not answer as a Plex Media Server")

    sections = server.get("/library/sections")
    music = [d for d in sections if d.attrib.get("type") == "artist"]
    if not music:
        raise SystemExit("shape-capture: this server has no music library")
    key = music[0].attrib["key"]
    base = f"/library/sections/{key}"

    elements: dict = {
        "root": names([root]),
        "section": names(list(sections)),
    }

    # -- what the section says it can filter and sort on
    meta = server.get(f"{base}/all", {"type": 10, "includeMeta": 1}, size=0)
    types: dict = {}
    for entry in meta.iter("Type"):
        libtype = entry.attrib.get("type")
        if libtype not in TYPE_CODES:
            continue
        types[libtype] = {
            "fields": {f.attrib["key"]: f.attrib.get("type", "") for f in entry.findall("Field")},
            "filters": sorted(f.attrib["filter"] for f in entry.findall("Filter")),
            "sorts": sorted(s.attrib["key"] for s in entry.findall("Sort")),
        }
    field_types = {
        entry.attrib["type"]: [
            [op.attrib["key"], op.attrib.get("title", "")] for op in entry.findall("Operator")
        ]
        for entry in meta.iter("FieldType")
    }
    elements["search.container"] = names([meta])

    # -- the rows of each libtype, and a spread of detail views
    for libtype, code in TYPE_CODES.items():
        rows = list(server.get(f"{base}/all", {"type": code}, size=SAMPLE) or [])
        elements[f"{libtype}.row"] = names(rows)
        step = max(1, len(rows) // DETAILS)
        details = []
        for row in rows[::step][:DETAILS]:
            answer = server.get(f"/library/metadata/{row.attrib['ratingKey']}")
            if answer is not None and len(answer):
                details.append(answer[0])
        elements[f"{libtype}.detail"] = names(details)
        elements[f"{libtype}.detail.children"] = children(details)
        if libtype == "track" and details:
            media = [m for d in details for m in d.findall("Media")]
            elements["media"] = names(media)
            elements["part"] = names([p for m in media for p in m.findall("Part")])
            checked = server.get(
                f"/library/metadata/{details[0].attrib['ratingKey']}", {"checkFiles": 1}
            )
            if checked is not None and len(checked):
                parts = [p for m in checked[0].findall("Media") for p in m.findall("Part")]
                elements["part.checked"] = names(parts)

    # -- the library's own preferences
    prefs = server.get(f"{base}/prefs")
    if prefs is not None:
        elements["setting"] = names(list(prefs))
        elements["setting.ids"] = sorted(s.attrib.get("id", "") for s in prefs)

    # -- playlists and one page of one playlist's items
    playlists = list(server.get("/playlists", {"playlistType": "audio"}) or [])
    elements["playlist"] = names(playlists)
    plain = [p for p in playlists if p.attrib.get("smart") != "1"] or playlists
    if plain:
        items_path = f"/playlists/{plain[0].attrib['ratingKey']}/items"
        counted = server.get(items_path, size=0)
        page = server.get(items_path, size=50)
        elements["playlist.items.container"] = names([counted])
        elements["playlist.item"] = names(list(page or []))

    # -- the free-text search the tool falls back to for the nearest titles
    # Common words, tried in turn: a hub is only useful here once it has a row.
    for word in HUB_PROBES:
        hubs = server.get("/hubs/search", {"query": word, "sectionId": key, "limit": 3})
        if hubs is None:
            break
        elements["hub"] = names(list(hubs))
        for hub in hubs:
            kind = hub.attrib.get("type")
            if kind in TYPE_CODES and len(hub) and f"hub.{kind}" not in elements:
                elements[f"hub.{kind}"] = names(list(hub))
                elements[f"hub.{kind}.tag"] = children([hub])
        if all(f"hub.{kind}" in elements for kind in TYPE_CODES):
            break

    # -- sessions and clients, when there are any to look at
    sessions = server.get("/status/sessions")
    if sessions is not None and len(sessions):
        elements["session.children"] = children(list(sessions))
        elements["player"] = names([p for s in sessions for p in s.findall("Player")])
    clients = server.get("/clients")
    if clients is not None:
        elements["clients.tag"] = children([clients])
        if len(clients):
            elements["client"] = names(list(clients))

    account = server.get("/myplex/account")
    if account is not None:
        elements["myplex.tag"] = [account.tag]
        elements["myplex"] = names([account])

    version = ".".join(root.attrib.get("version", "").split(".")[:3])
    return {
        "captured": {
            "date": datetime.date.today().isoformat(),
            "server_version": version,
            "note": "names only: no attribute value from the library is recorded here",
        },
        "field_types": field_types,
        "types": types,
        "elements": elements,
    }


def comparable(doc: dict) -> dict:
    """The capture without the fields that change on every run."""
    return {key: value for key, value in doc.items() if key != "captured"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true", help="refresh the committed capture")
    group.add_argument("--check", action="store_true", help="fail if the server has drifted")
    args = parser.parse_args(argv)

    base_url, token = os.environ.get("PLEX_URL", ""), os.environ.get("PLEX_TOKEN", "").strip()
    if not base_url or not token:
        print("shape-capture: PLEX_URL and PLEX_TOKEN must be set", file=sys.stderr)
        return 2
    if "://" not in base_url:
        base_url = f"http://{base_url}"

    doc = capture(Server(base_url, token))
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    if args.write:
        CAPTURE.parent.mkdir(parents=True, exist_ok=True)
        CAPTURE.write_text(text, encoding="utf-8")
        print(f"shape-capture: wrote {CAPTURE.relative_to(CAPTURE.parents[3])}")
        return 0
    if args.check:
        committed = json.loads(CAPTURE.read_text(encoding="utf-8"))
        if comparable(committed) == comparable(doc):
            print("shape-capture: the server still matches the committed capture")
            return 0
        print("shape-capture: the server has drifted from the committed capture", file=sys.stderr)
        for section in ("field_types", "types", "elements"):
            for name in sorted(set(committed[section]) | set(doc[section])):
                if committed[section].get(name) != doc[section].get(name):
                    print(f"  {section}.{name}", file=sys.stderr)
        return 1
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
