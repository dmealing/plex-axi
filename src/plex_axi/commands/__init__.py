"""Command modules: one per noun, each exporting ``COMMAND_FOR`` and ``run``.

Two modules here each serve three nouns. ``genres``/``moods``/``styles`` differ
only by which Plex filter field they read, and ``track``/``album``/``artist``
only by which libtype they accept, so each group is one parameterised module
rather than three near-identical files.

That is the one deliberate departure from the sibling AXI project's layout,
which exports a single ``COMMAND`` per module: a noun is passed in, and the
module answers with that noun's declaration. Adding a noun is still one entry in
``COMMAND_ORDER`` and one in ``_MODULES`` in ``cli.py`` -- root help, the
generated skill and the parametrised test sweeps all derive from those two.
"""
