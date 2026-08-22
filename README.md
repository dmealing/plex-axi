# plex-axi

[![PyPI](https://img.shields.io/pypi/v/plex-axi.svg)](https://pypi.org/project/plex-axi/)
[![Python versions](https://img.shields.io/pypi/pyversions/plex-axi.svg)](https://pypi.org/project/plex-axi/)
[![Licence: MIT](https://img.shields.io/pypi/l/plex-axi.svg)](LICENSE)

**Search a Plex music library field by field, from a command line built for agents.** Every value
gets its own flag — artist, track, genre, mood, year, minimum rating — and Plex evaluates the whole
predicate server-side. Every answer ends at a labelled `media_id`, the identifier you hand to
whatever plays music where you are.

**It does not play anything unless you switch playback on, and until you do it has no play command
at all.** Out of the box the tool stops at the identifier, and dispatch belongs to whatever already
owns your speakers — which is the right answer if you run Home Assistant or anything like it, since
two things that can both start music means two things that disagree about what is playing. If you
have Plex and nothing else, that was a dead end, so `PLEX_AXI_ALLOW_PLAYBACK=true` adds two
commands: `clients`, which lists what can play, and `play`, which starts one track, album, artist
or playlist on one of them. Without that variable they are not refused — they do not exist, in the
help, in the skill or in the command table, so an agent cannot pick a path you did not open. There
is no pause, stop, volume or queue command in either case, and there is not going to be one.

It is an [AXI](https://axi.md) tool — an *Agent eXperience Interface*, a convention for command
lines whose primary user is an LLM agent rather than a person. In practice that means
token-efficient structured output ([TOON](https://toonformat.dev/) rather than JSON), no interactive
prompts, a non-zero exit on every failure, and errors that carry the command which fixes them. It
reads perfectly well in a terminal — `--human` prints aligned tables — it is simply not optimised
for one.

## Why per-field search

Every published Plex CLI, MCP server and LLM wrapper takes a single free-text `query` string and
hands it to the server as one blob — which is why searching for an artist *and* a song title
reliably returns nothing. `plex-axi` gives each value its own flag and each flag its own Plex field,
and lets Plex evaluate the whole predicate server-side.

```sh
$ plex-axi search --artist "Example Artist" --track "Example Track"
count: 1 of 1 total
grouped: title
filters[2]{field,operator,value}:
  artist.title,contains,Example Artist
  track.title,contains,Example Track
tracks[1]{key,media_id,title,artist,album}:
  111,"plex://<machineIdentifier>/111",Example Track,Example Artist,Example Album
item:
  media_id: "plex://<machineIdentifier>/111"
  rating_key: 111
  guid: "plex://track/a1b2c3d4e5f60718293c0111"
  note: "rating_key is local to this server and changes when an item is re-matched or the library is rebuilt; guid is the identifier that survives, so keep them together"
```

It also exposes the parts of Plex's music surface that nothing else does: the library's own genre,
mood and style vocabularies; sonic similarity with the server's own `distance`; the music-analysis
version behind an empty "more like this"; and, behind a flag, whether the server can actually read
the file.

**What it hands back is an identifier, and that is the end of it.** What a `media_id` is and what
accepts one is [below](#what-media_id-is-and-what-consumes-it); why the tool refuses the step after
it, and the test that holds the line, are in [AGENTS.md](AGENTS.md).

**Two commands can change your library, and neither runs by accident.** `rate` sets the rating that
`--rated-min` reads, and `playlist` edits an audio playlist. Both are refused unless the operator
has exported `PLEX_AXI_ALLOW_WRITES=true`, and even then they preview the change and send nothing
until `--write` is passed. Every other command reads. See [Writing](#writing).

## Install

```sh
pipx install plex-axi        # or: uv tool install plex-axi
```

Or run it without installing:

```sh
uvx plex-axi search --artist "Example Artist"
pipx run plex-axi genres
```

## Configure

Both values come from the environment. There is **no `--token` flag and no credential file**: a
token on a command line leaks into shell history and the process table, and a Plex token is a bearer
credential for an entire library.

```sh
export PLEX_URL=http://plex.example.com:32400   # the server on your local network
export PLEX_TOKEN=<a Plex access token>
export PLEX_SECTION='Example Music'             # only if the server has more than one
export PLEX_AXI_ALLOW_WRITES=true               # only if `rate` and `playlist` may write
export PLEX_AXI_ALLOW_PLAYBACK=true             # only if you want `clients` and `play` to exist
export PLEX_ACCOUNT_TOKEN=<a plex.tv token>     # only to reach Sonos speakers; see Playback
```

Point `PLEX_URL` at the server itself rather than at plex.tv, so the tool keeps working when plex.tv
is unreachable and no invocation pays a cloud round-trip. Finding a token is documented at
<https://support.plex.tv/articles/204059436>.

```sh
plex-axi doctor    # exits non-zero when any check fails, so it works as a hook or CI gate
```

## Use

```sh
plex-axi                                              # the library at a glance
plex-axi search --artist "Example Artist" --rated-min 4
plex-axi search --genre Jazz --type album --limit 10
plex-axi pick --rated-min 4 --not-played-since 30d --exclude-live
plex-axi genres                                       # and `moods`, `styles`
plex-axi track 12345 --check-files
plex-axi similar 12345 --max-distance 0.1
plex-axi recent
plex-axi playlist show "Example Playlist"
plex-axi sessions
plex-axi api /library/sections                        # the escape hatch, GET only
```

Every command takes `--help`, which is the authoritative reference for its flags — including an
`access:` line under the description saying whether that command reads, writes or starts playback.

`pick` is the "give me something to listen to" command. Every one of its filters is a Plex
predicate the server evaluates — the rating comparison, the genre, the relative date, the
compilation/live exclusion — and the shuffle is Plex's own `sort=random` over the whole match set
rather than a shuffle of one page. A filter this particular server does not offer is reported under
`unapplied` rather than quietly applied in Python, because a client-side filter fights `--limit`
exactly as it fights Plex's own `limit`.

### Reading as another account

Ratings and playlists are per account, so `--user <plex-username>` answers the same questions for
somebody else on the server:

```sh
plex-axi --user example-friend playlist
```

It is **admin only** — the per-user tokens are the owner's to read — and it is the one flag here
that needs a round-trip to **plex.tv**, because the mapping from a username to that user's token for
this server exists nowhere else. Everything else keeps working with plex.tv down, and a failure here
says which of the two happened rather than arriving as an unexplained 401.

## Output format

Structured [TOON](https://toonformat.dev/) on stdout by default — Token-Oriented Object Notation, a
compact encoding of the same data JSON would carry, roughly 40% cheaper in tokens. A header names
the columns once and each row is one line:

```
count: 2 of 47 total
tracks[2]{key,media_id,title,artist,album}:
  111,"plex://a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0/111",Example Track,Example Artist,Example Album
  112,"plex://a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0/112",Second Example,Example Artist,Example Album
```

- `--human` renders aligned tables for a person.
- `--json` emits raw JSON, for anything that would rather parse than read.
- **Errors go to stdout too**, in the same structured shape, and carry the command that fixes them,
  so a wrong flag corrects itself in one turn. stderr carries only diagnostics (`--debug`), which
  agents do not read.
- Exit codes: `0` success — **including a search that matched nothing**, because an empty answer is
  an answer; `1` the outcome of a lookup against live state (nothing at that rating key, no music
  library on the server, an ambiguous section); `2` a usage error (unknown command, unknown flag, a
  rating key that is not a number, a write method on `api`).
- Unknown flags and extra arguments are **rejected by name** rather than ignored, with that
  subcommand's valid flags listed inline so the correction takes one turn, not two.

One documented deviation: `help[N]:` blocks render one suggestion per line rather than as a
delimiter-joined TOON array. Suggestions are command lines that routinely contain commas, and this
is the shape the AXI standard and the sibling AXI CLIs use. Every **data** structure is strict TOON,
and "strict" is a test result rather than a claim: the specification's own conformance fixtures are
vendored into the suite and every one of them has to pass.

## Rules of thumb

- **Use a flag per field.** `--artist X --track Y` searches two Plex fields; `--query "X Y"` searches
  one string. `--query` exists for the case where there genuinely is only one unstructured string,
  and its `--help` says so.
- **Ratings are stars, 0–5, in both directions.** A rating printed in a result can be passed straight
  back to `--rated-min`.
- **Genres and styles live on the artist**, not the track — that is how Plex tags a music library.
  `plex-axi genres` prints the exact strings the server will accept; pass one of those, not a synonym.
- **A zero result is an answer.** It names the filters that matched nothing and the command that
  lists the real vocabulary.
- **Every row carries a `media_id`.** That is what the tool is for: a labelled identifier a media
  consumer accepts, on every row of every list, so nothing needs a follow-up call to be usable.
- **`--fields` replaces the default columns**, it does not add to them. The default set is a
  suggestion and may grow a column when the data warrants one (`track_artist` on a compilation), so
  name the columns if you need a fixed schema.
- **`--rated-min` is a minimum in stars, and `0` is not a filter.** Zero is the bottom of the scale
  and narrows nothing; `--rated-min 0.5` is what asks for everything that carries a rating at all.
- **`rating_key` is local to one server and moves** when an item is re-matched or the library is
  rebuilt. Keep the `guid` beside it anywhere the value is written down — **unless** the guid reads
  `local://<rating_key>`, which is what Plex gives an item it never matched to its catalogue. That
  one is the rating key with a scheme in front of it, so it moves with it; the detail view says so
  rather than promising otherwise, and there is nothing durable to write down for those items.
- **A mutating command without `--write` is a useful command, not a nag.** It prints exactly what
  would change and sends nothing, which is how to check a playlist edit before making it — and how a
  smart playlist is caught before the server would refuse it.

## Writing

`plex-axi` began as a read-only tool and most of it still is. Two commands are not:

| Command | What it changes |
|---|---|
| `rate <rating_key> --stars <0-5>` | your rating on one track, album or artist — per account, not library metadata |
| `playlist create\|add\|remove` | the contents of an audio playlist |

Both are behind the same two-part gate, and the order matters:

1. **`PLEX_AXI_ALLOW_WRITES=true` in the environment.** This is the gate. It is a variable rather
   than a flag because of who sets it: the operator, once, outside the invocation. Something
   composing a command line cannot grant itself a permission it was not given, and the refusal names
   what to set. With it unset, a mutating command **never contacts the server at all** — the check
   runs before the connection is opened, so the attempt is not even something the server hears
   about.
2. **`--write` on the invocation.** Without it the command still runs: it reads the item or the
   playlist, prints the change it would make, and sends nothing.

```sh
$ plex-axi rate 12345 --stars 5
error: "refusing to rate 12345: writes are disabled (PLEX_AXI_ALLOW_WRITES is not set)"
code: WRITES_DISABLED
help[3]:
  Run `export PLEX_AXI_ALLOW_WRITES=true`, then run the command again with --write
  ...
```

`plex-axi api` stays **GET only** whatever the gate says. A raw path that could POST would make the
gate meaningless — anything a typed command refused could be reissued by hand — and several Plex
write endpoints are destructive.

There is still no metadata editing and no server administration, and no transport control: `play`
starts one thing on one target and nothing in this tool can pause, skip or stop it.

## Playback

Off by default, and while it is off the commands are not there to be found — not in `--help`, not
in the generated skill, not in the no-argument view. That is deliberate, and the default is the
important half.

**If you run Home Assistant, or anything else that already dispatches music, leave this switched
off.** Your automation owns the speakers — Sonos included, which it reaches by its own path — and
the shape that works is to use this tool to *find* music and let that system play it. A play issued
here goes around it, so its state is stale the moment the command succeeds; the problem is not that
nothing happens, it is that everything downstream is confidently wrong about what is playing. While
the switch is off an agent cannot see this path at all, which is the only reliable way to stop it
choosing one.

Switch it on if you have Plex and nothing else doing that job — which is exactly who it is for,
because without it the tool hands you an identifier and stops.

```sh
export PLEX_AXI_ALLOW_PLAYBACK=true

plex-axi clients                                        # what can actually play
plex-axi play 12345 --client 'Living Room'              # says what it would do, sends nothing
plex-axi play 12345 --client 'Living Room' --now        # starts it
```

The gate is an environment variable and `--now` is the confirmation, exactly as with writes: the
variable is your standing decision, the flag is this invocation's. Leaving `--now` off is not a nag,
it is a cheaper question — it resolves the item and the target and tells you which one it picked and
why, which is where "I have three clients and named none of them" gets caught before a speaker comes
on. If there is exactly one target it is used, and the answer says it was the only candidate.

`clients` lists only targets that advertise Plex's `playback` capability; anything else that
answered is counted, because a client that cannot play will accept the command and do nothing. No
network address is printed for any target — `--client` takes the exact title, or the `machine_id`
printed beside it when two targets share a name.

Two routes, and the second has conditions:

| Route | Reached via | Needs |
|---|---|---|
| `local` | the server's own `/clients` list | nothing beyond `PLEX_TOKEN`; the client's app must be running on the same network as the server |
| `sonos` | `sonos.plex.tv` | `PLEX_ACCOUNT_TOKEN`, a Plex Pass, speakers linked to that account, and remote access working |

`PLEX_ACCOUNT_TOKEN` is a **plex.tv account token, which is not the same thing as `PLEX_TOKEN`** — a
server token is refused by plex.tv outright, and the error says so rather than handing you a bare
401. The Sonos route is consulted only when that variable is set, and `clients` says which routes it
asked either way. It goes over Plex's cloud rather than through your server, so anything watching
your server for a session will lag the command; that matters if you run Home Assistant, and it is
another reason to leave this gate shut where something else already dispatches.

Starting playback is all `play` does. There is no pause, stop, resume, seek, next, previous, volume
or queue command, and there is not going to be one: a start button is a handoff, and a transport is
a second system believing it owns your queue.

**Both routes ship without having started music on real hardware.** Everything up to the final
request is confirmed against a live Plex Media Server — the play queue is created for a track, an
album and a playlist, and the empty-client case is handled — but no Plex client advertised to the
server while this was written, and no plex.tv account token was available for Sonos. If you are the
first to use it, `--now` is the moment to find out, and a report either way is welcome on the issue
tracker.

## What `media_id` is, and what consumes it

Every command that identifies one item prints a block like this and then stops — `play`, which
[Playback](#playback) can switch on, prints the same block and then starts the item:

```
item:
  media_id: "plex://a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0/111"
  rating_key: 111
  guid: "plex://track/a1b2c3d4e5f60718293c0111"
  note: "rating_key is local to this server and changes when an item is re-matched or the library is rebuilt; guid is the identifier that survives, so keep them together"
```

`media_id` is `plex://<machineIdentifier>/<ratingKey>`: the id of the item, prefixed by the id of
the server it lives on. That combination is what a media player needs to fetch it without being told
separately which Plex server you meant, and it is the form most Plex clients and integrations accept
as a media content id.

It matters that it is *that* form. Six `plex://` strings circulate and they all look alike. Two of
them break a consumer: `plex://track/<ratingKey>` parses the word `track` as a server name and
resolves to a server that does not exist, and `plex://track/<24-hex>` — which is a perfectly
legitimate Plex identifier, the one printed here as `guid` — raises an error inside consumers that
expect a number in that position. `plex-axi` emits only the safe form, and a test sweeps every
command asserting it never emits the other two.

**Every row of every list carries a `media_id` too**, not just the single-item block above. A list
view that printed a bare `key` would end one call short of the thing the tool exists to produce.
The `guid` is not in the default row: it is the identifier you write down rather than the one a
consumer takes, and it is available by name (`--fields key,title,guid`) and in the detail views.

**A playlist has one as well.** `plex-axi playlist list` and `plex-axi playlist show` print a
`media_id` for the playlist itself, so playing a whole playlist needs no more assembly than playing
one track does. A playlist's rating key lives in the same `/library/metadata` namespace, so the same
`plex://<machineIdentifier>/<ratingKey>` form resolves to the playlist — verified on a real server
and against a real consumer, not assumed.

Out of the box `plex-axi` does not dispatch it anywhere. Handing it to something that plays is a
single call in whatever already owns your speakers. In Home Assistant, for example, the
`media_player.play_media` service takes it directly:

```yaml
service: media_player.play_media
target:
  entity_id: media_player.example_speaker
data:
  media_content_type: music
  media_content_id: "plex://a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0/111"
```

That is illustrative, not a dependency: nothing in `plex-axi` knows Home Assistant exists, and the
same id is what Plex's own clients and other integrations consume. Substitute whatever plays music
where you are — or, if nothing does, [Playback](#playback) switches on a `play` command that takes
this rating key directly.

**Keep the `guid` with the `rating_key` wherever you write one down.** A rating key is a row number
in one server's database. It changes when an item is re-matched or the library is rebuilt, and the
same number will then resolve to a different recording — silently. The `guid` is usually the
identifier that survives, which is why both are printed together and why the note travels with them.

**"Usually", because of one shape.** An item Plex never matched to its catalogue carries
`local://<rating_key>` — the rating key with a scheme in front of it — and that is common enough to
matter, roughly one track in seven on a real library. Such a guid moves exactly when the rating key
moves, so there is nothing durable to record for those items and the note says that instead of
promising the opposite. Match them by artist and title if you need them to survive a rebuild.

## Agent integration

Install the [Agent Skill](https://agentskills.io) so an agent loads the guidance on demand,
without paying for it in every session:

```sh
npx skills add dmealing/plex-axi --skill plex-axi
```

`skills/plex-axi/SKILL.md` is generated from the CLI's own command table, so it cannot describe a
flag that does not exist.

## Design notes

- The client library is `python-plexapi`, chosen for its *model* rather than its transport: it is
  the only Plex library with `MusicSection`, the filter language, and server-side field validation.
  It is synchronous, which is a hazard in a long-running service and simply correct in a one-shot
  CLI — do not "fix" it.
- Plex's media-query language is documented in the community OpenAPI specification
  (<https://github.com/LukeHagar/plex-api-spec>, MIT), which is the thing to cite rather than
  re-derive.
- Playback reaches a local client through the server's own remote-control path and a Sonos speaker
  through one documented `sonos.plex.tv` endpoint parsed with the standard library. It deliberately
  does **not** use the client library's `PlexClient`/`MyPlexAccount`/`plexapi.sonos` object model,
  which is asserted by a test: that surface resolves speakers by name and dispatches to them, and
  keeping it out of the process is what stops "play one thing on one named target" growing into a
  control plane by accident.
- Development notes, including every sharp edge behind the code, are in [AGENTS.md](AGENTS.md).

## Contributing

```sh
pip install -e ".[dev]"
scripts/install-hooks.sh
pytest && ruff check . && ruff format --check . && scripts/leakcheck.py
```

This repository is public and a music library is full of identifying content, so a leak guard runs
in a pre-commit hook, a commit-msg hook, CI, and — on every open, push *and edit* — over the pull
request's own title and body. That last one is not a file: a title and a body are published the
moment they are written, are in no checkout and pass under no hook, and tooling routinely writes
into a body, where an embedded script's worktree variable or a `pytest` header's `rootdir:` line is
an absolute home path. It fails the check when it cannot read the pull request rather than reporting
a clean it cannot support, and it reports the field, line and rule of a match — plus the offset when
the finding's pass read the text as written — without printing the match, because a CI log is more
public than the page it came from. For the same reason a pull request cannot carry an `allow=`
marker: in a file that marker is committed and reviewed, and in a body it is an off-switch anyone
can add after every check has run.

**Its coverage is bounded and it does not replace review:** it detects shapes — tokens, addresses,
machine identifiers, media paths — and it cannot detect a real artist name, which has no shape. Use
obviously-synthetic content everywhere, including tests and fixtures.

```sh
scripts/leakcheck.py                       # scan every tracked file
scripts/leakcheck.py --staged              # scan what a commit would actually record
scripts/leakcheck.py --commit-msg <path>   # scan a commit message
scripts/leakcheck.py --pull-request <n>    # scan a pull request's title and body
scripts/leakcheck.py --rules               # list the rules, the surfaces, and the allowances
scripts/leakcheck.py --demo                # self-test: prove every rule still fires
```

The TOON encoder is held to the specification's own opinion as well as to this project's:
**every** official encode fixture is vendored byte-for-byte from
[`toon-format/spec`](https://github.com/toon-format/spec) and runs on every `pytest`. The case count
is asserted too, so a fixture that stops being collected fails the suite instead of quietly lowering
the score, and so are the per-file checksums, so a fixture edited to suit the encoder fails as well.

Commit messages are checked as well as scanned. release-please builds the changelog and the version
bump from them, and when its parser cannot read one it says so at debug level, drops the commit and
**exits 0** — a fix merged to `main` that is never published, with a green release run over it. So
`scripts/commitcheck.py` refuses a message that parser would reject, from the same `commit-msg` hook,
and the release workflow re-checks every commit since the last tag. Rich commit bodies are the point
of this history and nothing here restricts them; the one shape to know is that a body line must not
*begin* with a word run straight into an unclosed or nested parenthesis — `` `Decimal(repr(v))` ``
at a line start is refused, and the same phrase one word further along the line is fine. Run
`scripts/commitcheck.py --rules` for the grammar rule and its citation.

Tests never need a live Plex server or a real token, and must not start to.

## Changelog

Every release is recorded in [CHANGELOG.md](CHANGELOG.md), generated from Conventional Commit
messages by release-please.

## Licence

MIT. See [LICENSE](LICENSE).

`tests/fixtures/toon-spec/` vendors the TOON specification's conformance fixtures, which are MIT
licensed and copyright their authors; the upstream licence, the commit they came from and the
refresh recipe are recorded beside them in `PROVENANCE.md`.
