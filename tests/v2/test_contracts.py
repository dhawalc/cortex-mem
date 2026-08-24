from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from aoms.contracts import (
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
    MemoryKind,
    MemoryRecord,
    Provenance,
    RecallResult,
    RecallSource,
    Scope,
)


def test_memory_record_json_round_trip() -> None:
    record = MemoryRecord(
        id="memory-1",
        kind=MemoryKind.FACT,
        content={"claim": "Synthetic stars are bright", "confidence": 0.9},
        tags=[" astronomy ", "test", "test", ""],
        scope=Scope.USER_GLOBAL,
        provenance=Provenance(source="fixture", tier="semantic", record_type="fact"),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        supersedes="memory-0",
        metadata={"synthetic": True},
    )

    restored = MemoryRecord.model_validate_json(record.model_dump_json())

    assert restored == record
    assert restored.tags == ["astronomy", "test"]
    assert restored.model_dump(mode="json")["kind"] == "fact"
    assert restored.model_dump(mode="json")["scope"] == "user-global"


def test_recall_result_and_typed_error_round_trip() -> None:
    provenance = Provenance(source="fixture", tier="episodic")
    result = RecallResult(
        context="Packed synthetic context",
        sources=[
            RecallSource(
                memory_id="memory-1",
                kind=MemoryKind.EPISODE,
                provenance=provenance,
                excerpt="Synthetic excerpt",
            )
        ],
        token_count=4,
        truncated=False,
        diagnostics={"packer": "test"},
    )
    error = ErrorResponse(
        error=ErrorDetail(code=ErrorCode.NOT_FOUND, message="Memory not found")
    )

    assert RecallResult.model_validate_json(result.model_dump_json()) == result
    assert ErrorResponse.model_validate_json(error.model_dump_json()) == error


def test_contracts_reject_free_form_kind_and_scope() -> None:
    with pytest.raises(ValidationError):
        MemoryRecord(
            id="memory-1",
            kind="note",
            content="text",
            scope="team",
            provenance=Provenance(source="fixture"),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
