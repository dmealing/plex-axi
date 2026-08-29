#!/usr/bin/env sh
# Create this repository's development virtualenv and install the package into it.
#
# Use this rather than a bare editable install, and do not document one anywhere:
# `tests/test_dev_setup.py` fails if a copyable command reintroduces it, this
# file being the one place it belongs. This tool is normally installed as an isolated
# user-level tool (`pipx install`, `uv tool install`), and an editable install
# into whatever interpreter happens to be ambient *replaces that installation*:
# it overwrites the console script in ~/.local/bin with a launcher bound to the
# system interpreter, and leaves an editable pointer at this checkout. Delete
# the checkout — which is the ordinary end of a throwaway one — and the user's
# own copy of the tool dies with ModuleNotFoundError, with nothing to say why.
#
# A virtualenv cannot do that. It excludes the user site by construction, so
# everything installed here stays here. `.venv` is the same layout and the same
# call-by-path style CI already builds, so the repository has one pattern rather
# than two.
#
# Usage:
#   scripts/dev-setup.sh                    # create or reuse .venv, then install
#   PYTHON=python3.12 scripts/dev-setup.sh  # pick the interpreter to build it with
#
# To rebuild from scratch: rm -rf .venv && scripts/dev-setup.sh
set -e

root=$(git rev-parse --show-toplevel)
cd "$root"

python=${PYTHON:-python3}
venv=.venv

# A user-level pip.conf or PIP_USER=1 asks pip to install into the user site.
# This is not what keeps the install isolated — pip refuses a --user install
# inside a virtualenv rather than performing one — it only turns that refusal
# into the install the reader asked for.
PIP_USER=0
export PIP_USER

# -x rather than -d: a directory left behind by an interpreter that has since
# been removed or upgraded has no working python in it, and reusing it fails
# later and obscurely. `venv` repairs such a directory in place.
if [ ! -x "$venv/bin/python" ]; then
  echo "venv: creating $venv with $python"
  "$python" -m venv "$venv"
fi

"$venv/bin/python" -m pip install --upgrade pip
"$venv/bin/pip" install -e ".[dev]"

cat <<'EOF'

venv: .venv is ready. Call its tools by path, so nothing resolves to a copy
      installed somewhere else against a different interpreter:

  .venv/bin/pytest
  .venv/bin/ruff check . && .venv/bin/ruff format --check .
  .venv/bin/plex-axi skill --check
  scripts/leakcheck.py                     # stdlib only, so any python3 will do

hooks: run scripts/install-hooks.sh once per clone
EOF
