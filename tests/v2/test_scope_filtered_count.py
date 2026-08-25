"""The scope-filtered count: same answer as before, one query, bounded.

It used to be two unbounded ``COUNT(*)`` queries subtracted, both walking the
whole FTS match set. On a 165k-record store that was 320 ms of an 827 ms
recall. Counting the difference directly has to give the same number — the
subtraction had NULL semantics that a naive ``NOT (...)`` would quietly change
— so the old shape is kept here as the oracle.
"""

from __future__ import annotations

import itertools
import sqlite3
from datetime import datetime, timezone

import pytest

from aoms.contracts import (
    MemoryKind,
    MemoryRecord,
    Provenance,
    RecallRequest,
    Scope,
    ScopeContext,
)
from aoms.repositories import SQLiteMemoryRepository
from aoms.repositories.sqlite import (
    DEFAULT_SCOPE_FILTERED_COUNT_CAP,
    LATEST_SCHEMA_VERSION,
    ScopeFilteredCount,
)

NOW = datetime(2026, 5, 1, tzinfo=timezone.utc)
TASK = "shared deployment token budget record"

# scope, workspace id, agent id — including rows whose scope columns are NULL,
# which is where the subtraction and a plain negation disagree.
SCOPE_MIX = [
    (Scope.USER_GLOBAL, None, None),
    (Scope.WORKSPACE, "ws-a", None),
    (Scope.WORKSPACE, "ws-b", None),
    (Scope.WORKSPACE, None, None),
    (Scope.AGENT_PRIVATE, None, "agent-a"),
    (Scope.AGENT_PRIVATE, None, "agent-b"),
    (Scope.AGENT_PRIVATE, None, None),
]


def _subtraction_oracle(repository, connection, expression, request, scope_context):
    """The previous implementation, verbatim: count all, count visible, subtract."""

    include_contested = getattr(request, "include_contested", False)
    unscoped_clauses, unscoped_parameters = repository._filters(
        kinds=request.kinds,
        scopes=request.scopes,
        table_alias="m.",
        include_contested=include_contested,
    )
    unscoped_clauses.insert(0, "memories_fts MATCH ?")
    unscoped_parameters.insert(0, expression)
    unscoped = connection.execute(
        "SELECT COUNT(*) AS count FROM memories_fts "
        "JOIN memories AS m ON m.id = memories_fts.id "
        f"WHERE {' AND '.join(unscoped_clauses)}",
        unscoped_parameters,
    ).fetchone()["count"]

    scoped_clauses, scoped_parameters = repository._filters(
        kinds=request.kinds,
        scopes=request.scopes,
        table_alias="m.",
        scope_context=scope_context,
        include_contested=include_contested,
    )
    scoped_clauses.insert(0, "memories_fts MATCH ?")
    scoped_parameters.insert(0, expression)
    scoped = connection.execute(
        "SELECT COUNT(*) AS count FROM memories_fts "
        "JOIN memories AS m ON m.id = memories_fts.id "
        f"WHERE {' AND '.join(scoped_clauses)}",
        scoped_parameters,
    ).fetchone()["count"]
    return max(0, int(unscoped) - int(scoped))


async def _populated(tmp_path):
    repository = SQLiteMemoryRepository(tmp_path / "aoms.sqlite3")
    await repository.initialize()
    records = [
        MemoryRecord(
            id=f"r{index}-{copy}",
            kind=MemoryKind.FACT,
            scope=scope,
            content=f"{TASK} {index} {copy}",
            tags=[],
            provenance=Provenance(source="test"),
            created_at=NOW,
            updated_at=NOW,
            scope_agent_id=agent_id,
            scope_workspace_id=workspace_id,
        )
        for index, (scope, workspace_id, agent_id) in enumerate(SCOPE_MIX)
        for copy in range(3)
    ]
    await repository.store_many(records)

    # Force the NULL scope columns the constructor will not produce.
    with sqlite3.connect(tmp_path / "aoms.sqlite3") as connection:
        connection.execute(
            "UPDATE memories SET scope_workspace_id = NULL WHERE id LIKE 'r3-%'"
        )
        connection.execute(
            "UPDATE memories SET scope_agent_id = NULL WHERE id LIKE 'r6-%'"
        )
        connection.commit()
    return repository


@pytest.mark.asyncio
async def test_one_query_gives_exactly_what_the_subtraction_gave(tmp_path) -> None:
    repository = await _populated(tmp_path)
    contexts = [
        ScopeContext(agent_id=agent, workspace_id=workspace)
        for agent, workspace in itertools.product(
            ["agent-a", "agent-b", "agent-z"], ["ws-a", "ws-b", "ws-z"]
        )
    ]
    kind_filters = [None, [MemoryKind.FACT]]
    scope_filters = [None, [Scope.WORKSPACE], [Scope.USER_GLOBAL, Scope.AGENT_PRIVATE]]

    checked = 0
    for context, kinds, scopes in itertools.product(
        contexts, kind_filters, scope_filters
    ):
        request = RecallRequest(
            task=TASK, token_budget=500, kinds=kinds, scopes=scopes
        )
        expression = repository._recall_fts_expression(request.task)
        with repository._connect() as connection:
            actual = repository._scope_filtered_fts_count(
                connection, expression, request, context
            )
            expected = _subtraction_oracle(
                repository, connection, expression, request, context
            )
        assert actual == ScopeFilteredCount(count=expected, capped=False), (
            f"context={context.agent_id}/{context.workspace_id} "
            f"kinds={kinds} scopes={scopes}"
        )
        checked += 1

    # A green run over an empty product would prove nothing.
    assert checked == len(contexts) * len(kind_filters) * len(scope_filters)


@pytest.mark.asyncio
async def test_a_saturated_count_is_a_floor_and_says_so(tmp_path) -> None:
    repository = await _populated(tmp_path)
    context = ScopeContext(agent_id="agent-z", workspace_id="ws-z")
    request = RecallRequest(task=TASK, token_budget=500)
    expression = repository._recall_fts_expression(request.task)

    with repository._connect() as connection:
        exact = repository._scope_filtered_fts_count(
            connection, expression, request, context
        )
        repository.scope_filtered_count_cap = 2
        capped = repository._scope_filtered_fts_count(
            connection, expression, request, context
        )

    assert exact.capped is False
    assert exact.count > 2
    assert capped == ScopeFilteredCount(count=2, capped=True)


@pytest.mark.asyncio
async def test_no_scope_context_means_nothing_was_filtered(tmp_path) -> None:
    repository = await _populated(tmp_path)
    request = RecallRequest(task=TASK, token_budget=500)
    expression = repository._recall_fts_expression(request.task)
    with repository._connect() as connection:
        assert repository._scope_filtered_fts_count(
            connection, expression, request, None
        ) == ScopeFilteredCount(count=0, capped=False)


@pytest.mark.asyncio
async def test_the_candidate_batch_and_receipt_carry_the_bound(tmp_path) -> None:
    """A truncated count must not reach a receipt looking like a total."""

    repository = await _populated(tmp_path)
    context = ScopeContext(agent_id="agent-z", workspace_id="ws-z")
    request = RecallRequest(task=TASK, token_budget=500)

    batch = await repository.retrieve_recall_candidates(
        request, limit=10, query_vector=None, vector_profile=None, scope_context=context
    )
    assert batch.scope_filtered_count > 0
    assert batch.scope_filtered_count_capped is False

    repository.scope_filtered_count_cap = 1
    bounded = await repository.retrieve_recall_candidates(
        request, limit=10, query_vector=None, vector_profile=None, scope_context=context
    )
    assert bounded.scope_filtered_count == 1
    assert bounded.scope_filtered_count_capped is True


def test_the_cap_must_be_positive(tmp_path) -> None:
    with pytest.raises(ValueError, match="scope_filtered_count_cap"):
        SQLiteMemoryRepository(tmp_path / "aoms.sqlite3", scope_filtered_count_cap=0)


@pytest.mark.asyncio
async def test_the_covering_index_is_created_and_used(tmp_path) -> None:
    """Migration 8 exists to keep the count out of the record_json rows."""

    repository = await _populated(tmp_path)
    with repository._connect() as connection:
        version = connection.execute(
            "SELECT MAX(version) AS version FROM schema_version"
        ).fetchone()["version"]
        assert version == LATEST_SCHEMA_VERSION

        indexes = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' "
                "AND tbl_name = 'memories'"
            )
        }
        assert "idx_memories_scope_cover" in indexes

        request = RecallRequest(task=TASK, token_budget=500)
        expression = repository._recall_fts_expression(request.task)
        context = ScopeContext(agent_id="agent-z", workspace_id="ws-z")
        clauses, parameters = repository._filters(
            kinds=None, scopes=None, table_alias="m."
        )
        clauses.insert(0, "memories_fts MATCH ?")
        parameters.insert(0, expression)
        access, access_parameters = repository._scope_access_filter(
            context, table_alias="m."
        )
        clauses.append(f"{access[0]} IS NOT 1")
        parameters.extend(access_parameters)
        plan = " ".join(
            str(row[3])
            for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT COUNT(*) FROM (SELECT 1 FROM memories_fts "
                "JOIN memories AS m ON m.id = memories_fts.id "
                f"WHERE {' AND '.join(clauses)} LIMIT ?)",
                [*parameters, DEFAULT_SCOPE_FILTERED_COUNT_CAP],
            )
        )
    assert "COVERING INDEX idx_memories_scope_cover" in plan, plan
