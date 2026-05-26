"""
Embedding service for AOMS vector search.

Uses Ollama nomic-embed-text for local embeddings.
"""
import asyncio
import logging
from typing import List, Optional

import aiohttp

logger = logging.getLogger("aoms.embeddings")

OLLAMA_URL = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768  # nomic-embed-text dimension


async def get_embedding(text: str, model: str = EMBED_MODEL) -> Optional[List[float]]:
    """Get embedding vector for a single text."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": model, "prompt": text},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("embedding")
                else:
                    logger.error(f"Embedding error: {resp.status}")
                    return None
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return None


async def get_embeddings_batch(
    texts: List[str], 
    model: str = EMBED_MODEL,
    batch_size: int = 10
) -> List[Optional[List[float]]]:
    """Get embeddings for multiple texts with batching."""
    results = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        batch_results = await asyncio.gather(
            *[get_embedding(t, model) for t in batch],
            return_exceptions=True
        )
        for r in batch_results:
            if isinstance(r, Exception):
                results.append(None)
            else:
                results.append(r)
    return results


def text_for_embedding(entry: dict) -> str:
    """Extract text content from a memory entry for embedding."""
    parts = []
    
    # Title/subject
    if entry.get("title"):
        parts.append(entry["title"])
    if entry.get("subject"):
        parts.append(entry["subject"])
    
    # Content
    if entry.get("content"):
        parts.append(entry["content"])
    if entry.get("outcome"):
        parts.append(entry["outcome"])
    
    # Decision/rationale
    if entry.get("decision"):
        parts.append(entry["decision"])
    if entry.get("rationale"):
        parts.append(entry["rationale"])
    
    # Facts
    if entry.get("predicate") and entry.get("object"):
        parts.append(f"{entry.get('subject', '')} {entry['predicate']} {entry['object']}")

    # Skills / procedures (procedural tier has no title/content/subject fields).
    # Some skills store list-valued fields (e.g. a multi-step procedure), so coerce.
    for _fld in ("skill_name", "description", "when_to_use", "procedure"):
        _v = entry.get(_fld)
        if not _v:
            continue
        parts.append(" ".join(str(x) for x in _v) if isinstance(_v, list) else str(_v))

    # Tags
    if entry.get("tags"):
        parts.append(" ".join(entry["tags"]))
    
    return " ".join(str(p) for p in parts)[:2000]  # Limit ~500 tokens (str() guards non-str fields)
