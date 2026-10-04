#!/usr/bin/env bash
# Run the opt-in live suite against a real Plex Media Server.
#
# The default `pytest`, scripts/ci-local.sh and the gate never run tests/live/:
# the project's addopts deselect the `live` marker. This is the one entry point
# that selects it.
#
# Usage:
#   scripts/live-test.sh                  # reads and previews only
#   scripts/live-test.sh --writes         # also the two self-reversing writes
#   scripts/live-test.sh -k transport     # extra arguments go to pytest
#
# It needs PLEX_URL and PLEX_TOKEN in the environment and refuses to run without
# them. Nothing is read from a file: export them for the length of one shell
# session, e.g. `set -a; . <your env file>; set +a`.
#
# What it will and will not do:
#   - every invocation of the tool goes through a recording proxy that forwards
#     GETs only; a non-GET is answered 403 unless a write test armed it, and a
#     playback request is never forwarded at all
#   - `--now` and `--user` are refused by the runner, so nothing is played and
#     plex.tv is never reached
#   - with --writes: one track's rating is set and cleared (the test refuses a
#     track that is already rated; pin one with PLEX_AXI_LIVE_RATE_KEY), and one
#     playlist named zz-plex-axi-live-test-<epoch> is created and deleted. Both
#     are restored in a `finally` and verified against the raw API.
#   - no scan, no refresh, no analysis, no scheduled job, no paid call
#
# Captured output goes to .live-output/, which is git-ignored and is replaced
# on every run. It holds real library content: never commit or paste it.
set -uo pipefail

self=$(readlink -f "${BASH_SOURCE[0]}")
root=$(dirname "$self")/..
cd "$root" || exit 1

writes=0
args=()
while [ $# -gt 0 ]; do
  case $1 in
    --writes) writes=1; shift ;;
    -h | --help) sed -n '2,/^set -uo/p' "$self" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
    *) args+=("$1"); shift ;;
  esac
done

missing=()
[ -n "${PLEX_URL:-}" ] || missing+=(PLEX_URL)
[ -n "${PLEX_TOKEN:-}" ] || missing+=(PLEX_TOKEN)
if [ ${#missing[@]} -gt 0 ]; then
  echo "live-test: ${missing[*]} not set; export the server's address and a token first" >&2
  exit 2
fi

[ -x .venv/bin/plex-axi ] || scripts/dev-setup.sh

out=.live-output
rm -rf "$out"
mkdir -p "$out"

PLEX_AXI_LIVE_OUTPUT=$(readlink -f "$out")
export PLEX_AXI_LIVE_OUTPUT
if [ "$writes" -eq 1 ]; then
  export PLEX_AXI_LIVE_WRITES=1
else
  unset PLEX_AXI_LIVE_WRITES
fi
# The gates are the suite's to set, one invocation at a time.
unset PLEX_AXI_ALLOW_WRITES PLEX_AXI_ALLOW_PLAYBACK PLEX_ACCOUNT_TOKEN

# -p no:cacheprovider: a cache directory would record test ids, and some of
# those are built from the library.
.venv/bin/pytest -m live tests/live -p no:cacheprovider -rs "${args[@]}"
rc=$?

echo
echo "live-test: $(find "$out" -name '*.txt' | wc -l) invocations captured in $out/ (git-ignored)"
[ "$rc" -eq 0 ] && echo "live-test: PASS" || echo "live-test: FAIL" >&2
exit "$rc"
