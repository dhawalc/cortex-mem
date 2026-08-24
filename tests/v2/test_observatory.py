from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import quote

import pytest
from click.testing import CliRunner

from aoms.application import AOMSApplication
from aoms.contracts import (
    MemoryKind,
    MemoryRecord,
    Provenance,
    RecallRequest,
    Scope,
    ScopeContext,
)
from aoms.embeddings import NullProvider
from aoms.observatory import cli as observatory_cli
from aoms.observatory.cli import observe_command
from aoms.observatory.repository import ObservatoryRepository
from aoms.observatory.server import (
    LOOPBACK_HOST,
    ObservatoryApplication,
    ObservatoryHTTPServer,
)
from aoms.receipts import RecallReceipt
from aoms.repositories import SQLiteMemoryRepository

NOW = datetime(2026, 8, 23, 18, 0, tzinfo=timezone.utc)
CONTEXT = ScopeContext(agent_id="observatory-agent", workspace_id="observatory-workspace")


def _record(
    index: int,
    *,
    content: str | None = None,
    supersedes: str | None = None,
) -> MemoryRecord:
    timestamp = NOW - timedelta(seconds=index)
    return MemoryRecord(
        id=f"memory-{index:04d}",
        kind=MemoryKind.FACT if index % 2 == 0 else MemoryKind.DECISION,
        content=content or f"pagination fixture observatory item {index}",
        tags=["observatory", f"batch-{index % 5}"],
        scope=Scope.WORKSPACE,
        scope_workspace_id=CONTEXT.workspace_id,
        created_by_agent_id=CONTEXT.agent_id,
        provenance=Provenance(source=f"fixture-{index % 3}.jsonl"),
        created_at=timestamp,
        updated_at=timestamp,
        supersedes=supersedes,
    )


def _seed_receipt_fixture(db_path: Path) -> tuple[str, str]:
    async def arrange() -> tuple[str, str]:
        repository = SQLiteMemoryRepository(db_path)
        old = _record(1, content="orchid deployment used the red canary")
        current = _record(
            2,
            content="orchid deployment uses the blue canary and durable retries",
            supersedes=old.id,
        )
        await repository.store_many([old, current, *(_record(i) for i in range(3, 18))])
        application = AOMSApplication(
            repository,
            scope_context=CONTEXT,
            embedding_provider=NullProvider(),
        )
        result = await application.recall(
            RecallRequest(task="orchid deployment canary", token_budget=900)
        )
        return str(result.diagnostics["receipt_id"]), old.id

    return asyncio.run(arrange())


def test_endpoint_smoke_and_loopback_http_adapter(tmp_path: Path) -> None:
    db_path = tmp_path / "observatory.sqlite3"
    receipt_id, _ = _seed_receipt_fixture(db_path)
    application = ObservatoryApplication(db_path)

    for path, marker in (
        ("/memories", "Memories"),
        ("/memories/memory-0002", "Supersession chain"),
        ("/timeline", "Timeline"),
        ("/receipts", "Recall receipts"),
        (f"/receipts/{quote(receipt_id)}", "The receipt inspector"),
    ):
        response = application.handle("GET", path)
        assert response.status == 200
        assert marker.encode() in response.body

    predecessor = application.handle("GET", "/memories/memory-0001")
    assert b"successor" in predecessor.body
    assert b"memory-0002" in predecessor.body

    server = ObservatoryHTTPServer((LOOPBACK_HOST, 0), application)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert server.server_address[0] == "127.0.0.1"
        connection = HTTPConnection(LOOPBACK_HOST, server.server_port, timeout=3)
        connection.request("GET", "/memories")
        response = connection.getresponse()
        body = response.read()
        assert response.status == 200
        assert response.getheader("Content-Security-Policy")
        assert b"pagination fixture" in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_memory_search_and_keyset_pagination_are_complete(tmp_path: Path) -> None:
    db_path = tmp_path / "pages.sqlite3"

    async def arrange() -> None:
        repository = SQLiteMemoryRepository(db_path)
        await repository.store_many([_record(index) for index in range(125)])

    asyncio.run(arrange())
    repository = ObservatoryRepository(db_path)

    seen: list[str] = []
    cursor = None
    while True:
        page = repository.memories(cursor=cursor, limit=17)
        seen.extend(item.record.id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len(seen) == 125
    assert len(set(seen)) == 125
    assert seen == [f"memory-{index:04d}" for index in range(125)]

    search_seen: list[str] = []
    cursor = None
    while True:
        page = repository.memories(
            query="pagination fixture", cursor=cursor, limit=19
        )
        search_seen.extend(item.record.id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert set(search_seen) == set(seen)
    assert len(search_seen) == 125

    filtered = repository.memories(
        kind=MemoryKind.DECISION,
        scope=Scope.WORKSPACE,
        source="fixture-1.jsonl",
        limit=100,
    )
    assert filtered.items
    assert all(item.record.kind is MemoryKind.DECISION for item in filtered.items)
    assert all(item.record.scope is Scope.WORKSPACE for item in filtered.items)
    assert all(
        item.record.provenance.source == "fixture-1.jsonl" for item in filtered.items
    )


def test_receipt_keyset_pagination_is_complete(tmp_path: Path) -> None:
    db_path = tmp_path / "receipt-pages.sqlite3"

    async def arrange() -> None:
        repository = SQLiteMemoryRepository(db_path)
        await repository.initialize()
        for index in range(61):
            await repository.save_recall_receipt(
                RecallReceipt(
                    receipt_id=f"receipt-{index:03d}",
                    created_at=NOW - timedelta(seconds=index),
                    query=f"receipt pagination {index}",
                    scopes=None,
                    kinds=None,
                    token_budget=100,
                    candidate_count=0,
                    top_candidates=[],
                    rejected_sample=[],
                    selected=[],
                    context="",
                    total_tokens=0,
                    latency_ms=0,
                    engine_version="fixture",
                )
            )

    asyncio.run(arrange())
    repository = ObservatoryRepository(db_path)
    seen: list[str] = []
    cursor = None
    while True:
        page = repository.receipts(cursor=cursor, limit=13)
        seen.extend(receipt.receipt_id for receipt in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert seen == [f"receipt-{index:03d}" for index in range(61)]


def test_receipt_inspector_reconciles_real_context_and_static_export(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "receipt.sqlite3"
    receipt_id, old_id = _seed_receipt_fixture(db_path)
    repository = ObservatoryRepository(db_path)
    receipt = repository.receipt(receipt_id)
    assert receipt is not None
    assert receipt.context is not None
    assert sum(item.token_cost for item in receipt.selected) == receipt.total_tokens

    application = ObservatoryApplication(db_path)
    response = application.handle("GET", f"/receipts/{quote(receipt_id)}")
    html = response.body.decode()

    assert response.status == 200
    assert '<div class="inspector"' in html
    assert 'id="receipt-request"' in html
    assert 'id="selected-memory-cards"' in html
    assert 'id="receipt-evidence"' in html
    assert "Retrieved" in html and "Scope-filtered" in html
    assert "Superseded" in html and "Packed" in html
    assert "raw" in html and "weight" in html and "contribution" in html
    assert "Vector coverage" in html
    assert "Exact token arithmetic" in html
    assert html.count(f"<td>{receipt.total_tokens}</td><td>reconciled</td>") == 2
    assert old_id in html
    assert "superseded predecessor" in html
    assert "AOMS_MEMORY_START: UNTRUSTED" in html
    assert "immutable receipt evidence" in html

    exported = application.handle("GET", f"/receipts/{quote(receipt_id)}/export")
    assert exported.status == 200
    assert exported.headers["Content-Disposition"].endswith('.html"')
    assert b'<section id="context">' in exported.body
    assert b"AOMS_MEMORY_START: UNTRUSTED" in exported.body


def test_observatory_has_no_write_path_and_connections_are_query_only(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "readonly.sqlite3"
    _seed_receipt_fixture(db_path)
    before = (db_path.stat().st_size, db_path.stat().st_mtime_ns)
    application = ObservatoryApplication(db_path)

    assert application.repository.read_only is True
    assert not any(
        hasattr(application.repository, name)
        for name in ("store", "store_many", "save_recall_receipt", "delete", "update")
    )
    with application.repository._connect() as connection:  # noqa: SLF001
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly|prohibited"):
            connection.execute("CREATE TABLE forbidden_write(value TEXT)")

    response = application.handle("POST", "/memories")
    assert response.status == 405
    assert b"Read-only" in response.body
    assert (db_path.stat().st_size, db_path.stat().st_mtime_ns) == before


def test_observe_cli_resolves_store_and_port(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    db_path = data_dir / "aoms.sqlite3"
    asyncio.run(SQLiteMemoryRepository(db_path).initialize())
    called: dict[str, object] = {}

    def fake_serve(path: Path, *, port: int) -> None:
        called.update(path=path, port=port)

    monkeypatch.setattr(observatory_cli, "serve", fake_serve)
    result = CliRunner().invoke(
        observe_command, ["--data-dir", str(data_dir), "--port", "9123"]
    )

    assert result.exit_code == 0, result.output
    assert called == {"path": db_path, "port": 9123}


def _seed_scale_database(db_path: Path, total: int = 150_000) -> None:
    asyncio.run(SQLiteMemoryRepository(db_path).initialize())
    base = datetime(2022, 1, 1, tzinfo=timezone.utc)
    with sqlite3.connect(db_path) as connection:
        for start in range(0, total, 5_000):
            memory_rows: list[tuple[object, ...]] = []
            fts_rows: list[tuple[str, str, str, str]] = []
            for index in range(start, min(start + 5_000, total)):
                timestamp = (base + timedelta(seconds=index)).isoformat()
                record_id = f"scale-{index:06d}"
                content = f"synthetic observatory record beacon{index}"
                payload = {
                    "id": record_id,
                    "kind": "fact",
                    "content": content,
                    "tags": ["scale"],
                    "scope": "workspace",
                    "scope_agent_id": None,
                    "scope_workspace_id": "scale-workspace",
                    "created_by_agent_id": "fixture-generator",
                    "provenance": {
                        "source": "synthetic-scale",
                        "tier": None,
                        "record_type": None,
                        "details": {},
                    },
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "supersedes": None,
                    "metadata": {},
                }
                memory_rows.append(
                    (
                        record_id,
                        "fact",
                        "workspace",
                        None,
                        "scale-workspace",
                        "fixture-generator",
                        timestamp,
                        timestamp,
                        json.dumps(payload, separators=(",", ":")),
                    )
                )
                fts_rows.append((record_id, content, "scale", "fact"))
            connection.executemany(
                "INSERT INTO memories(id,kind,scope,scope_agent_id,scope_workspace_id,"
                "created_by_agent_id,created_at,updated_at,record_json) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                memory_rows,
            )
            connection.executemany(
                "INSERT INTO memories_fts(id,content,tags,kind) VALUES (?,?,?,?)",
                fts_rows,
            )
            connection.commit()


def test_scale_150k_list_search_timeline_endpoints_under_500ms(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "scale.sqlite3"
    _seed_scale_database(db_path)
    application = ObservatoryApplication(db_path)
    measurements: dict[str, float] = {}

    for name, path in (
        ("list", "/memories"),
        ("search", "/memories?q=beacon149999"),
        ("timeline", "/timeline"),
    ):
        started = time.perf_counter()
        response = application.handle("GET", path)
        elapsed_ms = (time.perf_counter() - started) * 1_000
        measurements[name] = elapsed_ms
        assert response.status == 200
        assert elapsed_ms < 500, f"{name} took {elapsed_ms:.1f}ms"
        assert len(response.body) < 250_000

    print(
        "OBSERVATORY_150K_PERF "
        + " ".join(f"{name}={value:.2f}ms" for name, value in measurements.items())
    )
