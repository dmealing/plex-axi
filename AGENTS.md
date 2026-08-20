# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test,
release, architecture, and sharp-edge notes that should travel with the code.

## The hard constraint: this repository is public and must stay generic

`plex-axi` talks to a Plex Media Server, and a music library is unusually rich in exactly the wrong
things: real artist and album names, absolute paths into somebody's collection, the server's
`machineIdentifier`, and a token that is a bearer credential for the whole library. Before writing
**anything** into this repo, including tests, fixtures, docs, examples and commit messages:

- **No host addresses.** No RFC1918 addresses, no `plex.direct` hostnames, no install-specific
  hostnames or ports. The base URL comes from `PLEX_URL`.
- **No credentials.** A Plex token is a 20-character bearer credential; the newer flow issues JWTs
  (`eyJ...`). Neither must ever appear in a commit, test, fixture, doc, example or log line.
- **No real library content.** No real artist, album or track names, and no real file paths. Invent
  obviously-synthetic ones: `Example Artist`, `Example Album`, `http://plex.example.com:32400`.
- **No `machineIdentifier`s, local paths or personal identifiers.**

`scripts/leakcheck.py` enforces the half that has a shape — do not rely on remembering it:

```sh
scripts/leakcheck.py                     # every tracked file
scripts/leakcheck.py --staged            # what a commit would record (pre-commit hook)
scripts/leakcheck.py --commit-msg PATH   # the message itself (commit-msg hook)
scripts/leakcheck.py --rules             # the live rule list
scripts/leakcheck.py --demo              # self-test: proves every rule still fires
scripts/install-hooks.sh                 # sets core.hooksPath to .githooks
```

CI runs `--demo` before the real scan, so a scanner that stopped detecting anything fails the build
rather than passing silently. If the scanner flags a line that legitimately needs the shape, add
`leakcheck: allow=<rule>` on that line — scoped to that one rule, never blanket. Do not weaken a
rule to make a commit pass, and do not bypass the hooks.

**Real content has no shape and the scanner cannot see it.** Artist and album names are the half
that is convention only. The README says the coverage is bounded; do not restore any claim that the
guard makes review unnecessary.

**Writing tests for the guard:** build credential shapes at run time. `leakcheck.synthetic_jwt()`
base64-encodes a payload and `leakcheck.synthetic_plex_token()` joins fragments, because the
condensed pass joins the whole file before re-scanning and will (correctly) find a literal split
across lines.

**A `leakcheck: allow=` marker must survive `ruff format`.** The marker is matched on the physical
line the shape lands on, and the formatter moves a trailing comment when it wraps the expression it
was attached to — which silently un-marks the line. Keep such lines short enough not to wrap, and
re-run the scanner *after* formatting, not before. This has already bitten once.

## Architecture

- `toon.py` — a strict TOON encoder (spec v4.1), taken unchanged from the sibling AXI project.
  Encoding happens **only** at the output boundary; command modules return plain JSON-shaped dicts.
  Do not loosen it to make output prettier.
- `output.py` — the single place anything reaches stdout, and therefore the only place redaction has
  to hold. `HelpBlock` is the one deliberate departure from strict TOON: `help[N]:` blocks render one
  suggestion per line, matching the AXI standard and the sibling AXI CLIs, because the suggestions
  are command lines full of commas.
- `plex.py` — connection, hardening and error translation. Nothing from the client library crosses
  this boundary: not its exceptions, not its response bodies, not its name.
- `music.py` — the product: section resolution, the per-field filter map, the search, the exact
  count, and the row shapes.
- `ids.py` — which `plex://` string may be printed. See "The five `plex://` forms" below.
- `writes.py` — the write gate and the `access` vocabulary. Nothing mutates without going through
  `writes.require`, and every command declares `access=READ_ONLY` or `access=MUTATING` so that
  `--help` and the generated skill are printing the *same declaration* rather than two descriptions
  that can drift. See "The write gate" below.
- `users.py` — `--user`: one plex.tv call, parsed with the standard library. Deliberately not the
  client library's own user switch; see the sharp edge below.
- `argspec.py` — per-subcommand flag declarations, and the `access:` block `--help` prints under the
  description. Unknown flags are rejected by name with the valid ones inlined; `RENAMED` maps
  plausible wrong guesses (mostly video vocabulary) to the real flag.
- `commands/` — one module per noun, each exposing `COMMAND_FOR(noun)` and
  `run(ctx, noun, sub, parsed)`.

**Deviation from the sibling project, and why.** The sibling AXI project maps one module to one noun and exports a
single `COMMAND`. Here two modules each serve three nouns that differ only by a Plex libtype or
filter field — `genres`/`moods`/`styles`, and `track`/`album`/`artist` — so modules export
`COMMAND_FOR(noun)` instead. Three near-identical files per group would have been worse than one
parameterised one. Adding a noun is still one entry in `COMMAND_ORDER` and one in `_MODULES` in
`cli.py`; root help, `SKILL.md` and the parametrised test sweeps all derive from those.

### Security invariants — do not regress these

- **Every output path is redacted, stdout and stderr alike.** `output.write`, `output.write_text`,
  `output.debug` and `output.debug_exception` all pass through `redact()`. stderr is not a safe
  channel just because agents ignore it: it reaches terminals, logs and CI output.
- **`cli.main` has a last-resort `except Exception`** that renders a structured, redacted error on
  **stdout** and names only the exception *type*, never its message. Without it an unexpected
  exception prints a raw traceback on stderr, bypassing redaction entirely and leaving stdout empty.
- **The token is registered as a secret in `config.load`**, at the moment it is read. It is rejected
  there if it contains whitespace or a control character, because an HTTP client raises a
  `ValueError` embedding the whole header when it finds one. A *trailing* newline is stripped
  instead of refused: `PLEX_TOKEN=$(cat token.txt)` is the common case, not a mistake.
- **`redact()` has a token-shaped backstop as well as the registered literal.** `X-Plex-Token=` as a
  URL parameter is redacted whether or not the value ever passed through this process's config,
  because the client library appends it to artwork, stream and web URLs.
- **`api` refuses write methods, and that did not change when the tool learned to write.** A raw
  path that could POST would make the gate meaningless: anything a typed command refused could be
  reissued by hand, with none of the validation, the preview or the explanation. Several Plex write
  endpoints are destructive besides. It also refuses a caller-supplied `--query X-Plex-Token=…`,
  which is how a credential reaches shell history.
- **A write is refused before the connection is opened.** `writes.require` runs at the top of
  `run()`, ahead of `ctx.server()`, so a mutating command with the gate closed reaches the server
  **zero times**. A refusal that read the item first and then declined would produce the same exit
  code and the same message while telling the server what was attempted;
  `tests/test_writes.py` asserts on `server.requests`, not on the exit code, for exactly that
  reason.
- **A per-user token is registered as a secret the moment it arrives.** `--user` receives a bearer
  credential from plex.tv that never passed through this process's own configuration, so
  `users.access_token` calls `register_secret` on it before returning.
- Tests for all of this live in `tests/test_credentials.py`, which asserts `capsys` **stderr** is
  clean as often as stdout.

## The write gate

The first release was read-only end to end and said so everywhere. This one is not, and the
mechanism that keeps that honest is one decision with two conjuncts:

1. **`PLEX_AXI_ALLOW_WRITES=true` in the environment is the gate**, matched case-insensitively
   after stripping. It is the primary because of *who sets it*: the operator, once, outside the
   invocation. A caller composing a command line cannot grant itself a permission it was not given,
   and the refusal can name what to change. A value that is set but is not `true` is refused **by
   name** rather than treated as false — an operator who exported `yes` meant to open it, and a
   silent "not set" would send them hunting for a variable they had already exported.
2. **`--write` on the invocation is the confirmation, and it is not a second gate.** With the gate
   open and the flag absent the command still runs and *previews*: it reads the item or the
   playlist, prints what would change, and sends nothing. That is what stops the flag being
   ceremony an agent shrugs off and retries past — leaving it out asks a different, cheaper
   question, and it is where both playlist failure modes are caught before anything is written.

`Command.access` / `Sub.access` are the declaration, and they default to `READ_ONLY` so a command
added without anyone thinking about the question is described as the thing it almost certainly is.
`argspec.render_access` prints it as the `access:` block directly under the description — not among
the notes, because "can this change my library?" is not a footnote — and `skill.py` renders the same
block from the same declaration, so the help and the skill cannot say different things.
`tests/test_writes.py` sweeps every noun asserting the block is there and near the top.

**Anything that claims the tool is read-only has to be qualified or deleted.** README, the generated
skill, the home view (`writes:`), root `--help` and this file were all updated together;
`tests/test_skill.py` fails if an unqualified claim comes back. The one place the old wording is
still correct is `api`, which is GET-only whatever the gate says.

## Sharp edges

Everything here was paid for once. Most of it is invisible until it is wrong.

- **There are two `search()` methods and only one of them works.** `Library.search` hits
  `/library/all`, validates nothing, and drops unknown keyword arguments straight into the query
  string; its own docstring says *"This is untested but seems to work. Use library section search
  when you can."* Everything in this tool goes through `MusicSection.searchTracks/Albums/Artists`.
  Never reach for `server.library.search`.
- **A numeric filter has three different meanings depending on how it is reached.**
  `userRating__gte=8` through `Library.search` is emitted verbatim into the URL and applied nowhere.
  Through `LibrarySection.search` it becomes a *client-side* post-filter applied after `limit` has
  already sliced the results, so it filters within the slice rather than narrowing the query. Only
  `filters={"userRating>": 8}` is a real, server-validated Plex predicate. `music._assert_server_side`
  fails loudly if anything ever lands in the client-side bucket again.
- **Plex's operator suffixes are not Python's.** `>` normalises to `>=` ("is greater than or
  equals") and `>>` to `>>=` ("is greater than"). The library validates the operator against the
  field's advertised set and raises listing the valid ones; `music._filter_error` turns that into a
  usable message rather than letting it escape.
- **`group` is not a field the server advertises — the client library adds it by hand.**
  `FilteringType._manualFields` injects `('group', 'string', 'SQL Group By Statement')` into *every*
  libtype, so `filters={"group": "title"}` validates on any server whatever its metadata says. That
  means grouping can never fail validation, and it also means *nothing in the request can tell you
  whether the server honoured it*. `music._verify_grouping` therefore checks the rows that came back
  for repeated titles and says so when they are there. Do not replace that with a claim based on
  what was asked.
- **Auto-reload is switched off, and it must stay off.** `PlexPartialObject.__getattribute__`
  re-fetches the whole object whenever a requested attribute is `None`. On a list of twenty albums,
  reading a field one of them happens not to carry is twenty extra HTTP requests, and the caller sees
  only a slow command. `plex.py` sets `PLEXAPI_PLEXAPI_AUTORELOAD=false` before the import; an absent
  value stays absent and is reported as `null`. The two places that genuinely need more data ask
  outright: the detail views fetch `/library/metadata/<key>`, and `--check-files` reloads.
  `tests/test_commands.py` asserts no list view ever fetches a per-item path.
- **`BASE_HEADERS` must be mutated in place, never rebound.** `plexapi.server` does
  `from plexapi import BASE_HEADERS` at import time, so assigning `plexapi.BASE_HEADERS = …` leaves
  the dict that is actually sent untouched — a near-miss that looks like it worked. `plex.harden`
  clears and updates the existing dict.
- **The client library publishes the machine's identity by default.** `X-Plex-Device-Name` is the
  operating system's hostname and `X-Plex-Client-Identifier` is derived from the MAC address, and
  both end up in the server's device list. `harden()` replaces the first with `plex-axi` and the
  second with a hash of the MAC — stable per machine, which is what Plex needs, without handing over
  the address itself.
- **Three switches decide whether the token is disclosed, not one.** The environment variable read at
  import time, the parsed config file, and the logging filter — plus `server._showSecrets`, which is
  what `url()` consults. A tool that merely avoids `includeToken=True` has covered none of them.
  `plex.harden` sets all four.
- **`accessible` and `exists` are empty unless you ask.** `PlexPartialObject._INCLUDES` sets
  `checkFiles: 0`, so the server never stats the file on an ordinary fetch. `--check-files` is a
  deliberate second round-trip, and with the flag off the detail view says **"not checked"** rather
  than "not accessible": reporting the empty value as absence would be a different untruth from the
  one it is avoiding.
- **A session element carries a `<User>` child and the library reads it unguarded.** A `/status/sessions`
  response without one raises `AttributeError` inside `PlexSession._loadData` rather than parsing to
  something empty. The test double models the real shape so this is exercised rather than assumed.
- **A boolean key in `filters` may not have a sibling.** `_validateAdvancedSearch` raises
  *"Multiple keys in the same dictionary with and/or is not allowed"* the moment `{'or': [...]}`
  shares a dictionary with anything else, so a parenthesised OR has to be composed as
  `{'and': [{...simple...}, {'or': [...]}]}` — which is what `pick._compose` does. This is also why
  `group=title` is no longer passed inside `filters`: it moved to `run_search`'s `**kwargs`, where
  `_buildSearchKey` validates it against the same field table and emits the same `group=title`
  parameter *outside* any group. A `group` inside the parentheses would be a SQL GROUP BY scoped to
  half the predicate, which is not what anyone means.
- **A never-played track has no `lastViewedAt` at all.** The column is null rather than zero, so
  `track.lastViewedAt<<=-30d` excludes exactly the tracks most obviously not played lately. That is
  why `pick --not-played-since` ORs the date predicate with `track.unplayed` server-side, and why
  the double models the attribute as absent rather than as `0` — a fixture with a zero there would
  let the wrong single-predicate version pass.
- **A tag filter is negated with `!`, and the value should be a list.** `--exclude-live` sends
  `filters={'album.subformat!': ['Compilation', 'Live']}` rather than Plex's own
  `'Compilation,Live'` string, because a list is resolved element by element to the numeric ids Plex
  filters on. The comma-joined string reaches the URL as text and only matches if the server happens
  to accept names there.
- **`rate()` refuses a negative rating from a caller.** `RatingMixin.rate` raises `BadRequest` for
  anything outside 0-10 and sends `-1` itself when the argument is *omitted*. So clearing a rating
  is `item.rate()` with no argument; passing `-1` through is a client-side refusal that never
  reaches the server and looks like the server said no.
- **`--user` does not go through the client library's user switch, and must not start to.**
  `switchUser` reaches the account object — the same object that resolves Sonos speakers by name and
  dispatches playback to them — and costs three round-trips, two of them to plex.tv. `users.py` asks
  plex.tv one question instead (`/api/servers/<machineId>/shared_servers`, which already carries the
  username, the user id *and* that user's access token for this machine) and parses it with
  `xml.etree`. One round-trip instead of two, and `MyPlexAccount`, `myPlexAccount`, `switchUser` and
  `plexapi.myplex` all stay on `tests/test_no_dispatch.py`'s forbidden list.
- **Plex Home users are not in the sharing record**, so `--user` cannot reach them. The error says
  so and points at exporting that user's own `PLEX_TOKEN`, rather than reporting them as absent.
- **Sort fields are libtype-scoped on the wire.** `recentlyAddedAlbums` builds
  `sort=album.addedAt:desc`, not `sort=addedAt:desc`. Anything parsing a sort parameter has to strip
  the scope.
- **A tag filter costs an extra round-trip.** `_validateFieldValueTag` calls `listFilterChoices` to
  map a genre *name* to the numeric id Plex filters on. That is why `--genre` is one request more
  than `--year`, and it is also what makes `--genre Jazz` work at all.
- **Genres and styles live on the artist.** In a Plex music library a track carries no genre, so a
  track-scoped genre filter returns nothing on a library tagged the ordinary way. `--genre` and
  `--style` resolve to `artist.genre` and `artist.style` whatever the searched libtype is; `--mood`
  scopes to the libtype, because Plex's analysis writes moods at every level.
- **Ratings are stars in both directions.** Plex stores 0–10; `--rated-min` takes 0–5 and every
  rating printed is 0–5, so a value read out of one command can be passed into the next. Breaking
  that symmetry would be a silent trap.
- **The exact count comes from a second request with an empty body.**
  `X-Plex-Container-Size: 0` returns the container metadata and no rows. The server-side `limit`
  parameter is deliberately *not* used for the page, because it also caps `totalSize` and would turn
  the exact total into a lie; `maxresults` bounds the fetch instead.
- **Exit codes follow one rule.** A static invocation problem — unknown flag, unknown command, a
  rating key that is not a number, a write method on `api` — exits 2. An outcome of a lookup against
  live state — nothing at that rating key, no music library, an ambiguous section — exits 1. A zero
  result from a well-formed search exits **0**: an empty answer is an answer.

### The five `plex://` forms

Five strings are in circulation and they all look like one identifier:

| Form | Produced by | Safe to print as a media id? |
|---|---|---|
| `plex://<machineIdentifier>/<ratingKey>` | a media browser | **yes** — the canonical form, and the only one this tool emits |
| `plex://<ratingKey>` | older integrations | yes, but consumers call it the legacy branch |
| `plex://{<json>}` | play-queue dispatch | yes, matched before URL parsing |
| `plex://track/<ratingKey>` | a tool's internal id | **no** — parses as a server named `track` |
| `plex://track/<24-hex>` | the client library's own `guid` | **no** — raises `ValueError` in a consumer |

The last two are the trap: the same shape in two namespaces, one of which is a legitimate Plex
identifier handed out under the attribute name `guid`. `ids.media_content_id` builds only the first
form and refuses anything that is not a decimal rating key; `tests/test_ids.py` sweeps every command
and asserts none of them ever emits form 4 or 5.

**Labels are vendor-neutral, and the output stops at the identifier.** The field is `media_id`, not
the name of any particular consumer: this ships to anyone with a Plex library, and naming one in the
default output would be wrong for everyone else. There is deliberately no "play this with …" line
and no configuration for one. A template could only ever come from the operator, so printing it back
tells the caller nothing they did not already know — it was ceremony. The `item:` block is exactly
four fields — `media_id`, `rating_key`, `guid`, `note` — and `tests/test_ids.py` asserts that list
verbatim. The README explains in prose what consumes a `media_id`; that belongs in documentation,
not in output.

**`rating_key` is not stable.** It is a row number in one server's database and it moves when an
item is re-matched or the library is rebuilt. Every command that emits one emits the `guid` beside
it and says so; do not drop the note from any output a human might paste into a configuration file.

## The command contract

`plex-axi api` reaches every readable Plex path, so a typed command is never justified by reach.
What the typed commands add is judgement.

**The promotion rule.** A command earns its place only when it does something `api` cannot — and the
PR must say what. The current set, each with its reason:

| Command | What `api` cannot do |
|---|---|
| `search` | build the filter expression at all: per-field scoping, operator normalisation and tag-id resolution are three round-trips and a validation pass |
| `pick` | compose a parenthesised OR, check the section's advertised fields before building a predicate, and report the ones this server cannot honour instead of applying them in Python |
| `genres` / `moods` / `styles` | know that the choices endpoint is per-field and per-libtype, and hand the list back as the recovery set on a miss |
| `track` / `album` / `artist` | the second round-trip behind `--check-files`, and the difference between "not checked" and "not accessible" |
| `similar` | surface `distance`, which is on the wire but meaningless without the seed's `analysis` version beside it |
| `recent` | pick the music-typed endpoint over the server-wide one that spans video |
| `sessions` | separate music sessions from the rest without the caller parsing types |
| `playlist` | pass `playlistType='audio'` (without it `playlists()` returns films and photos too), and tell the two `BadRequest`s apart — smart playlist means pick a different playlist, mixed media means pick different items |
| `rate` | convert stars to Plex's 0-10 in the same place the read path converts back, refuse a no-op, and read the result back rather than echoing the request |
| `doctor` | check four things in the order they fail, and exit non-zero |

**Demotion.** If a typed command's body reduces to flag-mapping plus a request, delete it — the
measure is the diff, not the intention.

**`--count` became `--limit`, deliberately.** The requirements table spells `pick`'s size flag
`--count`. Every other list command here takes `--limit`, and `RENAMED` already maps `--count` to
`--limit` as a wrong guess — so shipping both spellings would have made that correction table lie
and given an agent two names for one idea. The flag is `--limit`; the deviation is here rather than
silent.

**`queue create` (W11) is still out.** A playqueue id is not universally accepted — Sonos rejects
Plex playqueues outright — so shipping one without naming which platforms take it only moves the
discovery to a 500.

**What is deliberately absent, and will stay absent.** No playback of any kind, no speaker, room,
player, client or target concept, no video, no server administration, no *metadata* editing (a user
rating is per-account state, not library metadata, which is why `rate` is in and `edit` is not), no
second Plex client library, and no semantic name resolution by regex or substring. The first is enforced by
`tests/test_no_dispatch.py`; read its module docstring before touching it. The rule is not that the
tool *cannot* play music — the client library can, over a live cloud path to a Sonos and over a
local one to a Chromecast, and both are one attribute access away. It is that it *must not*, because
reaching past the seam makes two systems believe they own the same queue.

## Build, test, lint

```sh
pip install -e ".[dev]"
pytest                                   # ~400 tests, a couple of seconds
ruff check . && ruff format --check .
plex-axi skill --check                   # SKILL.md is generated, never hand-edited
scripts/leakcheck.py                     # run this AFTER formatting
```

**Tests never need a live server or a live token, and must not start to.** They run the real client
library against a Plex double in `tests/conftest.py` that speaks HTTP-shaped XML over a fake
`requests` session. That is the point: the claims worth testing — that a filter is applied
server-side, that the URL carries the operator Plex actually defines, that a count is exact — are
claims about the request the client library builds, and a double that only agreed with the client
could not test any of them.

**The double must answer like Plex, not like the client.** Two rules, neither optional:

- **Model the refusals.** `KNOWN_PARAMS` and `KNOWN_FIELDS` are an explicit allow-list; anything else
  is a `400`. A filter that reached the URL in a spelling Plex does not define — which a permissive
  server would ignore, returning a plausible unfiltered answer — is a refusal here. The tables are
  deliberately *not* imported from `plex_axi`: a second opinion that is a copy of the first is not
  one. A new parameter is refused until it is added to the table, and adding it is how the parameter
  gets confirmed rather than assumed.
- **Apply the filters for real.** A request for tracks rated four stars and up returns only those
  tracks, from the double's own predicate code. A double that returned the same rows whatever was
  asked would let a filter that does nothing pass every test.

The double also models both answers to the open question about grouping (`FakePlex(groupable=…)`):
a server that collapses repeated titles and one that accepts the parameter and ignores it. Which one
a given Plex build is cannot be settled without a live server, so the tool is tested against both and
reports which one it met. `FakePlex(spartan=True)` is the same idea for filter metadata: a library
that advertises none of the fields `pick` would like, so the "report it as unapplied" path has a
server to run against rather than a comment claiming it works.

**The writes half, and four things it needs.**

- **The fixture is per-server now.** `Tables` deep-copies the artist/album/track rows into each
  `FakePlex`, because a rating written by one test would otherwise be visible to the next. Ratings
  are keyed by `(account, rating_key)`, which is what makes `--user` testable: a rating written as
  one account is not the other's.
- **`FakeSession` has `put`, `post` and `delete`.** The client library reaches for them by name, so
  a double with only `get` makes every write path untestable rather than merely untested.
- **`FakePlex.writes` records every non-GET request**, and the gate test asserts it is empty. The
  gate test also asserts `requests` is empty, which is the stronger claim: the server never heard
  about the attempt at all.
- **The write endpoints refuse like Plex.** `/:/rate` requires `key`, `identifier` and a rating in
  0-10 (or `-1`); a playlist `uri` must name *this* machine identifier and may only carry items
  whose media type matches the playlist's. A double that accepted a 0-5 rating there would let the
  star conversion break silently, which is the one bug that endpoint can actually have.

**plex.tv is answered by the same double, routed on the hostname.** That is what lets "plex.tv is
unreachable but the library is fine" be a test case rather than a hypothetical, and it is why
`--user` uses `plex.build_session()` like everything else.

**The query parameters are handed over ordered as well as mapped.** A parenthesised filter
expression is carried by the *order* of `push`/`or`/`pop`, so a dictionary cannot represent it and a
test that only saw the mapping could not tell `(A or B) and C` from `A or (B and C)`.

Supported Pythons are 3.10 through 3.12, and **the floor is not a free choice — `PlexAPI` sets
it.** plexapi 4.18.0 raised its own `requires-python` to `>=3.10`, which raised this project's floor
with it and said nothing: `requires-python = ">=3.9"` stayed in `pyproject.toml`, the whole test
suite passed on 3.10 through 3.12, and the only thing that ever noticed was `pip install` on 3.9
failing to resolve the dependency at all. Published metadata is the one claim tests cannot check,
because the interpreter that would have failed is the one they were never run on. **Read plexapi's
`requires-python` before raising the pin, and treat a bump as a possible floor change until you
have.** `tests/test_python_floor.py` now holds `requires-python`, the `ci.yml` matrix and the
`Programming Language :: Python :: X.Y` classifiers to one number, so drifting any one of them
apart fails locally rather than at somebody's install.

Ruff's `target-version` is deliberately **still `py39`**, which is the one place the floor is stated
and was not moved with it. Raising it to `py310` enables `B905` (`zip()` without `strict=`), whose
only site is `commands/similar.py` — a correct fix, `rows_for` is 1:1 over its input, but a runtime
behaviour change to a shipped command, which does not belong in a change that moves published
metadata. Bump it in its own commit and take the `strict=True` with it. Leaving it low is safe
meanwhile: `target-version` only bounds which upgrades ruff proposes, and a low one is conservative,
never wrong.

`from __future__ import annotations` stays at the top of every module. It is no longer what makes
`X | None` safe — that is native from 3.10 — but it keeps annotations lazy and the modules uniform,
and removing them from every module is a separate change from moving a floor. Note that nested quotes inside a
multi-line f-string expression need 3.12; the test fixtures use `.format` for that reason.

`skills/plex-axi/SKILL.md` is generated from the CLI's command table. Change the commands, then run
`plex-axi skill` and commit the result; CI fails if the two disagree.

## Continuous integration

Three workflows, split by where the work is cheap:

- **`.github/workflows/ci.yml`** — the heavy matrix (leak scan, lint, `pytest` on 3.10 through 3.12,
  the generated-skill check) on the maintainer's self-hosted runner. Triggers: push to `main`, a
  nightly `schedule`, and `workflow_dispatch`. Never pull requests.
- **`.github/workflows/hygiene.yml`** — the leak scan alone, on `ubuntu-latest`, on `pull_request`.
  Exactly one GitHub-hosted check per PR, and it takes seconds.
- **`.github/workflows/release.yml`** — GitHub-hosted, and to stay that way: OIDC trusted publishing
  needs `id-token: write` on a GitHub-hosted runner.

**`ci.yml` must never gain a `pull_request` trigger.** This repository is public and the runner is
the maintainer's own workstation. Every trigger it has requires write access, so fork-submitted code
cannot reach the machine; `pull_request` would hand any contributor on the internet code execution on
it, in one line, with no other visible symptom. The reasoning is repeated at the top of the file so
it survives someone later "helpfully" adding PR coverage.

**A thin PR check is the design, not an oversight.** Every change goes through the local no-mistakes
gate — review, tests, lint, docs — before a PR is opened, so GitHub-hosted CI is not the primary
quality signal here. Do not add jobs to `hygiene.yml` to make pull requests look better covered.

**A self-hosted runner runs as a real user, and that user's `~/.local` is on every job's path.** A
bare `pytest`, `ruff` or `plex-axi` would therefore run the maintainer's copy against whatever
checkout it points at. Every job that needs third-party packages does
`python -m venv --clear .venv` and calls tools as `.venv/bin/<tool>`; a venv sets
`ENABLE_USER_SITE = False`, so the leak cannot happen. Do not "simplify" these back to bare names.

Checkouts on the self-hosted runner pass `persist-credentials: false`: that workspace outlives the
job, and a token left behind in its `.git/config` would outlive it too.

The nightly cron deliberately avoids 08:17 and 09:41 UTC, which sibling projects' self-hosted
workflows hold on the same workstation.

## Releasing

release-please owns the version. `.release-please-manifest.json` records the **last released**
version, which is not the same thing as the version in `pyproject.toml` and
`src/plex_axi/__init__.py` — those hold the version a release will *write*. During bootstrap, before
the first publish, the manifest deliberately trails the source: baseline `0.0.0` with source `0.1.0`
means "nothing released yet, the next `feat:` lands 0.1.0". Never "fix" a mismatch by raising the
baseline to match the source; that tells release-please the version is already out and it bumps past
it, permanently skipping a version number PyPI will never let us reuse.

## Licensing

MIT. Two constraints that came out of surveying the landscape and still hold:

- **Tautulli is GPL-3.** It solved some of the same problems — its rating-key remapping machinery is
  the best evidence that keys move — but not one line of its code, tests or fixtures may be copied
  here. Ideas only.
- **Two of the more interesting prior-art projects ship no licence at all**, which means all rights
  reserved. Their *shapes* are ideas and reading them is fine; their expression is not available.

The client library is BSD-3-Clause and the community OpenAPI specification that documents Plex's
media-query language is MIT; both are compatible, and the spec is the thing to cite rather than
re-derive.
