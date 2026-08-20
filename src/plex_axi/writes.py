"""The write gate: one decision with two conjuncts, and the access vocabulary.

Until this module existed the claim "plex-axi cannot change anything" was total,
and its value came from being total. The commands that break it therefore have
to be gated in a way a caller cannot talk its way past, and every command's
``--help`` has to say which side of the line it is on -- which is what
:data:`ACCESS` is for, so that the answer is declared once per command rather
than written into prose that can go stale.

**The environment variable is the gate, and that is the deliberate choice.**
niavasha's Plex MCP server is the only project in the landscape that gates its
mutations at all, and it gates them on ``PLEX_ENABLE_MUTATIVE_OPS`` being
exactly ``"true"``. What makes an environment variable the right primary is
*who sets it*: the operator, once, outside the invocation, in a shell profile or
a service unit. An agent composing a command line cannot grant itself a
permission it was not given, and the refusal can name what to change and who
changes it.

``--write`` is the second conjunct and it is **not** a second gate. With the
variable set but the flag absent, a mutating command still runs -- it previews.
It reads the item or the playlist, prints exactly what would change, and sends
nothing. That is a useful answer rather than a nag, it is where the two playlist
failure modes are caught before anything is written, and it means the flag is
load-bearing rather than ceremony an agent shrugs off and retries past: leaving
it out asks a different, cheaper question.

The order is fixed and it matters: **the gate is checked before the connection
is opened**, so a mutating command with the gate closed reaches the server zero
times rather than reading first and refusing afterwards.
"""

from __future__ import annotations

from .errors import AxiError

#: The operator's standing decision, read from the environment at the moment a
#: mutating command starts. Prefixed like ``PLEX_AXI_DEBUG`` rather than named
#: after the tool that inspired it: this is plex-axi's own switch.
ALLOW_VAR = "PLEX_AXI_ALLOW_WRITES"

#: The one accepted value, matched case-insensitively after stripping. Anything
#: else is refused *by name* rather than treated as false, because a variable
#: set to "yes" is an operator who meant to open the gate and a silent "no"
#: there reads as a broken tool.
ALLOW_VALUE = "true"

#: The per-invocation confirmation. Declared here so the commands, the help
#: renderer and the refusal text cannot spell it differently.
WRITE_FLAG = "--write"

READ_ONLY = "read-only"
MUTATING = "mutating"

#: What each access level means, in one line, printed by `--help` for every
#: command and by the generated skill. This is the sentence the S8 requirement
#: asks for, and it is declared rather than described so no command can omit it.
ACCESS = {
    READ_ONLY: "read-only - this command cannot change anything on the server",
    MUTATING: (
        f"mutating - needs {ALLOW_VAR}={ALLOW_VALUE} in the environment; "
        f"without {WRITE_FLAG} it previews the change and sends nothing"
    ),
}


class WriteRefused(AxiError):
    """A mutating command run against a closed gate.

    Exits 1 rather than 2: the invocation was well formed and the command
    exists. What is absent is the operator's opt-in, which is configuration --
    the same class of problem as an unset ``PLEX_TOKEN``, and reported the same
    way.
    """


def gate_value(environ) -> str:
    """The raw value of the gate variable, stripped. Empty when unset."""
    return (environ.get(ALLOW_VAR) or "").strip()


def allowed(environ) -> bool:
    return gate_value(environ).lower() == ALLOW_VALUE


def state(environ) -> str:
    """A one-line description of the gate, for the home view."""
    raw = gate_value(environ)
    if raw.lower() == ALLOW_VALUE:
        return f"enabled ({ALLOW_VAR}={raw}); mutating commands still need {WRITE_FLAG}"
    if raw:
        return f"disabled ({ALLOW_VAR} is {raw!r}, not {ALLOW_VALUE!r})"
    return f"disabled (export {ALLOW_VAR}={ALLOW_VALUE} to enable)"


def require(environ, *, action: str) -> None:
    """Refuse ``action`` unless this installation has been opted in.

    Called before the connection is opened, so a refusal costs no request and
    the server never hears about the attempt.
    """
    raw = gate_value(environ)
    if raw.lower() == ALLOW_VALUE:
        return
    detail = f"{ALLOW_VAR} is {raw!r}, not {ALLOW_VALUE!r}" if raw else f"{ALLOW_VAR} is not set"
    raise WriteRefused(
        f"refusing to {action}: writes are disabled ({detail})",
        help_lines=[
            f"Run `export {ALLOW_VAR}={ALLOW_VALUE}`, then run the command again with {WRITE_FLAG}",
            "The gate is an environment variable rather than a flag on purpose: it is the "
            "operator's decision, and a caller cannot grant itself one it was not given",
            "Nothing was sent to the server; every other command in plex-axi reads",
        ],
        code="WRITES_DISABLED",
    )


#: The line a preview prints instead of a result, so that "would" is never
#: mistaken for "did". AXI 6: a mutation response says what happened, and this
#: one says that nothing did.
PREVIEW_LINE = "nothing was sent to the server"


def preview_note(command: str) -> str:
    return f"{PREVIEW_LINE}; run `{command}` with {WRITE_FLAG} to apply it"
