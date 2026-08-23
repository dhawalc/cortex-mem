"""Run query suites through production ranking/packing with configurable ablations."""

from __future__ import annotations

import hashlib
import math
import platform
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from aoms.contracts import RecallRequest, ScopeContext
from aoms.embeddings import (
    EmbeddingProfile,
    EmbeddingProvider,
    EmbeddingVector,
    NullProvider,
    text_for_embedding,
)
from aoms.recall import (
    EmbeddingScorer,
    FTSScorer,
    RecallEngine,
    RecallRanker,
    RecencyScorer,
    ScopeSpecificityScorer,
)
from aoms.receipts import RecallReceipt
from aoms.repositories.base import RecallCandidate, RecallCandidateBatch
from aoms.repositories.sqlite import SQLiteMemoryRepository

from .corpus import BASE_TIME, EVAL_AGENT_ID, EVAL_WORKSPACE_ID
from .metrics import aggregate_metrics, score_case
from .models import (
    CorpusManifest,
    EngineConfig,
    EvalRun,
    QuerySuite,
    SyntheticCorpus,
)


PRESET_CONFIGS: dict[str, EngineConfig] = {
    "lexical-only": EngineConfig(
        name="lexical-only", lexical=True, vector=False, enforce_scope=True
    ),
    "vector-only": EngineConfig(
        name="vector-only", lexical=False, vector=True, enforce_scope=True
    ),
    "hybrid": EngineConfig(
        name="hybrid", lexical=True, vector=True, enforce_scope=True
    ),
    "no-supersession": EngineConfig(
        name="no-supersession",
        lexical=True,
        vector=True,
        enforce_scope=True,
        resolve_supersession=False,
    ),
    "no-scope": EngineConfig(
        name="no-scope", lexical=True, vector=True, enforce_scope=False
    ),
}


class DeterministicEmbeddingProvider:
    """Network-free hashed token vectors for reproducible synthetic runs."""

    profile = EmbeddingProfile("aoms-eval", "seeded-token-hash-v1", 64)
    _token_pattern = re.compile(r"[a-z0-9]+")

    async def embed_documents(
        self, texts: Sequence[str]
    ) -> list[EmbeddingVector | None]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, text: str) -> EmbeddingVector | None:
        return self._embed(text)

    @classmethod
    def _embed(cls, text: str) -> EmbeddingVector:
        vector = [0.0] * cls.profile.dimensions
        for token in cls._token_pattern.findall(text.casefold()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % cls.profile.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign
        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude == 0:
            vector[0] = 1.0
            return vector
        return [value / magnitude for value in vector]


class ReceiptCapture:
    """Writable receipt target kept outside a possibly read-only evaluated store."""

    def __init__(self) -> None:
        self.receipts: dict[str, RecallReceipt] = {}

    async def save_recall_receipt(self, receipt: RecallReceipt) -> None:
        self.receipts[receipt.receipt_id] = receipt


class ConfiguredRepository:
    """Apply retrieval-source and scope ablations without changing production code."""

    def __init__(self, repository: SQLiteMemoryRepository, config: EngineConfig):
        self.repository = repository
        self.config = config

    async def retrieve_recall_candidates(
        self,
        request: RecallRequest,
        *,
        limit: int = 100,
        query_vector: EmbeddingVector | None = None,
        vector_profile: EmbeddingProfile | None = None,
        scope_context: ScopeContext | None = None,
    ) -> RecallCandidateBatch:
        effective_request = (
            request
            if self.config.enforce_scope
            else request.model_copy(update={"scopes": None})
        )
        batch = await self.repository.retrieve_recall_candidates(
            effective_request,
            limit=limit,
            query_vector=(query_vector if self.config.vector else None),
            vector_profile=(vector_profile if self.config.vector else None),
            scope_context=(scope_context if self.config.enforce_scope else None),
        )
        candidates: list[RecallCandidate] = []
        for candidate in batch.candidates:
            if not self.config.lexical and "vector" not in candidate.retrieval_sources:
                continue
            candidates.append(
                RecallCandidate(
                    record=candidate.record,
                    fts_score=(candidate.fts_score if self.config.lexical else 0.0),
                    retrieval_sources=candidate.retrieval_sources,
                    vector_score=(candidate.vector_score if self.config.vector else None),
                )
            )
        return RecallCandidateBatch(
            candidates=tuple(candidates),
            scope_filtered_count=batch.scope_filtered_count,
        )


async def seed_fixture_repository(
    corpus: SyntheticCorpus,
    db_path: str | Path,
    *,
    embedding_provider: EmbeddingProvider | None = None,
) -> SQLiteMemoryRepository:
    """Create an isolated writable fixture store and populate deterministic vectors."""

    repository = SQLiteMemoryRepository(db_path)
    await repository.store_many(corpus.records)
    provider = embedding_provider or DeterministicEmbeddingProvider()
    if provider.profile is not None:
        texts = [text_for_embedding(record) for record in corpus.records]
        vectors = await provider.embed_documents(texts)
        for record, vector in zip(corpus.records, vectors, strict=True):
            if vector is not None:
                await repository.upsert_vector(record, provider.profile, vector)
    return repository


async def run_suite(
    repository: SQLiteMemoryRepository,
    suite: QuerySuite,
    config: EngineConfig,
    *,
    manifest: CorpusManifest | None = None,
    corpus_hash: str | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    scope_context: ScopeContext | None = None,
    environment: Mapping[str, Any] | None = None,
) -> EvalRun:
    """Run every case and return one self-contained machine-readable artifact."""

    provider: EmbeddingProvider = (
        embedding_provider or DeterministicEmbeddingProvider()
        if config.vector
        else NullProvider()
    )
    ranker = RecallRanker(
        [
            scorer
            for enabled, scorer in (
                (config.lexical, FTSScorer()),
                (config.vector, EmbeddingScorer()),
                (True, RecencyScorer()),
                (True, ScopeSpecificityScorer()),
            )
            if enabled
        ]
    )
    capture = ReceiptCapture()
    context = scope_context or ScopeContext(
        agent_id=EVAL_AGENT_ID, workspace_id=EVAL_WORKSPACE_ID
    )
    engine = RecallEngine(
        ConfiguredRepository(repository, config),  # type: ignore[arg-type]
        capture,  # type: ignore[arg-type]
        ranker=ranker,
        embedding_provider=provider,
        scope_context=context,
        candidate_limit=config.candidate_limit,
        receipt_top_n=config.candidate_limit,
        resolve_supersession=config.resolve_supersession,
        clock=(lambda: BASE_TIME + timedelta(days=400)) if corpus_hash else None,
    )
    supersession_pairs = manifest.supersession_pairs if manifest else []
    canary_ids = frozenset(manifest.canary_record_ids if manifest else [])
    case_metrics = []
    for case in suite.cases:
        result = await engine.recall(
            RecallRequest(
                task=case.query,
                token_budget=case.token_budget,
                kinds=case.kinds,
                scopes=case.scopes,
            )
        )
        receipt_id = str(result.diagnostics["receipt_id"])
        receipt = capture.receipts[receipt_id]
        case_metrics.append(
            score_case(
                case,
                ranked_ids=[item.memory_id for item in receipt.top_candidates],
                packed_ids=[source.memory_id for source in result.sources],
                token_count=result.token_count,
                latency_ms=receipt.latency_ms,
                supersession_pairs=supersession_pairs,
                canary_ids=canary_ids,
            )
        )

    now = datetime.now(timezone.utc)
    run_id = (
        f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-{config.name}-"
        f"{config.config_hash[:8]}-{uuid4().hex[:6]}"
    )
    detected_environment = {
        "python": platform.python_version(),
        "platform": sys.platform,
        "repository_read_only": repository.read_only,
    }
    detected_environment.update(environment or {})
    return EvalRun(
        run_id=run_id,
        created_at=now,
        suite_name=suite.name,
        suite_hash=suite.content_hash,
        corpus_hash=corpus_hash,
        engine_config=config,
        config_hash=config.config_hash,
        metrics=aggregate_metrics(case_metrics),
        cases=case_metrics,
        environment=detected_environment,
    )


async def run_matrix(
    repository: SQLiteMemoryRepository,
    suite: QuerySuite,
    configs: Sequence[EngineConfig],
    *,
    manifest: CorpusManifest | None = None,
    corpus_hash: str | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    scope_context: ScopeContext | None = None,
) -> list[EvalRun]:
    if not configs:
        raise ValueError("engine-config matrix must not be empty")
    return [
        await run_suite(
            repository,
            suite,
            config,
            manifest=manifest,
            corpus_hash=corpus_hash,
            embedding_provider=embedding_provider,
            scope_context=scope_context,
        )
        for config in configs
    ]


def resolve_configs(names: Sequence[str]) -> list[EngineConfig]:
    unknown = sorted(set(names) - set(PRESET_CONFIGS))
    if unknown:
        raise ValueError(
            f"unknown engine config(s): {', '.join(unknown)}; "
            f"choose from {', '.join(PRESET_CONFIGS)}"
        )
    return [PRESET_CONFIGS[name] for name in names]


__all__ = [
    "ConfiguredRepository",
    "DeterministicEmbeddingProvider",
    "PRESET_CONFIGS",
    "ReceiptCapture",
    "resolve_configs",
    "run_matrix",
    "run_suite",
    "seed_fixture_repository",
]
