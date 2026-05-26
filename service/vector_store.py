"""
Vector storage for AOMS semantic search.

Uses ChromaDB for persistent vector storage with per-tier collections.
Falls back gracefully if ChromaDB is unavailable (e.g., Python 3.14 compatibility).
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("aoms.vector")

CHROMA_PATH = Path.home() / "cortex-mem/cortex-mem/index/memory_vectors"

# Try to import chromadb, but handle failure gracefully
_chromadb_available = False
chromadb = None
Settings = None

try:
    import chromadb as _chromadb
    from chromadb.config import Settings as _Settings
    chromadb = _chromadb
    Settings = _Settings
    _chromadb_available = True
except Exception as e:
    logger.warning(f"ChromaDB unavailable (likely Python 3.14 compatibility): {e}")
    logger.warning("Vector search features will be disabled. Use keyword search instead.")

_client = None


def get_chroma_client():
    """Get or create ChromaDB client."""
    global _client
    if not _chromadb_available:
        return None
    if _client is None:
        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=str(CHROMA_PATH),
            settings=Settings(anonymized_telemetry=False),
        )
        logger.info(f"ChromaDB initialized at {CHROMA_PATH}")
    return _client


def get_collection(tier: str):
    """Get or create a collection for a memory tier."""
    client = get_chroma_client()
    if client is None:
        return None
    return client.get_or_create_collection(
        name=f"aoms_{tier}",
        metadata={"hnsw:space": "cosine"},
    )


async def add_to_index(
    tier: str,
    entry_id: str,
    embedding: List[float],
    metadata: Dict[str, Any],
    document: str,
) -> bool:
    """Add a single entry to the vector index."""
    try:
        collection = get_collection(tier)
        if collection is None:
            return False
        if collection is None:
            return False
        
        # ChromaDB metadata must be str, int, float, or bool
        clean_meta = {}
        for k, v in metadata.items():
            if isinstance(v, (str, int, float, bool)):
                clean_meta[k] = v
            elif isinstance(v, list):
                clean_meta[k] = ",".join(str(x) for x in v)
            elif v is not None:
                clean_meta[k] = str(v)
        
        collection.upsert(
            ids=[entry_id],
            embeddings=[embedding],
            metadatas=[clean_meta],
            documents=[document[:5000]],  # Truncate long docs
        )
        return True
    except Exception as e:
        logger.error(f"Failed to add to index: {e}")
        return False


async def semantic_search(
    query_embedding: List[float],
    tiers: Optional[List[str]] = None,
    limit: int = 10,
    min_score: float = 0.3,
) -> List[Tuple[str, str, float, Dict[str, Any], str]]:
    """
    Search across tier collections by embedding similarity.
    
    Returns: List of (tier, entry_id, score, metadata, document)
    """
    if not _chromadb_available:
        logger.warning("Semantic search unavailable: ChromaDB not loaded")
        return []
    
    search_tiers = tiers or ["episodic", "semantic", "procedural"]
    all_results = []
    
    for tier in search_tiers:
        try:
            collection = get_collection(tier)
            if collection is None:
                continue
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=limit,
                include=["metadatas", "distances", "documents"],
            )
            
            if results and results["ids"] and results["ids"][0]:
                for i, entry_id in enumerate(results["ids"][0]):
                    # ChromaDB returns distances, convert to similarity
                    distance = results["distances"][0][i] if results["distances"] else 0
                    score = 1 - distance  # Cosine distance to similarity
                    
                    if score >= min_score:
                        metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                        document = results["documents"][0][i] if results["documents"] else ""
                        all_results.append((tier, entry_id, score, metadata, document))
        except Exception as e:
            logger.error(f"Search failed for tier {tier}: {e}")
    
    # Sort by score descending
    all_results.sort(key=lambda x: x[2], reverse=True)
    return all_results[:limit]


async def get_index_stats() -> Dict[str, int]:
    """Get entry counts per tier in vector index."""
    stats = {}
    for tier in ["episodic", "semantic", "procedural"]:
        try:
            collection = get_collection(tier)
            if collection is not None:
                stats[tier] = collection.count()
            else:
                stats[tier] = 0
        except Exception:
            stats[tier] = 0
    return stats


def is_available() -> bool:
    """Check if vector search is available."""
    return _chromadb_available


async def delete_from_index(tier: str, entry_id: str) -> bool:
    """Delete an entry from the vector index."""
    if not _chromadb_available:
        return False
    try:
        collection = get_collection(tier)
        if collection is None:
            return False
        collection.delete(ids=[entry_id])
        return True
    except Exception as e:
        logger.error(f"Delete failed: {e}")
        return False
