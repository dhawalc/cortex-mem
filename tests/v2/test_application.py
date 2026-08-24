from pathlib import Path

import pytest

from aoms.application import AOMSApplication
from aoms.contracts import (
    MemoryKind,
    RecallRequest,
    RememberRequest,
    Scope,
    ScopeContext,
    SearchRequest,
)
from aoms.embeddings import NullProvider
from aoms.repositories import SQLiteMemoryRepository

CONTEXT = ScopeContext(agent_id="test-agent", workspace_id="test-workspace")


@pytest.mark.asyncio
async def test_remember_and_search_share_repository(tmp_path: Path) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "aoms.sqlite3")
    app = AOMSApplication(
        repository,
        scope_context=CONTEXT,
        embedding_provider=NullProvider(),
    )
    request = RememberRequest(
        id="stable-id",
        kind=MemoryKind.FACT,
        content="A synthetic marmalade deployment fact",
        tags=["deployment"],
        scope=Scope.WORKSPACE,
    )

    created = await app.remember(request)
    stored_before = await repository.get("stable-id")
    with pytest.raises(
        ValueError,
        match=r"in-place content change; append a successor with `supersedes` instead",
    ):
        await app.remember(
            request.model_copy(update={"content": "Marmalade was updated"})
        )
    retried = await app.remember(request)
    stored_after = await repository.get("stable-id")
    results = await app.search(SearchRequest(query="marmalade"))

    assert created.created is True
    assert retried.created is False
    assert retried.record == created.record
    assert stored_before == stored_after == created.record
    assert results.total == 1
    assert results.items[0].record.content == request.content


@pytest.mark.asyncio
async def test_recall_emits_an_empty_receipt_for_an_empty_store(tmp_path: Path) -> None:
    app = AOMSApplication(
        SQLiteMemoryRepository(tmp_path / "aoms.sqlite3"),
        scope_context=CONTEXT,
        embedding_provider=NullProvider(),
    )

    result = await app.recall(RecallRequest(task="Pack context", token_budget=100))
    receipts = await app.recent_recall_receipts()

    assert result.context == ""
    assert result.sources == []
    assert result.token_count == 0
    assert len(receipts) == 1
    assert receipts[0].receipt_id == result.diagnostics["receipt_id"]
