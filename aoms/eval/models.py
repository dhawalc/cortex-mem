"""Typed, serializable contracts for retrieval evaluation artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aoms.contracts import MemoryKind, MemoryRecord, Scope


class EvalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseCategory(str, Enum):
    EXACT_RECALL = "exact-recall"
    TEMPORAL = "temporal"
    CROSS_KIND = "cross-kind"
    SCOPE_FILTERING = "scope-filtering"
    BUDGET_PRESSURE = "budget-pressure"
    NEGATIVE = "negative"


class EvalCase(EvalModel):
    """One query with explicit positive, negative, and packing expectations."""

    id: str = Field(min_length=1)
    category: CaseCategory
    query: str = Field(min_length=1)
    gold_record_ids: list[str] = Field(default_factory=list)
    forbidden_record_ids: list[str] = Field(default_factory=list)
    token_budget: int = Field(ge=1, le=100_000)
    k: int = Field(default=10, ge=1, le=100)
    kinds: list[MemoryKind] | None = None
    scopes: list[Scope] | None = None
    notes: str | None = None

    @field_validator("gold_record_ids", "forbidden_record_ids")
    @classmethod
    def ids_are_unique(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def positive_and_forbidden_do_not_overlap(self) -> EvalCase:
        overlap = set(self.gold_record_ids) & set(self.forbidden_record_ids)
        if overlap:
            raise ValueError(f"gold and forbidden ids overlap: {sorted(overlap)}")
        if self.category is CaseCategory.NEGATIVE and self.gold_record_ids:
            raise ValueError("negative cases cannot declare gold records")
        return self


class QuerySuite(EvalModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    cases: list[EvalCase] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> QuerySuite:
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("query-suite case ids must be unique")
        return self

    @property
    def content_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class CorpusManifest(EvalModel):
    seed: int
    record_count: int = Field(ge=1)
    canary_record_ids: list[str] = Field(default_factory=list)
    supersession_pairs: list[tuple[str, str]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SyntheticCorpus(EvalModel):
    records: list[MemoryRecord] = Field(min_length=1)
    suite: QuerySuite
    manifest: CorpusManifest

    @model_validator(mode="after")
    def manifest_matches_records(self) -> SyntheticCorpus:
        ids = [record.id for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("corpus record ids must be unique")
        if self.manifest.record_count != len(ids):
            raise ValueError("manifest record_count does not match records")
        missing = (
            set(self.manifest.canary_record_ids)
            | {item for pair in self.manifest.supersession_pairs for item in pair}
            | {
                item
                for case in self.suite.cases
                for item in [*case.gold_record_ids, *case.forbidden_record_ids]
            }
        ) - set(ids)
        if missing:
            raise ValueError(f"manifest or suite references missing records: {sorted(missing)}")
        return self

    @property
    def content_hash(self) -> str:
        return stable_hash(
            {
                "record_ids": [record.id for record in self.records],
                "records": [record.model_dump(mode="json") for record in self.records],
                "manifest": self.manifest.model_dump(mode="json"),
            }
        )


class EngineConfig(EvalModel):
    name: str = Field(min_length=1)
    lexical: bool = True
    vector: bool = False
    enforce_scope: bool = True
    candidate_limit: int = Field(default=100, ge=1, le=10_000)

    @model_validator(mode="after")
    def has_retrieval_signal(self) -> EngineConfig:
        if not self.lexical and not self.vector:
            raise ValueError("an engine config needs lexical and/or vector retrieval")
        return self

    @property
    def config_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class CaseMetrics(EvalModel):
    case_id: str
    category: CaseCategory
    gold_count: int = Field(ge=0)
    ranked_ids: list[str]
    packed_ids: list[str]
    recall_at_k: float = Field(ge=0.0, le=1.0)
    budget_recall: float = Field(ge=0.0, le=1.0)
    non_gold_share: float = Field(ge=0.0, le=1.0)
    stale_numerator: int = Field(ge=0)
    stale_denominator: int = Field(ge=0)
    contradiction_numerator: int = Field(ge=0)
    contradiction_denominator: int = Field(ge=0)
    canary_count: int = Field(ge=0)
    packed_count: int = Field(ge=0)
    token_count: int = Field(ge=0)
    token_budget: int = Field(ge=1)
    token_utilization: float = Field(ge=0.0, le=1.0)
    latency_ms: float = Field(ge=0.0)
    forbidden_surfaced_ids: list[str] = Field(default_factory=list)


class AggregateMetrics(EvalModel):
    case_count: int = Field(ge=1)
    recall_at_k: float = Field(ge=0.0, le=1.0)
    budget_recall: float = Field(ge=0.0, le=1.0)
    non_gold_share: float = Field(ge=0.0, le=1.0)
    stale_rate: float = Field(ge=0.0, le=1.0)
    contradiction_rate: float = Field(ge=0.0, le=1.0)
    canary_leakage: float = Field(ge=0.0, le=1.0)
    canary_count: int = Field(ge=0)
    token_utilization: float = Field(ge=0.0, le=1.0)
    latency_p50_ms: float = Field(ge=0.0)
    latency_p95_ms: float = Field(ge=0.0)
    latency_p99_ms: float = Field(ge=0.0)


class EvalRun(EvalModel):
    schema_version: int = 1
    run_id: str = Field(min_length=1)
    created_at: datetime
    suite_name: str
    suite_hash: str
    corpus_hash: str | None = None
    engine_config: EngineConfig
    config_hash: str
    metrics: AggregateMetrics
    cases: list[CaseMetrics]
    environment: dict[str, Any] = Field(default_factory=dict)


class MetricDelta(EvalModel):
    baseline: float
    current: float
    delta: float


class RunComparison(EvalModel):
    baseline_run_id: str
    current_run_id: str
    same_config: bool
    same_suite: bool
    deltas: dict[str, MetricDelta]


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "AggregateMetrics",
    "CaseCategory",
    "CaseMetrics",
    "CorpusManifest",
    "EngineConfig",
    "EvalCase",
    "EvalRun",
    "MetricDelta",
    "QuerySuite",
    "RunComparison",
    "SyntheticCorpus",
    "stable_hash",
]
