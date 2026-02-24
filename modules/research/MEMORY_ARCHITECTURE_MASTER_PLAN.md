# Memory Architecture Master Plan
**Unified Design for OpenClaw + Daemon Memory Systems**

**Author:** ULTRON (Claude Sonnet 4-5)  
**Date:** 2026-02-22  
**Status:** Complete Design, Ready for Implementation  
**Scope:** Two parallel architectures that integrate at the API layer

---

## Executive Summary

This plan unifies **two complementary memory architectures** into a coherent system:

1. **Cortex Tiered Architecture (L0/L1/L2)** — Token-efficient hierarchical retrieval for Daemon's 4-tier memory
2. **openclaw-memory AOMS** — Always-On Memory Service, a standalone product that both OpenClaw and Daemon can share

**Key Innovation:** These aren't competing designs — they're layers in a unified stack:

```
┌─────────────────────────────────────────────────────────┐
│                   USER INTERFACES                       │
│  OpenClaw Agent (ULTRON) │ Daemon Agents (autonomous)  │
└────────────────┬────────────────────┬───────────────────┘
                 │                    │
                 v                    v
┌─────────────────────────────────────────────────────────┐
│              ALWAYS-ON MEMORY SERVICE (AOMS)            │
│  • FastAPI HTTP server (local only)                     │
│  • Unified read/write API for all memory tiers          │
│  • Survives Daemon downtime                             │
│  • Backup/sync to VPS                                   │
└────────────────┬────────────────────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────────────────────┐
│         CORTEX TIERED RETRIEVAL (L0/L1/L2)              │
│  • L0: 100-token abstracts (fast scan)                  │
│  • L1: 2K overviews (structured summary)                │
│  • L2: Full content (load on demand)                    │
│  • 88% token reduction (10K → 1.2K avg)                 │
└────────────────┬────────────────────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────────────────────┐
│              4-TIER MEMORY STORAGE                      │
│  Working │ Episodic │ Semantic │ Procedural             │
│  (PostgreSQL + ChromaDB + Filesystem)                   │
└─────────────────────────────────────────────────────────┘
```

**Target Outcomes:**
- 88% token reduction on memory queries (10K → 1.2K avg)
- Memory persists even when Daemon is offline
- Single source of truth, dual-access (OpenClaw + Daemon)
- Publishable as standalone product (npm/pip package)
- 7-day shadow mode migration (zero breakage)

---

# Part 1: Cortex Tiered Architecture (L0/L1/L2)

## 1.1 Problem Statement

**Current state:**
- Daemon queries memory → 8-12K tokens per query
- 100+ strategy docs, research papers, session logs
- 4 concurrent agents querying simultaneously
- ChromaDB vector search returns full documents

**Target state:**
- 90% of queries resolved with <2K tokens
- Hierarchical retrieval: scan abstracts → expand relevant → load full content
- Same fidelity, 10x efficiency

---

## 1.2 Architecture Overview

### Three-Tier Context Loading

| Tier | Size | Purpose | Use Case |
|------|------|---------|----------|
| **L0** | ~100 tokens | One-sentence abstract | Fast relevance scanning, "what exists?" |
| **L1** | ~2K tokens | Structured overview | "Tell me more about X" |
| **L2** | Full doc | Complete content | "I need all the details" |

### Storage Strategy

**PostgreSQL** (`cortex_tiers` schema):
- Document metadata (title, hierarchy, checksums)
- L0 abstracts (stored directly)
- L1 overviews (stored directly)
- L2 file paths (point to filesystem)
- Query logs (analytics)

**ChromaDB** (two collections):
- `cortex_l0` — Vector embeddings of L0 abstracts
- `cortex_l1` — Vector embeddings of L1 overviews

**Filesystem** (`/home/dhawal/daemon/memory/tiered/`):
- L2 full content (Markdown files)
- Organized by hierarchy (`/strategies/momentum/`, `/research/papers/`)

---

## 1.3 Database Schema

### PostgreSQL Tables

```sql
-- Schema: cortex_tiers
CREATE SCHEMA IF NOT EXISTS cortex_tiers;

-- Main metadata table
CREATE TABLE cortex_tiers.documents (
    doc_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hierarchy_path  TEXT NOT NULL,              -- e.g., '/strategies/momentum/120d_20hold'
    title           TEXT NOT NULL,
    doc_type        TEXT NOT NULL CHECK (doc_type IN (
        'strategy', 'backtest', 'research', 'episode', 
        'skill', 'pattern', 'session_learning', 'reference'
    )),
    
    -- Tier content
    l0_abstract     TEXT NOT NULL,              -- ~100 tokens max
    l0_token_count  INTEGER NOT NULL,
    l1_overview     TEXT,                       -- ~2K tokens max
    l1_token_count  INTEGER DEFAULT 0,
    l2_file_path    TEXT NOT NULL,              -- Absolute path to full doc
    l2_token_count  INTEGER DEFAULT 0,
    l2_checksum     TEXT NOT NULL,              -- SHA-256 for invalidation
    
    -- ChromaDB references
    chromadb_l0_id  TEXT,
    chromadb_l1_id  TEXT,
    
    -- Hierarchy
    parent_path     TEXT,
    depth           INTEGER DEFAULT 0,
    tags            TEXT[] DEFAULT '{}',
    
    -- Timestamps
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    l0_generated_at TIMESTAMPTZ,
    l1_generated_at TIMESTAMPTZ,
    
    -- Invalidation
    is_stale        BOOLEAN DEFAULT FALSE,
    stale_reason    TEXT,
    
    -- Source tracking
    source_type     TEXT DEFAULT 'manual',
    cortex_tier     TEXT CHECK (cortex_tier IN ('episodic', 'semantic', 'procedural'))
);

CREATE INDEX idx_docs_hierarchy ON cortex_tiers.documents (hierarchy_path);
CREATE INDEX idx_docs_parent ON cortex_tiers.documents (parent_path);
CREATE INDEX idx_docs_type ON cortex_tiers.documents (doc_type);
CREATE INDEX idx_docs_stale ON cortex_tiers.documents (is_stale) WHERE is_stale = TRUE;
CREATE INDEX idx_docs_tags ON cortex_tiers.documents USING GIN (tags);

-- Hierarchy directories
CREATE TABLE cortex_tiers.directories (
    dir_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    path            TEXT UNIQUE NOT NULL,
    parent_path     TEXT,
    name            TEXT NOT NULL,
    description     TEXT,
    doc_count       INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_dirs_parent ON cortex_tiers.directories (parent_path);

-- Query analytics
CREATE TABLE cortex_tiers.query_log (
    query_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text      TEXT NOT NULL,
    agent_id        TEXT,
    l0_results      INTEGER DEFAULT 0,
    l1_expansions   INTEGER DEFAULT 0,
    l2_loads        INTEGER DEFAULT 0,
    total_tokens    INTEGER DEFAULT 0,
    latency_ms      INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Auto-update trigger
CREATE OR REPLACE FUNCTION cortex_tiers.update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_docs_updated
    BEFORE UPDATE ON cortex_tiers.documents
    FOR EACH ROW EXECUTE FUNCTION cortex_tiers.update_timestamp();
```

---

## 1.4 Auto-Generation Pipeline

### L0/L1 Generation Prompts

```python
# Constants
L0_MAX_TOKENS = 100
L1_MAX_TOKENS = 2000
GENERATION_MODEL = "ollama/deepseek-r1:7b"  # Local, free

L0_PROMPT = """Summarize in ONE sentence (max 100 tokens): what this document 
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
```

### TierGenerator Class

```python
class TierGenerator:
    """Auto-generates L0 and L1 tiers from L2 content."""
    
    async def ingest_document(
        self,
        content: str,
        title: str,
        hierarchy_path: str,
        doc_type: str,
        tags: list[str] = None,
    ) -> str:
        """
        Full pipeline: store L2, generate L0/L1, index in ChromaDB.
        Returns doc_id.
        """
        # 1. Store L2 on filesystem
        l2_path = self._resolve_l2_path(hierarchy_path, title)
        l2_path.write_text(content)
        l2_checksum = hashlib.sha256(content.encode()).hexdigest()
        
        # 2. Generate L0/L1 via Ollama
        l0_abstract = await self._generate_l0(content, title, hierarchy_path, doc_type)
        l1_overview = await self._generate_l1(content, title, hierarchy_path, doc_type)
        
        # 3. Insert into PostgreSQL
        doc_id = await self.pg.fetchval("""
            INSERT INTO cortex_tiers.documents (
                hierarchy_path, title, doc_type,
                l0_abstract, l0_token_count,
                l1_overview, l1_token_count,
                l2_file_path, l2_checksum,
                parent_path, depth, tags
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            RETURNING doc_id
        """, ...)
        
        # 4. Index in ChromaDB
        self.l0_collection.upsert(ids=[doc_id], documents=[l0_abstract])
        self.l1_collection.upsert(ids=[doc_id], documents=[l1_overview])
        
        return doc_id
```

---

## 1.5 Query API

### TieredRetriever Class

```python
@dataclass
class TieredResult:
    doc_id: str
    title: str
    hierarchy_path: str
    score: float
    l0_abstract: str = ""      # Always populated
    l1_overview: str = None    # Populated on expand
    l2_content: str = None     # Populated on load
    
    @property
    def total_tokens(self) -> int:
        if self.l2_content: return self.l2_tokens
        if self.l1_overview: return self.l1_tokens
        return self.l0_tokens

class TieredRetriever:
    """Hierarchical, tier-aware retrieval."""
    
    async def retrieve_l0(
        self,
        query: str,
        top_k: int = 10,
        directory: str = None,  # e.g., '/strategies/momentum'
        min_score: float = 0.3,
    ) -> RetrievalResponse:
        """Search L0 abstracts. Fast, cheap (~100 tok/result)."""
        
    async def expand_to_l1(
        self,
        response: RetrievalResponse,
        indices: list[int] = None,
        score_threshold: float = 0.7,
    ) -> RetrievalResponse:
        """Expand selected L0 results to L1 overviews."""
        
    async def load_l2(
        self,
        response: RetrievalResponse,
        indices: list[int],
    ) -> RetrievalResponse:
        """Load full L2 content for specific results."""
        
    async def smart_query(
        self,
        query: str,
        token_budget: int = 2000,
        directory: str = None,
    ) -> RetrievalResponse:
        """
        Auto-escalating query that stays within budget.
        
        Algorithm:
        1. Search L0 (top 10)
        2. If top score > 0.7, expand top 3 to L1
        3. Only load L2 if score > 0.9 and budget allows
        """
```

### Usage Example

```python
# Daemon agent queries memory
retriever = TieredRetriever(pg_pool, chroma, ollama)

# Fast scan
response = await retriever.smart_query(
    "momentum strategies with Sharpe > 1.4",
    token_budget=2000,
    directory="/strategies"
)

# response.results contains L0/L1 depending on relevance
# Total tokens: ~800 (vs 8-12K before)
```

---

## 1.6 Invalidation System

### File Watcher

```python
class InvalidationDaemon:
    """
    Watches /daemon/memory/tiered/ for changes.
    Auto-regenerates L0/L1 when L2 is modified.
    """
    
    async def start(self):
        # Start filesystem watcher (inotify)
        self.observer.schedule(
            L2FileWatcher(self.pg, self.regen_queue),
            "/home/dhawal/daemon/memory/tiered",
            recursive=True
        )
        
        # Process regeneration queue
        await self._process_regeneration_queue()
        
        # Hourly checksum scan (catch missed changes)
        await self._periodic_checksum_scan()
```

---

## 1.7 Migration Script

```python
"""migrate_to_tiered.py — Batch migrate existing Cortex docs."""

async def run_migration():
    # Find all .md files in /daemon/memory/
    md_files = [f for f in MEMORY_ROOT.rglob("*.md") 
                if "tiered" not in f.parts]
    
    for filepath in md_files:
        content = filepath.read_text()
        doc_type, hierarchy_path = classify_document(filepath, content)
        
        await generator.ingest_document(
            content=content,
            title=filepath.stem.replace('_', ' ').title(),
            hierarchy_path=hierarchy_path,
            doc_type=doc_type,
            tags=[doc_type, "migrated"],
        )
```

---

## 1.8 Token Savings Projection

| Query Type | Before | After (L0/L1) | Reduction |
|-----------|--------|---------------|-----------|
| "Find relevant strategies" | 8-12K | 500-800 | ~92% |
| "Detail on momentum strategy" | 8K | 1.5-2K | ~78% |
| "Full strategy backtest" | 8K | 8K (L2) | 0% |
| **Weighted avg (90% L0/L1, 10% L2)** | **~10K** | **~1.2K** | **~88%** |

---

# Part 2: openclaw-memory AOMS (Always-On Memory Service)

## 2.1 Problem Statement

**Current state:**
- Memory is split: OpenClaw workspace files + Daemon Cortex data
- When Daemon is offline, Cortex memory unavailable
- No single source of truth
- Workspace files duplicated (OpenClaw writes, Daemon reads)

**Target state:**
- Standalone memory service (FastAPI)
- Survives Daemon downtime
- Both systems read/write via unified API
- Publishable as npm/pip package

---

## 2.2 Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                  ALWAYS-ON MEMORY SERVICE                │
│                    (FastAPI, port 9100)                  │
│                                                          │
│  Endpoints:                                              │
│  • POST /memory/{tier}        (write)                    │
│  • POST /memory/search        (query)                    │
│  • GET  /memory/browse/{path} (directory listing)        │
│  • GET  /health               (status check)             │
│                                                          │
│  Storage:                                                │
│  • /home/dhawal/openclaw-memory/                         │
│    ├── modules/identity/                                 │
│    ├── modules/memory/                                   │
│    ├── modules/operations/                               │
│    ├── modules/projects/                                 │
│    └── modules/research/                                 │
└──────────────────────────────────────────────────────────┘
         ▲                              ▲
         │                              │
    OpenClaw                        Daemon
  (workspace)                    (Cortex sync)
```

---

## 2.3 Module Tree Structure

```
openclaw-memory/
├── README.md                    # Product documentation
├── AGENTS.md                    # Repo onboarding (always loaded)
├── AGENT.md                     # Agent rules + decision table
├── router.yaml                  # Level 1 router (task → module)
│
├── modules/
│   ├── identity/
│   │   ├── IDENTITY.md          # Persona, tone, voice
│   │   ├── voice.md             # Communication style
│   │   └── values.yaml          # Personal info, preferences
│   │
│   ├── operations/
│   │   ├── OPERATIONS.md        # System priorities, workflows
│   │   ├── priorities.yaml      # Task prioritization rules
│   │   └── checklists.yaml      # Heartbeat checks, routines
│   │
│   ├── memory/
│   │   ├── MEMORY.md            # High-level memory overview
│   │   ├── episodic/
│   │   │   ├── experiences.jsonl   # Event log
│   │   │   ├── decisions.jsonl     # Major decisions
│   │   │   └── failures.jsonl      # Mistakes + learnings
│   │   ├── semantic/
│   │   │   ├── facts.jsonl         # Knowledge facts
│   │   │   └── relations.jsonl     # Entity relationships
│   │   └── procedural/
│   │       ├── skills.jsonl        # Learned procedures
│   │       └── patterns.jsonl      # Recurring patterns
│   │
│   ├── projects/
│   │   ├── projects.yaml        # Active projects metadata
│   │   └── status.jsonl         # Daily progress log
│   │
│   ├── network/
│   │   ├── contacts.jsonl       # People, relationships
│   │   ├── interactions.jsonl   # Communication history
│   │   └── network.md           # Network overview
│   │
│   ├── content/
│   │   ├── CONTENT.md           # Content strategy
│   │   ├── ideas.jsonl          # Content ideas
│   │   ├── posts.jsonl          # Published posts
│   │   └── templates/           # Post templates
│   │
│   └── research/
│       ├── RESEARCH.md          # Research overview
│       ├── papers.jsonl         # Paper summaries
│       └── notes.md             # Research notes
│
├── schemas/
│   └── jsonl_schemas.yaml       # Schema definitions per JSONL
│
├── index/
│   └── embeddings.db            # Optional: vector index
│
├── snapshots/
│   └── backup-YYYY-MM-DD.tar.gz # Daily backups
│
└── service/
    ├── api.py                   # FastAPI server
    ├── client.py                # Python client library
    └── config.yaml              # Service configuration
```

---

## 2.4 JSONL Schemas

### Schema Header Format

Every JSONL file starts with a schema header:
```jsonl
{"schema":"openclaw.experience.v1","fields":["ts","type","title","outcome","tags"]}
```

### Experience Schema (`episodic/experiences.jsonl`)

```jsonl
{"schema":"openclaw.experience.v1","fields":["ts","type","title","outcome","tags"]}
{"ts":"2026-02-22T10:45:00Z","type":"decision","title":"Workspace cleanup","outcome":"83% reduction","tags":["memory","optimization"]}
{"ts":"2026-02-22T11:35:00Z","type":"achievement","title":"Daemon all-Ollama config","outcome":"zero API costs","tags":["daemon","ollama"]}
{"ts":"2026-02-22T14:00:00Z","type":"error","title":"OpenClaw CLI invalid key","outcome":"fixed by removing skills.allow","tags":["openclaw","config"]}
```

### Decision Schema (`episodic/decisions.jsonl`)

```jsonl
{"schema":"openclaw.decision.v1","fields":["ts","decision","rationale","alternatives","outcome"]}
{"ts":"2026-02-21T00:00:00Z","decision":"All cron jobs use Ollama","rationale":"Prevent 24/7 API quota burn","alternatives":["Rate-limit Claude","Use cheaper models"],"outcome":"Zero costs, working"}
{"ts":"2026-02-22T10:00:00Z","decision":"Skills allowlist approach","rationale":"Better than deleting, reversible","alternatives":["Delete unused skills","Keep all 53"],"outcome":"16 essential skills, 70% reduction"}
```

### Fact Schema (`semantic/facts.jsonl`)

```jsonl
{"schema":"openclaw.fact.v1","fields":["ts","subject","predicate","object","confidence","source"]}
{"ts":"2026-02-22T00:00:00Z","subject":"Dhawal","predicate":"has_daughter","object":"Samvi","confidence":1.0,"source":"USER.md"}
{"ts":"2026-02-22T00:00:00Z","subject":"Samvi","predicate":"age","object":"4","confidence":1.0,"source":"USER.md"}
{"ts":"2026-02-22T00:00:00Z","subject":"Samvi","predicate":"attends","object":"Montessori","confidence":1.0,"source":"USER.md"}
```

### Skill Schema (`procedural/skills.jsonl`)

```jsonl
{"schema":"openclaw.skill.v1","fields":["ts","skill_name","category","success_rate","avg_duration","when_to_use"]}
{"ts":"2026-02-21T00:00:00Z","skill_name":"Workspace cleanup","category":"memory_optimization","success_rate":1.0,"avg_duration":"2h","when_to_use":"Context usage > 80%"}
{"ts":"2026-02-20T00:00:00Z","skill_name":"Model handover","category":"continuity","success_rate":0.9,"avg_duration":"5m","when_to_use":"Model switch needed"}
```

---

## 2.5 FastAPI Service

### Service Configuration (`service/config.yaml`)

```yaml
service:
  name: openclaw-memory
  port: 9100
  host: localhost  # Local only, no external access
  
storage:
  root: /home/dhawal/openclaw-memory
  backup_dir: /home/dhawal/openclaw-memory/snapshots
  
backup:
  enabled: true
  schedule: "0 4 * * *"  # Daily at 4 AM
  retention_days: 30
  remote_host: 178.156.239.16
  remote_path: /root/backups/openclaw-memory/
  
retrieval:
  embeddings: false  # Phase 1: keyword-only
  index_path: /home/dhawal/openclaw-memory/index/embeddings.db
```

### API Endpoints (`service/api.py`)

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import asyncio

app = FastAPI(title="openclaw-memory", version="1.0.0")

class MemoryWrite(BaseModel):
    tier: str  # 'episodic', 'semantic', 'procedural'
    type: str  # 'experience', 'fact', 'skill', etc.
    payload: dict
    tags: Optional[List[str]] = []

class MemorySearch(BaseModel):
    query: str
    tier: Optional[List[str]] = None  # ['episodic', 'semantic']
    limit: int = 5
    date_from: Optional[str] = None
    date_to: Optional[str] = None

@app.post("/memory/{tier}")
async def write_memory(tier: str, entry: MemoryWrite):
    """Append to JSONL log for specified tier."""
    if tier not in ['episodic', 'semantic', 'procedural']:
        raise HTTPException(400, "Invalid tier")
    
    # Append to appropriate JSONL file
    file_map = {
        'episodic': 'modules/memory/episodic/experiences.jsonl',
        'semantic': 'modules/memory/semantic/facts.jsonl',
        'procedural': 'modules/memory/procedural/skills.jsonl',
    }
    
    file_path = MEMORY_ROOT / file_map[tier]
    await append_jsonl(file_path, entry.payload)
    
    return {"status": "ok", "tier": tier}

@app.post("/memory/search")
async def search_memory(search: MemorySearch):
    """Keyword search across specified tiers."""
    results = []
    
    # Simple grep-based search (Phase 1)
    for tier in (search.tier or ['episodic', 'semantic', 'procedural']):
        tier_results = await keyword_search(tier, search.query, search.limit)
        results.extend(tier_results)
    
    return {"query": search.query, "results": results[:search.limit]}

@app.get("/memory/browse/{path:path}")
async def browse_directory(path: str):
    """List modules and files at path."""
    dir_path = MEMORY_ROOT / "modules" / path
    if not dir_path.exists():
        raise HTTPException(404, "Path not found")
    
    return {
        "path": path,
        "subdirs": [d.name for d in dir_path.iterdir() if d.is_dir()],
        "files": [f.name for f in dir_path.iterdir() if f.is_file()],
    }

@app.get("/health")
async def health_check():
    """Service health status."""
    return {
        "status": "ok",
        "service": "openclaw-memory",
        "version": "1.0.0",
        "uptime": get_uptime(),
    }
```

---

## 2.6 Client Library (`service/client.py`)

```python
import httpx
from typing import Optional, List, Dict, Any

class MemoryClient:
    """Python client for openclaw-memory AOMS."""
    
    def __init__(self, base_url: str = "http://localhost:9100"):
        self.base_url = base_url
        self.client = httpx.AsyncClient()
    
    async def write(
        self,
        tier: str,
        type: str,
        payload: Dict[str, Any],
        tags: Optional[List[str]] = None,
    ) -> Dict:
        """Write to memory tier."""
        response = await self.client.post(
            f"{self.base_url}/memory/{tier}",
            json={"tier": tier, "type": type, "payload": payload, "tags": tags or []},
        )
        response.raise_for_status()
        return response.json()
    
    async def search(
        self,
        query: str,
        tier: Optional[List[str]] = None,
        limit: int = 5,
    ) -> Dict:
        """Search memory."""
        response = await self.client.post(
            f"{self.base_url}/memory/search",
            json={"query": query, "tier": tier, "limit": limit},
        )
        response.raise_for_status()
        return response.json()
    
    async def browse(self, path: str = "") -> Dict:
        """Browse directory tree."""
        response = await self.client.get(f"{self.base_url}/memory/browse/{path}")
        response.raise_for_status()
        return response.json()
    
    async def health(self) -> Dict:
        """Check service health."""
        response = await self.client.get(f"{self.base_url}/health")
        response.raise_for_status()
        return response.json()

# Usage in OpenClaw
from service.client import MemoryClient

memory = MemoryClient()
await memory.write(
    tier="episodic",
    type="experience",
    payload={
        "ts": "2026-02-22T20:00:00Z",
        "type": "achievement",
        "title": "Shipped memory architecture plan",
        "outcome": "Complete design document",
        "tags": ["architecture", "memory"],
    },
)
```

---

## 2.7 Migration Map (Current → New)

| Current File | New Location | Format | Notes |
|-------------|--------------|--------|-------|
| `AGENTS.md` | `openclaw-memory/AGENTS.md` | Markdown | Direct copy |
| `SOUL.md` | `modules/identity/voice.md` | Markdown | Rename |
| `USER.md` | `modules/identity/values.yaml` | YAML | Convert to structured |
| `IDENTITY.md` | `modules/identity/IDENTITY.md` | Markdown | Direct copy |
| `MEMORY.md` | `modules/memory/MEMORY.md` | Markdown | Direct copy |
| `TOOLS.md` | `modules/operations/OPERATIONS.md` | Markdown | Rename |
| `HEARTBEAT.md` | `modules/operations/checklists.yaml` | YAML | Convert |
| `memory/2026-02-22.md` | `modules/memory/episodic/experiences.jsonl` | JSONL | Parse + append |
| `docs/*.md` | `modules/research/` | Markdown | Copy |
| `twitter_engagement_strategy_2026.md` | `modules/content/CONTENT.md` | Markdown | Merge |

---

# Part 3: Integration & Migration Plan

## 3.1 How The Two Architectures Integrate

**Cortex Tiered (L0/L1/L2)** sits **inside** AOMS:

```
AOMS FastAPI Service
├── /memory/episodic → modules/memory/episodic/experiences.jsonl
│   └── (if large) → Cortex L0/L1/L2 for retrieval optimization
│
├── /memory/semantic → modules/memory/semantic/facts.jsonl
│   └── Cortex L0/L1/L2 for research papers, large docs
│
└── /memory/procedural → modules/memory/procedural/skills.jsonl
    └── Cortex L0/L1/L2 for skill documentation
```

**Key insight:** Not all memory needs L0/L1/L2. Use it selectively:

| Memory Type | Storage | Needs L0/L1/L2? | Why |
|-------------|---------|-----------------|-----|
| Daily experiences | JSONL | No | Already small entries |
| Facts | JSONL | No | Already structured |
| Research papers | Markdown + L0/L1/L2 | **Yes** | Large docs, 8-12K tokens |
| Strategy docs | Markdown + L0/L1/L2 | **Yes** | 100+ docs, need fast scan |
| Session logs | JSONL + L0/L1/L2 | Maybe | If sessions are long |

---

## 3.2 Unified Migration Plan (7-Day Shadow Mode)

### Phase 1: Scaffold AOMS (Day 1)

**Actions:**
1. Create `/home/dhawal/openclaw-memory/` repo
2. Scaffold module tree structure
3. Copy current workspace files (no move)
4. Convert USER.md → values.yaml
5. Convert HEARTBEAT.md → checklists.yaml
6. Build FastAPI service skeleton

**Deliverables:**
- ✅ AOMS repo structure
- ✅ FastAPI service running on port 9100
- ✅ Health endpoint returns OK

**No breakage:** OpenClaw still reads from workspace, Daemon still reads from memory_data

---

### Phase 2: Dual-Write OpenClaw (Days 2-3)

**Actions:**
1. Add MemoryClient to OpenClaw
2. Write daily logs to **both**:
   - Legacy: `~/.openclaw/workspace/memory/2026-02-22.md`
   - AOMS: POST `/memory/episodic` (JSONL)
3. Write MEMORY.md updates to **both**:
   - Legacy: `~/.openclaw/workspace/MEMORY.md`
   - AOMS: `modules/memory/MEMORY.md`

**Deliverables:**
- ✅ OpenClaw writes to AOMS successfully
- ✅ Logs show dual-write confirmation
- ✅ No errors, no crashes

**Validation:**
- Compare legacy vs AOMS content daily
- Log any diffs (should be zero)

---

### Phase 3: Shadow-Read Daemon (Days 4-5)

**Actions:**
1. Add MemoryClient to Daemon
2. On Daemon boot:
   - Read from AOMS first
   - Fallback to legacy memory_data if AOMS unavailable
3. Log which source was used
4. Continue writing to legacy memory_data

**Deliverables:**
- ✅ Daemon reads from AOMS successfully
- ✅ Daemon syncs AOMS content into Cortex
- ✅ No data loss, no corruption

**Validation:**
- Daemon consciousness loop still works
- Memory queries return correct results
- Log diffs between AOMS and legacy

---

### Phase 4: Implement Cortex L0/L1/L2 (Day 6)

**Actions:**
1. Deploy PostgreSQL schema (`cortex_tiers`)
2. Implement TierGenerator + TieredRetriever
3. Migrate existing Daemon memory_data → tiered storage
4. Wire TieredRetriever into AOMS `/memory/search` endpoint

**Deliverables:**
- ✅ 8,698 episodes migrated → L0/L1/L2
- ✅ 17,973 facts + 12,213 relations migrated
- ✅ Search queries return L0 abstracts by default
- ✅ Token usage drops 80-90% on typical queries

**Validation:**
- Run 10 test queries, measure token usage before/after
- Verify L0 → L1 → L2 expansion works
- Check directory browsing (`/strategies`, `/research`)

---

### Phase 5: Cutover (Day 7)

**Actions:**
1. OpenClaw stops writing to legacy workspace
2. Daemon stops writing to legacy memory_data
3. AOMS becomes single source of truth
4. Backup legacy data to `/home/dhawal/memory-legacy-backup/`

**Deliverables:**
- ✅ AOMS is canonical memory store
- ✅ Cortex queries use L0/L1/L2
- ✅ Both OpenClaw and Daemon read/write via AOMS
- ✅ Legacy data archived safely

**Rollback plan:**
- If any issues: stop AOMS, revert OpenClaw/Daemon to legacy paths
- All legacy data still intact in backup

---

### Phase 6: VPS Backup Integration (Day 7+)

**Actions:**
1. Add AOMS backup job: daily rsync to skibidi-vps
2. Replicate `/home/dhawal/openclaw-memory/` → VPS `/root/backups/openclaw-memory/`
3. Test restore from VPS backup

**Deliverables:**
- ✅ Daily backups to VPS
- ✅ Successful restore test
- ✅ Backup monitoring via VPS health check

---

## 3.3 Rollback Strategy (Instant)

**If anything breaks during migration:**

1. **Stop AOMS:**
   ```bash
   systemctl --user stop openclaw-memory
   ```

2. **Revert OpenClaw config:**
   - Remove MemoryClient integration
   - Revert to reading from `~/.openclaw/workspace/`

3. **Revert Daemon config:**
   - Remove AOMS client
   - Revert to reading from `/home/dhawal/daemon/memory_data/`

4. **All legacy data intact:**
   - Workspace files never deleted
   - Daemon memory_data never deleted
   - AOMS writes were **additive only**

**Recovery time: <5 minutes**

---

# Part 4: Implementation Checklist

## 4.1 Cortex Tiered Architecture

### Database Setup
- [ ] Create PostgreSQL schema (`cortex_tiers`)
- [ ] Create ChromaDB collections (`cortex_l0`, `cortex_l1`)
- [ ] Test schema DDL executes without errors

### Code Implementation
- [ ] `tier_generator.py` — TierGenerator class
- [ ] `tiered_retrieval.py` — TieredRetriever class
- [ ] `tier_invalidation.py` — InvalidationDaemon
- [ ] `migrate_to_tiered.py` — Batch migration script
- [ ] `smoke_test_tiered.py` — Verification tests

### Integration
- [ ] Wire TierGenerator into Cortex.store_episode()
- [ ] Wire TierGenerator into Cortex.store_skill()
- [ ] Replace Cortex.query() with smart_query()
- [ ] Start InvalidationDaemon as background task

### Migration
- [ ] Run migrate_to_tiered.py (100+ docs)
- [ ] Verify all docs have L0/L1/L2
- [ ] Run smoke_test_tiered.py (6 tests)
- [ ] Measure token usage on 10 test queries

### Validation
- [ ] Token reduction ≥80% confirmed
- [ ] No data loss
- [ ] Concurrent queries work (4 agents)
- [ ] Directory browsing works

---

## 4.2 openclaw-memory AOMS

### Repository Setup
- [ ] Create `/home/dhawal/openclaw-memory/` Git repo
- [ ] Scaffold module tree (9 modules)
- [ ] Copy workspace files → new structure
- [ ] Convert USER.md → values.yaml
- [ ] Convert HEARTBEAT.md → checklists.yaml
- [ ] Define JSONL schemas (5 types)

### Service Implementation
- [ ] `service/api.py` — FastAPI server
- [ ] `service/client.py` — Python client library
- [ ] `service/config.yaml` — Configuration
- [ ] `/memory/{tier}` endpoint (write)
- [ ] `/memory/search` endpoint (search)
- [ ] `/memory/browse/{path}` endpoint
- [ ] `/health` endpoint

### Systemd Service
- [ ] Create `openclaw-memory.service` unit file
- [ ] Install to `~/.config/systemd/user/`
- [ ] Enable and start service
- [ ] Verify service starts on boot

### OpenClaw Integration
- [ ] Add MemoryClient to OpenClaw boot
- [ ] Dual-write daily logs (legacy + AOMS)
- [ ] Dual-write MEMORY.md (legacy + AOMS)
- [ ] Log diffs between sources

### Daemon Integration
- [ ] Add MemoryClient to Daemon boot
- [ ] Shadow-read from AOMS
- [ ] Fallback to legacy if AOMS down
- [ ] Log which source used

### Testing
- [ ] Write test entries to AOMS
- [ ] Search returns correct results
- [ ] Browse directory tree works
- [ ] Health check returns OK
- [ ] Service survives restart

### Backup Integration
- [ ] Add rsync backup to VPS
- [ ] Test backup creation
- [ ] Test restore from backup
- [ ] Verify VPS storage capacity

---

## 4.3 Cutover Checklist

### Pre-Cutover Validation
- [ ] 7 days shadow mode completed
- [ ] Zero data loss observed
- [ ] AOMS uptime 100% for 7 days
- [ ] Diff logs show zero discrepancies
- [ ] Cortex L0/L1/L2 token savings confirmed

### Cutover Actions
- [ ] OpenClaw: remove legacy write paths
- [ ] Daemon: remove legacy write paths
- [ ] Backup legacy data to archive directory
- [ ] Update documentation
- [ ] Announce cutover complete

### Post-Cutover Monitoring
- [ ] Monitor AOMS logs for 24h
- [ ] Check OpenClaw + Daemon still functional
- [ ] Verify backups still running
- [ ] Test rollback procedure (dry run)

---

# Part 5: Success Criteria

## 5.1 Cortex Tiered Architecture

| Metric | Target | Validation |
|--------|--------|------------|
| Token reduction | ≥80% | Measure 10 queries before/after |
| L0 latency | <200ms | Query log analysis |
| Migration success | 100% | All docs have L0/L1/L2 |
| Concurrent queries | 4+ agents, no deadlock | Load test |
| Invalidation speed | <60s | Modify file, check regen |

## 5.2 AOMS

| Metric | Target | Validation |
|--------|--------|------------|
| Service uptime | 99.9% | 7-day shadow mode |
| API response time | <50ms (local) | HTTP benchmark |
| Data integrity | Zero loss | Daily diff logs |
| Backup success | 100% daily | VPS backup monitoring |
| Rollback time | <5 minutes | Dry run test |

## 5.3 Integration

| Metric | Target | Validation |
|--------|--------|------------|
| OpenClaw boot time | No increase | Before/after measurement |
| Daemon boot time | No increase | Before/after measurement |
| Memory query accuracy | 100% | Compare AOMS vs legacy results |
| Cross-system consistency | Zero drift | Dual-write diff logs |

---

# Part 6: Open Questions & Decisions

## 6.1 Critical Decisions (Must Answer Before Implementation)

### 1. AOMS Service Stack
**Question:** FastAPI (Python) or Express (Node.js)?

**Recommendation:** **FastAPI (Python)**
- **Pros:** Integrates with Daemon (Python), async native, OpenAPI docs, type hints
- **Cons:** Node might be faster for simple file I/O

**Decision:** ☐ FastAPI  ☐ Express

---

### 2. Embeddings in Phase 1
**Question:** Include vector embeddings from start or keyword-only?

**Recommendation:** **Keyword-only first**
- **Pros:** Ship faster, simpler, good enough for 90% of queries
- **Cons:** Less semantic search, might need Phase 2 upgrade

**Decision:** ☐ Keyword-only  ☐ Include embeddings

---

### 3. Migrate Existing Daemon Memory
**Question:** Migrate 8,698 episodes + 17,973 facts or start fresh?

**Recommendation:** **Migrate**
- **Pros:** Preserve history, continuity, valuable learnings
- **Cons:** Migration script complexity, potential data quality issues

**Decision:** ☐ Migrate  ☐ Start fresh

---

### 4. Systemd Service
**Question:** Run AOMS as systemd service or manual start?

**Recommendation:** **Systemd**
- **Pros:** Auto-restart on crash, starts on boot, "always-on"
- **Cons:** Slight complexity in setup

**Decision:** ☐ Systemd  ☐ Manual

---

### 5. Repo Location
**Question:** `/home/dhawal/openclaw-memory/` (standalone) or `/home/dhawal/.openclaw/memory/` (embedded)?

**Recommendation:** **Standalone**
- **Pros:** Independent Git repo, publishable product, Daemon can use directly
- **Cons:** Need to configure OpenClaw to read external path

**Decision:** ☐ Standalone  ☐ Embedded

---

### 6. Daily Logs Format
**Question:** Keep as Markdown or convert to JSONL?

**Recommendation:** **Hybrid**
- **Keep:** Daily logs as Markdown (human-readable)
- **Extract:** Structured events → JSONL (machine-readable)
- **Best of both:** Human writes MD, system indexes JSONL

**Decision:** ☐ Hybrid  ☐ JSONL-only  ☐ Markdown-only

---

### 7. Personal Info Location
**Question:** Keep in MEMORY.md or move to identity/values.yaml?

**Recommendation:** **Split**
- **Personal:** Family, preferences → `identity/values.yaml`
- **System:** Infrastructure, decisions → `memory/MEMORY.md`

**Decision:** ☐ Split  ☐ Keep in MEMORY.md

---

## 6.2 Implementation Priority

**Recommended order:**

1. **AOMS scaffold** (Day 1) — Foundation for everything
2. **OpenClaw dual-write** (Days 2-3) — Start data flow
3. **Daemon shadow-read** (Days 4-5) — Prove integration
4. **Cortex L0/L1/L2** (Day 6) — Optimization layer
5. **Cutover** (Day 7) — Single source of truth

**Rationale:** AOMS is the foundation. Cortex tiered is an optimization **on top of** AOMS, not a prerequisite.

---

# Part 7: Risk Assessment & Mitigation

## 7.1 Identified Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Data loss during migration | Low | Critical | Dual-write, never delete legacy |
| AOMS service crashes | Medium | High | Systemd auto-restart, health monitoring |
| Schema drift (JSONL inconsistency) | Medium | Medium | Schema validation, header enforcement |
| Sync conflicts (dual-write) | Low | Medium | Append-only logs, server-side timestamps |
| Index drift (L0/L1 stale) | Medium | Low | InvalidationDaemon file watcher |
| Performance degradation | Low | Medium | Benchmark before/after, rollback if slower |
| VPS backup failure | Low | High | Daily health checks, test restore weekly |

## 7.2 Mitigation Strategies

### Data Loss Prevention
- **Never delete legacy data** during migration
- Dual-write for 7 days minimum
- Daily diff logs (AOMS vs legacy)
- Automated backup before any destructive operation

### Service Reliability
- Systemd with automatic restart on failure
- Health check endpoint (`/health`)
- Logging to file + systemd journal
- VPS backup as disaster recovery

### Data Integrity
- JSONL schema validation on write
- Append-only (no in-place edits)
- Server-side timestamps prevent conflicts
- Daily checksum verification

### Performance Monitoring
- Query latency logging (query_log table)
- Token usage tracking (before/after Cortex tiered)
- API response time benchmarks
- Alert if response time >100ms

---

# Part 8: Post-Migration Roadmap

## Phase 2 Enhancements (After 30 Days)

### 1. Vector Embeddings
- Integrate nomic-embed-text via Ollama
- Index episodic experiences + research papers
- Semantic search via `/memory/search?mode=semantic`

### 2. Web UI
- Simple web dashboard for browsing memory
- Timeline view of episodic experiences
- Knowledge graph visualization (semantic facts)

### 3. Multi-User Support
- Authentication layer
- Per-user memory isolation
- Shared semantic knowledge pool

### 4. Advanced Analytics
- Memory growth metrics dashboard
- Query pattern analysis
- Skill effectiveness tracking (procedural)

### 5. Export/Import
- Export memory to portable format (ZIP)
- Import from other systems
- Sync between multiple OpenClaw instances

---

# Part 9: Documentation & Publishing

## 9.1 Repository Documentation

### README.md
```markdown
# openclaw-memory

**Always-On Memory Service for AI Agents**

Unified memory architecture with 4-tier semantics (Working, Episodic, Semantic, Procedural) and progressive disclosure (L0/L1/L2 hierarchical retrieval).

## Features
- FastAPI service (local-only)
- JSONL append-only logs
- Progressive disclosure (router → module → data)
- 88% token reduction on queries
- Backup/restore to remote VPS
- Compatible with OpenClaw + autonomous agents

## Installation
```bash
git clone https://github.com/dhawal/openclaw-memory.git
cd openclaw-memory
pip install -r requirements.txt
python service/api.py
```

## Usage
See [USAGE.md](USAGE.md) for API examples.
```

### USAGE.md
- API endpoint documentation
- Python client examples
- JSONL schema reference
- Migration guide

### ARCHITECTURE.md
- System overview diagram
- Module breakdown
- Retrieval flow (L0 → L1 → L2)
- Integration with OpenClaw/Daemon

---

## 9.2 Publishing Strategy

### Open Source (GitHub)
- MIT license
- Public repo after 30-day private testing
- Tag v1.0.0 when stable

### Package Distribution
- **PyPI:** `pip install openclaw-memory`
- **npm:** `npm install @openclaw/memory` (if Node client built)

### Blog Post / Launch
- "Building an Always-On Memory Service for AI Agents"
- Technical deep-dive on L0/L1/L2 architecture
- Tweet thread with key insights
- Post to HN, Reddit r/LocalLLaMA

---

# Part 10: Summary & Next Steps

## What We've Designed

1. **Cortex Tiered Architecture (L0/L1/L2)**
   - 88% token reduction on memory queries
   - PostgreSQL + ChromaDB + filesystem hybrid
   - Auto-generation, invalidation, migration

2. **openclaw-memory AOMS**
   - Standalone memory service (FastAPI)
   - Survives Daemon downtime
   - Publishable product (npm/pip)

3. **Unified Integration**
   - AOMS provides API layer
   - Cortex tiered provides retrieval optimization
   - 7-day shadow mode migration (zero breakage)

## Implementation Estimate

| Component | Effort | Who |
|-----------|--------|-----|
| AOMS scaffold + FastAPI | 1 day | Codex or human |
| Cortex L0/L1/L2 implementation | 1 day | Codex |
| Migration scripts | 0.5 day | Codex |
| Testing + validation | 0.5 day | Human |
| Documentation | 0.5 day | Human |
| **Total** | **3.5 days** | **Mixed** |

## Critical Path

1. **Answer 7 decision questions** (above in Part 6.1)
2. **Scaffold AOMS** (Day 1)
3. **OpenClaw dual-write** (Days 2-3)
4. **Daemon shadow-read** (Days 4-5)
5. **Implement Cortex tiered** (Day 6)
6. **Cutover** (Day 7)

## Recommended Action

**Option A: Ship AOMS first**
- Focus on AOMS (Days 1-5)
- Prove dual-write + shadow-read
- Add Cortex tiered later (optimization)

**Option B: Ship Cortex tiered first**
- Focus on Daemon optimization only
- Skip AOMS for now
- Prove 88% token reduction

**Option C: Full integration (recommended)**
- Build both in parallel
- AOMS provides foundation
- Cortex tiered provides optimization
- 7-day migration, zero breakage

---

## Final Recommendation

**I recommend Option C: Full integration over 7 days.**

**Rationale:**
1. Both architectures are well-designed and complementary
2. AOMS solves "memory survives Daemon downtime"
3. Cortex solves "queries are too expensive"
4. Migration plan is safe (dual-write, shadow mode, rollback)
5. After 7 days, you have a publishable product + optimized Daemon

**First step:** Answer the 7 decision questions, then spawn Codex to implement.

---

**End of Master Plan**

*This document is the complete blueprint for unified memory architecture. Implementation can begin immediately after decision questions are answered.*
