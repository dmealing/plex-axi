"""Z: seeded random invocations, against the real server, behind the interlock.

The grammar has no ``--write`` and no ``--now`` in it, and it runs behind the
proxy anyway: whatever it builds, nothing but a GET can leave. What is asserted
is the floor every invocation owes -- a clean exit code, structured output, no
internal error, no traceback, no credential on either stream.
"""

from __future__ import annotations

import random

from support import HOSTILE

SEED = 20261004
ROUNDS = 300

COMMANDS = {
    "search": [
        "--artist",
        "--album",
        "--track",
        "--genre",
        "--mood",
        "--style",
        "--year",
        "--rated-min",
        "--query",
        "--type",
        "--limit",
        "--fields",
        "--sort",
        "--no-group",
    ],
    "pick": [
        "--rated-min",
        "--genre",
        "--not-played-since",
        "--exclude-live",
        "--limit",
        "--fields",
    ],
    "genres": ["--limit"],
    "moods": ["--type", "--limit"],
    "styles": ["--limit"],
    "track": ["--check-files", "--full"],
    "album": ["--full"],
    "artist": ["--full"],
    "similar": ["--limit", "--max-distance", "--fields"],
    "recent": ["--type", "--limit", "--fields"],
    "playlist": ["--limit", "--fields"],
    "sessions": ["--fields"],
    "api": ["--query", "--depth", "--full"],
    "doctor": [],
    "context": [],
}

BOOLEAN = {"--no-group", "--exclude-live", "--check-files", "--full"}

PLAUSIBLE = [
    "1",
    "0",
    "-1",
    "5",
    "20",
    "501",
    "4.5",
    "abc",
    "track",
    "album",
    "artist",
    "Jazz",
    "30d",
    "1999",
    "key,title",
    "nosuch",
    "addedAt:desc",
    "title:sideways",
    "0.25",
    "/",
    "/library/sections",
    "library",
    "type=10",
    "x",
    "12345",
    "999999999",
]

SUBS = {"playlist": ["list", "show", "nosuch"], "api": ["GET", "POST", "/", "/identity"]}


def invocations():
    rng = random.Random(SEED)
    for _ in range(ROUNDS):
        name = rng.choice(sorted(COMMANDS))
        argv = [name]
        if name in SUBS and rng.random() < 0.7:
            argv.append(rng.choice(SUBS[name]))
        for _ in range(rng.randint(0, 2)):
            argv.append(rng.choice(PLAUSIBLE + HOSTILE))
        for flag in rng.sample(COMMANDS[name], k=min(len(COMMANDS[name]), rng.randint(0, 3))):
            argv.append(flag)
            if flag not in BOOLEAN and rng.random() < 0.9:
                argv.append(rng.choice(PLAUSIBLE + HOSTILE))
        if rng.random() < 0.2:
            argv.append(rng.choice(["--json", "--human", "--debug"]))
        # A NUL cannot be passed in an argv at all; the offline fuzz covers it.
        yield [word.replace("\x00", "") for word in argv]


def test_no_invocation_is_an_internal_error_and_nothing_but_get_leaves(live, run, proxy):
    ran = 0
    for argv in invocations():
        assert "--now" not in argv and "--write" not in argv and "--user" not in argv
        result = run(*argv, check=False)
        ran += 1
        both = result.out + result.err
        assert result.code in (0, 1, 2), argv
        assert "INTERNAL_ERROR" not in both, argv
        assert "Traceback (most recent call last)" not in both, argv
        assert [leak for leak in live.leaks(both) if leak != "HOST"] == [], argv
        assert result.out.strip(), argv
    assert ran == ROUNDS
    assert proxy.methods <= {"GET"}
    assert proxy.blocked == []
