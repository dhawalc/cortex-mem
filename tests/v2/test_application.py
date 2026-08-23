from pathlib import Path

import pytest

from aoms.application import AOMSApplication
from aoms.contracts import (
    MemoryKind,
    RecallRequest,
    RememberRequest,
    Scope,
    SearchRequest,
)
from aoms.repositories import SQLiteMemoryRepository


@pytest.mark.asyncio
async def test_remember_and_search_share_repository(tmp_path: Path) -> None:
    app = AOMSApplication(SQLiteMemoryRepository(tmp_path / "aoms.sqlite3"))
    request = RememberRequest(
        id="stable-id",
        kind=MemoryKind.FACT,
        content="A synthetic marmalade deployment fact",
        tags=["deployment"],
        scope=Scope.WORKSPACE,
    )

    created = await app.remember(request)
    updated = await app.remember(request.model_copy(update={"content": "Marmalade was updated"}))
    results = await app.search(SearchRequest(query="marmalade"))

    assert created.created is True
    assert updated.created is False
    assert updated.record.created_at == created.record.created_at
    assert results.total == 1
    assert results.items[0].record.content == "Marmalade was updated"


@pytest.mark.asyncio
async def test_recall_emits_an_empty_receipt_for_an_empty_store(tmp_path: Path) -> None:
    app = AOMSApplication(SQLiteMemoryRepository(tmp_path / "aoms.sqlite3"))

    result = await app.recall(RecallRequest(task="Pack context", token_budget=100))
    receipts = await app.recent_recall_receipts()

    assert result.context == ""
    assert result.sources == []
    assert result.token_count == 0
    assert len(receipts) == 1
    assert receipts[0].receipt_id == result.diagnostics["receipt_id"]
