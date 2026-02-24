"""
TieredRetriever — hierarchical L0→L1→L2 retrieval with token budgets.

Algorithm:
1. Search L0 abstracts via ChromaDB (top_k, fast, ~100 tok/result)
2. If top score > threshold, auto-expand best results to L1 (~2K tok)
3. Only load L2 (full doc) when score > high threshold and budget allows
"""
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import db
from .tier_generator import _get_chroma_client, _estimate_tokens

logger = logging.getLogger("aoms.cortex")

L1_EXPAND_THRESHOLD = 0.4
L2_LOAD_THRESHOLD = 0.7
DEFAULT_TOKEN_BUDGET = 4000
DEFAULT_TOP_K = 10


@dataclass
class TieredResult:
    """A single retrieval result with progressive disclosure."""
    doc_id: str
    title: str
    hierarchy_path: str
    doc_type: str
    score: float
    l0_abstract: str = ""
    l1_overview: Optional[str] = None
    l2_content: Optional[str] = None
    l0_tokens: int = 0
    l1_tokens: int = 0
    l2_tokens: int = 0
    tier_loaded: str = "l0"

    @property
    def total_tokens(self) -> int:
        if self.l2_content is not None:
            return self.l2_tokens
        if self.l1_overview is not None:
            return self.l1_tokens
        return self.l0_tokens

    def to_dict(self) -> Dict:
        d = {
            "doc_id": self.doc_id,
            "title": self.title,
            "hierarchy_path": self.hierarchy_path,
            "doc_type": self.doc_type,
            "score": round(self.score, 4),
            "tier_loaded": self.tier_loaded,
            "tokens_used": self.total_tokens,
            "l0_abstract": self.l0_abstract,
        }
        if self.l1_overview is not None:
            d["l1_overview"] = self.l1_overview
        if self.l2_content is not None:
            d["l2_content"] = self.l2_content
        return d


@dataclass
class RetrievalResponse:
    """Response from a tiered query."""
    query: str
    results: List[TieredResult] = field(default_factory=list)
    total_tokens: int = 0
    l0_count: int = 0
    l1_count: int = 0
    l2_count: int = 0
    latency_ms: int = 0

    def to_dict(self) -> Dict:
        return {
            "query": self.query,
            "total_results": len(self.results),
            "total_tokens": self.total_tokens,
            "tiers": {"l0": self.l0_count, "l1": self.l1_count, "l2": self.l2_count},
            "latency_ms": self.latency_ms,
            "results": [r.to_dict() for r in self.results],
        }


class TieredRetriever:
    """Hierarchical, tier-aware retrieval with token budgets."""

    def __init__(self, db_conn=None):
        self.conn = db_conn or db.init_db()
        self._chroma = None

    @property
    def chroma(self):
        if self._chroma is None:
            self._chroma = _get_chroma_client()
        return self._chroma

    @property
    def l0_collection(self):
        return self.chroma.get_or_create_collection(
            "cortex_l0", metadata={"hnsw:space": "cosine"}
        )

    @property
    def l1_collection(self):
        return self.chroma.get_or_create_collection(
            "cortex_l1", metadata={"hnsw:space": "cosine"}
        )

    async def retrieve_l0(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        directory: Optional[str] = None,
        min_score: float = 0.0,
    ) -> RetrievalResponse:
        """Search L0 abstracts only. Fast, cheap (~100 tok/result)."""
        start = time.monotonic()

        where = None
        if directory:
            where = {"hierarchy_path": {"$contains": directory}}

        chroma_results = self.l0_collection.query(
            query_texts=[query],
            n_results=min(top_k, self.l0_collection.count() or 1),
            where=where if where else None,
        )

        results = []
        ids = chroma_results["ids"][0] if chroma_results["ids"] else []
        distances = chroma_results["distances"][0] if chroma_results["distances"] else []

        for doc_id, distance in zip(ids, distances):
            score = max(0, 1.0 - distance)
            if score < min_score:
                continue

            doc = db.get_document(self.conn, doc_id)
            if doc is None:
                continue

            results.append(TieredResult(
                doc_id=doc_id,
                title=doc["title"],
                hierarchy_path=doc["hierarchy_path"],
                doc_type=doc["doc_type"],
                score=score,
                l0_abstract=doc["l0_abstract"],
                l0_tokens=doc["l0_token_count"],
                tier_loaded="l0",
            ))

        elapsed = int((time.monotonic() - start) * 1000)
        total_tokens = sum(r.l0_tokens for r in results)

        response = RetrievalResponse(
            query=query,
            results=results,
            total_tokens=total_tokens,
            l0_count=len(results),
            latency_ms=elapsed,
        )

        db.log_query(
            self.conn, query, l0_results=len(results),
            l1_expansions=0, l2_loads=0,
            total_tokens=total_tokens, latency_ms=elapsed,
        )

        return response

    async def expand_to_l1(
        self,
        response: RetrievalResponse,
        indices: Optional[List[int]] = None,
        score_threshold: float = L1_EXPAND_THRESHOLD,
    ) -> RetrievalResponse:
        """Expand selected L0 results to L1 overviews."""
        expanded = 0
        for i, result in enumerate(response.results):
            if indices is not None and i not in indices:
                continue
            if result.score < score_threshold:
                continue
            if result.tier_loaded != "l0":
                continue

            doc = db.get_document(self.conn, result.doc_id)
            if doc and doc.get("l1_overview"):
                result.l1_overview = doc["l1_overview"]
                result.l1_tokens = doc["l1_token_count"]
                result.tier_loaded = "l1"
                expanded += 1

        response.l1_count = expanded
        response.total_tokens = sum(r.total_tokens for r in response.results)
        return response

    async def load_l2(
        self,
        response: RetrievalResponse,
        indices: List[int],
    ) -> RetrievalResponse:
        """Load full L2 content for specific results."""
        loaded = 0
        for i in indices:
            if i >= len(response.results):
                continue
            result = response.results[i]
            doc = db.get_document(self.conn, result.doc_id)
            if doc is None:
                continue

            l2_path = Path(doc["l2_file_path"])
            if l2_path.exists():
                result.l2_content = l2_path.read_text(encoding="utf-8")
                result.l2_tokens = doc["l2_token_count"]
                result.tier_loaded = "l2"
                loaded += 1

        response.l2_count = loaded
        response.total_tokens = sum(r.total_tokens for r in response.results)
        return response

    async def smart_query(
        self,
        query: str,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        top_k: int = DEFAULT_TOP_K,
        directory: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> RetrievalResponse:
        """
        Auto-escalating query that stays within token budget.

        Algorithm:
        1. Search L0 (top_k results)
        2. If top score > L1_EXPAND_THRESHOLD, expand top 3 to L1
        3. Only load L2 if score > L2_LOAD_THRESHOLD and budget allows
        """
        start = time.monotonic()

        # Step 1: L0 scan
        response = await self.retrieve_l0(query, top_k=top_k, directory=directory)

        if not response.results:
            return response

        tokens_used = response.total_tokens
        top_score = response.results[0].score if response.results else 0

        # Step 2: Auto-expand to L1 if warranted
        if top_score >= L1_EXPAND_THRESHOLD:
            expand_indices = []
            for i, r in enumerate(response.results):
                if r.score >= L1_EXPAND_THRESHOLD:
                    candidate_tokens = tokens_used + 2000
                    if candidate_tokens <= token_budget:
                        expand_indices.append(i)
                    if len(expand_indices) >= 3:
                        break

            if expand_indices:
                response = await self.expand_to_l1(response, indices=expand_indices)
                tokens_used = response.total_tokens

        # Step 3: Auto-load L2 for very high scoring results
        if top_score >= L2_LOAD_THRESHOLD and response.results:
            for i, r in enumerate(response.results):
                if r.score >= L2_LOAD_THRESHOLD and r.tier_loaded in ("l0", "l1"):
                    doc = db.get_document(self.conn, r.doc_id)
                    if doc and (tokens_used + doc["l2_token_count"]) <= token_budget:
                        response = await self.load_l2(response, [i])
                        tokens_used = response.total_tokens
                        break

        elapsed = int((time.monotonic() - start) * 1000)
        response.latency_ms = elapsed
        response.total_tokens = tokens_used

        db.log_query(
            self.conn, query,
            l0_results=response.l0_count,
            l1_expansions=response.l1_count,
            l2_loads=response.l2_count,
            total_tokens=tokens_used,
            latency_ms=elapsed,
            agent_id=agent_id,
        )

        return response

    async def get_document_tier(
        self, doc_id: str, tier: str = "l0"
    ) -> Optional[Dict]:
        """Get a specific tier of a document."""
        doc = db.get_document(self.conn, doc_id)
        if doc is None:
            return None

        result = {
            "doc_id": doc_id,
            "title": doc["title"],
            "hierarchy_path": doc["hierarchy_path"],
            "doc_type": doc["doc_type"],
            "tier": tier,
        }

        if tier == "l0":
            result["content"] = doc["l0_abstract"]
            result["tokens"] = doc["l0_token_count"]
        elif tier == "l1":
            result["content"] = doc.get("l1_overview") or doc["l0_abstract"]
            result["tokens"] = doc.get("l1_token_count") or doc["l0_token_count"]
        elif tier == "l2":
            l2_path = Path(doc["l2_file_path"])
            if l2_path.exists():
                result["content"] = l2_path.read_text(encoding="utf-8")
                result["tokens"] = doc["l2_token_count"]
            else:
                result["content"] = doc.get("l1_overview") or doc["l0_abstract"]
                result["tokens"] = doc.get("l1_token_count") or doc["l0_token_count"]
                result["tier"] = "l1"
                result["fallback"] = True
        else:
            return None

        return result
