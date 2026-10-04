"""Fixtures for the live suite: opt-in, and never part of the default run.

Everything under ``tests/live/`` is marked ``live`` and the project's ``addopts``
deselect that marker, so ``pytest``, ``scripts/ci-local.sh`` and the gate never
run it. ``scripts/live-test.sh`` does, against whatever server ``PLEX_URL`` and
``PLEX_TOKEN`` name.

The safety rules are in the harness rather than in each test, so a new test
inherits them:

* the tool is only ever run *through* the proxy or the stub -- there is no
  fixture that points it straight at the real server;
* the proxy answers every non-GET with 403 unless a test arms it, and never
  forwards a playback request, armed or not;
* ``--now`` and ``--user`` are refused by the runner itself;
* gates are stripped from the environment unless a case sets one, and the
  session-state directory always points into a scratch directory.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from .harness import TOOL, Catalogue, Live, Proxy, Stub

#: Real writes are a second opt-in on top of running the suite at all.
WRITES_VAR = "PLEX_AXI_LIVE_WRITES"


def pytest_collection_modifyitems(config, items):
    here = Path(__file__).resolve().parent
    missing = [name for name in ("PLEX_URL", "PLEX_TOKEN") if not os.environ.get(name)]
    for item in items:
        if here not in Path(str(item.fspath)).resolve().parents:
            continue
        item.add_marker(pytest.mark.live)
        if missing:
            item.add_marker(pytest.mark.skip(reason=f"{' and '.join(missing)} not set"))
        elif not Path(TOOL).exists():
            item.add_marker(pytest.mark.skip(reason="no .venv; run scripts/dev-setup.sh"))
        if "live_write" in item.keywords and os.environ.get(WRITES_VAR) != "1":
            item.add_marker(pytest.mark.skip(reason=f"real writes need {WRITES_VAR}=1"))


@pytest.fixture(scope="session")
def live(tmp_path_factory):
    capture = os.environ.get("PLEX_AXI_LIVE_OUTPUT")
    capture = Path(capture) if capture else tmp_path_factory.mktemp("captured")
    return Live(
        os.environ["PLEX_URL"],
        os.environ["PLEX_TOKEN"],
        tmp_path_factory.mktemp("scratch"),
        capture,
    )


@pytest.fixture(scope="session")
def _proxy(live):
    proxy = Proxy(live)
    yield proxy
    proxy.close()


@pytest.fixture
def proxy(_proxy):
    """The recording proxy, with an empty log, no fault and writes blocked."""
    _proxy.reset()
    yield _proxy
    # The interlock firing is a failure wherever it happens, unless the test
    # was asking whether it fires.
    _proxy.reset()


@pytest.fixture
def stub(live):
    made = Stub(live)
    yield made
    made.close()


@pytest.fixture(scope="session")
def catalogue(live):
    return Catalogue(live)


@pytest.fixture
def run(live, proxy):
    """Run the tool through the proxy, with the standing checks applied."""

    def _run(*argv, **kwargs):
        kwargs.setdefault("via", proxy)
        return live.run(*argv, **kwargs)

    return _run
