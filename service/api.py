"""
openclaw-memory AOMS — Always-On Memory Service.

FastAPI server providing:
- 4-tier JSONL memory (Episodic, Semantic, Procedural) with weighted retrieval
- Cortex L0/L1/L2 progressive disclosure for large documents
"""
import asyncio
import logging
import time
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Query

from .models import (
    ConsolidateRequest,
    CortexIngest,
    CortexQuery,
    DecayRequest,
    EntityExtractRequest,
    HealthResponse,
    MemorySearch,
    MemoryWrite,
    RecallRequest,
    RecallResponse,
    SemanticSearch,
    StatsResponse,
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

_raw_root = Path(config["storage"]["root"])
MEMORY_ROOT = _raw_root if _raw_root.is_absolute() else (CONFIG_PATH.parent.parent / _raw_root).resolve()
VERSION = "1.2.0"

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
    tier: str = Query(default="l0", pattern="^(l0|l1|l2)$"),
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
# SEMANTIC SEARCH (Vector)
# ========================================

@app.post("/memory/semantic-search")
async def semantic_search_memory(search: SemanticSearch):
    """Semantic (vector) search across memory tiers using embeddings."""
    from . import embeddings, vector_store
    
    # Get query embedding
    query_embedding = await embeddings.get_embedding(search.query)
    if query_embedding is None:
        raise HTTPException(
            status_code=503,
            detail="Embedding service unavailable. Is Ollama running with nomic-embed-text?"
        )
    
    # Vector search
    vector_results = await vector_store.semantic_search(
        query_embedding=query_embedding,
        tiers=search.tier,
        limit=search.limit,
        min_score=search.min_score,
    )
    
    results = []
    for tier, entry_id, score, metadata, document in vector_results:
        results.append({
            "tier": tier,
            "id": entry_id,
            "score": round(score, 4),
            "metadata": metadata,
            "preview": document[:200] if document else "",
        })
    
    # Optionally combine with keyword search
    if search.hybrid:
        keyword_results = await storage.search(
            query=search.query,
            tiers=search.tier,
            limit=search.limit,
        )
        
        # Merge and dedupe by ID
        seen_ids = {r["id"] for r in results}
        for kr in keyword_results:
            entry_id = kr["entry"].get("id")
            if entry_id and entry_id not in seen_ids:
                results.append({
                    "tier": kr["tier"],
                    "id": entry_id,
                    "score": kr["score"] * 0.8,  # Slightly lower weight for keyword
                    "metadata": {"type": kr["type"]},
                    "preview": str(kr["entry"])[:200],
                })
                seen_ids.add(entry_id)
        
        results.sort(key=lambda x: x["score"], reverse=True)
        results = results[:search.limit]
    
    return {
        "query": search.query,
        "total": len(results),
        "hybrid": search.hybrid,
        "results": results,
    }


# ========================================
# AGENT RECALL
# ========================================

@app.post("/recall", response_model=RecallResponse)
async def agent_recall(req: RecallRequest):
    """
    Single endpoint for agents to get relevant context.
    
    Searches across tiers, formats results for prompt injection.
    """
    from . import embeddings, vector_store
    
    tiers = req.tiers or ["episodic", "semantic", "procedural"]
    sources = []
    
    # Semantic (vector) search with a SHORT timeout + graceful keyword fallback.
    # Re-enabled 2026-05-26: nomic-embed-text is now pulled. The 8s cap means a
    # slow/absent embedding model degrades to keyword search instead of hanging
    # the endpoint (the reason this was originally disabled).
    query_embedding = None
    try:
        query_embedding = await asyncio.wait_for(
            embeddings.get_embedding(req.task), timeout=8.0
        )
    except asyncio.TimeoutError:
        logger.warning("Embedding timed out (8s), falling back to keyword search")
    except Exception as e:
        logger.warning(f"Embedding failed: {e}, falling back to keyword search")
    
    if query_embedding:
        vector_results = await vector_store.semantic_search(
            query_embedding=query_embedding,
            tiers=tiers,
            limit=20,
            min_score=0.35,
        )
        for tier, entry_id, score, metadata, document in vector_results:
            sources.append({
                "tier": tier,
                "id": entry_id,
                "score": score,
                "content": document,
                "type": metadata.get("_type", "unknown"),
            })
    
    # Supplement with keyword search ONLY when vector search was unavailable or
    # returned few hits. The keyword path scans the multi-GB JSONL files (and
    # chokes on the legacy blob lines), so we keep it off the hot path once
    # embeddings are working.
    if len(sources) < 8:
        keyword_results = await storage.search(
            query=req.task,
            tiers=tiers,
            limit=20,
        )

        seen_ids = {s["id"] for s in sources}
        for kr in keyword_results:
            entry_id = kr["entry"].get("id")
            if entry_id and entry_id not in seen_ids:
                entry = kr["entry"]
                sources.append({
                    "tier": kr["tier"],
                    "id": entry_id,
                    "score": kr["score"],
                    # facts/skills have no "content" field; render from their
                    # structured fields so they contribute real text, not "".
                    "content": entry.get("content") or embeddings.text_for_embedding(entry),
                    "type": kr["type"],
                })
    
    # Sort by score and build context
    sources.sort(key=lambda x: x["score"], reverse=True)
    
    # Format context within token budget
    context_parts = []
    total_tokens = 0
    included_sources = []
    
    # Tier headers
    tier_names = {
        "episodic": "Past Experiences",
        "semantic": "Known Facts", 
        "procedural": "Skills & Patterns",
    }
    
    if req.format == "markdown":
        context_parts.append("## Relevant Memory\n")
        total_tokens += 5
        
        current_tier = None
        for src in sources:
            # Estimate tokens (~4 chars per token)
            content_tokens = len(src["content"]) // 4
            
            if total_tokens + content_tokens > req.token_budget:
                break
            
            if src["tier"] != current_tier:
                current_tier = src["tier"]
                header = f"\n### {tier_names.get(current_tier, current_tier)}\n"
                context_parts.append(header)
                total_tokens += 5
            
            context_parts.append(f"- {src['content'][:500]}\n")
            total_tokens += content_tokens
            included_sources.append(src)
    
    elif req.format == "json":
        import json
        for src in sources:
            content_tokens = len(src["content"]) // 4
            if total_tokens + content_tokens > req.token_budget:
                break
            total_tokens += content_tokens
            included_sources.append(src)
        context_parts.append(json.dumps(included_sources, indent=2))
    
    else:  # plain
        for src in sources:
            content_tokens = len(src["content"]) // 4
            if total_tokens + content_tokens > req.token_budget:
                break
            context_parts.append(src["content"][:500] + "\n---\n")
            total_tokens += content_tokens
            included_sources.append(src)
    
    return RecallResponse(
        context="".join(context_parts),
        tokens=total_tokens,
        sources=included_sources,
        tiers_searched=tiers,
    )


# ========================================
# WEIGHT DECAY
# ========================================

@app.post("/memory/decay")
async def decay_weights(req: DecayRequest):
    """
    Apply time-based weight decay to old memories.
    
    Memories naturally fade unless reinforced.
    """
    from datetime import datetime, timezone, timedelta
    import json
    
    tiers = [req.tier] if req.tier else ALL_TIERS
    cutoff = datetime.now(timezone.utc) - timedelta(days=req.min_age_days)
    
    total_decayed = 0
    total_scanned = 0
    preview = []
    
    for tier in tiers:
        for filepath in storage._all_files_for_tier(tier):
            if not filepath.exists():
                continue
            
            lines = filepath.read_text(encoding="utf-8").splitlines()
            new_lines = []
            
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    new_lines.append(line)
                    continue
                
                try:
                    entry = json.loads(stripped)
                except json.JSONDecodeError:
                    new_lines.append(line)
                    continue
                
                if "schema" in entry:
                    new_lines.append(line)
                    continue
                
                total_scanned += 1
                
                # Check age
                ts = entry.get("ts") or entry.get("_written_at")
                if not ts:
                    new_lines.append(line)
                    continue
                
                try:
                    # Handle both float (unix timestamp) and string (ISO) formats
                    if isinstance(ts, (int, float)):
                        entry_time = datetime.fromtimestamp(ts, tz=timezone.utc)
                    else:
                        entry_time = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    
                    if entry_time > cutoff:
                        new_lines.append(line)
                        continue
                except (ValueError, TypeError, OSError):
                    new_lines.append(line)
                    continue
                
                # Apply decay
                old_weight = entry.get("weight", 1.0)
                days_old = (datetime.now(timezone.utc) - entry_time).days
                new_weight = old_weight * (req.decay_rate ** days_old)
                # Floor raised 0.1 -> 0.3 (2026-05-26): with no working reinforcement
                # caller, months of nightly decay had flattened every weight to the
                # 0.1 floor (weight_distribution.high == 0). 0.3 keeps decayed memories
                # rankable in keyword fallback. (Vector recall is weight-independent.)
                new_weight = max(0.3, min(5.0, new_weight))
                
                if abs(old_weight - new_weight) > 0.001:
                    if req.dry_run and len(preview) < 10:
                        preview.append({
                            "id": entry.get("id"),
                            "old_weight": round(old_weight, 4),
                            "new_weight": round(new_weight, 4),
                            "days_old": days_old,
                        })
                    
                    if not req.dry_run:
                        entry["weight"] = round(new_weight, 4)
                        entry["_decay_applied_at"] = datetime.now(timezone.utc).isoformat()
                        new_lines.append(json.dumps(entry, ensure_ascii=False) + "\n")
                        total_decayed += 1
                    else:
                        new_lines.append(line)
                        total_decayed += 1
                else:
                    new_lines.append(line)
            
            if not req.dry_run:
                filepath.write_text("".join(new_lines), encoding="utf-8")
    
    return {
        "status": "ok" if not req.dry_run else "dry_run",
        "scanned": total_scanned,
        "decayed": total_decayed,
        "decay_rate": req.decay_rate,
        "min_age_days": req.min_age_days,
        "preview": preview if req.dry_run else [],
    }


# ========================================
# CONSOLIDATION
# ========================================

@app.post("/memory/consolidate")
async def consolidate_memories(req: ConsolidateRequest):
    """
    Consolidate similar old memories into summaries.
    
    Clusters similar entries, generates summary, marks originals as consolidated.
    """
    from . import embeddings, vector_store
    import json
    from datetime import datetime, timezone, timedelta
    import aiohttp
    
    cutoff = datetime.now(timezone.utc) - timedelta(days=req.min_age_days)
    
    # Get entries from the tier
    entries = []
    for filepath in storage._all_files_for_tier(req.tier):
        if not filepath.exists():
            continue
        
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if "schema" in entry:
                        continue
                    if entry.get("_consolidated"):
                        continue
                    
                    # Check age
                    ts = entry.get("ts") or entry.get("_written_at")
                    if ts:
                        try:
                            if isinstance(ts, (int, float)):
                                entry_time = datetime.fromtimestamp(ts, tz=timezone.utc)
                            else:
                                entry_time = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                            if entry_time <= cutoff:
                                entries.append(entry)
                        except (ValueError, TypeError, OSError):
                            pass
                except json.JSONDecodeError:
                    continue
        
        if len(entries) >= req.max_entries:
            break
    
    entries = entries[:req.max_entries]
    
    if len(entries) < 2:
        return {
            "status": "ok",
            "message": "Not enough entries to consolidate",
            "entries_found": len(entries),
        }
    
    # Get embeddings
    texts = [embeddings.text_for_embedding(e) for e in entries]
    entry_embeddings = await embeddings.get_embeddings_batch(texts)
    
    # Simple clustering: find similar pairs
    clusters = []
    used = set()
    
    for i, emb_i in enumerate(entry_embeddings):
        if i in used or emb_i is None:
            continue
        
        cluster = [i]
        for j, emb_j in enumerate(entry_embeddings):
            if j <= i or j in used or emb_j is None:
                continue
            
            # Cosine similarity
            dot = sum(a * b for a, b in zip(emb_i, emb_j))
            norm_i = sum(a * a for a in emb_i) ** 0.5
            norm_j = sum(b * b for b in emb_j) ** 0.5
            similarity = dot / (norm_i * norm_j) if norm_i and norm_j else 0
            
            if similarity >= req.similarity_threshold:
                cluster.append(j)
                used.add(j)
        
        if len(cluster) >= 2:
            used.add(i)
            clusters.append(cluster)
    
    if not clusters:
        return {
            "status": "ok",
            "message": "No similar clusters found",
            "entries_scanned": len(entries),
        }
    
    consolidated = []
    
    for cluster_indices in clusters[:10]:  # Limit to 10 clusters per run
        cluster_entries = [entries[i] for i in cluster_indices]
        cluster_texts = [texts[i] for i in cluster_indices]
        
        # Generate summary via Ollama
        combined = "\n---\n".join(cluster_texts)
        
        if req.dry_run:
            consolidated.append({
                "cluster_size": len(cluster_indices),
                "entry_ids": [e.get("id") for e in cluster_entries],
                "preview": combined[:200],
            })
        else:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "http://localhost:11434/api/generate",
                        json={
                            "model": "qwen3:8b",
                            "prompt": f"Summarize these related memories into one concise entry:\n\n{combined[:3000]}",
                            "stream": False,
                        },
                        timeout=aiohttp.ClientTimeout(total=60),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            summary = data.get("response", "")
                        else:
                            summary = combined[:500]
            except Exception:
                summary = combined[:500]
            
            # Create consolidated entry
            new_entry = {
                "type": "consolidated",
                "title": f"Consolidated from {len(cluster_indices)} entries",
                "content": summary,
                "source_ids": [e.get("id") for e in cluster_entries],
                "source_count": len(cluster_indices),
            }
            
            record = await storage.append(
                tier="semantic",
                entry_type="fact",
                payload=new_entry,
                tags=["consolidated", "auto_generated"],
                weight=max(e.get("weight", 1.0) for e in cluster_entries),
            )
            
            consolidated.append({
                "new_id": record["id"],
                "cluster_size": len(cluster_indices),
                "source_ids": [e.get("id") for e in cluster_entries],
            })
    
    return {
        "status": "ok" if not req.dry_run else "dry_run",
        "entries_scanned": len(entries),
        "clusters_found": len(clusters),
        "consolidated": consolidated,
    }


# ========================================
# ENTITY EXTRACTION
# ========================================

@app.post("/entities/extract")
async def extract_entities(req: EntityExtractRequest):
    """
    Extract entities from text and optionally store as semantic relations.
    """
    import aiohttp
    import json
    
    prompt = f"""Extract entities and their relationships from this text.
Return JSON array of objects with: subject, predicate, object

Example output:
[{{"subject": "Daemon", "predicate": "is_a", "object": "AI agent"}},
 {{"subject": "AOMS", "predicate": "runs_on", "object": "port 9100"}}]

Text:
{req.text[:2000]}

JSON:"""
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "qwen3:8b",
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=503, detail="Ollama unavailable")
                
                data = await resp.json()
                response_text = data.get("response", "[]")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Entity extraction failed: {e}")
    
    # Parse entities
    try:
        # Find JSON array in response
        start = response_text.find("[")
        end = response_text.rfind("]") + 1
        if start >= 0 and end > start:
            entities = json.loads(response_text[start:end])
        else:
            entities = []
    except json.JSONDecodeError:
        entities = []
    
    stored = []
    if req.store and entities:
        for entity in entities[:20]:  # Limit per extraction
            if not all(k in entity for k in ("subject", "predicate", "object")):
                continue
            
            payload = {
                "subject": str(entity["subject"]),
                "predicate": str(entity["predicate"]),
                "object": str(entity["object"]),
                "source_id": req.source_id,
            }
            
            record = await storage.append(
                tier="semantic",
                entry_type="relation",
                payload=payload,
                tags=["auto_extracted"],
            )
            stored.append(record["id"])
    
    return {
        "status": "ok",
        "entities_found": len(entities),
        "entities": entities,
        "stored_ids": stored,
    }


# ========================================
# DEDUPLICATION
# ========================================

@app.post("/memory/deduplicate")
async def deduplicate_memories(
    tier: str = "episodic",
    similarity_threshold: float = 0.95,
    limit: int = 100,
    dry_run: bool = True,
):
    """
    Find and merge duplicate memories based on embedding similarity.
    """
    from . import embeddings, vector_store
    import json
    
    # Get recent entries
    entries = []
    for filepath in storage._all_files_for_tier(tier):
        if not filepath.exists():
            continue
        
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if "schema" not in entry:
                        entries.append(entry)
                except json.JSONDecodeError:
                    continue
    
    entries = entries[-limit:]  # Most recent
    
    if len(entries) < 2:
        return {"status": "ok", "message": "Not enough entries", "found": 0}
    
    # Get embeddings
    texts = [embeddings.text_for_embedding(e) for e in entries]
    entry_embeddings = await embeddings.get_embeddings_batch(texts)
    
    # Find duplicates
    duplicates = []
    for i, emb_i in enumerate(entry_embeddings):
        if emb_i is None:
            continue
        for j, emb_j in enumerate(entry_embeddings):
            if j <= i or emb_j is None:
                continue
            
            # Cosine similarity
            dot = sum(a * b for a, b in zip(emb_i, emb_j))
            norm_i = sum(a * a for a in emb_i) ** 0.5
            norm_j = sum(b * b for b in emb_j) ** 0.5
            similarity = dot / (norm_i * norm_j) if norm_i and norm_j else 0
            
            if similarity >= similarity_threshold:
                duplicates.append({
                    "id_1": entries[i].get("id"),
                    "id_2": entries[j].get("id"),
                    "similarity": round(similarity, 4),
                    "preview_1": texts[i][:100],
                    "preview_2": texts[j][:100],
                })
    
    merged = 0
    if not dry_run and duplicates:
        # Boost weight of first entry, mark second as merged
        for dup in duplicates[:20]:
            await storage.adjust_weight(
                entry_id=dup["id_1"],
                tier=tier,
                task_score=0.9,  # Boost
            )
            merged += 1
    
    return {
        "status": "ok" if not dry_run else "dry_run",
        "scanned": len(entries),
        "duplicates_found": len(duplicates),
        "duplicates": duplicates[:20],
        "merged": merged,
    }


# ========================================
# STATS & ANALYTICS
# ========================================

@app.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Get memory statistics and analytics."""
    from datetime import datetime, timezone, timedelta
    import json
    
    counts = await storage.count_entries()
    total = sum(counts.values())
    
    # Count by type
    by_type = {}
    weight_buckets = {"low": 0, "medium": 0, "high": 0}
    recent_24h = 0
    oldest = None
    newest = None
    
    cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    
    for tier in ALL_TIERS:
        for filepath in storage._all_files_for_tier(tier):
            if not filepath.exists():
                continue
            
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if "schema" in entry:
                            continue
                        
                        # Type count
                        entry_type = entry.get("_type", entry.get("type", "unknown"))
                        by_type[entry_type] = by_type.get(entry_type, 0) + 1
                        
                        # Weight distribution
                        weight = entry.get("weight", 1.0)
                        if weight < 0.5:
                            weight_buckets["low"] += 1
                        elif weight < 1.5:
                            weight_buckets["medium"] += 1
                        else:
                            weight_buckets["high"] += 1
                        
                        # Recency
                        ts = entry.get("ts") or entry.get("_written_at")
                        if ts:
                            try:
                                # Handle both float (unix timestamp) and string (ISO) formats
                                if isinstance(ts, (int, float)):
                                    entry_time = datetime.fromtimestamp(ts, tz=timezone.utc)
                                    ts_str = entry_time.isoformat()
                                else:
                                    entry_time = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                                    ts_str = str(ts)
                                
                                if entry_time > cutoff_24h:
                                    recent_24h += 1
                                if oldest is None or ts_str < oldest:
                                    oldest = ts_str
                                if newest is None or ts_str > newest:
                                    newest = ts_str
                            except (ValueError, TypeError, OSError):
                                pass
                    except json.JSONDecodeError:
                        continue
    
    # Vector index stats
    from . import vector_store
    vector_stats = await vector_store.get_index_stats()
    
    return StatsResponse(
        total_entries=total,
        by_tier=counts,
        by_type=by_type,
        vector_indexed=vector_stats,
        weight_distribution=weight_buckets,
        recent_24h=recent_24h,
        oldest_entry=oldest,
        newest_entry=newest,
    )


# ========================================
# VECTOR INDEX MANAGEMENT
# ========================================

@app.post("/memory/index")
async def index_memories(
    tier: str = "episodic",
    limit: int = 1000,
    skip_indexed: bool = True,
):
    """
    Index existing memories into the vector store.
    
    Run this to enable semantic search on existing entries.
    """
    from . import embeddings, vector_store
    import json
    
    indexed = 0
    skipped = 0
    errors = 0
    
    for filepath in storage._all_files_for_tier(tier):
        if not filepath.exists():
            continue
        
        entries = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if "schema" not in entry and entry.get("id"):
                        entries.append(entry)
                except json.JSONDecodeError:
                    continue
        
        # Process in batches
        batch_size = 20
        for i in range(0, min(len(entries), limit), batch_size):
            batch = entries[i:i + batch_size]
            texts = [embeddings.text_for_embedding(e) for e in batch]
            batch_embeddings = await embeddings.get_embeddings_batch(texts)
            
            for entry, text, emb in zip(batch, texts, batch_embeddings):
                if emb is None:
                    errors += 1
                    continue
                
                success = await vector_store.add_to_index(
                    tier=tier,
                    entry_id=entry["id"],
                    embedding=emb,
                    metadata={
                        "_type": entry.get("_type", ""),
                        "_written_at": entry.get("_written_at", ""),
                        "weight": entry.get("weight", 1.0),
                    },
                    document=text,
                )
                
                if success:
                    indexed += 1
                else:
                    errors += 1
            
            if indexed >= limit:
                break
    
    return {
        "status": "ok",
        "tier": tier,
        "indexed": indexed,
        "skipped": skipped,
        "errors": errors,
    }


# ========================================
# WRITE MEMORY (wildcard route - must come after specific routes)
# ========================================

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


# ========================================
# HEALTH
# ========================================

@app.get("/health")
async def health_check():
    """Lightweight service health check.

    Do not scan multi-GB memory stores here. Full counting belongs in `/stats`
    or offline maintenance, not the liveness probe.
    """
    uptime = time.monotonic() - _start_time

    return HealthResponse(
        status="ok",
        service="openclaw-memory",
        version=VERSION,
        uptime_seconds=round(uptime, 1),
        memory_root=str(MEMORY_ROOT),
        tiers={},
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
