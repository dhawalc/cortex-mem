from __future__ import annotations

from pathlib import Path
from collections.abc import Sequence

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
from aoms.embeddings import EmbeddingProfile, EmbeddingVector, NullProvider
from aoms.repositories import SQLiteMemoryRepository

AGENT_A = ScopeContext(agent_id="agent-a", workspace_id="workspace-one")
AGENT_B = ScopeContext(agent_id="agent-b", workspace_id="workspace-one")
AGENT_C = ScopeContext(agent_id="agent-c", workspace_id="workspace-two")


class SameVectorProvider:
    profile = EmbeddingProfile("fixture", "scope-canary", 2)

    async def embed_documents(
        self, texts: Sequence[str]
    ) -> list[EmbeddingVector | None]:
        return [[1.0, 0.0] for _ in texts]

    async def embed_query(self, text: str) -> EmbeddingVector | None:
        return [1.0, 0.0]


def application(
    repository: SQLiteMemoryRepository, context: ScopeContext
) -> AOMSApplication:
    return AOMSApplication(
        repository,
        scope_context=context,
        embedding_provider=NullProvider(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", list(Scope))
async def test_writes_stamp_constructor_bound_scope_and_agent_provenance(
    tmp_path: Path, scope: Scope
) -> None:
    repository = SQLiteMemoryRepository(tmp_path / f"{scope.value}.sqlite3")

    result = await application(repository, AGENT_A).remember(
        RememberRequest(
            id=f"written-{scope.value}",
            kind=MemoryKind.FACT,
            content=f"scope write {scope.value}",
            scope=scope,
        )
    )

    record = result.record
    assert record.created_by_agent_id == AGENT_A.agent_id
    assert record.scope_agent_id == (
        AGENT_A.agent_id if scope is Scope.AGENT_PRIVATE else None
    )
    assert record.scope_workspace_id == (
        AGENT_A.workspace_id if scope is Scope.WORKSPACE else None
    )
    assert record.provenance.details["agent_id"] == AGENT_A.agent_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "reader", "visible"),
    [
        (Scope.AGENT_PRIVATE, AGENT_A, True),
        (Scope.AGENT_PRIVATE, AGENT_B, False),
        (Scope.AGENT_PRIVATE, AGENT_C, False),
        (Scope.WORKSPACE, AGENT_A, True),
        (Scope.WORKSPACE, AGENT_B, True),
        (Scope.WORKSPACE, AGENT_C, False),
        (Scope.USER_GLOBAL, AGENT_A, True),
        (Scope.USER_GLOBAL, AGENT_B, True),
        (Scope.USER_GLOBAL, AGENT_C, True),
    ],
)
async def test_scope_read_visibility_matrix(
    tmp_path: Path,
    scope: Scope,
    reader: ScopeContext,
    visible: bool,
) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "matrix.sqlite3")
    record_id = f"matrix-{scope.value}"
    await application(repository, AGENT_A).remember(
        RememberRequest(
            id=record_id,
            kind=MemoryKind.FACT,
            content=f"matrixword {scope.value}",
            scope=scope,
        )
    )

    result = await application(repository, reader).search(
        SearchRequest(query="matrixword", scopes=[scope])
    )

    assert (record_id in {item.record.id for item in result.items}) is visible


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "writer", "allowed"),
    [
        (Scope.AGENT_PRIVATE, AGENT_A, True),
        (Scope.AGENT_PRIVATE, AGENT_B, False),
        (Scope.AGENT_PRIVATE, AGENT_C, False),
        (Scope.WORKSPACE, AGENT_A, True),
        (Scope.WORKSPACE, AGENT_B, True),
        (Scope.WORKSPACE, AGENT_C, False),
        (Scope.USER_GLOBAL, AGENT_A, True),
        (Scope.USER_GLOBAL, AGENT_B, True),
        (Scope.USER_GLOBAL, AGENT_C, True),
    ],
)
async def test_scope_existing_id_access_and_guard_matrix(
    tmp_path: Path,
    scope: Scope,
    writer: ScopeContext,
    allowed: bool,
) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "updates.sqlite3")
    record_id = f"update-{scope.value}"
    owner = application(repository, AGENT_A)
    await owner.remember(
        RememberRequest(
            id=record_id,
            kind=MemoryKind.FACT,
            content="original matrix update",
            scope=scope,
        )
    )
    request = RememberRequest(
        id=record_id,
        kind=MemoryKind.FACT,
        content="changed matrix update",
        scope=scope,
    )

    if allowed:
        with pytest.raises(
            ValueError,
            match=(
                r"in-place content change; append a successor with `supersedes` "
                r"instead"
            ),
        ):
            await application(repository, writer).remember(request)
        retried = await application(repository, writer).remember(
            request.model_copy(update={"content": "original matrix update"})
        )
        assert retried.created is False
        assert retried.record.created_by_agent_id == AGENT_A.agent_id
        assert retried.record.content == "original matrix update"
    else:
        with pytest.raises(PermissionError, match="inaccessible scope"):
            await application(repository, writer).remember(request)


@pytest.mark.asyncio
async def test_foreign_private_canary_never_reaches_search_recall_or_receipt(
    tmp_path: Path,
) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "canary.sqlite3")
    foreign = application(repository, AGENT_B)
    await foreign.remember(
        RememberRequest(
            id="foreign-canary-id",
            kind=MemoryKind.FACT,
            content="FOREIGN_CANARY_SECRET omega-zanzibar",
            scope=Scope.AGENT_PRIVATE,
        )
    )
    own = application(repository, AGENT_A)

    search = await own.search(
        SearchRequest(query="omega zanzibar", scopes=[Scope.AGENT_PRIVATE])
    )
    recalled = await own.recall(
        RecallRequest(
            task="omega zanzibar",
            token_budget=1_000,
            scopes=[Scope.AGENT_PRIVATE],
        )
    )
    receipt = (await own.recent_recall_receipts(limit=1))[0]

    assert search.items == []
    assert search.diagnostics["scope_filtered_count"] == 1
    assert recalled.sources == []
    assert "FOREIGN_CANARY_SECRET" not in recalled.context
    assert "foreign-canary-id" not in recalled.context
    assert recalled.diagnostics["scope_filtered_count"] == 1
    assert receipt.scope_filtered_count == 1
    serialized_receipt = receipt.model_dump_json()
    assert "FOREIGN_CANARY_SECRET" not in serialized_receipt
    assert "foreign-canary-id" not in serialized_receipt


@pytest.mark.asyncio
async def test_recent_receipts_are_private_to_the_bound_agent(tmp_path: Path) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "receipts.sqlite3")
    app_a = application(repository, AGENT_A)
    app_b = application(repository, AGENT_B)

    await app_a.recall(RecallRequest(task="agent alpha receipt"))
    await app_b.recall(RecallRequest(task="agent beta receipt"))

    assert [item.query for item in await app_a.recent_recall_receipts()] == [
        "agent alpha receipt"
    ]
    assert [item.query for item in await app_b.recent_recall_receipts()] == [
        "agent beta receipt"
    ]


@pytest.mark.asyncio
async def test_foreign_private_canary_is_excluded_from_vector_recall(
    tmp_path: Path,
) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "vector-canary.sqlite3")
    provider = SameVectorProvider()
    foreign = AOMSApplication(
        repository,
        scope_context=AGENT_B,
        embedding_provider=provider,
        background_embeddings=False,
    )
    await foreign.remember(
        RememberRequest(
            id="foreign-vector-canary",
            kind=MemoryKind.FACT,
            content="FOREIGN_VECTOR_SECRET",
            scope=Scope.AGENT_PRIVATE,
        )
    )
    await foreign.catch_up_embeddings()
    own = AOMSApplication(
        repository,
        scope_context=AGENT_A,
        embedding_provider=provider,
        background_embeddings=False,
    )

    recalled = await own.recall(
        RecallRequest(task="semantic only query", token_budget=1_000)
    )
    receipt = (await own.recent_recall_receipts(limit=1))[0]

    assert recalled.sources == []
    assert "FOREIGN_VECTOR_SECRET" not in recalled.context
    assert "foreign-vector-canary" not in receipt.model_dump_json()
