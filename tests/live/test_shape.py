"""R1, live: the committed capture still describes this server, and the double fits it.

``tests/test_shape_contract.py`` holds the double to the *committed* capture,
offline. This asks the other half: is the capture still true? A server upgrade
that renames an attribute or drops an operator changes what the double should
be, and nothing offline can know.
"""

from __future__ import annotations

import importlib.util
import json

from .harness import ROOT


def _capture_module():
    spec = importlib.util.spec_from_file_location(
        "shape_capture", ROOT / "scripts" / "shape-capture.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_filter_language_is_the_one_that_was_transcribed(live):
    module = _capture_module()
    fresh = module.capture(module.Server(f"{live.real.scheme}://{live.real.netloc}", live.token))
    committed = json.loads(module.CAPTURE.read_text(encoding="utf-8"))
    assert fresh["field_types"] == committed["field_types"], "the operator tables have changed"
    assert fresh["types"] == committed["types"], "the advertised fields, filters or sorts changed"
    # Every name that was transcribed is still sent. A name the server has
    # *gained* is reported and not failed on: which rows are rated or played
    # moves from one day to the next, and with it which attributes are present.
    gained = {}
    for name, names in committed["elements"].items():
        missing = set(names) - set(fresh["elements"].get(name, []))
        assert not missing, f"{name} no longer carries {sorted(missing)}"
        extra = set(fresh["elements"].get(name, [])) - set(names)
        if extra:
            gained[name] = sorted(extra)
    if gained:
        print("attributes this server sends that the capture does not list:", gained)
