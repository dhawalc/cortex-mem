"""Tests for the blindspot coverage check.

Two of these are the load-bearing ones: a decision surface whose every read
input is populated by its harness must pass, and one with a single unpopulated
input must fail and name it. The rest pin the analysis that makes those two
verdicts mean something.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import blindspot  # noqa: E402

# A miniature decision function with the same shape as the real one: an
# always-read input, one that gates a trigger, one that short-circuits the
# whole gate, and one the function never reads at all.
FIXTURE_MODULE = '''
from dataclasses import dataclass

@dataclass(frozen=True)
class Intent:
    digest: str
    slot: str | None = None
    stamp: str | None = None
    note: str | None = None

def decide(intent, state, *, now):
    if intent.slot is None:
        return Decision(disposition="admitted")
    if intent.digest == state.digest:
        return Decision(disposition="admitted")
    stale = intent.stamp is not None and intent.stamp < state.stamp
    if stale:
        return Decision(disposition="contested", trigger=Trigger.RETROGRADE)
    return Decision(disposition="admitted")
'''


@pytest.fixture
def module(tmp_path: Path) -> Path:
    path = tmp_path / "gate.py"
    path.write_text(FIXTURE_MODULE, encoding="utf-8")
    return path


def write_trace(tmp_path: Path, name: str, rows: list[dict]) -> Path:
    path = tmp_path / name
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )
    return path


def surface_of(module: Path):
    return blindspot.parse_declared_surface(
        module, intent_class="Intent", decide_function="decide"
    )


def test_declared_surface_separates_read_inputs_from_carried_ones(module: Path) -> None:
    surface = surface_of(module)
    assert {entry.name for entry in surface.fields} == {
        "digest",
        "slot",
        "stamp",
        "note",
    }
    assert surface.by_name("note").read is False
    assert surface.by_name("digest").read is True


def test_gate_attribution_follows_a_local_intermediate(module: Path) -> None:
    """``stale`` is a local; the field that built it still gates the trigger."""

    surface = surface_of(module)
    assert surface.by_name("stamp").gates == ("Trigger.RETROGRADE",)
    assert surface.by_name("slot").short_circuits is True


def test_complete_coverage_passes(tmp_path: Path, module: Path) -> None:
    trace = write_trace(
        tmp_path,
        "complete.jsonl",
        [
            {"digest": "a", "slot": "s1", "stamp": "2026-01-01", "note": None},
            {"digest": "b", "slot": "s2", "stamp": "2026-02-01", "note": None},
        ],
    )
    assert (
        blindspot.main(
            [
                "--module",
                str(module),
                "--intent-class",
                "Intent",
                "--trace",
                str(trace),
            ]
        )
        == 0
    )


def test_one_unpopulated_input_fails_and_is_named(tmp_path: Path, module: Path) -> None:
    trace = write_trace(
        tmp_path,
        "incomplete.jsonl",
        [
            {"digest": "a", "slot": "s1", "stamp": None, "note": None},
            {"digest": "b", "slot": "s2", "stamp": None, "note": None},
        ],
    )
    surface = surface_of(module)
    coverage, records = blindspot.load_trace(trace, surface)
    rows = blindspot.intersect(surface, coverage)
    blind = [row.name for row in rows if row.blind]

    assert records == 2
    assert blind == ["stamp"]
    assert (
        blindspot.main(
            [
                "--module",
                str(module),
                "--intent-class",
                "Intent",
                "--trace",
                str(trace),
            ]
        )
        == 1
    )


def test_an_input_the_function_never_reads_cannot_fail_the_run(
    tmp_path: Path, module: Path
) -> None:
    """``note`` is never populated and never read. That is not a blindspot."""

    trace = write_trace(
        tmp_path,
        "unread.jsonl",
        [{"digest": "a", "slot": "s1", "stamp": "2026-01-01", "note": None}],
    )
    surface = surface_of(module)
    rows = blindspot.intersect(surface, blindspot.load_trace(trace, surface)[0])
    note = next(row for row in rows if row.name == "note")
    assert note.status == blindspot.UNREAD
    assert note.blind is False


def test_a_populated_but_never_varying_input_is_flagged_constant(
    tmp_path: Path, module: Path
) -> None:
    trace = write_trace(
        tmp_path,
        "constant.jsonl",
        [
            {"digest": "a", "slot": "only", "stamp": "2026-01-01", "note": None},
            {"digest": "b", "slot": "only", "stamp": "2026-02-01", "note": None},
        ],
    )
    surface = surface_of(module)
    rows = blindspot.intersect(surface, blindspot.load_trace(trace, surface)[0])
    slot = next(row for row in rows if row.name == "slot")
    assert slot.status == blindspot.CONSTANT
    assert slot.blind is False


def test_a_trace_carrying_undeclared_fields_is_refused(
    tmp_path: Path, module: Path
) -> None:
    """A trace out of step with the surface would silently misreport coverage."""

    trace = write_trace(tmp_path, "drift.jsonl", [{"digest": "a", "invented": 1}])
    with pytest.raises(ValueError, match="does not declare"):
        blindspot.load_trace(trace, surface_of(module))


def test_the_real_aoms_gate_declares_both_deferred_inputs() -> None:
    """Regression lock on the claim the tool exists to test.

    If ``derived_from`` or ``asserted_at`` ever stops being a declared, read,
    trigger-gating input, the MCB-1.0 coverage result stops meaning what the
    write-up says it means.
    """

    contest = Path(__file__).resolve().parents[2] / "aoms" / "contest.py"
    surface = blindspot.parse_declared_surface(
        contest, intent_class="WriteIntent", decide_function="decide"
    )
    derived = surface.by_name("derived_from")
    asserted = surface.by_name("asserted_at")

    assert derived.read and derived.gates == ("ContestTrigger.DERIVED",)
    assert asserted.read and asserted.gates == ("ContestTrigger.RETROGRADE",)
    assert surface.by_name("claim_key").short_circuits is True
