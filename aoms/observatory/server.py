"""Small stdlib HTTP adapter for the loopback Recall Observatory.

``ThreadingHTTPServer`` is sufficient because pages are server-rendered GETs
over short SQLite reads. It adds no framework/runtime surface, and each request
uses an independent read-only connection so a slow browser cannot block other
local tabs.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping
from urllib.parse import parse_qs, unquote, urlsplit

from aoms.anatomy import generate_anatomy_html
from aoms.contracts import MemoryKind, Scope
from aoms.observatory.evidence import receipt_context
from aoms.observatory.render import (
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
                return self._html(200, truth_page(self.repository.chain_health()))
            if path == "/receipts":
                page = self.repository.receipts(
                    cursor=_one(parameters, "cursor") or None,
                    limit=DEFAULT_PAGE_SIZE,
                )
                return self._html(200, receipts_page(page))
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

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._respond(self.application.handle("GET", self.path), include_body=True)

    def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._respond(self.application.handle("HEAD", self.path), include_body=False)

    def do_POST(self) -> None:  # noqa: N802 - explicit read-only posture
        self._respond(self.application.handle("POST", self.path), include_body=True)

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
        # Preserve useful local access logs without reverse DNS or request bodies.
        super().log_message(format, *args)


class ObservatoryHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], application: ObservatoryApplication):
        self.application = application
        super().__init__(address, ObservatoryRequestHandler)


def serve(db_path: str | Path, *, port: int = 8765) -> None:
    """Serve forever on IPv4 loopback; no external bind option is exposed."""

    application = ObservatoryApplication(db_path)
    with ObservatoryHTTPServer((LOOPBACK_HOST, port), application) as server:
        print(f"Recall Observatory: http://{LOOPBACK_HOST}:{server.server_port}")
        print(f"Read-only store: {application.db_path}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


__all__ = [
    "LOOPBACK_HOST",
    "ObservatoryApplication",
    "ObservatoryHTTPServer",
    "Response",
    "serve",
]
