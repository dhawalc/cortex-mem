"""
TierGenerator — auto-generates L0/L1 tiers from L2 (full) documents.

Uses Ollama (deepseek-r1:7b) for summarization and ChromaDB for vector indexing.
Prompts follow MEMORY_ARCHITECTURE_MASTER_PLAN.md Section 1.4.
"""
import hashlib
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp
import chromadb

from . import db

logger = logging.getLogger("aoms.cortex")

OLLAMA_URL = "http://localhost:11434"
GENERATION_MODEL = "deepseek-r1:7b"
L0_MAX_TOKENS = 100
L1_MAX_TOKENS = 2000

L2_STORAGE_ROOT = Path("/home/dhawal/cortex-mem/cortex-mem/cortex/l2_docs")
CHROMA_PATH = Path("/home/dhawal/cortex-mem/cortex-mem/index/chroma")

L0_PROMPT = """Summarize in ONE sentence (max 100 tokens): what this document \
is about, its primary conclusion, and one key differentiator.

DOCUMENT TYPE: {doc_type}
HIERARCHY: {hierarchy_path}
TITLE: {title}

CONTENT:
{content}

ABSTRACT:"""

L1_PROMPT = """Create a structured overview (under 2000 tokens):

1. PURPOSE: What this is and why it exists (1-2 sentences)
2. KEY POINTS: 3-5 most important facts/findings
3. METRICS: Quantitative results (percentages, performance)
4. RELATIONSHIPS: What this relates to
5. ACTIONABILITY: When/how to use this

Format as clean markdown. Be data-dense.

DOCUMENT TYPE: {doc_type}
HIERARCHY: {hierarchy_path}
TITLE: {title}

CONTENT:
{content}

OVERVIEW:"""


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English."""
    return len(text) // 4


def _strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks that deepseek-r1 sometimes emits."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


async def _ollama_generate(prompt: str, max_tokens: int = 2048) -> str:
    """Call Ollama chat API and return the response text."""
    payload = {
        "model": GENERATION_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": 0.3},
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=120),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Ollama returned {resp.status}: {body}")
            data = await resp.json()
            return _strip_thinking_tags(data.get("response", ""))


def _get_chroma_client() -> chromadb.ClientAPI:
    CHROMA_PATH.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(CHROMA_PATH))


class TierGenerator:
    """Auto-generates L0 and L1 tiers from L2 content."""

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

    async def ingest_document(
        self,
        content: str,
        title: str,
        hierarchy_path: str,
        doc_type: str = "reference",
        tags: Optional[list] = None,
        source_file: Optional[str] = None,
    ) -> str:
        """
        Full pipeline: store L2, generate L0/L1, index in ChromaDB, save metadata.
        Returns doc_id.
        """
        doc_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        l2_checksum = hashlib.sha256(content.encode()).hexdigest()

        # 1. Store L2 on filesystem
        l2_path = self._resolve_l2_path(hierarchy_path, title)
        l2_path.parent.mkdir(parents=True, exist_ok=True)
        l2_path.write_text(content, encoding="utf-8")
        l2_tokens = _estimate_tokens(content)

        logger.info(f"Ingesting '{title}' ({l2_tokens} tokens) → generating L0/L1...")

        # 2. Generate L0 via Ollama
        t0 = time.monotonic()
        l0_abstract = await self._generate_l0(content, title, hierarchy_path, doc_type)
        l0_tokens = _estimate_tokens(l0_abstract)
        logger.info(f"  L0 generated: {l0_tokens} tokens ({time.monotonic()-t0:.1f}s)")

        # 3. Generate L1 via Ollama
        t1 = time.monotonic()
        l1_overview = await self._generate_l1(content, title, hierarchy_path, doc_type)
        l1_tokens = _estimate_tokens(l1_overview)
        logger.info(f"  L1 generated: {l1_tokens} tokens ({time.monotonic()-t1:.1f}s)")

        # 4. Index in ChromaDB
        self.l0_collection.upsert(
            ids=[doc_id],
            documents=[l0_abstract],
            metadatas=[{"title": title, "hierarchy_path": hierarchy_path, "doc_type": doc_type}],
        )
        self.l1_collection.upsert(
            ids=[doc_id],
            documents=[l1_overview],
            metadatas=[{"title": title, "hierarchy_path": hierarchy_path, "doc_type": doc_type}],
        )

        # 5. Save to SQLite
        parent_path = "/".join(hierarchy_path.rstrip("/").split("/")[:-1]) or "/"
        depth = hierarchy_path.strip("/").count("/")

        db.insert_document(self.conn, {
            "doc_id": doc_id,
            "hierarchy_path": hierarchy_path,
            "title": title,
            "doc_type": doc_type,
            "l0_abstract": l0_abstract,
            "l0_token_count": l0_tokens,
            "l1_overview": l1_overview,
            "l1_token_count": l1_tokens,
            "l2_file_path": str(l2_path),
            "l2_token_count": l2_tokens,
            "l2_checksum": l2_checksum,
            "chromadb_l0_id": doc_id,
            "chromadb_l1_id": doc_id,
            "parent_path": parent_path,
            "depth": depth,
            "tags": tags or [],
            "l0_generated_at": now,
            "l1_generated_at": now,
            "source_type": "file" if source_file else "manual",
        })

        total_time = time.monotonic() - t0
        logger.info(
            f"  Ingested '{title}': L2={l2_tokens}tok → L0={l0_tokens}tok + L1={l1_tokens}tok "
            f"({(1 - (l0_tokens + l1_tokens) / max(l2_tokens, 1)) * 100:.0f}% reduction, {total_time:.1f}s)"
        )
        return doc_id

    async def regenerate(self, doc_id: str) -> bool:
        """Re-generate L0/L1 for an existing document (e.g., after L2 update)."""
        doc = db.get_document(self.conn, doc_id)
        if doc is None:
            return False

        l2_path = Path(doc["l2_file_path"])
        if not l2_path.exists():
            logger.error(f"L2 file missing for {doc_id}: {l2_path}")
            return False

        content = l2_path.read_text(encoding="utf-8")
        now = datetime.now(timezone.utc).isoformat()

        l0 = await self._generate_l0(content, doc["title"], doc["hierarchy_path"], doc["doc_type"])
        l1 = await self._generate_l1(content, doc["title"], doc["hierarchy_path"], doc["doc_type"])

        self.conn.execute(
            """
            UPDATE documents SET
                l0_abstract = ?, l0_token_count = ?,
                l1_overview = ?, l1_token_count = ?,
                l2_checksum = ?, l2_token_count = ?,
                is_stale = 0, stale_reason = NULL,
                l0_generated_at = ?, l1_generated_at = ?
            WHERE doc_id = ?
            """,
            (
                l0, _estimate_tokens(l0),
                l1, _estimate_tokens(l1),
                hashlib.sha256(content.encode()).hexdigest(),
                _estimate_tokens(content),
                now, now, doc_id,
            ),
        )
        self.conn.commit()

        self.l0_collection.upsert(ids=[doc_id], documents=[l0])
        self.l1_collection.upsert(ids=[doc_id], documents=[l1])

        logger.info(f"Regenerated L0/L1 for '{doc['title']}'")
        return True

    async def _generate_l0(
        self, content: str, title: str, hierarchy_path: str, doc_type: str
    ) -> str:
        truncated = content[:12000]
        prompt = L0_PROMPT.format(
            doc_type=doc_type,
            hierarchy_path=hierarchy_path,
            title=title,
            content=truncated,
        )
        result = await _ollama_generate(prompt, max_tokens=400)
        if len(result.split()) < 10:
            logger.warning(f"L0 too short ({len(result.split())} words), using title-based fallback")
            first_500 = content[:2000].replace("\n", " ").strip()
            result = f"{title}: {first_500[:300]}"
        return result

    async def _generate_l1(
        self, content: str, title: str, hierarchy_path: str, doc_type: str
    ) -> str:
        truncated = content[:16000]
        prompt = L1_PROMPT.format(
            doc_type=doc_type,
            hierarchy_path=hierarchy_path,
            title=title,
            content=truncated,
        )
        return await _ollama_generate(prompt, max_tokens=3000)

    def _resolve_l2_path(self, hierarchy_path: str, title: str) -> Path:
        safe_title = re.sub(r"[^\w\-.]", "_", title)[:80]
        return L2_STORAGE_ROOT / hierarchy_path.strip("/") / f"{safe_title}.md"
