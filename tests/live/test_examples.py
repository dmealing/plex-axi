"""X: every documented example and every suggestion, run as written.

The examples in the README and the generated skill are the commands a reader
copies first, and the `Run ...` lines are the commands an agent executes next.
Both are held to the same standard here: they parse, and they are not usage
errors.

Two kinds of line are never run. Anything carrying ``--now`` would start music,
and anything carrying ``--user`` reaches plex.tv -- a previous live run made that
mistake by running a README example verbatim. Both are checked to be excluded
rather than assumed to be.
"""

from __future__ import annotations

import re
import shlex

from support import has_placeholder, parses, suggestions

from .harness import FORBIDDEN_FLAGS, ROOT

DOCUMENTS = ("README.md", "skills/plex-axi/SKILL.md")

#: Examples that only exist with a gate open. They are parsed, and run only as
#: previews, with that gate set for the one invocation.
PLAYBACK_NOUNS = ("play", "clients")


def documented_examples() -> list:
    """Every command line in a fenced block or at the start of an indented line."""
    found = []
    for name in DOCUMENTS:
        text = (ROOT / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            match = re.match(r"^\s*(?:\$ )?(plex-axi(?: .*)?)$", line)
            if match and "<" not in match.group(1) and "\u2026" not in match.group(1):
                found.append(match.group(1).split("  #")[0].strip())
    return list(dict.fromkeys(found))


def test_the_examples_are_found_and_the_dangerous_ones_are_set_aside():
    examples = documented_examples()
    assert len(examples) > 30, len(examples)
    skipped = [line for line in examples if any(flag in line for flag in FORBIDDEN_FLAGS)]
    assert skipped, "the documents no longer carry a --now or --user example to exclude"


def test_every_documented_example_runs_and_is_not_a_usage_error(live, run, proxy):
    for line in documented_examples():
        words = shlex.split(line)
        if any(flag in words for flag in FORBIDDEN_FLAGS):
            continue
        if "|" in words or ">" in words:
            continue
        env = {}
        if len(words) > 1 and words[1] in PLAYBACK_NOUNS:
            env = {"PLEX_AXI_ALLOW_PLAYBACK": "true"}
        if words[1:2] == ["setup"] or words[1:2] == ["skill"]:
            continue  # both write under a home directory; the offline suite owns them
        result = run(*words[1:], env=env, check=False)
        live.standing_checks(result) if "--debug" not in words else None
        assert result.code != 2, (line, result.out[:300])
        assert "INTERNAL_ERROR" not in result.out, line
    assert proxy.methods <= {"GET"}
    assert proxy.blocked == [], "an example tried to write or to play"


def test_every_suggestion_the_tool_prints_is_a_command_it_accepts(run, proxy, catalogue):
    track = catalogue.tracks[0]
    album = catalogue.albums[0]
    artist = catalogue.artists[0]
    seeds = [
        (),
        ("search", "--artist", artist["title"].replace(",", " ")),
        ("search", "--artist", "Zzzqqq Nobody"),
        ("search", "--album", album["title"].replace(",", " "), "--type", "album"),
        ("search",),
        ("search", "help"),
        ("pick",),
        ("genres",),
        ("moods",),
        ("styles",),
        ("track", track["ratingKey"]),
        ("album", album["ratingKey"]),
        ("artist", artist["ratingKey"]),
        ("track", album["ratingKey"]),
        ("track", "local://1"),
        ("rate", "local://1", "--stars", "4"),
        ("similar", track["ratingKey"]),
        ("recent",),
        ("playlist",),
        ("playlist", "show", "zz no such playlist"),
        ("playlist", "add", "zz no such playlist", "--key", "local://1"),
        ("sessions",),
        ("api", "/"),
        ("api", "library/sections"),
        ("api", "OPTIONS", "/x"),
        ("api", "http://plex.example.com:32400/identity"),
        ("doctor",),
        ("setup", "skill"),
        ("nosuch",),
    ]
    seeds += [("playlist", "show", p["ratingKey"], "--limit", "2") for p in catalogue.playlists[:4]]
    seen, followed = set(), 0
    for argv in seeds:
        result = run("--json", *argv)
        for line in suggestions(result.out):
            if line in seen:
                continue
            seen.add(line)
            words = parses(line)
            if has_placeholder(line) or any(flag in words for flag in FORBIDDEN_FLAGS):
                continue
            if words[1:2] in (["setup"], ["skill"]) or "--write" in words:
                continue
            answer = run(*words[1:])
            followed += 1
            assert answer.code != 2, (line, answer.out[:300])
            assert "INTERNAL_ERROR" not in answer.out, line
    assert followed > 20, followed
    assert proxy.methods <= {"GET"}
    assert proxy.blocked == []
