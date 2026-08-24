from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from aoms.contracts import (
    MemoryKind,
    MemoryRecord,
    Provenance,
    RecallRequest,
    Scope,
    ScopeContext,
)
from aoms.embeddings import NullProvider
from aoms.portable import PortableExportError, export_bundle, restore_bundle
from aoms.recall import RecallEngine
from aoms.repositories.sqlite import SQLiteMemoryRepository

CONTEXT = ScopeContext(agent_id="portable-agent", workspace_id="portable-workspace")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.asyncio
async def test_export_restore_round_trip_includes_receipts_and_manifest_hashes(
    tmp_path: Path,
) -> None:
    source = SQLiteMemoryRepository(tmp_path / "source" / "aoms.sqlite3")
    timestamp = datetime.now(timezone.utc)
    records = [
        MemoryRecord(
            id="portable-1",
            kind=MemoryKind.FACT,
            content="Orchid portable export fact",
            tags=["portable"],
            scope=Scope.AGENT_PRIVATE,
            scope_agent_id=CONTEXT.agent_id,
            created_by_agent_id=CONTEXT.agent_id,
            provenance=Provenance(source="portable-test"),
            created_at=timestamp,
            updated_at=timestamp,
        ),
        MemoryRecord(
            id="portable-2",
            kind=MemoryKind.PROCEDURE,
            content={"step": "verify every hash"},
            scope=Scope.WORKSPACE,
            scope_workspace_id=CONTEXT.workspace_id,
            created_by_agent_id=CONTEXT.agent_id,
            provenance=Provenance(source="portable-test"),
            created_at=timestamp,
            updated_at=timestamp,
        ),
    ]
    await source.store_many(records)
    engine = RecallEngine(
        source,
        embedding_provider=NullProvider(),
        scope_context=CONTEXT,
    )
    await engine.recall(RecallRequest(task="orchid portable", token_budget=200))

    bundle = tmp_path / "bundle"
    exported = await export_bundle(source, bundle)
    manifest = json.loads((bundle / "manifest.json").read_text())

    assert exported.records == 2
    assert exported.receipts == 1
    assert manifest["format"] == "aoms-portable-export"
    assert manifest["format_version"] == 1
    assert manifest["files"]["records.jsonl"]["sha256"] == sha256(
        bundle / "records.jsonl"
    )
    assert manifest["files"]["receipts.jsonl"]["sha256"] == sha256(
        bundle / "receipts.jsonl"
    )

    target = SQLiteMemoryRepository(tmp_path / "target" / "aoms.sqlite3")
    restored = await restore_bundle(target, bundle)

    assert restored.records == 2
    assert restored.receipts == 1
    assert {item.id for item in await target.list()} == {"portable-1", "portable-2"}
    scoped = await target.get("portable-1")
    assert scoped is not None
    assert scoped.scope is Scope.AGENT_PRIVATE
    assert scoped.scope_agent_id == CONTEXT.agent_id
    assert scoped.created_by_agent_id == CONTEXT.agent_id
    receipts = await target.recent_recall_receipts(scope_context=CONTEXT)
    assert len(receipts) == 1
    assert receipts[0].agent_id == CONTEXT.agent_id
    assert receipts[0].workspace_id == CONTEXT.workspace_id


@pytest.mark.asyncio
async def test_restore_rejects_tampered_payload_before_creating_target(
    tmp_path: Path,
) -> None:
    source = SQLiteMemoryRepository(tmp_path / "source.sqlite3")
    await source.initialize()
    bundle = tmp_path / "bundle"
    await export_bundle(source, bundle)
    with (bundle / "records.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{}\n")

    target_path = tmp_path / "target" / "aoms.sqlite3"
    with pytest.raises(PortableExportError, match=r"hash mismatch for records\.jsonl"):
        await restore_bundle(SQLiteMemoryRepository(target_path), bundle)

    assert not target_path.exists()
