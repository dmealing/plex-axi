"""Project-owned MetaObjects generators: what an upstream API answers, declared once.

The stock ``metaobjects gen`` runs these; ``metaobjects.config.yaml`` names each one as
``metagen:<symbol>``. They read the loaded model under ``metaobjects/`` and emit Python
that imports the standard library alone and is written in the oldest syntax the
consuming package supports, so the toolchain's own Python floor never reaches it.

Nothing here is imported by the package or by its test suite. It needs ``metaobjects``
and a Python that can run it, at development time only: to regenerate, and for
``metaobjects verify --codegen`` to prove the committed output is what the model emits.

Three generators, and what each one reads:

``rows``
    An object carrying a ``row`` bag is a row the tool prints. Its fields are the
    columns, in order; the projection whose fields extend them is the default set.
    Emits the column vocabulary, the default set and the attributes each column reads.
``elements``
    An object carrying a ``wire`` bag is something the server answers. Emits one
    builder per object that a test double builds its answers through, and that
    refuses an attribute the model does not declare.
``capture_contract``
    Emits the check that every declared attribute is in a committed capture of a real
    server's answers, or carries the reason it could not be observed.

This directory holds no name from any one project, so that it can move into a shared
library as it stands.
"""

from .emit import capture_contract, elements, rows

__all__ = ["capture_contract", "elements", "rows"]
