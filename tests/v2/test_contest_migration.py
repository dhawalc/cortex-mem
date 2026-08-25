"""Migration 7 and the ledger's storage plumbing.

The load-bearing property here is that an existing 165k-record store comes
through the migration meaning exactly what it meant before: every legacy row
opts out of the gate, and no row is rewritten, reordered, or reinterpreted.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from aoms.contest import DEFAULT_RULESET, content_digest
from aoms.contracts import (
    ContestEntry,
    ContestState,
    ContestTrigger,
    MemoryKind,
    MemoryRecord,
    Provenance,
    Scope,
    WriteDisposition,
)
from aoms.receipts import ENGINE_VERSION, WriteReceipt
from aoms.repositories import SQLiteMemoryRepository
from aoms.repositories.base import LedgerWrite
from aoms.repositories.sqlite import (
    LATEST_SCHEMA_VERSION,
    MIGRATION_7_COLUMNS,
    MIGRATIONS,
)

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def record(record_id: str, **overrides: object) -> MemoryRecord:
    base: dict[str, object] = {
        "id": record_id,
        "kind": MemoryKind.FACT,
        "content": f"content for {record_id}",
        "scope": Scope.WORKSPACE,
        "scope_workspace_id": "/w",
        "created_by_agent_id": "agent-a",
        "provenance": Provenance(source="test"),
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(overrides)
    return MemoryRecord(**base)  # type: ignore[arg-type]


def write_receipt(record_id: str, **overrides: object) -> WriteReceipt:
    base: dict[str, object] = {
        "receipt_id": f"wr-{record_id}",
        "created_at": NOW,
        "record_id": record_id,
        "kind": MemoryKind.FACT,
        "scope": Scope.WORKSPACE,
        "content_sha256": content_digest("x"),
        "disposition": WriteDisposition.ADMITTED,
        "ruleset_digest": DEFAULT_RULESET.digest,
        "engine_version": ENGINE_VERSION,
    }
    base.update(overrides)
    return WriteReceipt(**base)  # type: ignore[arg-type]


# --- the numbering correction --------------------------------------------


def test_latest_schema_version_is_current_and_six_is_still_the_fts_placeholder():
    # Every proposal and every judge said this constant was 5. It was 6, with
    # MIGRATIONS[6] a live placeholder dispatched by an `if version == 6`
    # branch. Numbering the new migration 6 would have overwritten that branch
    # and never applied to any existing store, while the version claimed it
    # had. This test is the regression guard for exactly that error.
    assert LATEST_SCHEMA_VERSION == 10
    assert MIGRATIONS[6] == ""
    assert set(MIGRATIONS) == {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}


@pytest.mark.asyncio
async def test_a_store_already_at_version_six_advances_to_the_latest(tmp_path):
    path = tmp_path / "aoms.sqlite3"
    first = SQLiteMemoryRepository(path)
    await first.initialize()
    await first.store_new(record("legacy-1"))

    # Rewind to a store that has recorded version 6 and knows nothing of 7.
    with sqlite3.connect(path) as connection:
        connection.execute(
            "DELETE FROM schema_version WHERE version IN (7, 8, 9, 10)"
        )
        connection.execute("DROP INDEX idx_memories_claim_slot")
        for index in (
            "idx_memories_contested",
            "idx_memories_scope_contested",
            "idx_memories_workspace_contested",
            "idx_memories_agent_contested",
            # Migration 8's covering index also names the contest columns.
            "idx_memories_scope_cover",
            # Migration 10 indexes the per-kind recency sample.
            "idx_memories_kind_recent",
        ):
            connection.execute(f"DROP INDEX {index}")
        connection.execute("ALTER TABLE memories DROP COLUMN claim_key")
        connection.execute("ALTER TABLE memories DROP COLUMN contested")
        connection.execute("DROP TABLE contest_entries")
        connection.execute("DROP TABLE write_receipts")
        connection.commit()

    upgraded = SQLiteMemoryRepository(path)
    assert await upgraded.schema_version() == LATEST_SCHEMA_VERSION
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(memories)").fetchall()
        }
        assert {"claim_key", "contested"} <= columns
        row = connection.execute(
            "SELECT claim_key, contested FROM memories WHERE id = 'legacy-1'"
        ).fetchone()
    assert row["claim_key"] is None
    assert row["contested"] == 0


@pytest.mark.asyncio
async def test_migration_seven_is_idempotent_when_reapplied(tmp_path):
    path = tmp_path / "aoms.sqlite3"
    await SQLiteMemoryRepository(path).initialize()
    with sqlite3.connect(path) as connection:
        # Simulate a crash between the DDL and the version row.
        connection.execute("DELETE FROM schema_version WHERE version = 7")
        connection.commit()
    retried = SQLiteMemoryRepository(path)
    await retried.initialize()
    assert await retried.schema_version() == LATEST_SCHEMA_VERSION


def test_migration_seven_touches_no_existing_data():
    ddl = MIGRATIONS[7].casefold()
    for forbidden in ("update ", "delete from", "record_json", "drop table", "drop index"):
        assert forbidden not in ddl
    assert set(MIGRATION_7_COLUMNS) == {"claim_key", "contested"}
    # NULL, not a weak comparable value: legacy rows opt out of the gate.
    assert "claim_key text" in ddl
    assert "default" not in MIGRATION_7_COLUMNS["claim_key"].casefold()


@pytest.mark.asyncio
async def test_every_pre_migration_record_loads_unchanged(tmp_path):
    path = tmp_path / "aoms.sqlite3"
    repository = SQLiteMemoryRepository(path)
    await repository.initialize()
    original = record("legacy-2")
    await repository.store_new(original)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        before = connection.execute(
            "SELECT record_json FROM memories WHERE id = 'legacy-2'"
        ).fetchone()["record_json"]

    reopened = SQLiteMemoryRepository(path)
    loaded = await reopened.get("legacy-2")
    assert loaded is not None
    assert loaded.claim_key is None
    assert loaded.disposition is WriteDisposition.ADMITTED
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        after = connection.execute(
            "SELECT record_json FROM memories WHERE id = 'legacy-2'"
        ).fetchone()["record_json"]
    assert after == before


# --- the projection and its drift check -----------------------------------


@pytest.mark.asyncio
async def test_a_clean_store_reports_no_drift(tmp_path):
    repository = SQLiteMemoryRepository(tmp_path / "aoms.sqlite3")
    await repository.initialize()
    await repository.store_new(record("a"))
    report = await repository.integrity_report()
    assert report.contested_projection_drift == []
    assert report.contested_count == 0
    assert report.healthy is True


@pytest.mark.asyncio
async def test_a_hand_corrupted_projection_is_named_and_makes_the_store_unhealthy(
    tmp_path,
):
    path = tmp_path / "aoms.sqlite3"
    repository = SQLiteMemoryRepository(path)
    await repository.initialize()
    await repository.store_new(record("a"))
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE memories SET contested = 1 WHERE id = 'a'")
        connection.commit()

    report = await repository.integrity_report()
    assert report.contested_projection_drift == ["a"]
    assert report.healthy is False


@pytest.mark.asyncio
async def test_an_open_entry_against_an_admitted_record_is_drift(tmp_path):
    path = tmp_path / "aoms.sqlite3"
    repository = SQLiteMemoryRepository(path)
    await repository.initialize()
    await repository.store_new(record("a"))
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO contest_entries(contest_id, record_id, claim_key, scope, "
            "incumbent_ids, trigger, trigger_detail, opened_at, "
            "opened_by_agent_id, state) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "ct-1",
                "a",
                "k",
                Scope.WORKSPACE.value,
                "[]",
                ContestTrigger.SLOT_COLLISION.value,
                "{}",
                NOW.isoformat(),
                "agent-a",
                ContestState.OPEN.value,
            ),
        )
        connection.commit()
    report = await repository.integrity_report()
    assert report.contested_projection_drift == ["a"]


# --- ledger writes are atomic and append-only -----------------------------


@pytest.mark.asyncio
async def test_the_contest_entry_and_receipt_commit_with_the_record(tmp_path):
    repository = SQLiteMemoryRepository(tmp_path / "aoms.sqlite3")
    await repository.initialize()
    await repository.store_new(record("incumbent", claim_key="price"))
    challenger = record(
        "challenger",
        claim_key="price",
        disposition=WriteDisposition.CONTESTED,
        content="different",
    )
    entry = ContestEntry(
        contest_id="ct-abc",
        record_id="challenger",
        claim_key="price",
        scope=Scope.WORKSPACE,
        scope_workspace_id="/w",
        incumbent_ids=["incumbent"],
        trigger=ContestTrigger.SLOT_COLLISION,
        trigger_detail={"undeclared_incumbent_count": 1},
        opened_at=NOW,
        opened_by_agent_id="agent-a",
    )
    await repository.store_new(
        challenger,
        ledger=LedgerWrite(
            receipt=write_receipt(
                "challenger", disposition=WriteDisposition.CONTESTED
            ),
            contest=entry,
        ),
    )

    stored = await repository.get_contest("ct-abc")
    assert stored is not None
    assert stored.incumbent_ids == ["incumbent"]
    assert stored.state is ContestState.OPEN
    receipts = await repository.recent_write_receipts()
    assert [item.record_id for item in receipts] == ["challenger"]
    report = await repository.integrity_report()
    assert report.contested_projection_drift == []
    assert report.contested_count == 1
    assert report.open_contest_count == 1


@pytest.mark.asyncio
async def test_write_receipts_are_exempt_from_recall_receipt_retention(tmp_path):
    # The direct regression test for the ring-buffer trim that runs inside the
    # transaction of every recall-receipt save. A design whose central safety
    # claim is "the declined write is retained" cannot store that claim in a
    # table that silently deletes its oldest 1,000th row.
    repository = SQLiteMemoryRepository(tmp_path / "aoms.sqlite3", receipt_retention=5)
    await repository.initialize()
    for index in range(2_000):
        await repository.save_write_receipt(
            write_receipt(f"r-{index:04d}", receipt_id=f"wr-{index:04d}")
        )
    assert await repository.write_receipt_count() == 2_000


@pytest.mark.asyncio
async def test_pruning_recall_receipts_never_touches_write_receipts(tmp_path):
    repository = SQLiteMemoryRepository(tmp_path / "aoms.sqlite3", receipt_retention=1)
    await repository.initialize()
    for index in range(10):
        await repository.save_write_receipt(
            write_receipt(f"r-{index}", receipt_id=f"wr-{index}")
        )
    await repository.prune_recall_receipts(retain=0)
    assert await repository.write_receipt_count() == 10


# --- slot state -----------------------------------------------------------


@pytest.mark.asyncio
async def test_slot_occupants_returns_only_admitted_chain_heads(tmp_path):
    repository = SQLiteMemoryRepository(tmp_path / "aoms.sqlite3")
    await repository.initialize()
    await repository.store_new(record("v1", claim_key="price"))
    await repository.store_new(
        record("v2", claim_key="price", supersedes="v1", content="v2 content")
    )
    await repository.store_new(
        record(
            "contested-1",
            claim_key="price",
            content="hostile",
            disposition=WriteDisposition.CONTESTED,
        )
    )
    occupants = await repository.slot_occupants(
        claim_key="price",
        scope=Scope.WORKSPACE,
        scope_agent_id=None,
        scope_workspace_id="/w",
    )
    assert [item.id for item in occupants] == ["v2"]


@pytest.mark.asyncio
async def test_a_contested_successor_cannot_freeze_its_incumbent(tmp_path):
    # Without excluding contested rows from lineage, a hostile agent could
    # write a contested successor and `supersede` would refuse forever,
    # because it treats any direct successor as proof the record is not a head.
    repository = SQLiteMemoryRepository(tmp_path / "aoms.sqlite3")
    await repository.initialize()
    await repository.store_new(record("head", claim_key="price"))
    await repository.store_new(
        record(
            "frozen-attempt",
            claim_key="price",
            supersedes="head",
            content="hostile",
            disposition=WriteDisposition.CONTESTED,
        )
    )
    from aoms.contracts import ScopeContext

    context = ScopeContext(agent_id="agent-a", workspace_id="/w")
    visible = await repository.lineage("head", scope_context=context)
    assert [item.id for item in visible] == ["head"]
    with_contested = await repository.lineage(
        "head", scope_context=context, include_contested=True
    )
    assert {item.id for item in with_contested} == {"head", "frozen-attempt"}


@pytest.mark.asyncio
async def test_a_read_only_store_still_at_schema_six_opens_and_reads(tmp_path):
    path = tmp_path / "aoms.sqlite3"
    repository = SQLiteMemoryRepository(path)
    await repository.initialize()
    await repository.store_new(record("a"))
    with sqlite3.connect(path) as connection:
        connection.execute(
            "DELETE FROM schema_version WHERE version IN (7, 8, 9, 10)"
        )
        connection.execute("DROP INDEX idx_memories_claim_slot")
        for index in (
            "idx_memories_contested",
            "idx_memories_scope_contested",
            "idx_memories_workspace_contested",
            "idx_memories_agent_contested",
            # Migration 8's covering index also names the contest columns.
            "idx_memories_scope_cover",
            # Migration 10 indexes the per-kind recency sample.
            "idx_memories_kind_recent",
        ):
            connection.execute(f"DROP INDEX {index}")
        connection.execute("ALTER TABLE memories DROP COLUMN claim_key")
        connection.execute("ALTER TABLE memories DROP COLUMN contested")
        connection.commit()

    from aoms.contracts import ScopeContext

    read_only = SQLiteMemoryRepository(path, read_only=True)
    listed = await read_only.list(
        scope_context=ScopeContext(agent_id="agent-a", workspace_id="/w")
    )
    assert [item.id for item in listed] == ["a"]


@pytest.mark.asyncio
async def test_the_ledger_survives_a_restart_and_reports_its_own_age(tmp_path):
    path = tmp_path / "aoms.sqlite3"
    repository = SQLiteMemoryRepository(path)
    await repository.initialize()
    await repository.store_new(record("c1", claim_key="k"))
    old = NOW - timedelta(days=40)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO contest_entries(contest_id, record_id, claim_key, scope, "
            "incumbent_ids, trigger, trigger_detail, opened_at, "
            "opened_by_agent_id, state) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "ct-old",
                "c1",
                "k",
                Scope.WORKSPACE.value,
                json.dumps(["x"]),
                ContestTrigger.DERIVED.value,
                json.dumps({"derived_from_count": 2}),
                old.isoformat(),
                "agent-a",
                ContestState.OPEN.value,
            ),
        )
        connection.execute("UPDATE memories SET contested = 1 WHERE id = 'c1'")
        connection.commit()

    reopened = SQLiteMemoryRepository(path)
    page = await reopened.list_contests(state=ContestState.OPEN)
    assert page.total == 1
    assert page.entries[0].opened_at == old
    assert page.entries[0].trigger_detail == {"derived_from_count": 2}


# --- portability ----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_legacy_store_round_trips_through_export_and_restore(tmp_path):
    """Migration 7 must not change what a record is, only what a store knows.

    Export a legacy-shaped store, restore it into a fresh one, and require the
    canonical JSON to come back byte-identical. If the migration had rewritten
    anything, this is where it would show.
    """

    from aoms.portable import export_bundle, restore_bundle

    source_path = tmp_path / "source.sqlite3"
    source = SQLiteMemoryRepository(source_path)
    await source.initialize()
    originals = [record(f"legacy-{index}") for index in range(5)]
    for original in originals:
        await source.store_new(original)

    with sqlite3.connect(source_path) as connection:
        connection.row_factory = sqlite3.Row
        before = {
            str(row["id"]): str(row["record_json"])
            for row in connection.execute("SELECT id, record_json FROM memories")
        }

    bundle = tmp_path / "bundle"
    await export_bundle(source, bundle)

    restored_path = tmp_path / "restored.sqlite3"
    restored = SQLiteMemoryRepository(restored_path)
    await restore_bundle(restored, bundle)

    with sqlite3.connect(restored_path) as connection:
        connection.row_factory = sqlite3.Row
        after = {
            str(row["id"]): str(row["record_json"])
            for row in connection.execute("SELECT id, record_json FROM memories")
        }
    assert after == before

    for original in originals:
        reloaded = await restored.get(original.id)
        assert reloaded is not None
        assert reloaded.claim_key is None
        assert reloaded.disposition is WriteDisposition.ADMITTED
    report = await restored.integrity_report()
    assert report.contested_projection_drift == []


@pytest.mark.asyncio
async def test_a_contested_record_survives_export_and_restore_as_contested(tmp_path):
    from aoms.portable import export_bundle, restore_bundle

    source_path = tmp_path / "source.sqlite3"
    source = SQLiteMemoryRepository(source_path)
    await source.initialize()
    await source.store_new(record("incumbent", claim_key="price"))
    challenger = record(
        "challenger",
        claim_key="price",
        content="rival",
        disposition=WriteDisposition.CONTESTED,
    )
    await source.store_new(
        challenger,
        ledger=LedgerWrite(
            receipt=write_receipt(
                "challenger", disposition=WriteDisposition.CONTESTED
            ),
            contest=ContestEntry(
                contest_id="ct-restore",
                record_id="challenger",
                claim_key="price",
                scope=Scope.WORKSPACE,
                scope_workspace_id="/w",
                incumbent_ids=["incumbent"],
                trigger=ContestTrigger.SLOT_COLLISION,
                trigger_detail={},
                opened_at=NOW,
                opened_by_agent_id="agent-a",
            ),
        ),
    )

    bundle = tmp_path / "bundle"
    await export_bundle(source, bundle)
    restored = SQLiteMemoryRepository(tmp_path / "restored.sqlite3")
    await restore_bundle(restored, bundle)

    reloaded = await restored.get("challenger")
    assert reloaded is not None
    assert reloaded.content == "rival"
    # The record's own disposition travels with it in record_json, so a
    # restored bundle never quietly promotes a contested claim to current.
    assert reloaded.disposition is WriteDisposition.CONTESTED


@pytest.mark.asyncio
async def test_the_ledger_travels_with_the_bundle(tmp_path):
    """A backup that dropped the ledger would be silent evidence loss.

    Before this, exporting and restoring a store left the contested record in
    place with no entry explaining why it was withheld — a record held back
    from recall that nothing in the store could account for, which `doctor`
    correctly reported as drift.
    """

    from aoms.portable import export_bundle, restore_bundle

    source_path = tmp_path / "source.sqlite3"
    source = SQLiteMemoryRepository(source_path)
    await source.initialize()
    await source.store_new(record("incumbent", claim_key="price"))
    await source.store_new(
        record(
            "challenger",
            claim_key="price",
            content="rival",
            disposition=WriteDisposition.CONTESTED,
        ),
        ledger=LedgerWrite(
            receipt=write_receipt(
                "challenger", disposition=WriteDisposition.CONTESTED
            ),
            contest=ContestEntry(
                contest_id="ct-travel",
                record_id="challenger",
                claim_key="price",
                scope=Scope.WORKSPACE,
                scope_workspace_id="/w",
                incumbent_ids=["incumbent"],
                trigger=ContestTrigger.SLOT_COLLISION,
                trigger_detail={"undeclared_incumbent_count": 1},
                opened_at=NOW,
                opened_by_agent_id="agent-a",
            ),
        ),
    )

    bundle = tmp_path / "bundle"
    exported = await export_bundle(source, bundle)
    assert exported.contests == 1
    assert exported.write_receipts == 1

    restored = SQLiteMemoryRepository(tmp_path / "restored.sqlite3")
    result = await restore_bundle(restored, bundle)
    assert result.contests == 1
    assert result.write_receipts == 1

    entry = await restored.get_contest("ct-travel")
    assert entry is not None
    assert entry.incumbent_ids == ["incumbent"]
    assert entry.trigger_detail == {"undeclared_incumbent_count": 1}
    assert entry.opened_at == NOW

    receipts = await restored.recent_write_receipts()
    assert [item.record_id for item in receipts] == ["challenger"]

    report = await restored.integrity_report()
    assert report.contested_projection_drift == []
    assert report.contested_count == 1
    assert report.open_contest_count == 1


@pytest.mark.asyncio
async def test_a_bundle_written_before_the_ledger_still_restores(tmp_path):
    import json as json_module

    from aoms.portable import (
        CONTESTS_FILE,
        MANIFEST_FILE,
        WRITE_RECEIPTS_FILE,
        export_bundle,
        restore_bundle,
    )

    source = SQLiteMemoryRepository(tmp_path / "source.sqlite3")
    await source.initialize()
    await source.store_new(record("legacy-a"))
    bundle = tmp_path / "bundle"
    await export_bundle(source, bundle)

    # Rewrite the bundle as one produced before the ledger existed.
    manifest = json_module.loads((bundle / MANIFEST_FILE).read_text())
    del manifest["files"][CONTESTS_FILE]
    del manifest["files"][WRITE_RECEIPTS_FILE]
    (bundle / MANIFEST_FILE).write_text(json_module.dumps(manifest, indent=2))
    (bundle / CONTESTS_FILE).unlink()
    (bundle / WRITE_RECEIPTS_FILE).unlink()

    restored = SQLiteMemoryRepository(tmp_path / "restored.sqlite3")
    result = await restore_bundle(restored, bundle)
    assert result.records == 1
    assert result.contests == 0
    assert result.write_receipts == 0
    reloaded = await restored.get("legacy-a")
    assert reloaded is not None
    assert reloaded.claim_key is None
    report = await restored.integrity_report()
    assert report.contested_projection_drift == []
