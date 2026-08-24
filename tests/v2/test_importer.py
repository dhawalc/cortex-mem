from pathlib import Path

import pytest

from aoms.contracts import MemoryKind, ScopeContext
from aoms.importer import JSONLImporter
from aoms.repositories import SQLiteMemoryRepository

FIXTURE_CORPUS = Path(__file__).parent / "fixtures" / "corpus"
CONTEXT = ScopeContext(agent_id="import-agent", workspace_id="import-workspace")


@pytest.mark.asyncio
async def test_fixture_import_is_idempotent_and_preserves_legacy_fields(tmp_path: Path) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "aoms.sqlite3")
    importer = JSONLImporter(repository, scope_context=CONTEXT, batch_size=2)

    first = await importer.import_directory(FIXTURE_CORPUS)
    second = await importer.import_directory(FIXTURE_CORPUS)
    records = await repository.list(limit=100)

    assert first.records_seen == 5
    assert first.records_upserted == 5
    assert first.schema_headers_skipped == 4
    assert first.issues == []
    assert second.records_upserted == 5
    assert len(records) == 5

    by_id = {record.id: record for record in records}
    assert by_id["synthetic-experience-1"].kind is MemoryKind.EPISODE
    assert by_id["synthetic-fact-1"].kind is MemoryKind.FACT
    assert by_id["synthetic-entity-1"].kind is MemoryKind.ENTITY
    assert by_id["synthetic-skill-1"].kind is MemoryKind.PROCEDURE
    assert by_id["synthetic-pattern-1"].kind is MemoryKind.PATTERN
    assert by_id["synthetic-experience-1"].created_at.isoformat().startswith("2026-03-01")
    assert by_id["synthetic-experience-1"].provenance.source == (
        "episodic/experiences.jsonl"
    )
    assert by_id["synthetic-experience-1"].provenance.tier == "episodic"
    assert by_id["synthetic-experience-1"].content["source"] == "fixture:sensor"
    assert by_id["synthetic-experience-1"].metadata["legacy"]["weight"] == 1.0
    assert by_id["synthetic-experience-1"].scope_workspace_id == CONTEXT.workspace_id
    assert by_id["synthetic-experience-1"].created_by_agent_id == CONTEXT.agent_id
