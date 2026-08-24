import asyncio
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
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


def test_concurrent_first_writes_atomically_retain_exactly_one_content(
    tmp_path: Path,
) -> None:
    database = tmp_path / "concurrent.sqlite3"
    asyncio.run(SQLiteMemoryRepository(database).initialize())
    observed_absent = threading.Barrier(2)

    class RacingRepository(SQLiteMemoryRepository):
        async def get(self, record_id: str):  # type: ignore[no-untyped-def]
            existing = await super().get(record_id)
            if record_id == "contended-new-id" and existing is None:
                await asyncio.to_thread(observed_absent.wait, 10)
            return existing

    def remember(content: str):  # type: ignore[no-untyped-def]
        application = AOMSApplication(
            RacingRepository(database),
            scope_context=CONTEXT,
            embedding_provider=NullProvider(),
        )
        try:
            return asyncio.run(
                application.remember(
                    RememberRequest(
                        id="contended-new-id",
                        kind=MemoryKind.FACT,
                        content=content,
                    )
                )
            )
        except Exception as exc:  # returned for symmetric thread assertions
            return exc

    contents = ("synthetic contender alpha", "synthetic contender beta")
    # Separate event loops and repository connections create a real SQLite
    # race. WAL still permits only one writer; BEGIN IMMEDIATE plus the
    # 30-second busy timeout serializes the contenders instead of surfacing a
    # timing-dependent SQLITE_BUSY failure.
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(remember, contents))

    winners = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
    conflicts = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
    assert len(winners) == 1
    assert winners[0].created is True
    assert len(conflicts) == 1
    assert isinstance(conflicts[0], ValueError)
    assert "in-place content change" in str(conflicts[0])

    retained = asyncio.run(SQLiteMemoryRepository(database).get("contended-new-id"))
    assert retained is not None
    assert retained.content == winners[0].record.content
    assert retained.content in contents
    assert retained.updated_at == retained.created_at
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM memories WHERE id = 'contended-new-id'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM memories_fts WHERE id = 'contended-new-id'"
        ).fetchone()[0] == 1


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
