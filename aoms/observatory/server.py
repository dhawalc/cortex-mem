"""Small stdlib HTTP adapter for the loopback Recall Observatory.

``ThreadingHTTPServer`` is sufficient because pages are server-rendered GETs
over short SQLite reads. It adds no framework/runtime surface, and each request
uses an independent read-only connection so a slow browser cannot block other
local tabs.
"""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import re
import secrets
import sqlite3
from dataclasses import dataclass, field
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping
from urllib.parse import parse_qs, unquote, urlsplit

from aoms.anatomy import generate_anatomy_html
from aoms.contracts import MemoryKind, Scope
from aoms.observatory.evidence import receipt_context
from aoms.observatory.render import (
    contest_detail_page,
    contests_page,
    error_page,
    memories_page,
    memory_detail_page,
    receipt_inspector_page,
    receipts_page,
    timeline_page,
    truth_page,
)
from aoms.observatory.repository import InvalidCursor, ObservatoryRepository
from aoms.repositories import SQLiteMemoryRepository

LOOPBACK_HOST = "127.0.0.1"
TOKEN_QUERY_PARAMETER = "_aoms_token"
TOKEN_COOKIE_NAME = "AOMSObservatory"
DEFAULT_PAGE_SIZE = 50
DEFAULT_TIMELINE_SIZE = 80
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    body: bytes
    content_type: str = "text/html; charset=utf-8"
    headers: Mapping[str, str] = field(default_factory=dict)


def _one(parameters: dict[str, list[str]], name: str) -> str:
    values = parameters.get(name, [])
    return values[0].strip() if values else ""


class ObservatoryApplication:
    """Route GET requests without exposing any mutation method."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser().resolve()
        self.repository = ObservatoryRepository(self.db_path)

    @staticmethod
    def _html(status: int, value: str) -> Response:
        return Response(status=status, body=value.encode("utf-8"))

    def handle(self, method: str, target: str) -> Response:
        if method not in {"GET", "HEAD"}:
            return self._html(405, error_page(405, "Read-only: method not allowed"))
        parsed = urlsplit(target)
        path = parsed.path.rstrip("/") or "/"
        parameters = parse_qs(parsed.query, keep_blank_values=True)
        try:
            if path == "/":
                return Response(302, b"", headers={"Location": "/memories"})
            if path == "/memories":
                values = {
                    "q": _one(parameters, "q")[:500],
                    "kind": _one(parameters, "kind"),
                    "scope": _one(parameters, "scope"),
                    "source": _one(parameters, "source")[:500],
                }
                kind = MemoryKind(values["kind"]) if values["kind"] else None
                scope = Scope(values["scope"]) if values["scope"] else None
                page = self.repository.memories(
                    query=values["q"],
                    kind=kind,
                    scope=scope,
                    source=values["source"] or None,
                    cursor=_one(parameters, "cursor") or None,
                    limit=DEFAULT_PAGE_SIZE,
                )
                return self._html(200, memories_page(page, parameters=values))
            if path == "/timeline":
                page = self.repository.timeline(
                    cursor=_one(parameters, "cursor") or None,
                    limit=DEFAULT_TIMELINE_SIZE,
                )
                return self._html(
                    200,
                    timeline_page(page, cursor=_one(parameters, "cursor") or None),
                )
            if path == "/truth":
                return self._html(
                    200,
                    truth_page(
                        self.repository.chain_health(),
                        contest_counts=self.repository.contest_counts(),
                    ),
                )
            if path == "/contests":
                offset = _one(parameters, "offset")
                page = self.repository.contests(
                    limit=DEFAULT_PAGE_SIZE,
                    offset=int(offset) if offset.isdigit() else 0,
                )
                return self._html(
                    200,
                    contests_page(page, counts=self.repository.contest_counts()),
                )
            if path == "/receipts":
                page = self.repository.receipts(
                    cursor=_one(parameters, "cursor") or None,
                    limit=DEFAULT_PAGE_SIZE,
                )
                return self._html(200, receipts_page(page))
            if path.startswith("/contests/"):
                contest_id = unquote(path.removeprefix("/contests/"))
                entry = self.repository.contest(contest_id)
                if entry is None:
                    return self._html(404, error_page(404, "Contest not found"))
                challenger = self.repository.memory(entry.record_id)
                incumbents = self.repository.memories_by_id(entry.incumbent_ids)
                return self._html(
                    200,
                    contest_detail_page(
                        entry,
                        challenger=challenger,
                        incumbents=[
                            incumbents[record_id]
                            for record_id in entry.incumbent_ids
                            if record_id in incumbents
                        ],
                    ),
                )
            if path.startswith("/memories/"):
                record_id = unquote(path.removeprefix("/memories/"))
                record = self.repository.memory(record_id)
                if record is None:
                    return self._html(404, error_page(404, "Memory not found"))
                chain = self.repository.supersession_chain(record_id)
                timeline = self.repository.truth_timeline(record_id)
                return self._html(200, memory_detail_page(record, chain, timeline))
            if path.startswith("/receipts/") and path.endswith("/export"):
                receipt_id = unquote(
                    path.removeprefix("/receipts/").removesuffix("/export").rstrip("/")
                )
                return self._export(receipt_id)
            if path.startswith("/receipts/"):
                receipt_id = unquote(path.removeprefix("/receipts/"))
                receipt = self.repository.receipt(receipt_id)
                if receipt is None:
                    return self._html(404, error_page(404, "Receipt not found"))
                ids = [item.memory_id for item in receipt.selected]
                ids.extend(receipt.superseded_suppressed)
                records = self.repository.memories_by_id(ids)
                chains = {
                    record_id: self.repository.predecessor_chain(record)
                    for record_id, record in records.items()
                    if record_id in {item.memory_id for item in receipt.selected}
                }
                context = receipt_context(receipt, self.repository)
                return self._html(
                    200,
                    receipt_inspector_page(
                        receipt, records=records, chains=chains, context=context
                    ),
                )
            return self._html(404, error_page(404, "Page not found"))
        except (InvalidCursor, ValueError) as exc:
            return self._html(400, error_page(400, str(exc)))
        except sqlite3.Error:
            return self._html(503, error_page(503, "SQLite read temporarily unavailable"))

    def _export(self, receipt_id: str) -> Response:
        receipt = self.repository.receipt(receipt_id)
        if receipt is None:
            return self._html(404, error_page(404, "Receipt not found"))
        store = SQLiteMemoryRepository(self.db_path, read_only=True)
        report = asyncio.run(
            generate_anatomy_html(receipt, store, label="Recall Observatory export")
        )
        safe_id = _SAFE_FILENAME.sub("-", receipt_id).strip("-") or "receipt"
        return Response(
            200,
            report.encode("utf-8"),
            headers={
                "Content-Disposition": f'attachment; filename="aoms-{safe_id}.html"'
            },
        )


class ObservatoryRequestHandler(BaseHTTPRequestHandler):
    """HTTP translation only; all routing lives in ``ObservatoryApplication``."""

    server_version = "AOMSObservatory/1"

    @property
    def application(self) -> ObservatoryApplication:
        return self.server.application  # type: ignore[attr-defined,no-any-return]

    @property
    def observatory_server(self) -> ObservatoryHTTPServer:
        return self.server  # type: ignore[return-value]

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._dispatch("GET", include_body=True)

    def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._dispatch("HEAD", include_body=False)

    def do_POST(self) -> None:  # noqa: N802 - explicit read-only posture
        self._dispatch("POST", include_body=True)

    def _dispatch(self, method: str, *, include_body: bool) -> None:
        rejection = self._security_rejection()
        if rejection is not None:
            self._respond(rejection, include_body=include_body)
            return
        response = self.application.handle(method, self.path)
        if self._query_token_is_valid():
            headers = dict(response.headers)
            headers["Set-Cookie"] = (
                f"{TOKEN_COOKIE_NAME}={self.observatory_server.url_token}; "
                "Path=/; HttpOnly; SameSite=Strict"
            )
            response = Response(
                status=response.status,
                body=response.body,
                content_type=response.content_type,
                headers=headers,
            )
        self._respond(response, include_body=include_body)

    def _security_rejection(self) -> Response | None:
        port = self.observatory_server.server_port
        if not _valid_loopback_host(self.headers.get("Host", ""), port=port):
            return self.application._html(403, error_page(403, "Forbidden request"))
        origin = self.headers.get("Origin")
        if origin is not None and not _valid_loopback_origin(origin, port=port):
            return self.application._html(403, error_page(403, "Forbidden request"))
        if not (self._query_token_is_valid() or self._cookie_token_is_valid()):
            return self.application._html(403, error_page(403, "Forbidden request"))
        return None

    def _query_token_is_valid(self) -> bool:
        values = parse_qs(urlsplit(self.path).query).get(TOKEN_QUERY_PARAMETER, [])
        return any(
            hmac.compare_digest(value, self.observatory_server.url_token)
            for value in values
        )

    def _cookie_token_is_valid(self) -> bool:
        raw_cookie = self.headers.get("Cookie", "")
        if not raw_cookie:
            return False
        cookie = SimpleCookie()
        try:
            cookie.load(raw_cookie)
        except CookieError:
            return False
        morsel = cookie.get(TOKEN_COOKIE_NAME)
        return bool(
            morsel
            and hmac.compare_digest(
                morsel.value,
                self.observatory_server.url_token,
            )
        )

    def _respond(self, response: Response, *, include_body: bool) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
        )
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.end_headers()
        if include_body:
            self.wfile.write(response.body)

    def log_message(self, format: str, *args: object) -> None:
        # Preserve local access logs without writing the URL bootstrap token.
        redacted = tuple(
            re.sub(
                rf"([?&]{TOKEN_QUERY_PARAMETER}=)[^& ]+",
                r"\1[REDACTED]",
                str(value),
            )
            for value in args
        )
        super().log_message(format, *redacted)


def _loopback_hostname(value: str) -> bool:
    if value.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _valid_loopback_host(value: str, *, port: int) -> bool:
    try:
        parsed = urlsplit(f"//{value}")
        request_port = parsed.port or 80
    except ValueError:
        return False
    return bool(
        parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and not parsed.path
        and _loopback_hostname(parsed.hostname)
        and request_port == port
    )


def _valid_loopback_origin(value: str, *, port: int) -> bool:
    try:
        parsed = urlsplit(value)
        origin_port = parsed.port or (80 if parsed.scheme == "http" else 443)
    except ValueError:
        return False
    return bool(
        parsed.scheme == "http"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
        and _loopback_hostname(parsed.hostname)
        and origin_port == port
    )


class ObservatoryHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        application: ObservatoryApplication,
        *,
        url_token: str | None = None,
    ):
        self.application = application
        self.url_token = url_token or secrets.token_urlsafe(32)
        super().__init__(address, ObservatoryRequestHandler)


def serve(db_path: str | Path, *, port: int = 8765) -> None:
    """Serve forever on IPv4 loopback; no external bind option is exposed."""

    application = ObservatoryApplication(db_path)
    with ObservatoryHTTPServer((LOOPBACK_HOST, port), application) as server:
        print(
            "Recall Observatory: "
            f"http://{LOOPBACK_HOST}:{server.server_port}/"
            f"?{TOKEN_QUERY_PARAMETER}={server.url_token}"
        )
        print(f"Read-only store: {application.db_path}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


__all__ = [
    "LOOPBACK_HOST",
    "TOKEN_QUERY_PARAMETER",
    "ObservatoryApplication",
    "ObservatoryHTTPServer",
    "Response",
    "serve",
]
