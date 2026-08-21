---
name: plex-axi
description: Search and diagnose a Plex music library through the plex-axi CLI - structured per-field search on artist, album, track, genre, mood, style, year and rating; the library's own genre/mood/style vocabulary; track, album and artist detail including file availability; and sonically similar tracks. It can also set a rating and edit an audio playlist, but only when the operator has enabled writes. Use whenever a task touches a Plex music library: finding a recording, checking why a search found nothing, or resolving a title to a media id. It never plays anything.
---

# plex-axi

Structured, per-field music search and diagnosis against a Plex Media Server. Prefer this over raw curl or a free-text search for anything about a music library.

## Configuration

Both values come from the environment. There is no `--token` flag and no credential
file: a token on a command line leaks into shell history and the process table, and a
Plex token is a bearer credential for the whole library.

```sh
export PLEX_URL=http://plex.example.com:32400   # the server on the local network
export PLEX_TOKEN=<a Plex access token>
export PLEX_SECTION='Example Music'             # only if there is more than one
export PLEX_AXI_ALLOW_WRITES=true        # only to allow `rate` and `playlist` to write
```

Point `PLEX_URL` at the server itself rather than at plex.tv, so the tool keeps
working when plex.tv is down and no invocation pays a cloud round-trip.
Run `plex-axi doctor` to confirm; it exits non-zero when any check fails.

## Running without a global install

```sh
uvx plex-axi search --artist 'Example Artist'
pipx run plex-axi genres
```

## Output

Commands print TOON on stdout and exit non-zero on failure. Add `--human` for a
readable table, or `--json` for raw JSON. Errors are structured on stdout too, and
carry the command that fixes them.

## What this tool does not do

- **It never plays anything.** There is no play command and no concept of a speaker,
  room or player. Every command ends at a labelled `media_id`, and dispatch belongs to
  whatever owns the speakers.
- **It is music only.** No films, shows, episodes or watchlist. The rest of the Plex
  tooling landscape is video-shaped; this is the half nothing else covers.
- **It reads unless it is told twice that it may write.** Only `rate` and
  `playlist create|add|remove` change anything. They refuse unless `PLEX_AXI_ALLOW_WRITES`
  is `true` in the environment, and even then they preview the change and
  send nothing until `--write` is passed. Every other command reads, and `api` refuses
  every method but GET rather than documenting that it should not be used for them.

## Commands

### `plex-axi search`

Search the music library field by field, server-side.

- **read-only - this command cannot change anything on the server**

```sh
plex-axi search --artist 'Example Artist' --track 'Example Track'
plex-axi search --genre Jazz --rated-min 4 --limit 10
plex-axi search --artist 'Example Artist' --type album
plex-axi search --mood mellow --sort userRating:desc --fields key,title,artist,rating
```

- each flag is searched on its own Plex field; that is the whole point of this tool
- ratings are stars (0-5) in and out, so a rating in a result can be passed to --rated-min
- track fields: key, media_id, title, artist, track_artist, album, year, rating, duration, plays, skips, index, guid
- album fields: key, media_id, title, artist, year, rating, tracks, added, guid
- artist fields: key, media_id, title, rating, added, guid
- identical track titles are collapsed with Plex's own `group=title`; --no-group shows each

### `plex-axi pick`

Choose tracks to play now, filtered and shuffled by the server.

- **read-only - this command cannot change anything on the server**

```sh
plex-axi pick
plex-axi pick --rated-min 4 --limit 20
plex-axi pick --genre Jazz --not-played-since 30d --exclude-live
```

- every filter is a Plex predicate evaluated server-side; anything this server does not offer is reported under `unapplied`, never applied client-side
- the shuffle is the server's `sort=random` over the whole match set, not a shuffle of one page
- identical titles are collapsed with Plex's own `group=title`, so one song does not fill the list from three pressings
- ratings are stars (0-5) in and out, so a rating in a result can be passed back

### `plex-axi genres`

List the genres this library uses.

- **read-only - this command cannot change anything on the server**

```sh
plex-axi genres
plex-axi search --genre '<value>'
```

- the values this library will accept for `search --genre`, read from the server
- genres are carried on the artist in a Plex music library, not on the track

### `plex-axi moods`

List the moods this library uses.

- **read-only - this command cannot change anything on the server**

```sh
plex-axi moods
plex-axi search --mood '<value>'
```

- the values this library will accept for `search --mood`, read from the server
- moods are written at every level; --type chooses which set to list

### `plex-axi styles`

List the styles this library uses.

- **read-only - this command cannot change anything on the server**

```sh
plex-axi styles
plex-axi search --style '<value>'
```

- the values this library will accept for `search --style`, read from the server
- styles are carried on the artist in a Plex music library, not on the track

### `plex-axi track`

Show one track in full, with its media id.

- **read-only - this command cannot change anything on the server**

```sh
plex-axi track 12345
plex-axi search --artist 'Example Artist' --type track
```

- analysis is Plex's musicAnalysisVersion; 0 means `similar` has no seed
- rating is in stars (0-5), the same scale as `search --rated-min`
- rating_key is local to this server; guid is the identifier that survives a re-match
- run `plex-axi rate <rating_key> --stars <0-5>` to change the rating this reports

### `plex-axi album`

Show one album in full, with its media id.

- **read-only - this command cannot change anything on the server**

```sh
plex-axi album 12345
plex-axi search --artist 'Example Artist' --type album
```

- rating is in stars (0-5), the same scale as `search --rated-min`
- rating_key is local to this server; guid is the identifier that survives a re-match
- run `plex-axi rate <rating_key> --stars <0-5>` to change the rating this reports

### `plex-axi artist`

Show one artist in full, with its media id.

- **read-only - this command cannot change anything on the server**

```sh
plex-axi artist 12345
plex-axi search --artist 'Example Artist' --type artist
```

- rating is in stars (0-5), the same scale as `search --rated-min`
- rating_key is local to this server; guid is the identifier that survives a re-match
- run `plex-axi rate <rating_key> --stars <0-5>` to change the rating this reports

### `plex-axi similar`

List tracks Plex's analysis finds sonically similar, with distances.

- **read-only - this command cannot change anything on the server**

```sh
plex-axi similar 12345
plex-axi similar 12345 --max-distance 0.1 --limit 5
```

- distance is the server's own sonic distance: 0 is identical, larger is further away
- a seed with no `analysis` version has not been analysed and can return nothing at all

### `plex-axi recent`

List what was added to the music library most recently.

- **read-only - this command cannot change anything on the server**

```sh
plex-axi recent
plex-axi recent --type track --limit 50
```

- scoped to the music library: the server-wide recently-added list spans video too

### `plex-axi playlist`

List, inspect and edit the audio playlists on this server.

- **list, show: read-only - this command cannot change anything on the server**
  - create, add, remove: mutating - needs PLEX_AXI_ALLOW_WRITES=true in the environment; without --write it previews the change and sends nothing

```sh
plex-axi playlist
plex-axi playlist show 'Example Playlist'
plex-axi playlist show 501
plex-axi playlist add 'Example Playlist' --key 12345 --key 12346
plex-axi playlist create 'Example Playlist' --key 12345 --write
```

- only audio playlists are listed or edited; video and photo playlists on the same server are deliberately invisible here
- a smart playlist's contents are a saved search and cannot be edited by adding items; the command says so rather than letting the server refuse
- a playlist is named by its `key` from `playlist list`, or by its exact case-folded title; on a miss the real keys and titles are handed back
- `items` in a listing is the count the server declares, which for a smart playlist is cached; `playlist show` reports what it actually holds
- nothing here plays a playlist: `show` prints the tracks and their media ids

### `plex-axi rate`

Set or clear your rating on one track, album or artist.

- **mutating - needs PLEX_AXI_ALLOW_WRITES=true in the environment; without --write it previews the change and sends nothing**

```sh
plex-axi rate 12345 --stars 4
plex-axi rate 12345 --stars 4 --write
plex-axi rate 12345 --clear --write
```

- the rating printed afterwards is read back from the server, not echoed from the request
- a rating is per-account state, not library metadata; editing metadata stays out of scope
- rating something to the value it already has is a no-op and exits 0

### `plex-axi sessions`

List the streams the server currently believes are playing.

- **read-only - this command cannot change anything on the server**

```sh
plex-axi sessions
```

- music sessions are listed first; anything else is counted, not detailed
- nothing here can start, stop or address a stream: listing one is a read

### `plex-axi api`

Make an authenticated GET to any Plex API path.

- **read-only - this command cannot change anything on the server**

```sh
plex-axi api /
plex-axi api /library/sections
plex-axi api /status/sessions
plex-axi api /library/sections/1/all --query type=10 --query limit=5
```

- the method is GET, spelled out or omitted; a HEAD is refused because it has no body to render
- write methods are refused here even when writes are enabled: a mutation goes through a typed command that can validate and preview it, and several Plex write endpoints are destructive
- the token is sent as a header and never appears in the path this prints
- paths are absolute: `library/sections` is refused, `/library/sections` is the path

### `plex-axi doctor`

Check the environment, the server, the music library and its filters.

- **read-only - this command cannot change anything on the server**

```sh
plex-axi doctor
plex-axi --section 'Example Music' doctor
```

- exits non-zero when any check fails, so it works as a CI or hook gate
- a rejected token is reported as invalid or expired separately, because Plex answers 401 to both and only the response text tells them apart

### `plex-axi skill`

Write or verify the generated Agent Skill for this CLI.

- **read-only - this command cannot change anything on the server**

```sh
plex-axi skill
plex-axi skill --check
```

- writes skills/plex-axi/SKILL.md; never hand-edit that file, it is generated
- needs no server and no token: it reads the command table, not the library

## Rules of thumb

- **Use a flag per field.** `--artist 'X' --track 'Y'` searches two Plex fields;
  `--query 'X Y'` searches one string and is why other Plex tools miss. `--query`
  exists for the case where there genuinely is only one unstructured string.
- **Ratings are stars, 0-5, in both directions.** A rating printed in a result can
  be passed straight to `--rated-min`.
- **Genres and styles live on the artist**, not on the track. `plex-axi genres`
  prints the exact strings the server will accept; pass one of those, not a synonym.
- **A zero result is an answer.** It names the filters that matched nothing and the
  command that lists the real vocabulary. Drop one flag at a time to find the
  one that was wrong.
- **Every row carries a `media_id`.** That is the product: a labelled identifier
  a media consumer accepts, so a list view needs no follow-up call to be useful.
- **`rating_key` is local to one server and moves.** It changes when an item is
  re-matched or the library is rebuilt, so keep the `guid` beside it anywhere the
  value is written down -- *unless* the guid is `local://<rating_key>`, which Plex
  gives an item it never matched. That one moves with the rating key, and the
  detail view says so rather than promising it will not.
- **A track whose `analysis` is not a version number has never been analysed**, so
  `similar` has nothing to work from and its empty answer is not a statement about
  the library.
- **`--fields` replaces the default columns**; it does not add to them. The default
  set is a suggestion and may grow a column when the data warrants one, so a caller
  that needs a fixed schema should name it.
- **`--rated-min` is a minimum in stars, and 0 is not a filter.** `--rated-min 0`
  is the bottom of the scale and narrows nothing; `--rated-min 0.5` is what asks
  for everything that carries a rating at all.
- **A mutating command run without `--write` is safe and useful.** It prints what
  would change and sends nothing, which is how to check a playlist edit before
  making it -- and how a smart playlist is caught before the server refuses.
- Every command supports `--help`, which is the authoritative reference for its flags.
