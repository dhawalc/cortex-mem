"""The operator surface: every resolution is a named human act, receipted."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from click.testing import CliRunner

from aoms.cli import main
from aoms.contracts import ContestResolution, ContestState, WriteDisposition
from aoms.repositories import SQLiteMemoryRepository


@pytest.fixture
def store(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("AOMS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("AOMS_EMBEDDING_PROVIDER", "none")
    monkeypatch.setenv("AOMS_AGENT_ID", "operator-a")
    monkeypatch.setenv("AOMS_WORKSPACE", "/workspace")
    runner = CliRunner()
    assert runner.invoke(main, ["init"]).exit_code == 0
    return runner, data_dir / "aoms.sqlite3"


def run(runner, *args):
    result = runner.invoke(main, list(args))
    assert result.exit_code == 0, result.output + str(result.exception)
    return result.output


def open_contest(runner) -> tuple[str, str, str]:
    run(runner, "remember", "--content", "price is 100", "--claim-key", "price")
    challenger = run(
        runner, "remember", "--content", "price is 80", "--claim-key", "price"
    )
    assert "CONTESTED" in challenger
    listing = json.loads(run(runner, "contest", "list", "--json"))
    entry = listing["entries"][0]
    return entry["contest_id"], entry["record_id"], entry["incumbent_ids"][0]


def ask(db_path, question):
    """Query the store from a sync test, since the CLI owns its own loop."""

    async def run():
        return await question(SQLiteMemoryRepository(db_path))

    return asyncio.run(run())


# --- listing and inspection ----------------------------------------------


def test_list_reports_an_empty_ledger_without_inventing_anything(store):
    runner, _ = store
    output = run(runner, "contest", "list")
    assert "0 matching" in output
    assert "Nothing to review" in output


def test_show_prints_both_sides_and_the_commands_that_resolve_it(store):
    runner, _ = store
    contest_id, challenger_id, incumbent_id = open_contest(runner)
    output = run(runner, "contest", "show", contest_id)
    assert "price is 100" in output
    assert "price is 80" in output
    assert "Standing (current memory, unchanged)" in output
    assert f"--supersede {incumbent_id}" in output
    assert challenger_id in output


def test_drain_writes_nothing(store):
    runner, db_path = store
    contest_id, _, _ = open_contest(runner)
    with sqlite3.connect(db_path) as connection:
        before = connection.execute(
            "SELECT COUNT(*), SUM(occurrence_count) FROM contest_entries"
        ).fetchone()
    output = run(runner, "contest", "drain")
    assert "writes nothing" in output
    assert contest_id in output
    with sqlite3.connect(db_path) as connection:
        after = connection.execute(
            "SELECT COUNT(*), SUM(occurrence_count) FROM contest_entries"
        ).fetchone()
    assert before == after


# --- resolution paths -----------------------------------------------------


def test_admit_gives_the_challenger_the_slot(store):
    runner, db_path = store
    contest_id, challenger_id, _ = open_contest(runner)
    output = run(runner, "contest", "resolve", contest_id, "--admit")
    assert "admit" in output

    challenger = ask(db_path, lambda repo: repo.get(challenger_id))
    assert challenger.disposition is WriteDisposition.ADMITTED
    entry = ask(db_path, lambda repo: repo.get_contest(contest_id))
    assert entry.state is ContestState.RESOLVED
    assert entry.resolution is ContestResolution.ADMIT
    assert entry.resolved_by == "operator-a"
    report = ask(db_path, lambda repo: repo.integrity_report())
    assert report.contested_projection_drift == []


def test_supersede_appends_a_successor_and_never_rewrites_a_predecessor(store):
    runner, db_path = store
    contest_id, challenger_id, incumbent_id = open_contest(runner)
    before = ask(db_path, lambda repo: repo.get(incumbent_id)).model_dump_json()

    output = run(runner, "contest", "resolve", contest_id, "--supersede", incumbent_id)
    assert "admit-superseding" in output

    after = ask(db_path, lambda repo: repo.get(incumbent_id)).model_dump_json()
    assert after == before

    successors = [
        record
        for record in ask(db_path, lambda repo: repo.list(limit=100))
        if record.supersedes == incumbent_id
    ]
    assert len(successors) == 1
    assert successors[0].content == "price is 80"
    assert successors[0].claim_key == "price"
    assert successors[0].disposition is WriteDisposition.ADMITTED

    # The contested record survives untouched as the ledger's evidence.
    challenger = ask(db_path, lambda repo: repo.get(challenger_id))
    assert challenger.content == "price is 80"
    assert challenger.disposition is WriteDisposition.CONTESTED


def test_set_aside_deletes_nothing_and_leaves_the_record_searchable(store):
    runner, db_path = store
    contest_id, challenger_id, _ = open_contest(runner)
    run(
        runner,
        "contest",
        "resolve",
        contest_id,
        "--set-aside",
        "--reason",
        "unsupported observation, no source",
    )
    challenger = ask(db_path, lambda repo: repo.get(challenger_id))
    assert challenger is not None
    assert challenger.content == "price is 80"
    assert challenger.disposition is WriteDisposition.CONTESTED

    entry = ask(db_path, lambda repo: repo.get_contest(contest_id))
    assert entry.resolution is ContestResolution.SET_ASIDE
    assert entry.resolution_note == "unsupported observation, no source"

    from aoms.contracts import SearchRequest

    found = ask(
        db_path,
        lambda repo: repo.search_by_keyword(
            SearchRequest(query="price", include_contested=True)
        ),
    )
    assert challenger_id in {hit.record.id for hit in found.items}


def test_split_refiles_the_record_under_a_free_slot(store):
    runner, db_path = store
    contest_id, challenger_id, _ = open_contest(runner)
    run(
        runner,
        "contest",
        "resolve",
        contest_id,
        "--split",
        "--claim-key",
        "wholesale-price",
    )
    challenger = ask(db_path, lambda repo: repo.get(challenger_id))
    assert challenger.claim_key == "wholesale-price"
    assert challenger.disposition is WriteDisposition.ADMITTED
    assert challenger.content == "price is 80"
    report = ask(db_path, lambda repo: repo.integrity_report())
    assert report.contested_projection_drift == []


def test_split_refuses_to_create_a_second_collision(store):
    runner, _ = store
    contest_id, _, _ = open_contest(runner)
    result = runner.invoke(
        main, ["contest", "resolve", contest_id, "--split", "--claim-key", "price"]
    )
    assert result.exit_code != 0
    assert "already held" in result.output


def test_resolution_requires_exactly_one_verdict(store):
    runner, _ = store
    contest_id, _, incumbent_id = open_contest(runner)
    both = runner.invoke(
        main, ["contest", "resolve", contest_id, "--admit", "--supersede", incumbent_id]
    )
    assert both.exit_code != 0
    assert "exactly one" in both.output
    neither = runner.invoke(main, ["contest", "resolve", contest_id])
    assert neither.exit_code != 0


def test_set_aside_requires_a_stated_reason(store):
    runner, _ = store
    contest_id, _, _ = open_contest(runner)
    result = runner.invoke(main, ["contest", "resolve", contest_id, "--set-aside"])
    assert result.exit_code != 0
    assert "--reason" in result.output


def test_a_resolved_contest_is_not_silently_resolved_twice(store):
    runner, _ = store
    contest_id, _, _ = open_contest(runner)
    run(runner, "contest", "resolve", contest_id, "--admit")
    second = runner.invoke(main, ["contest", "resolve", contest_id, "--admit"])
    assert second.exit_code != 0
    assert "already resolved" in second.output


def test_every_resolution_is_receipted_with_the_resolver(store):
    runner, db_path = store
    contest_id, _, _ = open_contest(runner)
    run(runner, "contest", "resolve", contest_id, "--admit")
    receipts = ask(db_path, lambda repo: repo.recent_write_receipts())
    resolution_receipts = [
        item for item in receipts if item.trigger_detail.get("resolution")
    ]
    assert len(resolution_receipts) == 1
    assert resolution_receipts[0].agent_id == "operator-a"
    assert resolution_receipts[0].trigger_detail["resolution"] == "admit"


# --- doctor ---------------------------------------------------------------


def test_doctor_passes_on_a_clean_ledger_and_warns_on_an_open_one(store):
    runner, _ = store
    clean = run(runner, "doctor")
    assert "[PASS] Contest inbox: no open entries" in clean
    open_contest(runner)
    warned = runner.invoke(main, ["doctor"])
    assert warned.exit_code == 0
    assert "[WARN] Contest inbox" in warned.output


def test_doctor_fails_on_projection_drift_and_names_the_ids(store):
    runner, db_path = store
    run(runner, "remember", "--content", "a fact", "--claim-key", "k")
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE memories SET contested = 1")
        connection.commit()
    result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 1
    assert "[FAIL] Contested projection" in result.output
    assert "disagree with the ledger" in result.output


def test_doctor_fails_when_an_entry_is_past_its_review_window(store, monkeypatch):
    runner, db_path = store
    open_contest(runner)
    stale = datetime.now(timezone.utc) - timedelta(days=40)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE contest_entries SET opened_at = ?", (stale.isoformat(),)
        )
        connection.commit()
    result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 1
    assert "past the 14-day review window" in result.output
    assert "Nothing resolves on a timer" in result.output


def test_an_aged_entry_reports_as_expired_held_without_being_rewritten(store):
    runner, db_path = store
    open_contest(runner)
    stale = datetime.now(timezone.utc) - timedelta(days=60)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE contest_entries SET opened_at = ?", (stale.isoformat(),)
        )
        connection.commit()
    output = runner.invoke(main, ["contest", "list"]).output
    assert "expired-held" in output
    # Derived, never stored: expiry decides nothing and rewrites nothing.
    with sqlite3.connect(db_path) as connection:
        stored = connection.execute("SELECT state FROM contest_entries").fetchone()[0]
    assert stored == "open"


def test_the_disposition_map_is_a_dry_run(store):
    runner, db_path = store
    open_contest(runner)
    with sqlite3.connect(db_path) as connection:
        before = connection.execute(
            "SELECT COUNT(*), SUM(contested) FROM memories"
        ).fetchone()
    output = run(runner, "doctor", "--contests")
    assert "zero writes" in output
    assert "admitted=1  contested=1" in output
    with sqlite3.connect(db_path) as connection:
        after = connection.execute(
            "SELECT COUNT(*), SUM(contested) FROM memories"
        ).fetchone()
    assert before == after


def test_the_disposition_map_counts_non_participating_records(store):
    runner, _ = store
    run(runner, "remember", "--content", "a legacy-shaped write")
    output = run(runner, "doctor", "--contests")
    assert "1 record(s) do not participate in the gate" in output


def test_write_receipts_are_listable_without_a_model_facing_tool(store):
    runner, _ = store
    open_contest(runner)
    output = run(runner, "receipts")
    assert "append-only, never pruned" in output
    assert "contested" in output
    assert "admitted" in output
