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
scripts/leakcheck.py --pull-request N    # a pull request's title and body (hygiene.yml)
scripts/leakcheck.py --rules             # the live rule list
scripts/leakcheck.py --demo              # self-test: proves every rule still fires
scripts/install-hooks.sh                 # sets core.hooksPath to .githooks
```

CI runs `--demo` before the real scan, so a scanner that stopped detecting anything fails the build
rather than passing silently. If the scanner flags a line that legitimately needs the shape, add
`leakcheck: allow=<rule>` on that line — scoped to that one rule, never blanket. Do not weaken a
rule to make a commit pass, and do not bypass the hooks.

**A file that cannot carry a marker** — JSON has no comment syntax, and vendored third-party data
must stay byte-for-byte — is exempted in `PATH_ALLOWANCES` in `scripts/leakcheck.py` instead, per
path *and* per rule, and `--rules` prints the table so the exemption is visible where the rules
are. There are three entries today: the vendored TOON fixture whose backslash-escaping case is a
synthetic Windows drive path, and the two commit-message fixtures transcribed from this
repository's own history, which must stay byte-for-byte the commits they pin and whose co-author
trailers carry no-reply addresses. `tests/test_leakcheck.py` re-scans each exempted file with the
table switched off and asserts that the rules which fire, and the shapes they match, are exactly
the ones the entry names — an entry that has outlived its cause fails the suite rather than
quietly covering something new.

**An allowance is matched against the exact path it names, and every entry point has to agree on
what that path is.** `path_allowances` is a dictionary lookup: a name that merely *ends with* an
allowed one — `attic/<allowed>`, `<allowed>.bak`, an absolute name from a scan rooted elsewhere — is
a different file, and honouring it would grant the entry every directory it is ever copied into. An
exact comparison is only worth as much as that agreement, so `repo_relative` gives one file one
name whatever found it: the tracked-files scan and `--staged` get repository-relative names from
git, and explicit paths and the `os.walk` fallback are normalised against `--root`. Both halves are
load-bearing and both are tested by mutation: `tests/test_leakcheck.py` runs the whole allowance
through all four entry points against a repository that also holds a *decoy* under a shadowing
directory, and asserts the named file is exempt while the decoy is reported.

**The other loose matches in the guard, audited alongside that fix and left as they are.** Three are
deliberate and one is worth knowing about:

- `_email_allowed` compares the domain with `endswith("." + allowed)`. That is DNS semantics, not a
  widening — the leading dot anchors it, so `myexample.com` is still reported — and it is what makes
  `noreply@sub.example.com` legitimate. Keep it.
- The `leakcheck: allow=` marker is found by `line.find`, anywhere on the physical line, so that it
  works in any comment syntax. The rule *names* it yields are then compared exactly. The consequence
  worth remembering: a **misspelled rule name exempts nothing and says nothing**, so a line that
  reads as protected is not. Fail-safe, and invisible.
- `SKIP_DIRECTORIES` matches a directory *name at any depth*, not a path, so a directory called
  `dist`, `build`, `venv` or `node_modules` anywhere in the tree is skipped whole. It only applies to
  the `os.walk` modes: the tracked-files scan and `--staged` list files from git and never consult
  it, so nothing tracked escapes the scan this way.
- `tests/test_no_dispatch.py` stopped being a loose match at all when this change rewrote its scan
  from raw lines to an AST walk over names, attributes, imports and string literals. It reads no
  comments and no docstrings, so there is no per-line exemption to narrow. The string-literal half
  is what keeps `getattr(x, 'playMedia')` caught as surely as the attribute would be; the
  docstring-blindness is what lets `cloud.py` explain at length why it does *not* use
  `plexapi.sonos` without that paragraph being the offence -- a rule the prose could trip would be
  answered by deleting the prose, which is the opposite of what it is for.

**There are three surfaces, and the third one is not a file.** A pull request title and body are
published the moment they are written, are in no checkout, pass under no hook, and can be edited
after every other check has run — so neither the tracked-file scan nor `--commit-msg` has ever seen
one. That is not theoretical: the pipeline's own document step writes into the body, embedding an
evidence script that assigns the checkout it ran from and pasting captured pytest output whose
header carries a `rootdir:` line. Both are absolute home paths, and between this repository and the
sibling that mechanism published a home directory **three times in one day**, with every check green
each time — because the only check that read the body at all, `commitcheck --pull-request`, was
reading it for a different question and answering that one correctly. **The rules were never the
problem; the reach was**, which is why `--pull-request` reuses `RULES` and `scan_text` outright
rather than growing a second pattern list. A rule added later covers all three surfaces with nobody
remembering to wire it up.

**Captured tool output was the leak source twice over, and one of the two was the scanner's own
self-test.** `--demo` printed what each rule caught to prove the rules fire — and those samples are
leak-shaped by construction, so pasting the demo's output into a body as evidence fails the very
check it opens, which is what happened to the sibling's pull request that introduced that check. The
demo therefore reports every finding without the value, the way the pull request reporter already
did, and `tests/test_leakcheck.py` pins that the demo's output passes the pull request scan.

Three things about that scan are load-bearing:

- **`edited` in `hygiene.yml`'s trigger list is the whole mechanism.** The document step writes the
  evidence into the body *after* the pull request is opened, so a check firing only on `opened` and
  `synchronize` would scan the empty original body and pass. This repository already carried
  `edited` for release-please's sake; the leak scan rides the same trigger, so two separate guards
  now depend on it, and `tests/test_leakcheck.py` asserts it is still there by parsing the workflow
  rather than matching it as text.
- **It fails closed, in both directions.** No token, no `owner/name`, a fetch that does not answer,
  an answer that is not a pull request, or an empty `RULES` — every one of them fails the check
  rather than reporting a clean it cannot support. `0 findings` from a guard that never saw the
  artefact converts an unknown risk into a false assurance, which is worse than not running.
- **The report names the field, line, rule and offset, and never the match.** A pull request check
  runs on a public log; printing the excerpt the file report prints would republish the leak to a
  wider audience than the pull request page. The offset is printed only when the finding's pass read
  the text as written — one surfaced in a percent-decoded or joined view indexes a string that
  exists nowhere the reader can open, so it prints `-` and the pass column instead. For the same
  reason a pull request cannot carry a `leakcheck: allow=` marker: in a file that marker is
  committed, diffed and reviewed, and in a body it is an off-switch anyone can add after every check
  has run, on the one artefact whose being editable-after-the-fact is why the surface needs a guard
  at all. An attribution trailer is still exempt from the address rule alone, because GitHub's
  squash box offers the body as the commit message.

**A finding is deduplicated per location, not per value, and the difference is one round of
scrubbing per occurrence.** `Finding.key` carries the line as well as the matched value. Without it
the same value on nine lines — which is what a capture step pasting the same header nine times
produces — was reported once, at the first line. Somebody scrubbing exactly what the report named
published the other eight, and the re-run then named the next one: convergent, but one round per
occurrence, which in practice means a partial fix and a green check. This was measured, not
supposed: a sweep of this repository and its sibling found **eight leaking pull request bodies, one
of them with six separate matches**, and re-scanning this project's own first leaky body reports
**fifteen** `home-path` locations behind **three** distinct values where the old key reported one.

The half of the old key that was right is kept. Deduplicating on the *value* exists so the line pass
and the condensed pass do not report one leak twice, and those two passes agree on the line — the
condensed pass attributes a match to the line its region starts on — so the line joins the key
without weakening that. The line pass runs first, so the survivor is the one carrying an offset.
`tests/test_leakcheck.py` pins both halves: every location of a repeated value is reported, on a
pull request and in a file alike, and one location seen by two passes is still reported once.

`leakcheck.py` borrows `commitcheck.py`'s GitHub reader rather than growing its own — same token
resolution, same slug resolution, same error taxonomy — and imports it at the point of use so the
hooks never pay for it. The reuse deliberately runs one way only: `commitcheck.py` is byte-identical
with the sibling project's copy and must stay that way.

**Writing a report that says where without saying what is a constraint on the prose too.** The help
text under a pull request finding must not contain the words a leaked path is made of: an assertion
that the leaked value never reaches the log is a substring check, and advice that happened to use
the word `checkout` tripped it. Describe the *source* of a leak (a worktree variable, a pytest
header) rather than the shape of one.

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

- `toon.py` — a strict TOON encoder (spec v4.1), shared with the sibling AXI project. Encoding
  happens **only** at the output boundary; command modules return plain JSON-shaped dicts. Do not
  loosen it to make output prettier. Two suites cover it and they are not interchangeable:
  `tests/test_toon.py` states the behaviour in this project's words, and
  `tests/test_toon_conformance.py` runs the specification's own encode fixtures — every one of
  them, vendored byte-for-byte from `toon-format/spec` under `tests/fixtures/toon-spec/` (MIT;
  provenance, checksums and the refresh recipe live in `PROVENANCE.md` beside them). `CASE_COUNT`
  there is the only place the case count is written, and it is asserted, so a fixture that stops
  being collected fails instead of shrinking the score. A rule nobody thought to write a test for
  reads as passing, which is how 0.2.2 shipped two failing cases while the README claimed
  strictness.
- `output.py` — the single place anything reaches stdout, and therefore the only place redaction has
  to hold. `HelpBlock` is the one deliberate departure from strict TOON: `help[N]:` blocks render one
  suggestion per line, matching the AXI standard and the sibling AXI CLIs, because the suggestions
  are command lines full of commas.
- `plex.py` — connection, hardening and error translation. Nothing from the client library crosses
  this boundary: not its exceptions, not its response bodies, not its name.
- `music.py` — the product, and only the half of it that needs a live server: section resolution,
  the operator titles a section advertises, the search, the exact total, the `plexapi` exception
  classification and the whole `--fields` row vocabulary.
- `axi_toolkit.plex.filters` — the pure half of the same product, and no longer in this repository:
  `LIBTYPES`, the stars conversion both ways, `FIELD_MAP`, the operators, `build_filters`, the
  relative dates and `parse_sort`. Everything there takes a flag's raw value and returns a value or
  raises; nothing there takes a `server` or a `section`. See "The shared package" below.
- `axi_toolkit.plex.ids` — which `plex://` string may be printed, also no longer here. See "The six
  `plex://` forms" below.
- `errors.py` — this tool's error classes, and the one place a shared refusal is rendered. See "The
  shared package".
- `writes.py` — the write gate and the `access` vocabulary. Nothing mutates without going through
  `writes.require`, and every command declares `access=READ_ONLY` or `access=MUTATING` so that
  `--help` and the generated skill are printing the *same declaration* rather than two descriptions
  that can drift. See "The write gate" below.
- `playback.py` — the playback gate and the one seam that addresses a player. It holds the gate
  variable, the `dispatching` access level, the target model, target resolution across both routes,
  and the local dispatch itself. Deliberately not the client library's `PlexClient`/`playMedia`
  object model; see "The playback gate" below.
- `cloud.py` — the Sonos route: one `sonos.plex.tv` call with `requests`, parsed with the standard
  library, on the same pattern as `users.py` and for the same reason. Imported lazily, and only
  when `PLEX_ACCOUNT_TOKEN` is set.
- `users.py` — `--user`: one plex.tv call, parsed with the standard library. Deliberately not the
  client library's own user switch; see the sharp edge below.
- `hooks.py` — the session integration AXI §7 calls the *primary* discovery path, and the one
  place this repository writes to a machine rather than to a library: the `SessionStart` hook for
  Claude Code and Codex, the managed OpenCode plugin, and the atomic writes and path repair that
  keep a reinstall from duplicating an entry. Installed only from `plex-axi setup hooks`. See
  "The session integration" below, because the one thing it does not inherit from the sibling is
  the thing the hook actually runs.
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

**A second deviation, and it is the playback gate's doing.** `COMMAND_ORDER` and `_MODULES` are no
longer the whole table. `cli.command_order(environ)` and `cli.modules(environ)` append
`PLAYBACK_ORDER` and `_PLAYBACK_MODULES` when the gate is open, and *everything that lists commands
reads the function rather than the constant* — the dispatcher, root help, the home view and
`skill.py`. That is what makes a closed gate invisible rather than merely refusing. A surface that
reaches for `COMMAND_ORDER` directly is describing the base installation, which is correct for the
committed `SKILL.md` and for the tests that pin the public surface, and wrong for anything a caller
sees. Adding a playback noun is one entry in each of those two, plus its module.

**Two output shapes have exactly one construction site, and the row builders deliberately do not.**
`describe_filter(field, operator, value)` builds every echoed filter — five call sites in
`commands/pick.py` now, the two that sat in `music.py` having moved with `build_filters` and
`rating_predicate`, and the builder itself being `axi_toolkit.plex.filters`' — and
`doctor._check(name, status, detail)` builds all nine rows
of the doctor report. Neither shape had ever diverged, so collapsing them removed the *opportunity*
rather than reconciling a difference — which is what made it checkable as byte-identical output on
every surface that prints either shape, rather than only as a green suite.
`describe_filter` hands back a plain mutable dict on purpose: `label_filters` rewrites the operator
in place afterwards. It is not named `described` because that is the name of the list every caller
appends it to.

The seven **row builders** — `music.track_row`/`album_row`/`artist_row`, `playlist._item_rows` and
`_playlist_row`, `sessions._row`, and the inline one in `home._recent` — look like the same drift
and are not. Each is a set of per-source coercion rules: which server attribute a column reads, what
an absent value becomes, which of the three artist names a compilation needs. A shared builder would
have to carry all of that as parameters, which is the hand-written version with indirection in front
of it. **Leave them hand-written.** What they needed was not deduplication but a check that the
tests reach all of them — see "Build, test, lint".

### The shared package: what left, and the one thing it changed

`axi-toolkit` carries the parts of this tool that two AXI CLIs had in common. Two of them were
this repository's:

- **`ids.py` moved whole** and is `axi_toolkit.plex.ids`. The six forms, the `local://` note, the
  regular expressions and the refusals are the same code; `src/plex_axi/ids.py` is gone and there
  is no shim standing where it was.
- **The pure half of `music.py`** is `axi_toolkit.plex.filters`: `LIBTYPES`, `POINTS_PER_STAR`,
  `stars`, `parse_stars`, `FIELD_MAP`, `BARE_OPERATOR`, `RATING_OPERATOR`, `RATED_MIN_ZERO_NOTE`,
  `describe_filter`, `rating_predicate`, `build_filters`, `assert_server_side`, `RELATIVE_DATE`,
  `ABSOLUTE_DATE`, `parse_relative_date`, `SORT_DIRECTIONS` and `parse_sort`.

**What deliberately stayed, and the line the split follows.** Anything taking a `server`, a
`section` or a page of items is here — `resolve_section`, `run_search`, `count_matches`, the
`advertised_*` probes, `offers`, `label_filters`, `SearchResult` — along with the `plexapi`
exception classification and the whole `--fields` row vocabulary (`ROW_FIELDS`, `default_fields`,
`available_fields`, the seven row builders, `rows_for`, `with_track_artist`, `tag_titles`,
`date_only`, `number`). Those are decisions about *this* tool's output rather than about Plex's
query language. **Do not propose moving them.**

**Every call site was repointed rather than re-exported, and that was a decision.** `music.py`
could have kept importing the moved names and handing them on, which would have left every
existing importer untouched — and would have left two import paths for one object with nothing to
say which is canonical. That ambiguity is the thing the extraction exists to end, so `search.py`,
`pick.py`, `rate.py`, `item.py`, `sessions.py`, `genres.py` and `_common.py` name
`axi_toolkit.plex.filters` directly.

**The one thing that genuinely changed is where the tool's name lives, and it is the reason this
was not a mechanical move.** A dozen recovery lines used to be written out at the point of the
raise, with `plex-axi` baked into the sentence:

```
help_lines=["Run `plex-axi search --track '<title>'` to get this server's rating key"]
```

Upstream those are *intent* — `run(("search", "--track", "'<title>'"), purpose="to get this
server's rating key")` — with no tool name anywhere in them, which is what lets one module serve a
second CLI. So the name has to be supplied here, and there is exactly one place that does it:

- **`plex_axi.errors.AxiError` subclasses `axi_toolkit.errors.AxiError`**, which this module
  re-exports as `AnyAxiError`. That name is what an `except` clause should catch: *an error already
  in AXI's shape, whoever raised it*. A handler catching `AxiError` alone silently misses every
  refusal raised inside `axi_toolkit.plex`, and there were three that would have — the last-resort
  clause in `cli.main`, and the two pass-through arms in `music.run_search` and `commands/pick`,
  each of which would have re-wrapped a caller's typo as a plexapi translation or an
  `INTERNAL_ERROR`. All three are asserted in `tests/test_recovery.py`.
- **`errors.help_lines_for(exc)` is the only place `plex-axi` is put in front of a recovery.** It
  returns this tool's own `help_lines` when it has them and renders the recovery through
  `axi_toolkit.render.cli` when it does not. `cli._error_document`, `doctor` and the home view all
  read it rather than the attribute.
- **`validate_rating_key` takes `command` now, not `invocation`** — the caller's own words *after*
  the tool name, as a tuple: `("track",)`, `("playlist", "add", "'Example Playlist'")`. A bare
  string is refused upstream rather than accepted, because `run` would take one apart into its
  characters and the resulting line would look plausible right up until somebody read it.

**The bar this move had to clear was byte-for-byte output, and it was measured rather than
argued.** 324 invocations — every `--help` surface with each gate open and closed, every refusal
in both moved modules, the successful commands that echo a filter, and the config failures — were
captured from `main` before the change and re-captured after. The two files are identical. Do not
take a green suite as the evidence here: the suite passed on the day the tool's headline filter
did not work against any real server. `tests/test_recovery.py` pins the refusal lines so the next
change to them fails locally.

**A consequence in the other repository, which is not this one's to fix.** `axi-toolkit`'s drift
gates `plexDomainDefinitions`, `plexIdBehaviour` and `plexFilterBehaviour` read *this* repository's
`ids.py` and `music.py` at capture time, to prove the two copies stayed in agreement while both
existed. There is nothing left here for them to read, so they need retiring over there. Nothing
was added here to compensate, and nothing should be.

### Security invariants — do not regress these

- **Every output path is redacted, stdout and stderr alike.** `output.write`, `output.write_text`,
  `output.debug` and `output.debug_exception` all pass through `redact()`. stderr is not a safe
  channel just because agents ignore it: it reaches terminals, logs and CI output.
- **`--debug` is wired, and it stays wired.** It was advertised in root help and in the
  internal-error advice while `output.debug` had *zero* call sites, so the flag wrote nothing on
  every path — including the errors a caller is most likely to be debugging. It now emits the
  command and mode, the connection and the server it reached, the **built search key** (the exact
  resolved predicate, which is the single most useful line this tool can print), the exact total,
  the raw path and query behind `api`, and, from `plex.translate`, what the client library actually
  said before its message was replaced. A handled error adds its type, code and exit code — not a
  traceback, which would bury the line above it; only the last-resort `INTERNAL_ERROR` prints one.
  A test asserts stderr is non-empty with the flag and **empty without it**, on both a successful
  command and a handled error. Either wire a diagnostic or stop advertising the flag; advertised and
  inert is the one state that is not allowed.
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
- **Playback handles two more credentials and both are registered where they arrive.**
  `PLEX_ACCOUNT_TOKEN` is read by `playback.account_token`, which calls `register_secret` before
  returning it; the short-lived delegation token `/security/token` mints is registered by
  `playback._delegation_token` the moment the server hands it over. The delegation one also has a
  shape-based backstop in `redact()` — it travels in a URL under the bare name `token`, so
  `[?&]token=` is redacted like `X-Plex-Token=` is, anchored on a query separator so prose about
  tokens survives.
- **A refused *dispatch* reaches the server zero times, and it is two latches rather than one.**
  With the gate closed `cli` will not route a playback noun at all, and `playback.require` runs at
  the top of `run()` ahead of `ctx.server()` anyway. `tests/test_playback.py` asserts on
  `server.requests` and `server.played`, not on the exit code, for the same reason
  `tests/test_writes.py` does.
- **No network address reaches any output stream.** A `/clients` element carries `host`, `address`
  and `port` and a Sonos resource carries `lanIP`; none of them is read into a row or a message,
  and the double carries them so that withholding them is a test rather than an assumption.
- Tests for all of this live in `tests/test_credentials.py`, which asserts `capsys` **stderr** is
  clean as often as stdout, and in `tests/test_playback.py`.

## The playback gate, and the reversal it records

**The first two releases could not play music, and this file said so in three places.** That
decision is now reversed under a gate. It is worth reading the reasoning before touching any of it,
because the reversal is narrower than it looks and the thing that makes it safe is not the same
thing that makes the write gate safe.

**Why playback is gated at all, rather than simply added.** It was never "playing music is
dangerous". It is that some houses already have something that owns the speakers, and in those
houses a second tool that can also start music lets an agent pick the path the first one cannot
see — leaving the home-automation system, and every assistant downstream of it, describing
something that is not what is playing. Nothing about the code prevents that; only the gate does.

**Why the gate defaults closed, and who should never open it.** The default has to be the answer
that is safe in the house where it is wrong to guess, and that is the house that already
dispatches. **If you run Home Assistant, do not set `PLEX_AXI_ALLOW_PLAYBACK`.** HA owns dispatch
there — Sonos included, which it reaches by its own path — and the intended shape is to use this
tool to *find* music and let HA play it. A play issued here bypasses HA entirely, so HA's state
goes stale the moment it succeeds; the failure is not that nothing happens but that everything
downstream is confidently wrong. The gate exists so that a house with Plex and nothing else can
have the capability without a house that has HA ever being offered it.

**This supersedes the blanket exclusion the first two releases shipped, and the reason it does is
that the exclusion was about one house rather than about the capability.** The rule was written
from this repository's own operator's installation — Home Assistant, Sonos, dispatch already
solved — and generalised into "the tool must never play anything". For anybody with a Plex library
and nothing else that generalisation was simply wrong: the tool dead-ended at an identifier with
nothing to do with it. Both halves are true at once now, and it is the gate that makes them so —
closed and *invisible* by default for the first house, opt-in for the second. If you are here
because you found the old wording somewhere and think this is a regression: the old wording was
right about the house it was written in, and that house is still served by the default.

**What was surrendered, permanently.** `tests/test_no_dispatch.py` used to prove the capability was
not *reachable* — no command, no flag, no code path. Once playback code exists that proof is gone
and it cannot come back: the strongest available claim is that the capability is *gated*, never
that it is *absent*. The file's docstring says exactly that, and lists what it guarantees instead.
Do not add a test asserting the absence of a command that ships; it would have to be deleted the
first time anyone ran it, and a deleted test protects nothing.

### Two conjuncts, and one extra requirement the write gate does not have

1. **`PLEX_AXI_ALLOW_PLAYBACK=true` in the environment is the gate**, matched case-insensitively
   after stripping — the same shape and the same reasoning as `PLEX_AXI_ALLOW_WRITES`.
2. **`--now` on the invocation is the confirmation, and it is not a second gate.** With the gate
   open and the flag absent, `play` resolves the item, resolves the target, prints which one it
   picked and why, and sends nothing. That is where "three clients and you named none of them" and
   "that rating key is a film" are caught, cheaply, before a speaker in somebody's house comes on.
   It is `--now` rather than `--play` because `plex-axi play 12345 --play` reads as ceremony,
   where `--now` says what its absence means.
3. **When the gate is closed the commands do not exist.** This is the requirement that is *not*
   shared with the write gate, and it is the one that keeps the original reasoning working.
   Refusing is not enough: if `play` appeared in `--help`, in the home view or in the generated
   skill, an agent in a house that also runs a home-automation CLI would see two ways to start
   music and would sometimes choose the wrong one. So `cli.command_order(environ)` and
   `cli.modules(environ)` are gate-aware and the *dispatcher* reads them: with the gate closed,
   `plex-axi play` is an unknown command answered by `_OUT_OF_SCOPE` with exactly the message it
   has always been answered with, root help lists the commands it always did, the home view prints
   no `playback:` line, and the skill is byte-for-byte the one this repository commits.
   `tests/test_playback.py` sweeps every one of those surfaces for every string that would betray
   the capability — including the names of both environment variables, because an agent that saw
   the name of the gate would know there was a gate.

**The one place it is deliberately less secretive.** A gate variable that is *set* but is not
`true` refuses **by name**, exactly as the write gate does. Invisibility is owed to somebody who has
not opted in; somebody who has exported the variable has typed the capability's name, so there is
nothing left to hide from them, and answering "unknown command" would send them hunting for a
variable they had already set. The commands still do not appear in help — they are not enabled —
but the refusal explains itself. `playback.misconfigured` is that distinction.

**Why it is a separate variable from the write gate, and not a value of it.** Playing is not a
write: a write changes library or account state that persists and that somebody reads back later,
where playback changes what is coming out of a speaker until somebody presses stop. But the
stronger reason is that the two gates answer different questions. `PLEX_AXI_ALLOW_WRITES` answers
"may this tool change my library"; `PLEX_AXI_ALLOW_PLAYBACK` answers "does anything *else* in this
house own the speakers". An operator who wanted `rate` has said nothing about the second question,
and folding them together would mean opening one silently granted the other — which is the exact
coupling this gate exists to prevent. `tests/test_playback.py` asserts both directions.

### The access vocabulary grew a third level

`READ_ONLY` and `MUTATING` were the whole vocabulary while the tool could only read and write the
library. Starting playback is neither, and describing it as either would be a lie in one direction
or the other, so `playback.ACCESS` adds `dispatching`. Each gate module owns its own entry and
`argspec.ACCESS` merges them, rather than `writes.py` naming the playback variable — the two gates
stay independent in code as well as in prose. `clients` is declared `READ_ONLY`, because listing
targets genuinely cannot start anything and an access block that overstated it would stop being
read.

### The two routes, and what each costs

- **`local`** — `/clients`, which is the server's own list of what has announced itself to it. It
  lists a client only while that client's app is running and reachable on the same network as the
  server, which is why an empty answer is a snapshot rather than an inventory, and why it says so.
- **`sonos`** — `sonos.plex.tv`, which is how Plex reaches a Sonos speaker linked to a plex.tv
  account. Plex for Sonos is a current product, not a discontinued one, and for somebody with Sonos
  and no home-automation system it is the only thing that makes a `media_id` useful. Two things it
  needs and both are handled explicitly: a **plex.tv account token** in `PLEX_ACCOUNT_TOKEN`, which
  is a broader credential than `PLEX_TOKEN` and not interchangeable with it (a server token gets a
  flat 401 from plex.tv — measured, not assumed), registered as a secret the moment it is read; and
  a statement, in `--help` and here, that the command goes over Plex's cloud, so a house running
  Home Assistant will find HA's state stale. That is information for the operator, not a refusal.

**Why Sonos is implemented here rather than through `plexapi.sonos`, and what that preserves.**
`plexapi.sonos` reaches `PlexSonosClient` through `MyPlexAccount.sonos_speakers()`, and the account
object is the thing this package has never let into its process: it resolves speakers by name, it
dispatches playback, and it is one attribute access away from every module here. So `cloud.py` does
what `users.py` does for `--user` — asks the one documented endpoint with `requests`, parses the
answer with `xml.etree`. The consequence is the part of the old rule that survived **intact**:
`plexapi.sonos`, `PlexSonosClient`, `sonos_speakers`, `MyPlexAccount`, `switchUser` and their
relatives are still named nowhere in this package's code and still never enter the process, gate
open or closed. That is a weaker claim than "the Sonos route is unreachable" and it is the strongest
one that survives implementing the route; do not let the two be confused.

### Verification status: neither route has started music on a real device

A green suite is not evidence the tool works — that rule is stated at length under "Build, test,
lint" and it applies to this feature more than to anything else in the repository, because this is
the first feature whose whole point is an effect on a device the tests cannot see. **Both routes
ship unverified against real hardware, and that has to stay written down until somebody fixes it.**

What *was* checked against a live Plex Media Server, and is therefore settled:

- `/clients` answers, and answered `size="0"` throughout — the command handles the empty case, and
  `play` reports `NO_TARGETS` rather than failing obscurely.
- `POST /playQueues` succeeds for a track, an album and a playlist, and expands an album and a
  playlist to their tracks. The `uri` shape and `item.key`'s two forms were confirmed this way. An
  artist, the fourth playable kind, was never queued on the live server; `play` accepts one on the
  expectation that the server answers it like an album, which is the one playable kind whose queue
  the double alone has tested.
- `GET /library/metadata/<playlistRatingKey>` answers 200 with a `<Playlist>` element, which is
  what lets one lookup serve all four playable kinds.
- `/security/token` answers **403**, which is where the optional-delegation-token branch comes
  from.
- The gate-closed surfaces render exactly as they did before the feature existed.

What was **not** checked, and what it would take:

- **`local`** — no `playMedia` has ever reached a real client. No Plex client advertised to the
  server during development, over repeated checks across several hours, so there was no target to
  send one to. Everything up to the final request is confirmed; the final request is not. Open a
  Plex client on the server's network, run `plex-axi clients`, and play a track, an album, an
  artist and a playlist to it.
- **`sonos`** — no plex.tv account token was available; the credential to hand was a server token,
  and plex.tv answered it 401, which is the failure the route's own error message describes. The
  route is exercised end to end against the double, including the two-credential split, but the
  double's shapes for `sonos.plex.tv` are transcribed from `plexapi.sonos` rather than from a live
  capture — which is the softer half of the double-fidelity rule, not the strong half.

Neither of these is a reason to withhold the feature: it is off by default and invisible while it
is off, so an unverified route harms nobody who has not opted in. It *is* a reason to say so
plainly wherever the feature is described, and to add the result to `tests/test_live_audit.py`
rather than starting another file when somebody does run it.

### Sharp edges paid for by the live audit of this feature

- **`PlexServer.clients()` reaches plex.tv.** When a client fails to advertise a port it calls
  `myPlexAccount().devices()` to look one up — which would pull the account object, and with it the
  Sonos dispatch surface, into a process that has no other reason to hold it. `playback._local_targets`
  reads `/clients` and parses it here instead. The double carries a portless client so that this is
  a test rather than a comment.
- **`/security/token` answered `403` on a real server.** The client library's `PlexClient.playMedia`
  calls `createToken()` unconditionally and lets the failure propagate, so its play path fails
  outright on any server whose token is not a plex.tv account token — which is exactly what a
  server permitting unauthenticated access on the local network hands out. `playback._delegation_token`
  notes the refusal and plays without one, and the double refuses to mint one *by default* so that
  the path every test takes is the path a real installation takes.
- **`POST /playQueues` needs the `X-Plex-*` identity headers.** A bare `curl` with only
  `X-Plex-Token` gets `400 Bad Request` with an HTML body; the same request through the client
  library's session succeeds. Anything hand-testing a playback endpoint has to send the headers
  `plex.harden()` sets, or it will diagnose a working implementation as broken.
- **A play queue is created with one POST and only its `playQueueID` is read.** Not
  `createPlayQueue`: that builds a whole `PlayQueue` object, which indexes its own contents to find
  the selected item — so a ten-thousand-track playlist is parsed in full to hand back a number.
- **`item.key` differs by kind and both forms work.** A track or album is `/library/metadata/<n>`;
  a playlist fetched from that same namespace is `/playlists/<n>` (the client library strips the
  `/items` suffix). The `uri` is `server://<machineIdentifier>/com.plexapp.plugins.library<item.key>`
  either way, and Plex expands an album or a playlist to its tracks — verified live for track,
  album and playlist.
- **Plexamp and Plex for Android answer a successful playback command with `OK`, not XML.** The
  status code is read before the body is parsed, so a parse failure after a 200 is success. The
  double models exactly that for the client that plays, which means the ordinary test path is the
  awkward one rather than a tidier one that does not exist.
- **A `/clients` entry is a `<Server>` element and carries the player's name under `name`**, not
  `title` — the mirror image of the `<Player>`/`title` trap under "Sharp edges". It also carries
  `host`, `address` and `port`, and a Sonos resource carries `lanIP`. **None of them is printed**:
  nothing needs them to address a target, and this repository is public. The double carries them so
  that withholding them is a test rather than an assumption.

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

- **The canonical decimal range is wider than Python's float repr.** Spec section 2 makes decimal
  form a MUST for `0` and for `1e-6 <= |n| < 1e21`; `repr` leaves decimal form outside roughly
  `[1e-4, 1e16)`, so `json.dumps` alone violates that MUST in the band at each end. `_number`
  formats through `Decimal(repr(value))` inside the range and defers to `json.dumps` outside it,
  where an exponent is permitted. `Decimal(value)` would be wrong: it expands the exact binary
  value into a fifty-digit fraction instead of the shortest round-tripping digits. No typed command
  reaches either band today — `filters.stars` yields half-star steps and `similar` rounds a sonic
  distance to four places — so the guarantee is the encoder's, which is what the README's
  strictness claim is about, and not any one row shape's.
- **Tabular form is not available in list-item position.** A tabular header on a hyphen line is a
  keyless fields-bearing header, which section 6 allows only at the document root, so section 9.4
  requires list form however uniform the items are. `array()` carries `allow_tabular` and
  `list_item()` passes `False`; the restriction is the position, not the depth, so a *key* inside a
  list-item object still reaches tabular form. Nothing here nests an array directly inside an array
  today — `api` renders XML attributes, which are strings under a key — but the document the
  encoder emitted before was one a strict decoder must reject, and the encoder is the boundary
  every command prints through.
- **There are two `search()` methods and only one of them works.** `Library.search` hits
  `/library/all`, validates nothing, and drops unknown keyword arguments straight into the query
  string; its own docstring says *"This is untested but seems to work. Use library section search
  when you can."* Everything in this tool goes through `MusicSection.searchTracks/Albums/Artists`.
  Never reach for `server.library.search`.
- **A numeric filter has three different meanings depending on how it is reached.**
  `userRating__gte=8` through `Library.search` is emitted verbatim into the URL and applied nowhere.
  Through `LibrarySection.search` it becomes a *client-side* post-filter applied after `limit` has
  already sliced the results, so it filters within the slice rather than narrowing the query. Only
  `filters={"userRating>>": 7}` is a real, server-validated Plex predicate.
  `axi_toolkit.plex.filters.assert_server_side`, called from `music._execute`, fails loudly if
  anything ever lands in the client-side bucket again.
- **Plex's operator suffixes are not Python's, and one of the two you would reach for does not
  exist.** `>` normalises to `>=` ("is greater than or equals") and `>>` to `>>=` ("is greater
  than") — but **no real music section advertises `>=` for any type**, so the natural spelling of
  "at least" validates against nothing and is refused. The library checks the operator against the
  field's advertised set and raises listing the valid ones; `music._filter_error` turns that into a
  usable message rather than letting it escape, and it now says outright that reaching it is a bug
  in this tool, because every comparison here is built from a flag rather than typed by a caller.
  Its advice used to name `--rated-min` as "the supported at-least comparison" — recommending the
  command that had just failed.
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
- **A real `<Player>` has no `title`.** It carries `address`, `device`, `machineIdentifier`,
  `platform`, `product`, `profile`, `state` and `version` — three different names for the thing
  playing and not one of them `title`. `sessions._device` reads `device`, then `product`, then
  `platform`, most specific first. Reading `title` alone left the one column that says *where the
  music is playing* empty on every real session, and full on every test, because the double had
  invented the attribute.
- **`playlist.leafCount` is what the server declares, not what the playlist holds.** For a smart
  playlist it is a cached figure and drifts — 0 declared against 81 actual on a real server — and it
  is off by one even on a static list. `playlist list` has nothing else to print, so it prints the
  declared count and names it as such; `playlist show` has the real contents and reports the
  disagreement. The two commands must never contradict each other in silence.
- **A boolean key in `filters` may not have a sibling.** `_validateAdvancedSearch` raises
  *"Multiple keys in the same dictionary with and/or is not allowed"* the moment `{'or': [...]}`
  shares a dictionary with anything else, so a parenthesised OR has to be composed as
  `{'and': [{...simple...}, {'or': [...]}]}` — which is what `pick._compose` does. This is also why
  `group=title` is no longer passed inside `filters`: it moved to `run_search`'s `**kwargs`, where
  `_buildSearchKey` validates it against the same field table and emits the same `group=title`
  parameter *outside* any group. A `group` inside the parentheses would be a SQL GROUP BY scoped to
  half the predicate, which is not what anyone means.
- **A never-played track has no `lastViewedAt` at all, and Plex matches the null anyway.** The
  column is null rather than zero. What a real server does with that in a "before" comparison is the
  half that was guessed and got it backwards: `track.lastViewedAt<<=-30d` **includes** never-played
  tracks (9 993 of 10 000 on the library this was measured against), where SQL would say neither
  true nor false. It is not visible from the request and it is not necessarily the same on every
  build, so `pick --not-played-since` asks for the never-played half explicitly and server-side —
  ORed with **`track.viewCount=0`**, which is a field every scanned music section advertises.
  It used to OR with `track.unplayed`, **which no real music section offers**: the field was in the
  double's table and nowhere else, so the predicate degraded on every real server while the good
  path was the one every test took. Where `viewCount` is genuinely absent the date runs alone, and
  the `unapplied` reason is settled by looking at the rows rather than asserting an answer — the
  same discipline as `music._verify_grouping`. The previous wording ("tracks it has never played are
  not included") was false on every real server: the command produced the right answer and explained
  it wrongly, which is worse, because a caller who believes it adds a compensating query for tracks
  already in the list.
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
- **Adding a column to `ROW_FIELDS` changes what `recent` prints by default.** `recent.run` appends
  `added` to the default row of *any* libtype that advertises it, so the branch was already written
  for a column a track did not have. Giving `track_row` an `added` column therefore did two things
  at once: `--fields key,added` stopped being an unknown-field usage error on a track, and the
  recently-added list stopped omitting the one thing it is sorted by. Both are wanted; a column
  added later without wanting the second would need that branch looked at first.
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
- **There is no "greater than or equals" for an integer, so "at least N" is "greater than N−1".**
  A real music section advertises exactly `=`, `!=`, `>>=` and `<<=` for the integer type, and both
  inequalities are *strict*: `>>=` is "is greater than", `<<=` is "is less than". The `<=` and `>=`
  under the *string* type are "begins with" and "ends with" — not numeric comparisons, which is how
  they came to look like the missing pair. `--rated-min N` therefore builds
  `{libtype}.userRating>>` with `ceil(2N) − 1`, and prints the operator back as `>` because that is
  what the predicate is. (`ceil` rather than a plain subtraction so a value between the half-stars
  Plex can store rounds the way the caller meant, and so the URL never carries a fraction.) The
  server *does* accept `userRating>=8` on the wire and returns the right answer, but it does not
  advertise it and plexapi validates against what is advertised; do not build on that.
- **`--rated-min 0` applies no filter, and says so.** Zero is the bottom of the scale, so it
  constrains nothing. The arithmetic above would make it `userRating > -1`, which quietly means
  "rated at all" and withholds every unrated item — the overwhelming majority of an ordinary
  library — behind a flag that reads as "no minimum". "Rated at all" already has an exact spelling,
  `--rated-min 0.5` (`userRating > 0`), so the vacuous reading is the one kept for the vacuous
  value. `search` alone with it still exits 2 as `NO_FILTERS`, with the reason its flag did not
  count.
- **The exact count comes from a second request with an empty body.**
  `X-Plex-Container-Size: 0` returns the container metadata and no rows. The server-side `limit`
  parameter is deliberately *not* used for the page, because it also caps `totalSize` and would turn
  the exact total into a lie; `maxresults` bounds the fetch instead.
- **Exit codes follow one rule.** A static invocation problem — unknown flag, unknown command, a
  rating key that is not a number, a write method on `api` — exits 2. An outcome of a lookup against
  live state — nothing at that rating key, no music library, an ambiguous section — exits 1. A zero
  result from a well-formed search exits **0**: an empty answer is an answer.

### The six `plex://` forms

Six strings are in circulation and they all look like one identifier:

| Form | Produced by | Safe to print as a media id? |
|---|---|---|
| 1. `plex://<machineIdentifier>/<ratingKey>` | a media browser | **yes** — the canonical form, and the only one this tool emits |
| 2. `plex://<ratingKey>` | older integrations | yes, but consumers call it the legacy branch |
| 3. `plex://{<json>}` | play-queue dispatch | yes, matched before URL parsing |
| 4. `plex://track/<ratingKey>` | a tool's internal id | **no** — parses as a server named `track` |
| 5. `plex://track/<24-hex>` | the client library's own `guid` | **no** — raises `ValueError` in a consumer |
| 6. `local://<ratingKey>` | Plex, for an item it never matched | **no** — a guid, and not a durable one |

Forms 4 and 5 are the trap: the same shape in two namespaces, one of which is a legitimate Plex
identifier handed out under the attribute name `guid`. `media_content_id`, in
`axi_toolkit.plex.ids`, builds only the first form and refuses anything that is not a decimal
rating key; `tests/test_ids.py` sweeps every command and asserts none of them ever emits form 4
or 5.

**Form 6 is the one that makes the durability note conditional.** An item Plex never matched to its
catalogue carries `local://<ratingKey>` — the rating key with a scheme in front of it, so it moves
exactly when the rating key moves. It is not rare: roughly one track in seven on a real library. The
note printed beside it used to say "guid is the identifier that survives, so keep them together",
which is false for exactly those items and is printed at the moment somebody is about to write one
into a configuration file. `ids.stability_note(guid)` reads the scheme and says which situation
the caller is in; the double carries a `local://` row so the branch has a fixture rather than a
comment.

**Labels are vendor-neutral, and the output stops at the identifier.** The field is `media_id`, not
the name of any particular consumer: this ships to anyone with a Plex library, and naming one in the
default output would be wrong for everyone else. There is deliberately no "play this with …" line
and no configuration for one. A template could only ever come from the operator, so printing it back
tells the caller nothing they did not already know — it was ceremony. The `item:` block is exactly
four fields — `media_id`, `rating_key`, `guid`, `note` — and `tests/test_ids.py` asserts that list
verbatim. Only the *text* of the fourth varies. The README explains in prose what consumes a
`media_id`; that belongs in documentation, not in output. `play` is the one output that goes past
this block — gated, and it names no consumer either: it addresses a target the server itself listed.

**`media_id` is in every default row, and `guid` is not.** A list view that printed `key` alone
under-delivered on the tool's own premise — it ends at a labelled identifier — and cost the caller
one detail request per row to finish the job. So `search`, `pick`, `recent`, `similar`,
`playlist show` and `sessions` all carry `media_id` by default, and `music.rows_for` takes the
machine identifier as a **required** argument so a new surface cannot forget it. The `guid` stays in
the detail views: it is the identifier a human writes down rather than the one a consumer takes, and
form 6 means it is not always even that — doubling every row's width for it is a poor trade.

**A playlist has a `media_id` too, and this was checked rather than assumed.** `playlist list` and
`playlist show` both print one for the playlist *itself*, beside the `key`, because "play this whole
playlist" is the case where the container is obviously what is wanted — and without it the caller
had to assemble `plex://<machineIdentifier>/<key>` by hand, which is precisely the hand-assembly the
six-forms table exists to prevent.

The claim needed evidence, since form 1 is only correct where the key resolves. Two independent
checks, both against real things:

- **On a real server, a playlist's rating key is in the `/library/metadata` namespace.**
  `GET /library/metadata/<playlistRatingKey>` answers `200` with a `<Playlist>` element, and
  `PlexServer.fetchItem(<playlistRatingKey>)` returns a `Playlist`. That is the same namespace and
  the same call a track's key takes.
- **A real consumer resolves the form by exactly that call.** Home Assistant's Plex integration
  parses `plex://<machineIdentifier>/<ratingKey>` into `plex_key`, calls `fetch_item(key)` →
  `fetchItem`, and does not type-check or reject the result — a `Playlist` comes back and is used.

So the id is form 1, correctly built, resolving to the playlist. Note that the same consumer also
offers a *playlist-specific* route keyed on the title (form 3, a JSON payload). **Do not emit that**:
it is one consumer's schema, and naming one in default output is the vendor-specific coupling this
tool refuses everywhere else. A playlist's own `guid` — `com.plexapp.agents.none://<uuid>` — is not
a media id either, and is not printed.

**Advice has to be re-read whenever the output it points away from changes.** Six list views said
"Run `plex-axi track <key>` for one item's detail and its media id". That was true while a row
carried only `key`, and became an advertised round trip for a value already on the screen the moment
rows carried `media_id` — the same defect as advice naming a value the tool never prints, arriving
by a different route. `tests/test_live_audit.py` sweeps every row-bearing surface asserting no `Run`
line mentions a media id at all. When a row gains a field, grep the help lines for it.

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
| `clients` | read `protocolCapabilities` and say which targets can actually play, ask the Sonos route only when its credential exists, and report which routes it consulted — and print no network address from either |
| `play` | create the play queue at all (`api` is GET-only, so it cannot), resolve a target explicitly across two routes, and step over a server that will not mint a delegation token |

**Demotion.** If a typed command's body reduces to flag-mapping plus a request, delete it — the
measure is the diff, not the intention.

**`--count` became `--limit`, deliberately.** The requirements table spells `pick`'s size flag
`--count`. Every other list command here takes `--limit`, and `RENAMED` already maps `--count` to
`--limit` as a wrong guess — so shipping both spellings would have made that correction table lie
and given an agent two names for one idea. The flag is `--limit`; the deviation is here rather than
silent.

**`queue create` (W11) is still out.** A playqueue id is not universally accepted — Sonos rejects
Plex playqueues outright — so shipping one without naming which platforms take it only moves the
discovery to a 500. `play` creates a queue and hands the *client* its id in the same command, which
is a different thing from publishing one as a result a caller has to find a use for.

**What is deliberately absent, and will stay absent.** No transport control of any kind — no pause,
stop, resume, seek, next, previous, volume or queue management — no video, no server
administration, no *metadata* editing (a user rating is per-account state, not library metadata,
which is why `rate` is in and `edit` is not), no second Plex client library, and no semantic name
resolution by regex or substring. `play` starts one item on one explicitly resolved target and
that is the whole of it: the thing that was missing from a tool ending at an identifier was a way
to *use* the identifier, and the rest was never missing. A control surface is where two systems
start believing they own the same queue, which is why the line is drawn after the start button
rather than before
it. `tests/test_no_dispatch.py` enforces it, on the playback commands as well as on every other
one; read its module docstring before touching it.

## The session integration, and the one thing it could not inherit

AXI §7 makes a **SessionStart hook the primary discovery path** and the installable skill the
secondary one. This tool shipped only the skill for three releases, which is the standard's own
primary integration missing from a tool submitted to the standard's own catalog.

`plex-axi setup hooks` installs it, and everything about the installer is the sibling AXI CLI's
contract, deliberately: the same four targets (Claude Code, Codex, Codex's `[features] hooks`
flag, and a managed OpenCode plugin), the same atomic writes into the user's own global settings,
the same PATH-verified portable command, the same idempotence and path repair, and the same
refusal to overwrite an OpenCode plugin it did not write. Do not redesign any of that; the two
tools are meant to install the same way.

**What could not be inherited is what the hook runs, and this is the load-bearing paragraph.** The
sibling's hook runs its bare executable, whose no-argument view is live state. Here the
no-argument view is `commands/home.py`, and running it from a hook fails on three separate counts,
each of which alone would be fatal:

- **It needs credentials.** With `PLEX_URL` unset it reports `NOT_CONFIGURED` and exits 1, so on
  every machine that has the package and no server the hook would open every session with a
  failure.
- **It touches the network.** It resolves the section, asks three item counts, the mood
  vocabulary, the recently-added albums and the sessions. A hook runs before anybody has decided
  to use the tool; it may not spend that.
- **It prints a host address.** `url:` is the second line. Hook output lands in an agent's context
  and is routinely logged and transcribed, which makes it a *wider* surface than a terminal, not a
  narrower one — and this repository's whole discipline is that a server's address is a thing you
  do not write down.

So the hook runs **`plex-axi context`** (`commands/context.py`), which reads the environment and
the command table and nothing else. `tests/test_hooks.py` asserts that rather than describing it:
the document reaches the server **zero times** — on `server.requests`, not on an exit code, for the
same reason `tests/test_writes.py` does — exits 0 with no environment at all, and prints neither
the base URL nor the token on either stream, including the one URL shape where the address is
itself a secret. The test that joins the two halves is the one asserting the *installed* command
is `<executable> context` and not the bare executable.

**The document is gate-aware, and it is a surface the playback sweep now reads.** Its commands come
from `cli.command_order(environ)` and its `media_id:` line is chosen rather than fixed, because
"this tool ends at a media id and leaves dispatch to whatever owns the speakers" is false with the
playback gate open. `tests/test_playback.py`'s `_surfaces` carries `context` alongside root help,
the home view, every `--help` and the skill — it is the widest of them, being the one that arrives
unasked.

**Its size is asserted, not intended.** It loads on *every* session, so `tests/test_hooks.py` pins
a byte ceiling. A line added without weighing the cost fails there rather than being paid forever
by everybody who installed the hook.

**Three smaller decisions, each a deliberate divergence from the sibling.**

- **`setup` carries `hooks` and not `skill`.** There, `setup skill` is the skill's only spelling.
  Here `plex-axi skill` already exists, is what CI runs as `--check`, and is named in the README
  and in the generated skill; adding `setup skill` would be two names for one idea — the thing
  this project refused when it declined to ship `--count` beside `--limit`, and the ambiguity the
  shared-package extraction exists to end. The *choice* between the two paths is explained in
  `setup --help`, which is what AXI §7 asks for. `commands/skill.py` and `skill.py` were not
  touched by the change that added hooks, and a test asserts `setup` has no `skill` subcommand.
- **`setup hooks` declares `READ_ONLY`.** It writes files, but the access vocabulary is about the
  *server*, and `MUTATING` is defined as needing `PLEX_AXI_ALLOW_WRITES` and previewing without
  `--write` — none of which is true here, so declaring it would put a false sentence in `--help`.
  `plex-axi skill` set the precedent: it writes a file too, declares read-only, and names the file
  in a note. `setup hooks` names all four. Do not route it through `writes.require`; coupling
  "may I install a hook on this machine" to "may I change your library" is exactly the coupling
  the two gates exist to keep apart.
- **The hook command is shell-quoted.** The sibling's is a single token and needs no quoting. This
  one carries an argument after the path, so an unquoted space would split the executable in two.

**Neither `setup` nor `context` is subject to the promotion rule below.** That rule asks what a
typed command does that `api` cannot, and `api` is a GET proxy onto a Plex server. These two do not
address the server at all — one configures this machine, the other describes the installation — so
the question does not apply to them rather than being answered generously.

**Verification status: the OpenCode plugin was run, the two JSON hooks were not.** The generated
plugin was executed under Node against a real build of this package and did push the context
document into `output.system`, so that route is confirmed end to end. The Claude Code and Codex
entries were verified as *written* — correct file, correct shape, correct command — and the command
they record was run directly, but neither agent has been restarted against them. That is the same
distinction `tests/test_live_audit.py` draws elsewhere and it belongs in the same place when
somebody closes it.

## Build, test, lint

```sh
pip install -e ".[dev]"
pytest                                   # ~900 tests, a few seconds
ruff check . && ruff format --check .
plex-axi skill --check                   # SKILL.md is generated, never hand-edited
scripts/leakcheck.py                     # run this AFTER formatting
```

**Do not edit a vendored conformance fixture.** If one fails, the encoder is wrong until proven
otherwise; the checksum test will catch the edit anyway. Refreshing them from upstream is its own
commit, separate from any encoder change made to satisfy it, and `PROVENANCE.md` carries the recipe.

**Six cases that used to be in `tests/test_ids.py` are gone on purpose, and are not lost.** They
called `media_content_id` and `validate_rating_key` directly, and both live in
`axi_toolkit.plex.ids` now, stated in its own suite along with direct coverage of `media_id_for`,
`handoff` and `stability_note` — which this repository only ever reached through a command. Two
copies of one test is the divergence the shared package exists to end. What replaced them is
stronger and is *this* tool's to keep: `tests/test_recovery.py` pins the exact bytes of every
refusal those two modules raise, because the tool's name now arrives at a renderer rather than
being written into the sentence, and that is the one thing the move could have broken silently.

**A green suite is not evidence the tool works.** It was green for the whole of 0.2.0, and 0.2.0's
headline filter did not work against any real Plex server. The suite proves the tool behaves
correctly *against the double*; whether the double behaves like Plex is a separate question and the
tests cannot ask it. So a change that touches what the server answers — a filter, an operator, a
field, an element attribute — is not finished until it has been run against a real server, with the
commands a user would type. Read-only is enough for almost all of it, and the credentials belong in
the environment for the length of one shell session and nowhere else. `tests/test_live_audit.py`
carries one regression per bug the first such audit found; add to it rather than starting another
file, so the list of "things a real server does that we got wrong" stays in one place.

**A hand-written sweep list is only as complete as whoever last remembered it, so the list is
checked against a discovered set.** `tests/test_live_audit.py` sweeps `ROW_BEARING_SURFACES` — every
command that prints rows — asserting each carries a `media_id`. Nothing said that list covered every
module that builds rows, so a new row-building noun would have joined the codebase untested *and
silent about it*, which from the outside reads exactly like coverage. `_row_building_modules()` now
walks each command module's parse tree for a `rows_for` call or a `*_row` definition and the sweep
must contain everything it finds. This is `CASE_COUNT` in `tests/test_toon_conformance.py` applied
one layer up: the count of things covered is asserted rather than assumed. The coverage is bounded
and the test's docstring says how — a module that inlines its rows in a comprehension without naming
a builder is not found, which is what `home._recent` does and why `home` is not swept.

**Tests never need a live server or a live token, and must not start to.** They run the real client
library against a Plex double in `tests/conftest.py` that speaks HTTP-shaped XML over a fake
`requests` session. That is the point: the claims worth testing — that a filter is applied
server-side, that the URL carries the operator Plex actually defines, that a count is exact — are
claims about the request the client library builds, and a double that only agreed with the client
could not test any of them.

**The double must answer like Plex, not like the client.** Three rules, none optional:

- **Model the refusals.** `KNOWN_PARAMS` and `KNOWN_FIELDS` are an explicit allow-list; anything else
  is a `400`. A filter that reached the URL in a spelling Plex does not define — which a permissive
  server would ignore, returning a plausible unfiltered answer — is a refusal here. The tables are
  deliberately *not* imported from `plex_axi`: a second opinion that is a copy of the first is not
  one. A new parameter is refused until it is added to the table, and adding it is how the parameter
  gets confirmed rather than assumed.
- **Apply the filters for real.** A request for tracks rated four stars and up returns only those
  tracks, from the double's own predicate code. A double that returned the same rows whatever was
  asked would let a filter that does nothing pass every test.
- **The double-fidelity rule**, below. It is the third because it is the one that was learned last,
  and the most expensive.

### The double-fidelity rule: transcribe, never author

**Any table describing what the *server* answers must be transcribed from a real capture. Everything
the tool *asks* may be invented; nothing the server *answers* may be.**

That covers operator tables, advertised field and filter lists, sort keys, the attributes on an XML
element, and the *shape* a value arrives in. It does not cover library content, which is invented on
purpose and must stay that way — this repository is public. Transcribe shapes, never content.

The rule is not a principle somebody liked. The first release was built entirely against this double
and shipped fourteen bugs, and the two worst were single wrong lines in tables nobody had checked
against a server:

- `_INT_OPS` carried `<=` ("is less than or equals") and `>=` ("is greater than or equals").
  **Real Plex defines neither, for any type.** A music section advertises exactly `=`, `!=`, `>>=`
  and `<<=` for an integer, and both inequalities are strict. `--rated-min` was built on the invented
  one, so the tool's headline numeric filter failed at *every value on every real server* while
  passing every test here. The other four operator tables were right, which is what makes the case
  worth remembering: one guessed line among five correct ones is invisible.
- `<Player>` carried a `title` attribute. A real one carries `address`, `device`, `machineIdentifier`,
  `platform`, `product`, `profile`, `state` and `version`, and **no `title`** — so `sessions` read an
  attribute that is never there and the column naming where the music is playing was empty on every
  real session and full on every test.

Two more were the same rule in a softer form — the double modelled the *tidy* value where real Plex
is messy. A never-played `lastViewedAt` was modelled as not matching a "before" comparison, where a
real server matches it; a playlist's declared `leafCount` was kept in agreement with its contents,
where a real one drifts (0 declared against 81 actual, and off by one even on a static playlist).
Both are now modelled as they are, not as they ought to be.

**How to obey it.** Capture the metadata from a real server and copy the values across:

```sh
curl -s -H "X-Plex-Token: $PLEX_TOKEN" -H 'X-Plex-Container-Size: 0' \
  "$PLEX_URL/library/sections/<key>/all?type=10&includeMeta=1"
```

The `<Meta>` element carries every `<Type>`, `<Filter>`, `<Sort>`, `<Field>` and `<FieldType>` the
section offers; `section.fieldTypes()` and `section.listFields(<libtype>)` read the same thing
through the client library, which is also what plexapi validates against. Any element the tool reads
(`<Player>`, `<Part>`, `<Playlist>`) should have its attribute list read off a real response rather
than recalled. A committed redacted capture would be the strongest form of this and is worth doing
if the tables grow; either way the standard is the same — if you cannot point at where a value came
from, it is authored, and it is a bug waiting for a user to find.

Note also that **real Plex is more permissive than this double, not less**, and deliberately so
here: it silently ignores an unknown *filter field* and returns the unfiltered set, so the production
failure mode is a plausible whole-library answer rather than an error. The double's `400` is what
stops a misspelled field ever shipping, and `music.advertised_fields` is what stops one being sent —
treat that function as load-bearing rather than defensive. (An unknown *operator* is refused on the
wire, with a 500; the permissiveness is field-name-shaped, not universal.)

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
it**, still, now that there are two runtime dependencies rather than one: `axi-toolkit` publishes
`requires-python >= 3.9`, so it has no say in the floor today. That is a thing to re-read whenever
either pin moves, not a thing to assume. plexapi 4.18.0 raised its own `requires-python` to
`>=3.10`, which raised this project's floor with it and said nothing: `requires-python = ">=3.9"`
stayed in `pyproject.toml`, the whole test suite passed on 3.10 through 3.12, and the only thing
that ever noticed was `pip install` on 3.9 failing to resolve the dependency at all. Published
metadata is the one claim tests cannot check, because the interpreter that would have failed is the
one they were never run on. **Read plexapi's
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

## The README, and the metadata PyPI renders

The README is the landing page for three audiences at once — PyPI, GitHub, and the public AXI
catalog at <https://axi.md> — and it has to serve **two readers**, which is the thing that erodes
silently:

- **A stranger, cold, who has never heard of AXI or TOON.** Thirty seconds to learn what this is,
  whether they want it, and how to start. The first release failed this: it said output was "TOON on
  stdout" and linked neither <https://toonformat.dev> nor <https://axi.md>, so a reader was left
  believing the tool emitted an unnamed proprietary format. Both acronyms are now expanded *and*
  linked in the opening block. Do not un-link them, and do not compress the explanation back to the
  acronym.
- **An agent that has the tool and must use it correctly first time.** This half was already strong
  and must not be traded away to serve the first. The rules of thumb, the `media_id` section and the
  exit-code semantics are the agent-facing content; edit them for accuracy, never for brevity.

**The never-plays claim belongs in the opening block, in its qualified form.** That out of the box
the tool plays nothing and has no play command at all — until `PLEX_AXI_ALLOW_PLAYBACK` switches
one on — is the single most distinctive fact about the tool, it is the one thing a reader is most
likely to assume wrongly, and it was originally four paragraphs down. Anything that pushes it below
the fold is a regression, not a tidy-up. The qualification is deliberate, not a hedge: playback
ships behind the gate, so the old absolute wording ("it never plays anything", full stop) is false
now, and an edit that restores it is undoing the reversal rather than tidying.

**The "Output format" section is a deliberate port from the sibling AXI CLI**, so that two tools
built to the same standard describe the same contract in the same words. It carries the TOON link,
the sample block, the `--human`/`--json` pair, the stdout-errors rule, the exit codes and the
`help[N]:` deviation. Keep it in step with the sibling rather than rewriting it locally, and state
the token saving the way the sibling does — *roughly 40% cheaper in tokens than the equivalent
JSON*. "Roughly 40% of the tokens" is a different and much stronger claim; it is easy to write by
accident.

**The sample TOON block was generated, not typed.** Feed the document to `toon.encode` and paste
what comes back, so a reader who copies the shape is copying the real one.

**What an installation costs belongs under `Install`, not under `Design notes`.** The two runtime
dependencies were described only in a design note for a while, which is the wrong end of the page:
a design note is read after somebody has decided to install the tool, and "what lands in my
environment" is one of the questions that decides it. `Install` names both — `PlexAPI` for the Plex
model layer, `axi-toolkit` for the shared id and filter language — and says that `axi-toolkit`
declares no runtime dependency of its own, so it costs exactly one name and nothing transitive. The
design note keeps the *why* and points at `Install` for the price, so the two cannot drift into
different numbers. Deliberately no Python version in that prose: the floor is held to one number by
`tests/test_python_floor.py` across `pyproject.toml`, `ci.yml` and the classifiers, and a fourth
copy in the README would be the one nothing checks. The badge reports it from PyPI instead.

**`[project.urls]` is what PyPI renders as the sidebar links** on the project page, and `Homepage`
and `Source` alone left a cold reader with no route to the issue tracker or the changelog.
`Documentation`, `Changelog` and `Issues` are there now. **The toml is not the check** — the wheel's
`METADATA` is:

```sh
python -m build --wheel --outdir dist . && unzip -p dist/*.whl '*/METADATA' | head -30
```

`twine check` validates the rendered long description, and `trove-classifiers` is the authority on
whether a classifier string exists at all — a misspelled one is not an error, it is simply ignored,
which is the failure mode worth a thirty-second check.

**Badges are for the human half only.** PyPI version, supported Pythons, licence. An agent reads
none of them; a drive-by GitHub reader wants exactly those three facts before scrolling.

## Continuous integration

Three workflows, split by where the work is cheap:

- **`.github/workflows/ci.yml`** — the heavy matrix (leak scan, lint, `pytest` on 3.10 through 3.12,
  the generated-skill check) on the maintainer's self-hosted runner. Triggers: push to `main`, a
  nightly `schedule`, and `workflow_dispatch`. Never pull requests.
- **`.github/workflows/hygiene.yml`** — the leak scan and the pull-request-body check, on
  `ubuntu-latest`, on `pull_request` (including `edited`). It scans the tracked tree *and* the pull
  request's own title and body. Exactly one GitHub-hosted job per PR, and it takes seconds; the two
  steps that read the pull request are the one deliberate exception to keeping this workflow thin,
  and the reasons for them are under "There are three surfaces" above and "Releasing" below.
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

**A commit release-please parses perfectly can still cut no release at all, and that is not a
failure — it is the changelog sections doing their job.** Only `feat:` and `fix:` (and a breaking
change) move the version; `refactor:`, `chore:`, `docs:`, `test:` and `ci:` are recorded and
nothing more. That is right almost always and wrong in one shape: a change with no behaviour to
describe that nevertheless alters **what a user installs**. Adopting `axi-toolkit` was exactly
that — a `refactor:` on `main`, correctly typed, while PyPI went on serving a version that still
carried its own copy of the extracted code, so the duplication the extraction removed was the only
thing users had.

**The lever is a `Release-As: <version>` footer**, on its own line at the end of the commit
message, which makes release-please propose that version whatever the types in the range say. Two
things about it:

- **It has to survive the squash.** release-please reads the merged commit's message, not the
  branch's, so a footer typed on a local commit and dropped from the squash box does nothing and
  says nothing — the same silent-no-op class as an unparseable message, reached from the other
  side. Whoever merges has to carry it across, so say so in the pull request.
- **Do not hand-edit a version string to compensate.** `pyproject.toml`,
  `src/plex_axi/__init__.py`, `.release-please-manifest.json` and `CHANGELOG.md` are all
  release-please's, and the paragraph above is what happens when one of them is set by hand.

**A commit message release-please cannot parse is dropped silently, and the run stays green.**
This cost one release: `41bcb73` merged to `main`, the release workflow exited **success** with
`commit could not be parsed` at debug level and `Considering: 0 commits`, and the fix sat
unpublished while PyPI stayed on 0.2.2. `parseConventionalCommits` wraps every parse in
`try { … } catch { logger.debug(…) }`, so an unreadable message costs a commit and reports nothing.

**The rule, established against the parser rather than guessed at.** release-please 17.3.0 parses
with `@conventional-commits/parser` (`^0.4.1`), whose grammar offers **every physical body line** to
`<footer> ::= <token> <separator> <whitespace>* <value>`. `<token>` is `<type> ["(" <scope> ")"]`,
and `<type>` consumes from the line start until whitespace, a newline, `!`, `:`, `(` or `)`. If it
stops on `(` the parser is committed to a scope: it reads to the next `(`, `)` or newline, and if
that is not `)` it **throws** (`lib/parser.js:177`) — the only `throw` reachable from the body, and
the only production that raises rather than returning an `Error` its caller can back out of. So

- `` `Decimal(repr(value))` inside … `` at a line start — **refused**;
- `… through `Decimal(repr(value))` inside … ` — **fine**, one word further along.

It is not parentheses, not backticks, not the `-` used as a dash, and not position alone: it is the
interaction. The sibling project's own copy of that paragraph parsed for exactly this reason, which
is luck, not design. `scripts/commitcheck.py --rules` prints the rule with its citation, and
`--demo` proves the checker still tells the shapes apart.

**Two engines, and the reason there are two.** `vendor/conventional-commits-parser/` is a
byte-for-byte copy of the four dependency-free upstream modules (ISC; provenance, checksums,
refresh recipe and the reason `utils.js` is excluded are in its `PROVENANCE.md`), so `--engine node`
runs *the* parser with no `npm install` and no network. `--engine python` is a transcription of the
same grammar, so a machine without `node` gets a verdict rather than a skip. `--engine auto` — the
default, and what the hooks use — prefers `node`. `tests/test_commit_message.py` runs the whole
corpus through both and compares the verdict, line, column and token; the transcription is only
worth anything because that comparison passes, and CI installs `node` so it is never skipped there.
It has already earned its keep: it caught the node path's error regex failing to match when the
offending token was a newline, which would have silently downgraded a real rejection.

**Do not solve this by banning rich commit bodies.** The bodies carry the reasoning that makes this
history worth reading, and a guard that made prose the problem would be answered by writing less of
it. `DEMO_ACCEPTED` in `commitcheck.py` pins the shapes that must keep working — nested parentheses
mid-line, markdown bullets, footers, breaking-change notes, a full rich body — and
`test_the_rule_is_the_interaction_and_not_any_one_ingredient` asserts each ingredient alone is fine.
A change that makes one of those fail is a regression in the guard, not a discovery about the prose.

**Three layers, and one of them is the real fix.**

- `.githooks/commit-msg` runs `commitcheck.py` after `leakcheck.py`. This is the one that matters:
  it rejects the message before it can reach `main`, and it names the line, the column and what to
  change.
- `.github/workflows/release.yml` has a `commit-audit` job that re-checks every commit since the
  last release tag. It deliberately does **not** `needs:` the release-please job — it has to fail on
  its own account, including on a run where release-please itself errored. It exists because a hook
  cannot see a message typed into GitHub's squash-merge box.
- `.github/workflows/ci.yml` runs the same audit nightly, so an allowance that has outlived its
  cause surfaces without waiting for a merge, and installs `node` in the `test` job so the
  agreement between the engines is enforced rather than skipped. Nightly matters more than it looks
  now that the audit reads pull request bodies: a body edited a week after the merge changes what
  the next release contains, with nothing else having run in between.
- `.github/workflows/hygiene.yml` gained a step, which is the one exception to "keep this workflow
  to the one cheap job". It is not coverage for its own sake: it checks the pull request body, which
  exists *only* on a pull request, never passes under a hook, and can replace the merged commit
  message outright. Its trigger list carries `edited` for the same reason. Still one job, still
  seconds. The leak scan of the same two fields rides the same trigger, for the same reason from the
  other direction — see "There are three surfaces" above.

The claim that used to sit here — "`hygiene.yml` was deliberately left alone; the release audit
already covers what a PR-time check would" — was false, and cost the second release. The release
audit runs *after* the merge. Nothing looked at the body before it.

**The audit's verdict is only as wide as its reach, and it has to say when it is narrower.**
`resolve_bodies` has three modes and no fourth: `require` (the workflows) fails without a token
rather than checking a different artefact and calling it green, `auto` (a developer's checkout)
consults GitHub when it can and prints `NOT consulted` in the output when it cannot, and `skip` is
git only, on purpose, which is what the unit tests pass so they never reach the network. There is
deliberately no silent fallback: silent fallback to the wrong string is precisely the state the
first guard shipped in. A per-commit miss is not an
outage either: the commits endpoint answers 422 for a SHA GitHub does not have, which is the
ordinary state of a local branch, so `resolve_bodies` reaches the repository once before the loop
and only then reads a miss as "no pull request" — and names the commits it applied to. Reading a 404
as "no pull request" without that probe would let a token with no access report an all-clear for
every commit, which is this same blind spot from the other side.

**The audit reads `--first-parent`, because that is what release-please reads.** It asks GitHub for
the *merge commits on the branch*, not for everything reachable from it. A plain `git log` would
report a work-in-progress message inside a merged branch as a commit release-please dropped, and a
guard that cries wolf gets switched off.

**`KNOWN_UNPARSEABLE` is the `PATH_ALLOWANCES` pattern applied to a commit.** One full SHA, one
reason, printed by `--rules`, and pinned by the suite: an entry whose commit now parses fails
`test_every_known_unparseable_entry_is_still_earning_its_place` rather than quietly covering
something new. It is matched on the **full** SHA — a prefix is not an identifier, and that is the
same defect the leak scanner's trailing path match had, one layer down. There is one entry today,
`41bcb73`, and it is there because the audit would otherwise re-report a loss that has been made
good: its content is restated as a conventional-commit section in the release that followed it, so
the changelog names the TOON conformance and leak-allowance work even though release-please could
never read the original.

**The message is not always the message, and that is what the first version of this guard got
wrong.** It diagnosed the grammar rule correctly, shipped three layers built on it, and then passed
— green, twice — on a release that considered zero commits. release-please does not parse the commit
message. It parses `splitMessages(preprocessCommitMessage(commit))`, and `preprocessCommitMessage`
is four lines:

```js
const overrideMessage = (commit.pullRequest.body.split('BEGIN_COMMIT_OVERRIDE')[1] || '')
  .split('END_COMMIT_OVERRIDE')[0]
  .trim()
if (overrideMessage) return overrideMessage
```

`String.split` finds that literal **anywhere in a pull request body**, including in a sentence that
merely names it. The pull request that shipped the guard had a body explaining this very mechanism,
so release-please threw the commit message away and parsed the paragraph after the word instead. It
began `block from the PR body when there is one`; `block` is five characters; the parser stopped on
the space after it and reported `unexpected token ' ' at 1:6`. Column 6 makes no sense on a
`fix(ci):` subject, which is the clue that the text being parsed was not the subject at all. The
commit message parsed perfectly — and a checker that reads commit messages therefore said so.

**Three artefacts reach release-please and only one of them passes under a commit-msg hook.**

| artefact | written | checked by |
| --- | --- | --- |
| the commit message | locally, by a developer | `--commit-msg` (the hook) |
| the merge commit's message | in GitHub's squash box | `--since-release` (after the merge) |
| the pull request body | in GitHub's editor | `--pull-request` (`hygiene.yml`) |

The body is the dangerous one. It *replaces* the other two, it can be edited after every check has
run, and nothing in the repository records it — so `--since-release` and `--commit` resolve it from
the GitHub API rather than trusting `git log`, and `--pull-requests require` (what the workflows
pass) makes a missing credential a failure. Reaching for the network from a guard is a cost worth
naming, and the alternative was measured: without it the audit validates a string release-please may
never read, which is not a weaker check but a different one.

**One rule here is stricter than upstream, deliberately.** Upstream is content with an override
block that is never closed — it simply reads to the end of the body. That is exactly the shape an
accidental mention takes, so `override_faults` refuses a block that names the marker and never closes
it. Without that rule an accidental mention whose next paragraph *happened* to parse would silently
become the changelog entry. An empty block is not refused: upstream's `if (overrideMessage)` is falsy
on an empty string, so a body ending on the marker loses nothing and crying wolf at it would train
somebody to stop reading the output.

**The other fidelity note.** One commit may carry several conventional commits, split on
`BEGIN_NESTED_COMMIT` or on a blank line before a new `type:` line. `split_messages` transcribes that
so a message that loses only *part* of itself is still refused.

**Releasing a fix release-please already dropped.** Landing a parseable commit makes it re-scan the
range, but the unparseable commit is dropped again and never reaches the changelog — so the release
notes would omit the very fix being shipped. The route is to restate it: give the new commit message
a second conventional-commit section for the dropped work, which `splitMessages` turns into its own
changelog entry. Do not rewrite `main` to fix the original message; a tag or a published sha is not
worth the history.

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
