"""Built-in and JSON-backed retrieval query suites."""

from __future__ import annotations

from pathlib import Path

from aoms.contracts import MemoryKind

from .models import CaseCategory, EvalCase, QuerySuite


STARTER_CASES_PER_CATEGORY = 6


def starter_suite() -> QuerySuite:
    """Return the 36-case suite paired with :func:`generate_corpus`."""

    cases: list[EvalCase] = []
    for index in range(STARTER_CASES_PER_CATEGORY):
        cases.append(
            EvalCase(
                id=f"exact-{index:02d}",
                category=CaseCategory.EXACT_RECALL,
                query=f"What is the exact quartz{index} launch code?",
                gold_record_ids=[f"gold-exact-{index:02d}"],
                forbidden_record_ids=[f"distractor-exact-{index:02d}"],
                token_budget=420,
                k=5,
                notes="Exact lexical identifier with a near-duplicate distractor.",
            )
        )
        cases.append(
            EvalCase(
                id=f"temporal-{index:02d}",
                category=CaseCategory.TEMPORAL,
                query=f"What is the current comet{index} deployment region?",
                gold_record_ids=[f"gold-temporal-new-{index:02d}"],
                forbidden_record_ids=[f"stale-temporal-old-{index:02d}"],
                token_budget=420,
                k=5,
                notes="Newest successor is gold; the obsolete predecessor is forbidden.",
            )
        )
        cases.append(
            EvalCase(
                id=f"cross-kind-{index:02d}",
                category=CaseCategory.CROSS_KIND,
                query=f"Assemble the atlas{index} release context.",
                gold_record_ids=[
                    f"gold-cross-fact-{index:02d}",
                    f"gold-cross-decision-{index:02d}",
                    f"gold-cross-procedure-{index:02d}",
                ],
                forbidden_record_ids=[f"distractor-cross-{index:02d}"],
                token_budget=760,
                k=8,
                notes="Relevant evidence is split across fact, decision, and procedure.",
            )
        )
        cases.append(
            EvalCase(
                id=f"scope-{index:02d}",
                category=CaseCategory.SCOPE_FILTERING,
                query=f"What is the harbor{index} workspace canary value?",
                gold_record_ids=[f"gold-scope-{index:02d}"],
                forbidden_record_ids=[f"canary-foreign-{index:02d}"],
                token_budget=420,
                k=5,
                notes="A stronger lexical match exists only in an inaccessible scope.",
            )
        )
        cases.append(
            EvalCase(
                id=f"budget-{index:02d}",
                category=CaseCategory.BUDGET_PRESSURE,
                query=f"Summarize the priority nebula{index} incident facts.",
                gold_record_ids=[
                    f"gold-budget-primary-{index:02d}",
                    f"gold-budget-secondary-{index:02d}",
                ],
                forbidden_record_ids=[f"distractor-budget-{index:02d}"],
                token_budget=260,
                k=6,
                notes=(
                    "Two gold records cannot both fit; ranking should pack the concise "
                    "primary fact before a verbose distractor."
                ),
            )
        )
        cases.append(
            EvalCase(
                id=f"negative-{index:02d}",
                category=CaseCategory.NEGATIVE,
                query=f"Find nonexistent zephyrlattice{index} evidence.",
                gold_record_ids=[],
                forbidden_record_ids=[],
                token_budget=260,
                k=5,
                kinds=[MemoryKind.RELATION],
                notes="No relevant record exists; an empty result is fully correct.",
            )
        )

    return QuerySuite(
        name="starter-retrieval-credibility",
        version="1.0",
        cases=cases,
        metadata={
            "case_count": len(cases),
            "categories": {
                category.value: STARTER_CASES_PER_CATEGORY for category in CaseCategory
            },
        },
    )


def load_suite(path: str | Path) -> QuerySuite:
    return QuerySuite.model_validate_json(Path(path).read_text(encoding="utf-8"))


def save_suite(suite: QuerySuite, path: str | Path) -> None:
    Path(path).write_text(suite.model_dump_json(indent=2), encoding="utf-8")


__all__ = ["STARTER_CASES_PER_CATEGORY", "load_suite", "save_suite", "starter_suite"]
