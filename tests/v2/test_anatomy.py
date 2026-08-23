from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest

from aoms.anatomy import generate_anatomy_html, main
from aoms.contracts import MemoryKind, MemoryRecord, Provenance, Scope
from aoms.receipts import (
    CandidateScore,
    RecallReceipt,
    ScoreComponent,
    SelectedMemory,
)
from aoms.repositories import SQLiteMemoryRepository

NOW = datetime(2026, 8, 23, 16, 30, tzinfo=timezone.utc)


class ReportParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.section_ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        attributes = dict(attrs)
        if tag == "section" and attributes.get("id"):
            self.section_ids.add(str(attributes["id"]))


def _component(raw: float, weight: float) -> ScoreComponent:
    return ScoreComponent(raw=raw, weight=weight, contribution=raw * weight)


def _candidate(
    memory_id: str, score: float, *, selected: bool, reason: str | None = None
) -> CandidateScore:
    return CandidateScore(
        memory_id=memory_id,
        kind=MemoryKind.FACT,
        scope=Scope.WORKSPACE,
        updated_at=NOW,
        retrieval_sources=["fts", "vector"],
        total_score=score,
        breakdown={
            "fts": _component(score, 0.4),
            "vector": _component(score, 0.35),
            "recency": _component(1.0, 0.15),
            "scope_specificity": _component(0.7, 0.1),
        },
        selected=selected,
        rejection_reason=reason,
    )


def _receipt(
    receipt_id: str = "receipt-primary", *, total_tokens: int = 100
) -> RecallReceipt:
    return RecallReceipt(
        receipt_id=receipt_id,
        created_at=NOW,
        agent_id="relay-implementer",
        workspace_id="relay-gauntlet",
        query="How should the durable relay preserve retries?",
        scopes=[Scope.WORKSPACE],
        kinds=[MemoryKind.FACT],
        token_budget=1_000,
        candidate_count=3,
        scope_filtered_count=2,
        top_candidates=[
            _candidate("constraint-current", 0.91, selected=True),
            _candidate("constraint-redaction", 0.84, selected=True),
            _candidate(
                "tempting-wrong", 0.41, selected=False, reason="token_budget"
            ),
        ],
        rejected_sample=[
            _candidate(
                "tempting-wrong", 0.41, selected=False, reason="token_budget"
            )
        ],
        selected=[
            SelectedMemory(
                memory_id="constraint-current", token_cost=61, truncated=False
            ),
            SelectedMemory(
                memory_id="constraint-redaction",
                token_cost=total_tokens - 61,
                truncated=True,
            ),
        ],
        total_tokens=total_tokens,
        latency_ms=12.345,
        engine_version="2.0.0",
        vector_coverage=2 / 3,
    )


async def _store_fixture(repository: SQLiteMemoryRepository) -> None:
    for record in (
        MemoryRecord(
            id="constraint-old",
            kind=MemoryKind.FACT,
            content="Original durable retry rule",
            scope=Scope.WORKSPACE,
            scope_workspace_id="relay-gauntlet",
            created_by_agent_id="relay-planner",
            provenance=Provenance(source="planner-notes", tier="raw"),
            created_at=NOW,
            updated_at=NOW,
        ),
        MemoryRecord(
            id="constraint-current",
            kind=MemoryKind.FACT,
            content="Persist event IDs before acknowledgement",
            scope=Scope.WORKSPACE,
            scope_workspace_id="relay-gauntlet",
            created_by_agent_id="relay-planner",
            provenance=Provenance(
                source="scenario.yaml",
                record_type="runtime-injected",
                details={"stage": 1},
            ),
            created_at=NOW,
            updated_at=NOW,
            supersedes="constraint-old",
        ),
        MemoryRecord(
            id="constraint-redaction",
            kind=MemoryKind.FACT,
            content="Recursively redact token keys",
            scope=Scope.WORKSPACE,
            scope_workspace_id="relay-gauntlet",
            created_by_agent_id="relay-planner",
            provenance=Provenance(source="scenario.yaml"),
            created_at=NOW,
            updated_at=NOW,
        ),
    ):
        await repository.store(record)


@pytest.mark.asyncio
async def test_anatomy_renders_receipt_numbers_and_reconciles_tokens(
    tmp_path: Path,
) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "anatomy.sqlite3")
    await _store_fixture(repository)

    report = await generate_anatomy_html(_receipt(), repository, label="full engine")
    parser = ReportParser()
    parser.feed(report)

    assert report.startswith("<!doctype html>")
    assert {"request", "funnel", "selected", "accounting", "contract"} <= parser.section_ids
    assert parser.tags.count("table") >= 2
    assert "Retrieved</span><strong>5" in report
    assert "Scope-visible &amp; scored</span><strong>3" in report
    assert "constraint-current" in report
    assert "constraint-old" in report
    assert "token_budget" in report
    assert "61" in report and "39" in report
    assert report.count("<td>100</td><td>reconciled</td>") == 2
    assert "12.35 ms" in report
    assert "Receipt contract</span><strong>v1" in report
    assert "https://" not in report


@pytest.mark.asyncio
async def test_anatomy_renders_labeled_ablation_comparison(tmp_path: Path) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "ablation.sqlite3")
    await _store_fixture(repository)
    comparison = _receipt("receipt-vector", total_tokens=80)

    report = await generate_anatomy_html(
        _receipt(),
        repository,
        label="full engine",
        comparisons=[("vector-only", comparison)],
    )

    assert '<section id="ablations">' in report
    assert "full engine" in report
    assert "vector-only" in report
    assert "100 / 1000" in report
    assert "80 / 1000" in report


def test_anatomy_cli_reads_receipt_by_id(tmp_path: Path) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "cli.sqlite3")

    async def arrange() -> None:
        await _store_fixture(repository)
        await repository.save_recall_receipt(_receipt())

    asyncio.run(arrange())
    output = tmp_path / "report.html"

    assert main(
        [
            "--db",
            str(repository.db_path),
            "--receipt-id",
            "receipt-primary",
            "--out",
            str(output),
        ]
    ) == 0
    assert "Anatomy of a 100-token handoff" in output.read_text(encoding="utf-8")
