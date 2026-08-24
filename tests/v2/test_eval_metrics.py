from __future__ import annotations

import pytest

from aoms.eval.metrics import aggregate_metrics, percentile, score_case
from aoms.eval.models import CaseCategory, EvalCase


def case(*, gold: list[str]) -> EvalCase:
    return EvalCase(
        id="mini",
        category=CaseCategory.EXACT_RECALL if gold else CaseCategory.NEGATIVE,
        query="mini query",
        gold_record_ids=gold,
        forbidden_record_ids=["old"] if gold else [],
        token_budget=100,
        k=2,
    )


def test_metrics_match_hand_computed_positive_case() -> None:
    scored = score_case(
        case(gold=["a", "b"]),
        ranked_ids=["a", "x", "b"],
        packed_ids=["a", "old", "canary"],
        token_count=75,
        latency_ms=12.0,
        supersession_pairs=[("old", "new")],
        canary_ids={"canary"},
    )

    assert scored.recall_at_k == 0.5
    assert scored.budget_recall == 0.5
    assert scored.non_gold_share == pytest.approx(2 / 3)
    assert (scored.stale_numerator, scored.stale_denominator) == (1, 1)
    assert (scored.contradiction_numerator, scored.contradiction_denominator) == (
        0,
        1,
    )
    assert scored.canary_count == 1
    assert scored.token_utilization == 0.75
    assert scored.forbidden_surfaced_ids == ["old"]


def test_negative_and_contradiction_conventions_are_explicit() -> None:
    empty = score_case(
        case(gold=[]),
        ranked_ids=[],
        packed_ids=[],
        token_count=0,
        latency_ms=1,
    )
    noisy = score_case(
        case(gold=[]),
        ranked_ids=["noise"],
        packed_ids=["old", "new"],
        token_count=50,
        latency_ms=3,
        supersession_pairs=[("old", "new")],
    )

    assert (empty.recall_at_k, empty.budget_recall) == (1.0, 1.0)
    assert (noisy.recall_at_k, noisy.budget_recall) == (0.0, 0.0)
    assert noisy.non_gold_share == 1.0
    assert (noisy.stale_numerator, noisy.stale_denominator) == (0, 1)
    assert (noisy.contradiction_numerator, noisy.contradiction_denominator) == (
        1,
        1,
    )

    aggregate = aggregate_metrics([empty, noisy])
    assert aggregate.recall_at_k == 0.5
    assert aggregate.budget_recall == 0.5
    assert aggregate.non_gold_share == 1.0
    assert aggregate.contradiction_rate == 1.0
    assert aggregate.token_utilization == 0.25
    assert aggregate.latency_p50_ms == 2.0


def test_percentile_uses_linear_type_seven_interpolation() -> None:
    assert percentile([0, 10, 20, 30], 50) == 15
    assert percentile([0, 10, 20, 30], 95) == pytest.approx(28.5)
