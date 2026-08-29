"""Error types carrying the structured shape the CLI prints on stdout.

**The base is shared now, and that is what makes one ``except`` clause enough.**
:class:`axi_toolkit.errors.AxiError` is the contract every AXI tool raises
against, and the refusals inside :mod:`axi_toolkit.plex` -- the `plex://` forms
and the music filter language -- arrive as that class rather than as this
module's. :data:`AnyAxiError` is that base under a name that says what catching
it means: *an error already in AXI's shape, whoever raised it*. Everything
defined here specialises it, so a handler that catches :data:`AnyAxiError`
catches both and a handler that catches :class:`AxiError` alone would silently
miss half of them.

What this module adds is ``help_lines``: the recovery already written out as the
sentences this tool prints. The shared classes carry recovery as *data* with no
tool name anywhere in it -- which is exactly what lets one module serve two CLIs
-- so :func:`help_lines_for` is the single place the name is put back, at the
output boundary and nowhere earlier.
"""

from __future__ import annotations

from axi_toolkit.errors import EXIT_ERROR, EXIT_OK, EXIT_USAGE
from axi_toolkit.errors import AxiError as AnyAxiError
from axi_toolkit.render import cli as render

#: Named explicitly because three of these are re-exports: the exit codes and the
#: shared base come from ``axi_toolkit.errors`` now, and the rest of the package
#: has always read all of them from here.
__all__ = [
    "EXIT_ERROR",
    "EXIT_OK",
    "EXIT_USAGE",
    "TOOL",
    "AnyAxiError",
    "ApiError",
    "AuthFailed",
    "AxiError",
    "ConfigError",
    "ConnectionFailed",
    "NotFound",
    "UsageError",
    "help_lines_for",
]

#: The name that goes in front of a recovery's own words. It is supplied here
#: rather than stored beside the recovery: a recovery carrying it would belong
#: to this tool forever, which is the coupling moving those modules removed.
TOOL = "plex-axi"


class AxiError(AnyAxiError):
    """An error the agent should be able to read, understand and act on.

    ``help_lines`` carry the specific command that fixes the problem, per the
    AXI standard: on errors, suggest the fix rather than pointing at --help.
    """

    exit_code = EXIT_ERROR

    def __init__(
        self,
        message: str,
        *,
        help_lines: list[str] | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message, code=code)
        self.help_lines = list(help_lines or [])


class UsageError(AxiError):
    """A malformed invocation: unknown flag, missing argument, bad value."""

    exit_code = EXIT_USAGE


class ConfigError(AxiError):
    """Required environment configuration is missing or unusable."""


class ConnectionFailed(AxiError):
    """The Plex Media Server could not be reached."""


class AuthFailed(AxiError):
    """Plex rejected the token."""


class NotFound(AxiError):
    """The requested item, section or path does not exist."""


class ApiError(AxiError):
    """Plex answered, but refused the request."""


def help_lines_for(exc: AnyAxiError) -> list:
    """The lines printed under an error, whoever raised it.

    This tool writes its own. A refusal raised inside :mod:`axi_toolkit.plex`
    carries structured recovery instead, with a hole where a tool's name goes,
    and this is where the name arrives -- once, rather than at each of the dozen
    places such a refusal is raised.
    """
    lines = exc.help_lines if isinstance(exc, AxiError) else render.lines(exc.recovery, TOOL)
    return [line for line in lines if line]
