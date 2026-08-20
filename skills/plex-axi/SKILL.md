---
name: plex-axi
description: Search and diagnose a Plex music library through the plex-axi CLI - structured per-field search on artist, album, track, genre, mood, style, year and rating; the library's own genre/mood/style vocabulary; track, album and artist detail including file availability; and sonically similar tracks. Use whenever a task touches a Plex music library: finding a recording, checking why a search found nothing, or resolving a title to a media id. It never plays anything.
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
- **It is read-only.** Nothing here changes the library, and `api` refuses write
  methods rather than documenting that it should not be used for them.

## Commands

### `plex-axi search`

Search the music library field by field, server-side.

```sh
plex-axi search --artist 'Example Artist' --track 'Example Track'
plex-axi search --genre Jazz --rated-min 4 --limit 10
plex-axi search --artist 'Example Artist' --type album
plex-axi search --mood mellow --sort userRating:desc --fields key,title,artist,rating
```

- each flag is searched on its own Plex field; that is the whole point of this tool
- ratings are stars (0-5) in and out, so a rating in a result can be passed to --rated-min
- track fields: key, title, artist, track_artist, album, year, rating, duration, plays, skips, index, guid
- album fields: key, title, artist, year, rating, tracks, added, guid
- artist fields: key, title, rating, added, guid
- identical track titles are collapsed with Plex's own `group=title`; --no-group shows each
- read-only: this command cannot change anything on the server

### `plex-axi genres`

List the genres this library uses.

```sh
plex-axi genres
plex-axi search --genre '<value>'
```

- the values this library will accept for `search --genre`, read from the server
- genres are carried on the artist in a Plex music library, not on the track
- read-only: this command cannot change anything on the server

### `plex-axi moods`

List the moods this library uses.

```sh
plex-axi moods
plex-axi search --mood '<value>'
```

- the values this library will accept for `search --mood`, read from the server
- moods are written at every level; --type chooses which set to list
- read-only: this command cannot change anything on the server

### `plex-axi styles`

List the styles this library uses.

```sh
plex-axi styles
plex-axi search --style '<value>'
```

- the values this library will accept for `search --style`, read from the server
- styles are carried on the artist in a Plex music library, not on the track
- read-only: this command cannot change anything on the server

### `plex-axi track`

Show one track in full, with its media id.

```sh
plex-axi track 12345
plex-axi search --artist 'Example Artist' --type track
```

- analysis is Plex's musicAnalysisVersion; 0 means `similar` has no seed
- rating is in stars (0-5), the same scale as `search --rated-min`
- rating_key is local to this server; guid is the identifier that survives a re-match
- read-only: this command cannot change anything on the server

### `plex-axi album`

Show one album in full, with its media id.

```sh
plex-axi album 12345
plex-axi search --artist 'Example Artist' --type album
```

- rating is in stars (0-5), the same scale as `search --rated-min`
- rating_key is local to this server; guid is the identifier that survives a re-match
- read-only: this command cannot change anything on the server

### `plex-axi artist`

Show one artist in full, with its media id.

```sh
plex-axi artist 12345
plex-axi search --artist 'Example Artist' --type artist
```

- rating is in stars (0-5), the same scale as `search --rated-min`
- rating_key is local to this server; guid is the identifier that survives a re-match
- read-only: this command cannot change anything on the server

### `plex-axi similar`

List tracks Plex's analysis finds sonically similar, with distances.

```sh
plex-axi similar 12345
plex-axi similar 12345 --max-distance 0.1 --limit 5
```

- distance is the server's own sonic distance: 0 is identical, larger is further away
- a seed whose `analysis` is 0 has not been analysed and can return nothing at all
- read-only: this command cannot change anything on the server

### `plex-axi recent`

List what was added to the music library most recently.

```sh
plex-axi recent
plex-axi recent --type track --limit 50
```

- scoped to the music library: the server-wide recently-added list spans video too
- read-only: this command cannot change anything on the server

### `plex-axi sessions`

List the streams the server currently believes are playing.

```sh
plex-axi sessions
```

- music sessions are listed first; anything else is counted, not detailed
- read-only: this command reports sessions and cannot control one

### `plex-axi api`

Make an authenticated GET to any Plex API path.

```sh
plex-axi api /
plex-axi api /library/sections
plex-axi api /status/sessions
plex-axi api /library/sections/1/all --query type=10 --query limit=5
```

- the method is GET, spelled out or omitted; a HEAD is refused because it has no body to render
- write methods are refused: plex-axi is read-only, and several Plex write endpoints are destructive
- the token is sent as a header and never appears in the path this prints

### `plex-axi doctor`

Check the environment, the server, the music library and its filters.

```sh
plex-axi doctor
plex-axi --section 'Example Music' doctor
```

- exits non-zero when any check fails, so it works as a CI or hook gate
- a rejected token is reported as invalid or expired separately, because Plex answers 401 to both and only the response text tells them apart

### `plex-axi skill`

Write or verify the generated Agent Skill for this CLI.

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
- **`rating_key` is local to one server and moves.** It changes when an item is
  re-matched or the library is rebuilt, so keep the `guid` beside it anywhere the
  value is written down.
- **A track with `analysis: 0` has never been analysed**, so `similar` has nothing
  to work from and its empty answer is not a statement about the library.
- Every command supports `--help`, which is the authoritative reference for its flags.
