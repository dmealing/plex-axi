"""The opt-in live suite: `scripts/live-test.sh`, never the default run.

A package, unlike the rest of ``tests/``, for one reason: it has a ``conftest.py``
of its own, and two modules both importable as ``conftest`` would leave every
``from conftest import ...`` in the offline suite reading whichever was loaded
last. Inside a package this one is ``live.conftest``.
"""
