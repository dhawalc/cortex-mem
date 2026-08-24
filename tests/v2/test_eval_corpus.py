from __future__ import annotations

from collections import Counter

import pytest

from aoms.eval.corpus import MIN_STARTER_RECORDS, generate_corpus
from aoms.eval.models import CaseCategory


def test_generator_is_deterministic_and_seed_controls_output() -> None:
    first = generate_corpus(record_count=96, seed=2026)
    repeated = generate_corpus(record_count=96, seed=2026)
    changed = generate_corpus(record_count=96, seed=2027)

    assert first.model_dump_json() == repeated.model_dump_json()
    assert first.content_hash == repeated.content_hash
    assert first.content_hash != changed.content_hash
    assert len(first.records) == 96
    assert {record.kind for record in first.records} == set(type(first.records[0].kind))
    assert {record.scope for record in first.records} == set(type(first.records[0].scope))


def test_starter_suite_has_six_cases_in_every_required_category() -> None:
    corpus = generate_corpus(record_count=MIN_STARTER_RECORDS, seed=9)
    composition = Counter(case.category for case in corpus.suite.cases)

    assert len(corpus.suite.cases) == 36
    assert composition == Counter({category: 6 for category in CaseCategory})
    assert len(corpus.manifest.supersession_pairs) == 6
    assert len(corpus.manifest.canary_record_ids) == 6
    assert {record.kind for record in corpus.records} == set(type(corpus.records[0].kind))
    assert {record.scope for record in corpus.records} == set(
        type(corpus.records[0].scope)
    )


def test_generator_rejects_corpus_too_small_for_starter_gold() -> None:
    with pytest.raises(ValueError, match="at least 78"):
        generate_corpus(record_count=77)
