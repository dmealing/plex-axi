# plex-axi

An Agent eXperience Interface (AXI) CLI for a Plex music library.

**Structured, per-field music search.** Every published Plex CLI, MCP server and LLM wrapper takes a
single free-text `query` string and hands it to the server as one blob — which is why searching for
an artist *and* a song title reliably returns nothing. `plex-axi` gives each value its own flag and
each flag its own Plex field, and lets Plex evaluate the whole predicate server-side.

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

**It deliberately does not play anything.** There is no play command and no concept of a speaker,
room, player or client. Every command ends at a labelled `media_id`, and dispatch belongs to
whatever owns the speakers where you are. That is a decision enforced by a test, not a missing
feature — see [AGENTS.md](AGENTS.md).

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
`access:` line under the description saying whether that command reads or writes.

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

### Output

TOON on stdout, exit non-zero on failure. `--human` for a readable table, `--json` for raw JSON.
Errors are structured on stdout too and carry the command that fixes them, so a wrong flag corrects
itself in one turn.

### Rules of thumb

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

There is still no playback, no speaker, no metadata editing and no server administration. Rating a
track and editing a playlist are not dispatch; playing one is.

## What `media_id` is, and what consumes it

Every command that identifies one item prints a block like this and then stops:

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

`plex-axi` does not dispatch it anywhere. Handing it to something that plays is a single call in
whatever already owns your speakers. In Home Assistant, for example, the `media_player.play_media`
service takes it directly:

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
where you are.

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

Install the skill so an agent loads the guidance on demand:

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
- Development notes, including every sharp edge behind the code, are in [AGENTS.md](AGENTS.md).

## Contributing

```sh
pip install -e ".[dev]"
scripts/install-hooks.sh
pytest && ruff check . && ruff format --check . && scripts/leakcheck.py
```

This repository is public and a music library is full of identifying content, so a leak guard runs
in a pre-commit hook, a commit-msg hook and CI. **Its coverage is bounded and it does not replace
review:** it detects shapes — tokens, addresses, machine identifiers, media paths — and it cannot
detect a real artist name, which has no shape. Use obviously-synthetic content everywhere, including
tests and fixtures.

Tests never need a live Plex server or a real token, and must not start to.

## Licence

MIT. See [LICENSE](LICENSE).
