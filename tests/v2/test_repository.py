import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aoms.contracts import (
    MemoryKind,
    MemoryRecord,
    Provenance,
    Scope,
    SearchRequest,
)
from aoms.repositories.sqlite import LATEST_SCHEMA_VERSION, SQLiteMemoryRepository


def make_record(
    record_id: str,
    content: str,
    *,
    kind: MemoryKind = MemoryKind.FACT,
    scope: Scope = Scope.WORKSPACE,
    age_days: int = 0,
) -> MemoryRecord:
    timestamp = datetime.now(timezone.utc) - timedelta(days=age_days)
    return MemoryRecord(
        id=record_id,
        kind=kind,
        content=content,
        tags=["fixture", kind.value],
        scope=scope,
        provenance=Provenance(source="repository-test"),
        created_at=timestamp,
        updated_at=timestamp,
    )


@pytest.mark.asyncio
async def test_migrations_are_idempotent_and_enable_wal(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "aoms.sqlite3"
    repository = SQLiteMemoryRepository(db_path)

    await repository.initialize()
    await repository.initialize()
    await SQLiteMemoryRepository(db_path).initialize()

    assert await repository.schema_version() == LATEST_SCHEMA_VERSION
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert (
            connection.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
            == LATEST_SCHEMA_VERSION
        )


@pytest.mark.asyncio
async def test_store_get_upsert_and_list(tmp_path: Path) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "aoms.sqlite3")
    first = make_record("record-1", "Original synthetic content", age_days=1)
    second = make_record(
        "record-2",
        "Private synthetic procedure",
        kind=MemoryKind.PROCEDURE,
        scope=Scope.AGENT_PRIVATE,
    )

    assert await repository.store_many([]) == []
    assert await repository.store_many([first, second]) == [first, second]
    changed = first.model_copy(
        update={
            "content": "Updated synthetic content",
            "updated_at": datetime.now(timezone.utc),
        }
    )
    await repository.store(changed)

    assert await repository.get("missing") is None
    assert await repository.get("record-1") == changed
    assert len(await repository.list()) == 2
    assert await repository.list(kinds=[MemoryKind.PROCEDURE]) == [second]
    assert await repository.list(scopes=[Scope.AGENT_PRIVATE]) == [second]


@pytest.mark.asyncio
async def test_fts_keyword_search_and_filters(tmp_path: Path) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "aoms.sqlite3")
    await repository.store(make_record("fact", "Orchid launch checklist and telemetry"))
    await repository.store(
        make_record(
            "procedure",
            "Orchid launch runbook",
            kind=MemoryKind.PROCEDURE,
            scope=Scope.AGENT_PRIVATE,
        )
    )
    await repository.store(make_record("other", "Completely unrelated synthetic note"))

    all_results = await repository.search_by_keyword(SearchRequest(query="orchid launch"))
    filtered = await repository.search_by_keyword(
        SearchRequest(
            query="orchid",
            kinds=[MemoryKind.PROCEDURE],
            scopes=[Scope.AGENT_PRIVATE],
        )
    )
    empty = await repository.search_by_keyword(SearchRequest(query="---"))

    assert all_results.total == 2
    assert {item.record.id for item in all_results.items} == {"fact", "procedure"}
    assert filtered.total == 1
    assert filtered.items[0].record.id == "procedure"
    assert empty.items == []
    assert empty.diagnostics["reason"] == "query_has_no_tokens"
