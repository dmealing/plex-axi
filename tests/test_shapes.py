"""The pure judgements about an answer and a path, stated on their own.

`plex_axi.toolkit.shapes` takes strings and returns a string or a boolean: no server, no
error class, no XML. These tests take the same view of it, so that the module
and its tests can be lifted into a shared package together.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from plex_axi.toolkit import shapes


@pytest.mark.parametrize(
    ("body", "kind"),
    [
        ("", shapes.EMPTY),
        ("   \n\t", shapes.EMPTY),
        (None, shapes.EMPTY),
        ('{"MediaContainer": {}}', shapes.UNPARSEABLE),
        ('<?xml version="1.0"?><MediaContainer size="3"><Dire', shapes.UNPARSEABLE),
        ("OK", shapes.UNPARSEABLE),
        ("<!DOCTYPE html><html><body>login</body></html>", shapes.FOREIGN),
        ("  <!doctype HTML>\n<html>", shapes.FOREIGN),
        ("<html><body><p>router</p></body></html>", shapes.FOREIGN),
        ("<HTML lang='en'>", shapes.FOREIGN),
        ("<htmlish/>", shapes.UNPARSEABLE),
    ],
)
def test_a_body_that_is_not_plexs_is_named(body, kind):
    assert shapes.answer_kind(body) == kind


def test_a_parsed_web_page_is_recognised_by_its_root():
    assert shapes.is_foreign_root("html") and shapes.is_foreign_root("HTML")
    assert not shapes.is_foreign_root("MediaContainer")
    assert not shapes.is_foreign_root("MyPlex")


@pytest.mark.parametrize(
    "name",
    [
        "authToken",
        "token",
        "accessToken",
        "X-Plex-Token",
        "password",
        "apiKey",
        "authKey",
        "clientSecret",
    ],
)
def test_a_credential_is_known_by_its_name(name):
    assert shapes.is_credential_name(name)


@pytest.mark.parametrize(
    "name", ["title", "ratingKey", "key", "username", "machineIdentifier", "guid"]
)
def test_an_ordinary_attribute_is_not_a_credential(name):
    assert not shapes.is_credential_name(name)


@pytest.mark.parametrize(
    "path",
    [
        "/:/rate",
        "/:/scrobble",
        "/:/unscrobble",
        "/:/timeline",
        "/:/progress",
        "/:/prefs",
        "/:/",
        "/player/playback/playMedia",
        "/player/playback/stop",
        "/playQueues",
        "/playQueues/12",
        "/PLAYQUEUES",
        "/library/sections/1/refresh",
        "/library/sections/all/refresh",
        "/library/sections/1/analyze",
        "/library/sections/1/emptyTrash",
        "/library/optimize",
        "/library/clean/bundles",
        "/library/metadata/5/match",
        "/library/metadata/5/unmatch",
        "/library/metadata/5/refresh/",
        "/butler/BackupDatabase",
        "/updater/check",
        "/%3A/rate",
        "/%253A/rate",
        "//:/rate",
        "/:/rate/",
    ],
)
def test_a_path_whose_get_changes_something_is_recognised(path):
    assert shapes.acts_on_get(path)


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/identity",
        "/library/sections",
        "/library/sections/1/all",
        "/library/metadata/5",
        "/library/metadata/5/children",
        "/library/metadata/5/nearest",
        "/status/sessions",
        "/playlists",
        "/playlists/5/items",
        "/clients",
        "/hubs/search",
        "/myplex/account",
        "/library/sections/1/prefs",
        "/players",
        "/refresher",
        "/library/matches",
    ],
)
def test_a_path_that_only_reads_is_left_alone(path):
    assert not shapes.acts_on_get(path)


@pytest.mark.parametrize("path", ["/library/../:/rate", "/./identity", "/a/%2e%2e/b", "/.."])
def test_a_path_that_climbs_is_recognised(path):
    assert shapes.has_dot_segments(path)


@pytest.mark.parametrize("path", ["/library/sections", "/a.b/c", "/..hidden", "/file.."])
def test_a_dot_inside_a_segment_is_not_a_climb(path):
    assert not shapes.has_dot_segments(path)


def test_the_module_imports_nothing_of_this_tools():
    """What keeps it movable: the standard library and nothing else."""
    tree = ast.parse(Path(shapes.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, "a relative import ties this module to the tool"
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "re", "urllib"}, imported
