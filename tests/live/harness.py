"""The live harness: runner, leak scan, recording proxy, stub, raw client.

Four ideas carry the live suite, and each one found defects the offline suite
could not:

1. **A recording reverse proxy in front of the real server.** Every tool
   invocation points ``PLEX_URL`` at it. It logs method, path and query keys, so
   "reaches the server zero times" and "a preview sends GETs only" are observed
   on the wire rather than inferred from an exit code. It is also the safety
   interlock: a non-GET is answered 403 and never forwarded unless a test arms
   it, and anything shaped like a playback request is never forwarded at all.
2. **Fault injection in that proxy.** Delay, error status, a foreign body, a
   truncated body, a dropped connection -- the answers a real network gives and
   a mock that raises a chosen exception cannot.
3. **A stub that forwards nothing.** For the questions that must never reach
   the real server: does the tool send this dangerous request at all?
4. **Raw-API ground truth.** The catalogue is fetched once and the tool's totals
   and rows are compared against it. Samples are chosen from it at run time by
   *shape* -- a title with a typographic apostrophe, a title with a comma -- so
   no real name is ever written into this repository.

Every invocation gets the same standing checks: no token or token fragment on
either stream, no credential-named attribute left unredacted, the real server's
address nowhere (the tool only ever sees the proxy's), stderr empty unless
``--debug`` was passed.
"""

from __future__ import annotations

import contextlib
import http.client
import http.server
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: Never the installed copy: a bare `plex-axi` is whatever is on PATH.
TOOL = str(ROOT / ".venv" / "bin" / "plex-axi")

#: Stripped from every invocation's environment unless a case sets one.
GATES = ("PLEX_AXI_ALLOW_WRITES", "PLEX_AXI_ALLOW_PLAYBACK", "PLEX_ACCOUNT_TOKEN", "PLEX_SECTION")

#: The flags that start playback or reach plex.tv. No command line the harness
#: builds, extracts from documentation or follows from a suggestion may hold one.
FORBIDDEN_FLAGS = ("--now", "--user")

CREDENTIAL_ATTRIBUTE = re.compile(
    r"(?im)^\s*\"?\w*(token|secret|password|authKey)\w*\"?: \"?(?!<redacted>)[^\s\"]{8,}"
)
TOKEN_SHAPE = re.compile(r"X-Plex-Token[=:]\s*(?!<)[A-Za-z0-9_\-]{8,}")


class Result:
    __slots__ = ("argv", "code", "err", "out", "seconds")

    def __init__(self, argv, code, out, err, seconds):
        self.argv, self.code, self.out, self.err, self.seconds = argv, code, out, err, seconds

    def json(self):
        return json.loads(self.out)

    def line(self, prefix: str) -> str:
        for line in self.out.splitlines():
            if line.strip().startswith(prefix):
                return line.strip()
        return ""


class Live:
    """The real server's coordinates, and everything that talks to it."""

    def __init__(self, base_url: str, token: str, scratch: Path, capture: Path) -> None:
        if "://" not in base_url:
            base_url = f"http://{base_url}"
        self.real = urllib.parse.urlparse(base_url.rstrip("/"))
        self.token = token.strip()
        self.scratch = scratch
        self.capture = capture
        self.capture.mkdir(parents=True, exist_ok=True)
        self.invocations = 0
        self._armed = False

    # ------------------------------------------------------------- leak scan

    def leaks(self, text: str) -> list:
        found = []
        if self.token in text or self.token[:10] in text or self.token[-10:] in text:
            found.append("TOKEN")
        if TOKEN_SHAPE.search(text):
            found.append("TOKEN-SHAPE")
        if CREDENTIAL_ATTRIBUTE.search(text):
            found.append("CREDENTIAL-ATTRIBUTE")
        if self.real.hostname and self.real.hostname in text:
            found.append("HOST")
        return found

    # ---------------------------------------------------------------- runner

    def run(
        self, *argv, via, env=None, unset=(), stdin=None, timeout=120, check=True, allow=()
    ) -> Result:
        """One invocation of this checkout's tool, through a proxy or a stub.

        ``via`` is required: there is no way to run the tool straight at the
        real server from here, which is what makes the interlock an interlock.
        """
        for flag in FORBIDDEN_FLAGS:
            assert flag not in argv, f"{flag} is never passed by the live suite"
        environment = {k: v for k, v in os.environ.items() if k not in GATES}
        environment["XDG_STATE_HOME"] = str(self.scratch / "state")
        environment["PLEX_URL"] = via.url
        environment["PLEX_TOKEN"] = self.token
        for name in unset:
            environment.pop(name, None)
        environment.update(env or {})
        start = time.perf_counter()
        done = subprocess.run(
            [TOOL, *argv],
            env=environment,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(self.scratch),
        )
        result = Result(
            argv, done.returncode, done.stdout, done.stderr, time.perf_counter() - start
        )
        self.invocations += 1
        self._save(result)
        if check:
            self.standing_checks(result, allow=allow)
        return result

    def standing_checks(self, result: Result, *, allow=()) -> None:
        """What every invocation owes, whatever it was asked.

        ``allow`` names a leak class a surface prints by design. The one use is
        ``HOST`` on a raw ``api`` path whose answer is the server describing its
        own network: `api` renders what the server says, and says so.
        """
        both = result.out + result.err
        found = [leak for leak in self.leaks(both) if leak not in allow]
        assert found == [], (result.argv, found)
        assert result.code in (0, 1, 2), result.argv
        if "--debug" not in result.argv:
            assert result.err == "", (result.argv, result.err[:300])
        assert "Traceback (most recent call last)" not in both, result.argv

    def _save(self, result: Result) -> None:
        """Captured output, for the scan that runs after the suite."""
        path = self.capture / f"{self.invocations:05d}.txt"
        path.write_text(f"exit: {result.code}\n--- stdout\n{result.out}--- stderr\n{result.err}")

    # ------------------------------------------------------------ raw client

    def raw(self, path: str, params=None, *, start=None, size=None):
        """Ground truth: straight to the server, parsed. GET only."""
        return self._request("GET", path, params, start=start, size=size)

    def arm(self) -> None:
        """Allow the raw client one class of write: cleaning up what a test made."""
        self._armed = True

    def raw_delete(self, path: str) -> int:
        assert self._armed, "the raw client refuses a write unless a test armed it"
        return self._request("DELETE", path, None, parse=False)

    def _request(self, method, path, params, *, start=None, size=None, parse=True):
        query = urllib.parse.urlencode(params or {}, doseq=True)
        headers = {"X-Plex-Token": self.token, "Accept": "application/xml"}
        if size is not None:
            headers["X-Plex-Container-Start"] = str(start or 0)
            headers["X-Plex-Container-Size"] = str(size)
        request = urllib.request.Request(
            f"{self.real.scheme}://{self.real.netloc}{path}" + (f"?{query}" if query else ""),
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            body = response.read()
            if not parse:
                return response.status
        return ElementTree.fromstring(body) if body.strip() else None


class Proxy:
    """Records every request; forwards GETs; blocks everything else; injects faults."""

    PLAYBACK = ("/player/", "playMedia", "/playQueues")

    def __init__(self, live: Live) -> None:
        self.live = live
        self.log: list = []
        self.fault = None
        self.allow_writes = False
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _any(self):
                outer.handle(self)

            do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_PATCH = do_OPTIONS = _any

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def reset(self) -> None:
        self.log.clear()
        self.fault = None
        self.allow_writes = False

    # -- what a test asserts on

    @property
    def methods(self) -> set:
        return {entry["method"] for entry in self.log}

    @property
    def blocked(self) -> list:
        return [entry for entry in self.log if entry["blocked"]]

    @property
    def paths(self) -> list:
        return [entry["path"] for entry in self.log]

    def handle(self, handler) -> None:
        parts = urllib.parse.urlsplit(handler.path)
        query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        body = handler.rfile.read(int(handler.headers.get("Content-Length") or 0))
        entry = {
            "method": handler.command,
            "path": parts.path,
            "keys": [key for key, _ in query],
            "token_in_query": any("token" in key.lower() for key, _ in query),
            "token_header": bool(handler.headers.get("X-Plex-Token")),
            "blocked": False,
        }
        self.log.append(entry)

        def send(status, payload=b"", ctype="text/plain"):
            handler.send_response(status)
            handler.send_header("Content-Type", ctype)
            handler.send_header("Content-Length", str(len(payload)))
            handler.end_headers()
            handler.wfile.write(payload)

        playback = any(marker in handler.path for marker in self.PLAYBACK)
        if playback or (handler.command != "GET" and not self.allow_writes):
            entry["blocked"] = True
            return send(403, b"blocked by the live harness")

        fault = self.fault if self.fault and self.fault.get("match", "") in parts.path else None
        if fault:
            time.sleep(fault.get("delay", 0))
            if "drop" in fault:
                handler.close_connection = True
                with contextlib.suppress(OSError):
                    handler.connection.shutdown(socket.SHUT_RDWR)
                return None
            if "status" in fault:
                return send(
                    fault["status"], fault.get("body", b""), fault.get("ctype", "text/html")
                )
        payload, status, headers = self.forward(handler, body)
        if fault and "truncate" in fault:
            payload = payload[: max(1, len(payload) // 2)]
        handler.send_response(status)
        for key, value in headers:
            if key.lower() not in (
                "transfer-encoding",
                "connection",
                "keep-alive",
                "content-length",
            ):
                handler.send_header(key, value)
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)
        return None

    def forward(self, handler, body: bytes) -> tuple:
        real = self.live.real
        connection_class = (
            http.client.HTTPSConnection if real.scheme == "https" else http.client.HTTPConnection
        )
        connection = connection_class(real.hostname, real.port, timeout=90)
        sent = {
            key: value
            for key, value in handler.headers.items()
            if key.lower() not in ("host", "connection", "accept-encoding")
        }
        connection.request(
            handler.command, handler.path, body=body or None, headers={**sent, "Host": real.netloc}
        )
        response = connection.getresponse()
        payload = response.read()
        connection.close()
        return payload, response.status, response.getheaders()


class Stub(Proxy):
    """Answers from a can and forwards nothing: for requests the real server must never see."""

    ROOT_XML = (
        '<MediaContainer size="0" machineIdentifier="{}" version="0.0.0-stub" friendlyName="Stub"/>'
    )

    def __init__(self, live: Live, canned=None) -> None:
        super().__init__(live)
        self.canned = canned or {}

    def handle(self, handler) -> None:
        parts = urllib.parse.urlsplit(handler.path)
        handler.rfile.read(int(handler.headers.get("Content-Length") or 0))
        self.log.append({"method": handler.command, "path": parts.path, "blocked": False})
        text = self.canned.get(parts.path)
        if text is None:
            text = (
                self.ROOT_XML.format("5" * 40)
                if parts.path == "/"
                else '<MediaContainer size="0"/>'
            )
        payload = text.encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "text/xml;charset=utf-8")
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)


class Catalogue:
    """The library as the raw API reports it, fetched once. Ground truth."""

    PAGE = 4000

    def __init__(self, live: Live) -> None:
        self.live = live
        sections = live.raw("/library/sections")
        music = [d for d in sections if d.attrib.get("type") == "artist"]
        assert music, "the live server has no music library"
        self.section = music[0].attrib["key"]
        self.machine = live.raw("/").attrib["machineIdentifier"]
        self.artists = self._all(8)
        self.albums = self._all(9)
        self.tracks = self._all(10)
        self.playlists = [dict(p.attrib) for p in live.raw("/playlists", {"playlistType": "audio"})]

    def _all(self, code: int) -> list:
        rows, start = [], 0
        while True:
            page = self.live.raw(
                f"/library/sections/{self.section}/all", {"type": code}, start=start, size=self.PAGE
            )
            rows.extend(dict(row.attrib) for row in page)
            if len(page) < self.PAGE:
                return rows
            start += self.PAGE

    def total(self, params: dict) -> int:
        """An exact count from the raw API, for one filter."""
        answer = self.live.raw(f"/library/sections/{self.section}/all", params, start=0, size=0)
        return int(answer.attrib.get("totalSize", answer.attrib.get("size", 0)))

    def sample(self, rows: list, predicate, limit: int) -> list:
        """Up to ``limit`` rows matching ``predicate``, spread across the library."""
        matching = [row for row in rows if predicate(row)]
        step = max(1, len(matching) // limit)
        return matching[::step][:limit]
