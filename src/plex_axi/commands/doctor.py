"""`plex-axi doctor` -- prove the environment, the server and the filters work.

Five checks in the order a failure actually happens, because the first one to
fail is the one worth reporting. The last is the one no other Plex tool makes:
a music search is only as good as the server's filter metadata, and a library
that has not finished scanning advertises fields that are not there yet.
"""

from __future__ import annotations

from ..argspec import Command, Sub
from ..config import describe_environment, missing_env_vars, setup_help
from ..errors import AxiError
from ..music import MUSIC_SECTION_TYPE
from ..output import HelpBlock
from ._common import plural

COMMAND = Command(
    name="doctor",
    summary="Check the environment, the server, the music library and its filters",
    usage="usage: plex-axi doctor",
    default_sub="doctor",
    subs=(Sub(name="doctor", summary="Run every connection check"),),
    notes=(
        "exits non-zero when any check fails, so it works as a CI or hook gate",
        "a rejected token is reported as invalid or expired separately, because "
        "Plex answers 401 to both and only the response text tells them apart",
    ),
    examples=("plex-axi doctor", "plex-axi --section 'Example Music' doctor"),
)


def COMMAND_FOR(name: str) -> Command:
    return COMMAND


#: Fields a structured music search depends on. Their absence is the difference
#: between "no results" and "this library cannot answer that question yet".
REQUIRED_FIELDS = ("title", "userRating")


def run(ctx, name: str, sub: str, parsed):
    env = describe_environment(ctx.environ)
    checks = []

    missing = missing_env_vars(ctx.environ)
    if missing:
        checks.append(
            {
                "check": "environment",
                "status": "fail",
                "detail": f"{' and '.join(missing)} not set",
            }
        )
        return _document(checks, healthy=False)

    checks.append(
        {
            "check": "environment",
            "status": "ok",
            "detail": f"{env['url_var']} and {env['token_var']} are set",
        }
    )

    try:
        server = ctx.server()
    except AxiError as exc:
        checks.append({"check": "server", "status": "fail", "detail": exc.message})
        return _document(checks, healthy=False, extra_help=exc.help_lines)

    checks.append(
        {
            "check": "server",
            "status": "ok",
            "detail": f"{server.friendlyName} (Plex Media Server {server.version})",
        }
    )

    try:
        section = ctx.section()
    except AxiError as exc:
        checks.append({"check": "music library", "status": "fail", "detail": exc.message})
        return _document(checks, healthy=False, extra_help=exc.help_lines)

    checks.append(
        {
            "check": "music library",
            "status": "ok",
            "detail": f"{section.title} (key {section.key}, type {MUSIC_SECTION_TYPE})",
        }
    )

    healthy = True
    try:
        fields = [f.key.rsplit(".", 1)[-1] for f in section.listFields("track")]
        absent = [name for name in REQUIRED_FIELDS if name not in fields]
        if absent:
            healthy = False
            checks.append(
                {
                    "check": "filter fields",
                    "status": "fail",
                    "detail": (
                        f"this library does not advertise {', '.join(absent)} for a track; "
                        "a structured search cannot be built on it yet"
                    ),
                }
            )
        else:
            checks.append(
                {
                    "check": "filter fields",
                    "status": "ok",
                    "detail": f"{plural(len(fields), 'queryable field')} on a track",
                }
            )
    except Exception as exc:
        healthy = False
        checks.append(
            {
                "check": "filter fields",
                "status": "fail",
                "detail": _brief(exc),
            }
        )

    return _document(checks, healthy=healthy, version=server.version)


def _brief(exc: Exception) -> str:
    """A doctor line is a diagnosis, not a stack trace or a vendor message."""
    text = str(exc).split(";")[0].strip()
    return text[:120] or "the library did not answer with its filter metadata"


def _document(checks, *, healthy: bool, version: str = "", extra_help=None):
    doc = {"healthy": healthy, "checks": checks}
    if version:
        doc["version"] = version
    if not healthy:
        lines = list(extra_help or [])
        # No "run doctor to check" line: doctor is what just ran.
        lines.extend(setup_help(include_doctor=False))
        doc["help"] = HelpBlock(list(dict.fromkeys(line for line in lines if line)))
        doc["__exit_code__"] = 1
    return doc
