"""Metric calculations for ranked candidates and budget-packed context."""

from __future__ import annotations

import math
from collections.abc import Sequence

from .models import AggregateMetrics, CaseMetrics, EvalCase


def score_case(
    case: EvalCase,
    *,
    ranked_ids: Sequence[str],
    packed_ids: Sequence[str],
    token_count: int,
    latency_ms: float,
    supersession_pairs: Sequence[tuple[str, str]] = (),
    canary_ids: set[str] | frozenset[str] = frozenset(),
) -> CaseMetrics:
    """Score one case using top-k ranking and the actual packed source IDs."""

    top_k = list(ranked_ids[: case.k])
    packed = list(packed_ids)
    gold = set(case.gold_record_ids)
    if gold:
        recall_at_k = len(gold & set(top_k)) / len(gold)
        budget_recall = len(gold & set(packed)) / len(gold)
    else:
        recall_at_k = float(not top_k)
        budget_recall = float(not packed)

    non_gold_count = sum(record_id not in gold for record_id in packed)
    non_gold_share = non_gold_count / len(packed) if packed else 0.0
    packed_set = set(packed)
    stale_numerator = 0
    contradiction_numerator = 0
    pair_opportunities = 0
    for predecessor, successor in supersession_pairs:
        predecessor_packed = predecessor in packed_set
        successor_packed = successor in packed_set
        if predecessor_packed or successor_packed:
            pair_opportunities += 1
        if predecessor_packed and not successor_packed:
            stale_numerator += 1
        if predecessor_packed and successor_packed:
            contradiction_numerator += 1

    return CaseMetrics(
        case_id=case.id,
        category=case.category,
        gold_count=len(gold),
        ranked_ids=list(ranked_ids),
        packed_ids=packed,
        recall_at_k=recall_at_k,
        budget_recall=budget_recall,
        non_gold_share=non_gold_share,
        stale_numerator=stale_numerator,
        stale_denominator=pair_opportunities,
        contradiction_numerator=contradiction_numerator,
        contradiction_denominator=pair_opportunities,
        canary_count=sum(record_id in canary_ids for record_id in packed),
        packed_count=len(packed),
        token_count=token_count,
        token_budget=case.token_budget,
        token_utilization=token_count / case.token_budget,
        latency_ms=latency_ms,
        forbidden_surfaced_ids=sorted(set(case.forbidden_record_ids) & packed_set),
    )


def aggregate_metrics(cases: Sequence[CaseMetrics]) -> AggregateMetrics:
    if not cases:
        raise ValueError("cannot aggregate an empty evaluation")
    stale_denominator = sum(case.stale_denominator for case in cases)
    contradiction_denominator = sum(
        case.contradiction_denominator for case in cases
    )
    packed_count = sum(case.packed_count for case in cases)
    non_gold_count = sum(
        round(case.non_gold_share * case.packed_count) for case in cases
    )
    canary_count = sum(case.canary_count for case in cases)
    total_budget = sum(case.token_budget for case in cases)
    latencies = [case.latency_ms for case in cases]
    return AggregateMetrics(
        case_count=len(cases),
        recall_at_k=sum(case.recall_at_k for case in cases) / len(cases),
        budget_recall=sum(case.budget_recall for case in cases) / len(cases),
        non_gold_share=(non_gold_count / packed_count if packed_count else 0.0),
        stale_rate=(
            sum(case.stale_numerator for case in cases) / stale_denominator
            if stale_denominator
            else 0.0
        ),
        contradiction_rate=(
            sum(case.contradiction_numerator for case in cases)
            / contradiction_denominator
            if contradiction_denominator
            else 0.0
        ),
        canary_leakage=(canary_count / packed_count if packed_count else 0.0),
        canary_count=canary_count,
        token_utilization=sum(case.token_count for case in cases) / total_budget,
        latency_p50_ms=percentile(latencies, 50),
        latency_p95_ms=percentile(latencies, 95),
        latency_p99_ms=percentile(latencies, 99),
    )


def percentile(values: Sequence[float], percentile_value: float) -> float:
    """Return a linearly interpolated (Hyndman-Fan type 7) percentile."""

    if not values:
        raise ValueError("percentile needs at least one value")
    if not 0 <= percentile_value <= 100:
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * percentile_value / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


__all__ = ["aggregate_metrics", "percentile", "score_case"]
