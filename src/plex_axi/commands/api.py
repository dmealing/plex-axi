"""`plex-axi api <path>` -- one authenticated escape hatch, not a wrapper layer.

Every endpoint this tool does not model is still reachable, so a missing typed
command is an inconvenience rather than a wall. One raw-path command covers the
whole residue; a wrapper per endpoint would be the anti-pattern this tool exists
to avoid, and would drift from the server the moment Plex shipped a change.

**GET only, and it stays GET only now that the tool can write.** `rate` and
`playlist` mutate, and both are gated, previewable and specific about what they
touch; a raw path that could POST would be none of those, and it would make the
gate meaningless because anything refused by a typed command could be reissued
here by hand. Several Plex write endpoints are destructive and answer a
GET-shaped URL, so the restriction is enforced rather than documented --
"documented" is not a control. A HEAD is refused as well: the command's whole
value is the response body it renders, and a HEAD has none -- `api GET <path>`
answers whether a path exists and shows what is there.

Plex answers XML. The response is converted to the same structured shape every
other command prints, so an agent does not have to parse two formats.
"""

from __future__ import annotations

from ..argspec import Command, Flag, Sub
from ..errors import UsageError
from ..output import HelpBlock
from ..plex import translate
from ._common import parse_pairs

#: The only method this escape hatch may issue. Anything else is refused by name.
METHODS = ("GET",)

#: Methods a caller might try, and what to say instead of "unknown method".
_WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

#: Safe but unsupported: a HEAD returns headers and no body, and the body is
#: this command's entire value. Refused by name rather than executed as the GET
#: a defaulted request method would send.
_HEAD_METHODS = ("HEAD",)

#: How deep the XML is walked before the shape is summarised. Plex nests media
#: parts and streams several levels down, and a detail view that dumped all of
#: it would cost more tokens than every list command combined.
MAX_DEPTH = 3

COMMAND = Command(
    name="api",
    summary="Make an authenticated GET to any Plex API path",
    usage="usage: plex-axi api [GET] <path> [flags]",
    default_sub="api",
    subs=(
        Sub(
            name="api",
            args=("[method-or-path]", "[path]"),
            flags=(
                Flag("--query", "<key=value>", repeat=True, note="query string parameter"),
                Flag("--depth", "<n>", default=MAX_DEPTH, note="how deep to render nested XML"),
            ),
            summary="Request a Plex API path",
        ),
    ),
    notes=(
        "the method is GET, spelled out or omitted; a HEAD is refused because it has no body to render",
        "write methods are refused here even when writes are enabled: a mutation goes "
        "through a typed command that can validate and preview it, and several Plex write "
        "endpoints are destructive",
        "the token is sent as a header and never appears in the path this prints",
    ),
    examples=(
        "plex-axi api /",
        "plex-axi api /library/sections",
        "plex-axi api /status/sessions",
        "plex-axi api /library/sections/1/all --query type=10 --query limit=5",
    ),
)


def COMMAND_FOR(name: str) -> Command:
    return COMMAND


def run(ctx, name: str, sub: str, parsed):
    method, path = _method_and_path(parsed.positionals)
    query = parse_pairs(parsed.get("query", []), flag="--query")
    depth = _parse_depth(parsed.get("depth"))
    _reject_token_in_query(query)

    server = ctx.server()
    try:
        data = server.query(path, params=query or None)
    except Exception as exc:
        raise translate(
            exc,
            what=f"the path {path}",
            help_lines=[
                "Run `plex-axi api /` to confirm the server answers at all",
                "Run `plex-axi api /library/sections` to list the paths below a section",
            ],
        ) from None

    doc = {"request": {"method": method, "path": path}}
    if query:
        doc["request"]["query"] = ", ".join(f"{k}={v}" for k, v in sorted(query.items()))
    if data is None:
        doc["result"] = f"{method} succeeded with an empty response"
        return doc
    doc["result"] = _render(data, depth)
    doc["help"] = HelpBlock(
        [
            "Run the same path with `--depth 5` if a nested element was summarised",
            "A typed command exists for search, detail, genres, similar, recent and sessions",
        ]
    )
    return doc


def _render(element, depth: int):
    """Convert one XML element into the plain shape the output boundary prints."""
    node = dict(element.attrib)
    children = list(element)
    if children and depth > 0:
        grouped: dict = {}
        for child in children:
            grouped.setdefault(child.tag, []).append(_render(child, depth - 1))
        node.update(grouped)
    elif children:
        counts: dict = {}
        for child in children:
            counts[child.tag] = counts.get(child.tag, 0) + 1
        node["_children"] = ", ".join(f"{tag} x{n}" for tag, n in sorted(counts.items()))
    return node


def _parse_depth(raw) -> int:
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        raise UsageError(
            f"--depth needs a whole number, got {raw!r}",
            help_lines=[f"Run the command again with `--depth {MAX_DEPTH}`"],
            code="BAD_DEPTH",
        ) from None
    if not 0 <= value <= 8:
        raise UsageError(
            f"--depth is between 0 and 8, got {value}",
            help_lines=[f"Run the command again with `--depth {MAX_DEPTH}`"],
            code="BAD_DEPTH",
        )
    return value


def _reject_token_in_query(query: dict) -> None:
    """Refuse a caller-supplied token rather than putting one in a URL.

    Plex accepts `X-Plex-Token` as a query parameter, which is how it ends up in
    shell history, proxy logs and screenshots. The tool already authenticates
    from the environment, so a token here is never needed and always a leak.
    """
    for key in query:
        if key.lower().replace("_", "-") in ("x-plex-token", "token"):
            raise UsageError(
                f"--query {key}=... would put a credential in a URL",
                help_lines=[
                    "The token is already sent as a header, from PLEX_TOKEN; drop the parameter",
                ],
                code="TOKEN_IN_QUERY",
            )


def _method_and_path(positionals: list):
    values = [value for value in positionals if value is not None]
    if not values:
        raise UsageError(
            "a path is required",
            help_lines=["Run `plex-axi api /`", "Run `plex-axi api /library/sections`"],
            code="MISSING_PATH",
        )
    head = values[0].upper()
    if head in _WRITE_METHODS:
        raise UsageError(
            f"{head} is not available: `api` is read-only whatever else is enabled",
            help_lines=[
                "Run `plex-axi api GET <path>` to read the same resource",
                "Run `plex-axi rate --help` or `plex-axi playlist --help` for the writes this "
                "tool does offer, each gated and previewable",
            ],
            code="READ_ONLY",
        )
    if head in _HEAD_METHODS:
        raise UsageError(
            f"{head} is not available: plex-axi renders response bodies, and a {head} has none",
            help_lines=["Run `plex-axi api GET <path>` to read the resource"],
            code="UNSUPPORTED_METHOD",
        )
    if head in METHODS:
        if len(values) < 2:
            raise UsageError(
                f"a path is required after {head}",
                help_lines=[f"Run `plex-axi api {head} /library/sections`"],
                code="MISSING_PATH",
            )
        return head, values[1]
    if len(values) > 1:
        raise UsageError(
            f"unexpected argument {values[1]!r}",
            help_lines=[f"methods must come first: `plex-axi api GET {values[0]}`"],
            code="UNEXPECTED_ARGUMENT",
        )
    return "GET", values[0]
