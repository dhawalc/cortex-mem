from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aoms.application import AOMSApplication
from aoms.contracts import (
    MemoryKind,
    MemoryRecord,
    Provenance,
    Scope,
    ScopeContext,
    SearchRequest,
    SupersedeRequest,
)
from aoms.embeddings import NullProvider
from aoms.observatory.server import ObservatoryApplication
from aoms.repositories import SQLiteMemoryRepository
from aoms.truth import (
    BOTH_ENDS_RETRIEVABLE,
    CYCLE,
    DANGLING_TARGET,
    MULTIPLE_HEADS,
    SCOPE_BOUNDARY,
    diagnose_chains,
)
from tests.v2.test_cli import ROOT, run_cli

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
CONTEXT = ScopeContext(agent_id="truth-agent", workspace_id="truth-workspace")


def record(
    record_id: str,
    *,
    content: str | None = None,
    created_at: datetime = NOW,
    supersedes: str | None = None,
    scope: Scope = Scope.WORKSPACE,
    workspace: str | None = CONTEXT.workspace_id,
    agent: str | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        kind=MemoryKind.FACT,
        content=content or f"truth fixture {record_id}",
        tags=["truth-fixture"],
        scope=scope,
        scope_workspace_id=workspace if scope is Scope.WORKSPACE else None,
        scope_agent_id=agent if scope is Scope.AGENT_PRIVATE else None,
        created_by_agent_id="fixture",
        provenance=Provenance(source="truth-fixture"),
        created_at=created_at,
        updated_at=created_at,
        supersedes=supersedes,
    )


def diagnostic_fixture() -> list[MemoryRecord]:
    return [
        record("cycle-a", supersedes="cycle-b"),
        record("cycle-b", supersedes="cycle-a"),
        record("dangling", supersedes="missing-target"),
        record("branch-root"),
        record("branch-a", supersedes="branch-root"),
        record("branch-b", supersedes="branch-root"),
        record("retrievable-old"),
        record("retrievable-new", supersedes="retrievable-old"),
        record("scope-old", workspace="workspace-a"),
        record("scope-new", supersedes="scope-old", workspace="workspace-b"),
    ]


def test_each_deterministic_chain_diagnostic_and_doctor_surface(
    tmp_path: Path,
) -> None:
    records = diagnostic_fixture()
    report = diagnose_chains(records, fts_memory_ids={item.id for item in records})

    assert report.count(CYCLE) == 1
    assert report.count(DANGLING_TARGET) == 1
    assert report.count(MULTIPLE_HEADS) == 1
    assert report.count(BOTH_ENDS_RETRIEVABLE) >= 1
    assert report.count(SCOPE_BOUNDARY) == 1
    assert all("semantic" not in finding.detail for finding in report.findings)

    data_dir = tmp_path / "doctor"
    run_cli("init", data_dir=data_dir, check=True)
    asyncio.run(
        SQLiteMemoryRepository(data_dir / "aoms.sqlite3").store_many(records)
    )
    doctor = run_cli("doctor", data_dir=data_dir, check=True)

    for title in (
        "Supersession cycles",
        "Dangling supersedes targets",
        "Multiple apparent heads",
        "Both-ends-retrievable pairs",
        "Scope-boundary anomalies",
    ):
        assert f"[WARN] {title}" in doctor.stdout
    assert "no auto-fix is performed" in doctor.stdout


@pytest.mark.asyncio
async def test_application_supersede_appends_and_preserves_predecessor(
    tmp_path: Path,
) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "supersede.sqlite3")
    old = record("old", content="Orchid region is west")
    await repository.store(old)
    application = AOMSApplication(
        repository,
        scope_context=CONTEXT,
        embedding_provider=NullProvider(),
        background_embeddings=False,
    )

    result = await application.supersede(
        old.id,
        SupersedeRequest(id="new", content="Orchid region is east"),
    )
    timeline = await application.chain_timeline(result.record.id)

    assert result.created is True
    assert result.record.supersedes == old.id
    assert result.record.scope is old.scope
    assert result.record.tags == old.tags
    assert await repository.get(old.id) == old
    assert [item.record.id for item in timeline.versions] == ["old", "new"]
    assert timeline.versions[0].valid_until == result.record.created_at
    with pytest.raises(ValueError, match="not an apparent head"):
        await application.supersede(
            old.id, SupersedeRequest(content="accidental branch")
        )
    with pytest.raises(ValueError, match="already in use"):
        await application.supersede(
            result.record.id,
            SupersedeRequest(id=old.id, content="must not overwrite old"),
        )
    assert await repository.get(old.id) == old


def test_supersede_cli_accepts_content_or_prompts_and_shows_chain(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "cli"
    run_cli("init", data_dir=data_dir, check=True)
    cli_workspace = str(ROOT.resolve())
    records = [
        record("cli-old", workspace=cli_workspace),
        record("cli-prompt-old", workspace=cli_workspace),
    ]
    asyncio.run(
        SQLiteMemoryRepository(data_dir / "aoms.sqlite3").store_many(records)
    )

    accepted = run_cli(
        "supersede",
        "cli-old",
        "--successor-id",
        "cli-new",
        "--content",
        "accepted correction",
        data_dir=data_dir,
        check=True,
    )
    prompted = run_cli(
        "supersede",
        "cli-prompt-old",
        "--successor-id",
        "cli-prompt-new",
        data_dir=data_dir,
        input_text="prompted correction\n",
        check=True,
    )

    assert "Created successor cli-new superseding cli-old" in accepted.stdout
    assert "Declared-lineage reconstruction" in accepted.stdout
    assert "cli-old" in accepted.stdout and "cli-new" in accepted.stdout
    assert "New content:" in prompted.stdout
    assert "prompted correction" in prompted.stdout


def test_observatory_truth_inbox_and_declared_timeline_rendering(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "observatory.sqlite3"
    first = record(
        "timeline-old",
        content="Workspace believed the launch was Monday.",
        created_at=NOW,
    )
    changed = record(
        "timeline-new",
        content="Workspace believed the launch was Tuesday.",
        created_at=NOW + timedelta(days=2),
        supersedes=first.id,
    )
    asyncio.run(
        SQLiteMemoryRepository(db_path).store_many(
            [first, changed, *diagnostic_fixture()]
        )
    )
    application = ObservatoryApplication(db_path)

    truth = application.handle("GET", "/truth")
    detail = application.handle("GET", "/memories/timeline-new")
    branch_detail = application.handle("GET", "/memories/branch-a")
    truth_html = truth.body.decode()
    detail_html = detail.body.decode()

    assert truth.status == 200
    for category in (
        CYCLE,
        DANGLING_TARGET,
        MULTIPLE_HEADS,
        BOTH_ENDS_RETRIEVABLE,
        SCOPE_BOUNDARY,
    ):
        assert category in truth_html
    assert 'href="/memories/cycle-a"' in truth_html
    assert "do not infer semantic conflicts" in truth_html
    assert detail.status == 200
    assert "What this store declared, and when it changed" in detail_html
    assert "not omniscient event history" in detail_html
    assert first.created_at.isoformat() in detail_html
    assert changed.created_at.isoformat() in detail_html
    assert "Workspace believed the launch was Monday" in detail_html
    assert "Workspace believed the launch was Tuesday" in detail_html
    assert branch_detail.status == 200
    assert "branch-b" in branch_detail.body.decode()


@pytest.mark.asyncio
async def test_as_of_search_and_chain_never_leak_out_of_scope_successor(
    tmp_path: Path,
) -> None:
    """Mandatory temporal scope canary: hidden lineage cannot affect output."""

    repository = SQLiteMemoryRepository(tmp_path / "data" / "aoms.sqlite3")
    old = record(
        "visible-old",
        content="boundaryquartz legacyamber visible value was amber",
        created_at=NOW,
    )
    hidden = record(
        "PRIVATE-CANARY-ID",
        content="boundaryquartz PRIVATE-CANARY-CONTENT",
        created_at=NOW + timedelta(days=1),
        supersedes=old.id,
        scope=Scope.AGENT_PRIVATE,
        workspace=None,
        agent="other-agent",
    )
    current = record(
        "visible-current",
        content="boundaryquartz modernblue visible value became blue",
        created_at=NOW + timedelta(days=2),
        supersedes=old.id,
    )
    await repository.store_many([old, hidden, current])
    application = AOMSApplication(
        repository,
        scope_context=CONTEXT,
        embedding_provider=NullProvider(),
    )

    middle = NOW + timedelta(days=1, hours=12)
    middle_search = await application.search(
        SearchRequest(query="boundaryquartz"), as_of=middle
    )
    middle_chain = await application.chain_timeline(old.id, as_of=middle)
    current_search = await application.search(
        SearchRequest(query="boundaryquartz"), as_of=NOW + timedelta(days=3)
    )
    current_chain = await application.chain_timeline(
        current.id, as_of=NOW + timedelta(days=3)
    )
    past_from_current_wording = await application.search(
        SearchRequest(query="modernblue"), as_of=middle
    )
    current_from_old_wording = await application.search(
        SearchRequest(query="legacyamber"), as_of=NOW + timedelta(days=3)
    )

    assert [item.record.id for item in middle_search.items] == [old.id]
    assert [item.record.id for item in middle_chain.versions] == [old.id]
    assert middle_chain.versions[0].valid_until is None
    assert [item.record.id for item in current_search.items] == [current.id]
    assert [item.record.id for item in past_from_current_wording.items] == [old.id]
    assert [item.record.id for item in current_from_old_wording.items] == [current.id]
    assert [item.record.id for item in current_chain.versions] == [old.id, current.id]
    serialized = repr((middle_search, middle_chain, current_search, current_chain))
    assert "PRIVATE-CANARY-ID" not in serialized
    assert "PRIVATE-CANARY-CONTENT" not in serialized

    data_dir = repository.db_path.parent
    environment = {
        "AOMS_AGENT_ID": CONTEXT.agent_id,
        "AOMS_WORKSPACE": CONTEXT.workspace_id,
    }
    searched = run_cli(
        "search",
        "boundaryquartz",
        "--as-of",
        middle.isoformat(),
        data_dir=data_dir,
        environ_overrides=environment,
        check=True,
    )
    chained = run_cli(
        "chain",
        old.id,
        "--as-of",
        middle.isoformat(),
        data_dir=data_dir,
        environ_overrides=environment,
        check=True,
    )
    cli_output = searched.stdout + chained.stdout
    assert old.id in cli_output
    assert "Declared-lineage reconstruction" in cli_output
    assert "PRIVATE-CANARY-ID" not in cli_output
    assert "PRIVATE-CANARY-CONTENT" not in cli_output
