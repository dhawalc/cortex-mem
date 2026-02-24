"""
openclaw-memory AOMS — Always-On Memory Service.

FastAPI server providing:
- 4-tier JSONL memory (Episodic, Semantic, Procedural) with weighted retrieval
- Cortex L0/L1/L2 progressive disclosure for large documents
"""
import logging
import time
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Query

from .models import (
    CortexIngest,
    CortexQuery,
    HealthResponse,
    MemorySearch,
    MemoryWrite,
    WeightUpdate,
)
from .storage import ALL_TIERS, TIER_FILE_MAP, MemoryStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("aoms")

CONFIG_PATH = Path(__file__).parent / "config.yaml"

with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

MEMORY_ROOT = Path(config["storage"]["root"])
VERSION = "1.1.0"

app = FastAPI(
    title="openclaw-memory",
    description="Always-On Memory Service — unified memory + Cortex L0/L1/L2 tiered retrieval",
    version=VERSION,
)

storage = MemoryStorage(MEMORY_ROOT)
_start_time = time.monotonic()

# Lazy-init cortex components (heavy deps: chromadb, sqlite)
_tier_generator = None
_tiered_retriever = None


def _get_generator():
    global _tier_generator
    if _tier_generator is None:
        from cortex.tier_generator import TierGenerator
        _tier_generator = TierGenerator()
    return _tier_generator


def _get_retriever():
    global _tiered_retriever
    if _tiered_retriever is None:
        from cortex.tiered_retrieval import TieredRetriever
        _tiered_retriever = TieredRetriever()
    return _tiered_retriever


# ========================================
# MEMORY TIER ENDPOINTS (JSONL)
# ========================================

@app.post("/memory/search")
async def search_memory(search: MemorySearch):
    """Keyword search across memory tiers with weighted scoring."""
    if search.tier:
        invalid = [t for t in search.tier if t not in TIER_FILE_MAP]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tier(s): {invalid}. Valid: {ALL_TIERS}",
            )

    results = await storage.search(
        query=search.query,
        tiers=search.tier,
        limit=search.limit,
        date_from=search.date_from,
        date_to=search.date_to,
        min_weight=search.min_weight,
    )

    return {
        "query": search.query,
        "total": len(results),
        "results": results,
    }


@app.post("/memory/weight")
async def update_weight(update: WeightUpdate):
    """Adjust a memory entry's weight based on task outcome (reinforcement)."""
    if update.tier not in TIER_FILE_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tier '{update.tier}'. Valid: {ALL_TIERS}",
        )

    result = await storage.adjust_weight(
        entry_id=update.entry_id,
        tier=update.tier,
        task_score=update.task_score,
    )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Entry '{update.entry_id}' not found in tier '{update.tier}'",
        )

    return {
        "status": "ok",
        "id": update.entry_id,
        "new_weight": result["weight"],
    }


@app.post("/memory/{tier}")
async def write_memory(tier: str, entry: MemoryWrite):
    """Append an entry to a memory tier's JSONL log."""
    if tier not in TIER_FILE_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tier '{tier}'. Valid tiers: {ALL_TIERS}",
        )

    record = await storage.append(
        tier=tier,
        entry_type=entry.type,
        payload=entry.payload,
        tags=entry.tags,
        weight=entry.weight,
    )

    return {
        "status": "ok",
        "tier": tier,
        "type": entry.type,
        "id": record["id"],
    }


@app.get("/memory/browse/{path:path}")
async def browse_directory(path: str = ""):
    """Browse the module tree at a given path."""
    result = await storage.browse(path)
    if not result["exists"]:
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")
    return result


@app.get("/memory/browse")
async def browse_root():
    """Browse the root of the module tree."""
    return await storage.browse("")


# ========================================
# CORTEX L0/L1/L2 ENDPOINTS
# ========================================

@app.post("/cortex/ingest")
async def cortex_ingest(req: CortexIngest):
    """Ingest a document: store L2, auto-generate L0/L1 via Ollama, index in ChromaDB."""
    gen = _get_generator()

    try:
        doc_id = await gen.ingest_document(
            content=req.content,
            title=req.title,
            hierarchy_path=req.hierarchy_path,
            doc_type=req.doc_type,
            tags=req.tags,
        )
    except Exception as e:
        logger.error(f"Cortex ingest failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    from cortex import db as cortex_db
    doc = cortex_db.get_document(gen.conn, doc_id)

    return {
        "status": "ok",
        "doc_id": doc_id,
        "title": req.title,
        "l0_tokens": doc["l0_token_count"] if doc else 0,
        "l1_tokens": doc["l1_token_count"] if doc else 0,
        "l2_tokens": doc["l2_token_count"] if doc else 0,
    }


@app.post("/cortex/query")
async def cortex_query(req: CortexQuery):
    """Smart tiered query with auto-escalation (L0 → L1 → L2) within token budget."""
    retriever = _get_retriever()

    try:
        response = await retriever.smart_query(
            query=req.query,
            token_budget=req.token_budget,
            top_k=req.top_k,
            directory=req.directory,
            agent_id=req.agent_id,
        )
    except Exception as e:
        logger.error(f"Cortex query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return response.to_dict()


@app.get("/cortex/document/{doc_id}")
async def cortex_get_document(
    doc_id: str,
    tier: str = Query(default="l0", regex="^(l0|l1|l2)$"),
):
    """Get a specific tier of a document."""
    retriever = _get_retriever()

    result = await retriever.get_document_tier(doc_id, tier=tier)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")

    return result


@app.post("/cortex/regenerate/{doc_id}")
async def cortex_regenerate(doc_id: str):
    """Re-generate L0/L1 for an existing document (e.g., after L2 content changed)."""
    gen = _get_generator()

    success = await gen.regenerate(doc_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found or L2 file missing")

    return {"status": "ok", "doc_id": doc_id, "regenerated": True}


@app.get("/cortex/documents")
async def cortex_list_documents():
    """List all documents in the cortex index."""
    from cortex import db as cortex_db
    retriever = _get_retriever()
    docs = cortex_db.get_all_documents(retriever.conn)

    return {
        "total": len(docs),
        "documents": [
            {
                "doc_id": d["doc_id"],
                "title": d["title"],
                "hierarchy_path": d["hierarchy_path"],
                "doc_type": d["doc_type"],
                "l0_tokens": d["l0_token_count"],
                "l1_tokens": d.get("l1_token_count", 0),
                "l2_tokens": d.get("l2_token_count", 0),
                "is_stale": d.get("is_stale", False),
            }
            for d in docs
        ],
    }


# ========================================
# HEALTH
# ========================================

@app.get("/health")
async def health_check():
    """Service health check with tier entry counts."""
    counts = await storage.count_entries()
    uptime = time.monotonic() - _start_time

    return HealthResponse(
        status="ok",
        service="openclaw-memory",
        version=VERSION,
        uptime_seconds=round(uptime, 1),
        memory_root=str(MEMORY_ROOT),
        tiers=counts,
    )


def main():
    """Run the server directly."""
    import uvicorn

    host = config["service"]["host"]
    port = config["service"]["port"]
    logger.info(f"Starting openclaw-memory AOMS on {host}:{port}")
    uvicorn.run(
        "service.api:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
