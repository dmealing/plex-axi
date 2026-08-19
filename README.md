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
tracks[1]{key,title,artist,album}:
  111,Example Track,Example Artist,Example Album
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
plex-axi genres                                       # and `moods`, `styles`
plex-axi track 12345 --check-files
plex-axi similar 12345 --max-distance 0.1
plex-axi recent
plex-axi sessions
plex-axi api /library/sections                        # the escape hatch, read-only
```

Every command takes `--help`, which is the authoritative reference for its flags.

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
- **`rating_key` is local to one server and moves** when an item is re-matched or the library is
  rebuilt. Keep the `guid` beside it anywhere the value is written down.

### Handing an id to something that plays it

`plex-axi` prints `media_id` in the one `plex://` form that is unambiguous —
`plex://<machineIdentifier>/<ratingKey>` — and never the two forms that break a consumer. What
plays it is your business, not the tool's, so the "play this with…" line is configuration:

```sh
export PLEX_AXI_PLAY_HINT='my-player enqueue {media_id}'
```

With the variable unset, no such line is printed. `{media_id}`, `{rating_key}` and `{guid}` are
substituted.

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
