# AOMS Architecture

**openclaw-memory** — Always-On Memory Service

---

## System Overview

```
┌─────────────────────────────────────────────────────────┐
│                   USER INTERFACES                       │
│  OpenClaw Agent (ULTRON) │ Daemon Agents (autonomous)  │
└────────────────┬────────────────────┬───────────────────┘
                 │                    │
                 v                    v
┌─────────────────────────────────────────────────────────┐
│              ALWAYS-ON MEMORY SERVICE (AOMS)            │
│  • FastAPI HTTP server (localhost:9100)                 │
│  • Systemd service (auto-restart, boot-on-start)        │
│  • Dual interface: file sync + direct API               │
│  • Survives Daemon downtime                             │
└────────────────┬────────────────────────────────────────┘
                 │
        ┌────────┴────────┐
        │                 │
        v                 v
┌──────────────┐  ┌──────────────────────┐
│ Core Memory  │  │ Cortex L0/L1/L2      │
│ (JSONL)      │  │ (Progressive)        │
├──────────────┤  ├──────────────────────┤
│ • Episodic   │  │ • L0: 100-token abs  │
│ • Semantic   │  │ • L1: 2K overview    │
│ • Procedural │  │ • L2: Full content   │
│              │  │ • 95-99% reduction   │
└──────────────┘  └──────────────────────┘
        │                 │
        v                 v
┌─────────────────────────────────────────┐
│           STORAGE LAYER                 │
│  • JSONL (append-only logs)             │
│  • SQLite (Cortex metadata)             │
│  • ChromaDB (vector embeddings)         │
│  • Filesystem (L2 content)              │
└─────────────────────────────────────────┘
```

---

## Components

### 1. FastAPI Service

**Location:** `service/api.py`

**Endpoints:**

| Endpoint | Purpose | Layer |
|----------|---------|-------|
| POST `/memory/{tier}` | Write memory | Core |
| POST `/memory/search` | Keyword search | Core |
| POST `/memory/weight` | Adjust weights (RL) | Core |
| GET `/memory/browse/{path}` | Directory tree | Core |
| POST `/cortex/ingest` | Ingest doc → L0/L1/L2 | Cortex |
| POST `/cortex/query` | Smart query + escalation | Cortex |
| GET `/cortex/document/{id}` | Get specific tier | Cortex |
| POST `/cortex/regenerate/{id}` | Regenerate L0/L1 | Cortex |
| GET `/cortex/documents` | List all | Cortex |
| GET `/health` | Service status | Meta |

### 2. Core Memory (Episodic/Semantic/Procedural)

**Storage:** JSONL (JSON Lines)

**Tiers:**

- **Episodic** (`modules/memory/episodic/*.jsonl`)
  - Experiences, decisions, failures
  - Timestamped events
  - Weighted by category (user_teaching=2.0, observation=0.8)

- **Semantic** (`modules/memory/semantic/*.jsonl`)
  - Facts (subject-predicate-object triples)
  - Relations (entity links)
  - Confidence scores

- **Procedural** (`modules/memory/procedural/*.jsonl`)
  - Skills (learned procedures)
  - Patterns (recurring workflows)
  - Success rates, usage metrics

**JSONL Schema:**
```jsonl
{"schema":"openclaw.experience.v1","fields":["ts","type","title","outcome","tags","weight"]}
{"id":"abc-123","ts":"2026-02-23T21:00:00Z","type":"achievement","title":"Deployed AOMS","outcome":"Success","tags":["deployment"],"weight":1.0}
```

### 3. Cortex L0/L1/L2 (Progressive Disclosure)

**Purpose:** 95-99% token reduction for large documents

**Tiers:**

| Tier | Size | Purpose | Use Case |
|------|------|---------|----------|
| L0 | 50-100 tokens | One-sentence abstract | Fast scan, "what exists?" |
| L1 | 500-2K tokens | Structured overview | "Tell me more" |
| L2 | Full document | Complete content | "All details" |

**Auto-Generation:**

```python
# L0 Prompt
"Summarize in ONE sentence (max 100 tokens): 
what this document is about, its primary conclusion, 
and one key differentiator."

# L1 Prompt
"Create a structured overview (under 2000 tokens):
1. PURPOSE: What this is and why it exists
2. KEY POINTS: 3-5 most important facts
3. METRICS: Quantitative results
4. RELATIONSHIPS: What this relates to
5. ACTIONABILITY: When/how to use"
```

**Model:** `deepseek-r1:7b` (Ollama, local, free)

**Storage:**
- SQLite: Metadata + tier references (`cortex/cortex.db`)
- ChromaDB: Vector embeddings (`cortex/chroma/`)
- Filesystem: L2 full content (`cortex/documents/`)

**Auto-Escalation:**

```python
def smart_query(query, token_budget=2000):
    # 1. Search L0 (fast, ~100 tok/result)
    l0_results = chroma_l0.query(query, top_k=10)
    
    # 2. Expand high scorers to L1
    for result in l0_results:
        if result.score > 0.4 and budget_remaining:
            expand_to_l1(result)
    
    # 3. Only load L2 if score > 0.7 and critical
    for result in l1_results:
        if result.score > 0.7 and budget_remaining:
            load_l2(result)
    
    return results  # Stays within token_budget
```

### 4. Weighted Memory (Reinforcement Learning)

**Pattern:** Memory quality improves over time

**Weight Adjustment:**

```python
task_score = calculate_outcome(
    success=True/False,
    tokens_used=12000,
    user_corrections=0,
    duration_ms=4200
)

if task_score > 0.7:
    weight *= 1.1  # Boost helpful memories
elif task_score < 0.3:
    weight *= 0.9  # Decay unhelpful memories
else:
    weight *= 0.995  # Time decay
```

**Category-Based Initial Weights:**

| Type | Initial Weight | Rationale |
|------|----------------|-----------|
| user_teaching | 2.0 | User explicitly taught us |
| user_correction | 1.8 | User corrected us |
| self_correction | 1.5 | We caught our mistake |
| achievement | 1.3 | Successful completion |
| skill | 1.2 | Learned procedure |
| failure | 1.0 | Failed attempt (learn from it) |
| observation | 0.8 | Passive observation |

**Retrieval Scoring:**

```python
score = (
    keyword_hits 
    × weight 
    × (0.995 ** days_old)  # Recency decay
)
```

Range: weights clamped to 0.1 – 5.0

### 5. Module Tree Structure

```
openclaw-memory/
├── modules/
│   ├── identity/
│   │   ├── IDENTITY.md          # Who we are
│   │   ├── voice.md             # Communication style
│   │   └── values.yaml          # Personal info
│   ├── operations/
│   │   ├── OPERATIONS.md        # Priorities, workflows
│   │   ├── priorities.yaml      # Task rules
│   │   └── checklists.yaml      # Heartbeat checks
│   ├── memory/
│   │   ├── MEMORY.md            # Overview
│   │   ├── episodic/
│   │   │   ├── experiences.jsonl
│   │   │   ├── decisions.jsonl
│   │   │   └── failures.jsonl
│   │   ├── semantic/
│   │   │   ├── facts.jsonl
│   │   │   └── relations.jsonl
│   │   └── procedural/
│   │       ├── skills.jsonl
│   │       └── patterns.jsonl
│   ├── projects/
│   │   ├── projects.yaml
│   │   └── status.jsonl
│   ├── research/
│   │   └── *.md                 # Research docs
│   ├── content/
│   │   ├── CONTENT.md
│   │   ├── ideas.jsonl
│   │   └── templates/
│   └── network/
│       ├── contacts.jsonl
│       └── interactions.jsonl
├── cortex/
│   ├── schema.sql
│   ├── db.py
│   ├── tier_generator.py
│   ├── tiered_retrieval.py
│   ├── cortex.db               # SQLite metadata
│   ├── chroma/                 # ChromaDB vector index
│   └── documents/              # L2 content
├── service/
│   ├── api.py                  # FastAPI app
│   ├── storage.py              # JSONL storage engine
│   ├── models.py               # Pydantic schemas
│   ├── client.py               # Python client
│   └── config.yaml
├── schemas/
│   └── jsonl_schemas.yaml
├── snapshots/
│   └── aoms-*.tar.gz           # Daily backups
├── openclaw_integration.py     # OpenClaw helpers
├── daemon_integration.py       # Daemon helpers
├── migrate_workspace.py        # Migration script
├── ingest_all_docs.py          # Bulk ingestion
├── backup_to_vps.sh            # VPS backup
├── run.py                      # Entry point
└── requirements.txt
```

---

## Data Flow

### Write Flow (Episodic Memory)

```
OpenClaw/Daemon
    │
    v
POST /memory/episodic
    │
    v
storage.py (validate schema)
    │
    v
Append to modules/memory/episodic/experiences.jsonl
    │
    v
Return entry_id
```

### Read Flow (Cortex Smart Query)

```
Client
    │
    v
POST /cortex/query {"query": "...", "token_budget": 2000}
    │
    v
tiered_retrieval.py
    │
    ├─> ChromaDB search L0 (top 10)
    │   └─> Score results
    │
    ├─> Auto-expand to L1 (if score > 0.4)
    │   └─> Load from SQLite + ChromaDB
    │
    ├─> Auto-load L2 (if score > 0.7)
    │   └─> Read from filesystem
    │
    v
Return results (within token budget)
```

### Ingestion Flow (Cortex)

```
POST /cortex/ingest {"title": "...", "content": "..."}
    │
    v
tier_generator.py
    │
    ├─> Call Ollama deepseek-r1:7b (generate L0 abstract)
    │   └─> ~100 tokens
    │
    ├─> Call Ollama deepseek-r1:7b (generate L1 overview)
    │   └─> ~2K tokens
    │
    ├─> Store L2 on filesystem
    │   └─> cortex/documents/{doc_id}.md
    │
    ├─> Insert metadata into SQLite
    │   └─> cortex.db (documents table)
    │
    ├─> Index L0 + L1 in ChromaDB
    │   └─> cortex_l0, cortex_l1 collections
    │
    v
Return {"doc_id": "...", "l0_tokens": 87, "l1_tokens": 555, "l2_tokens": 10896}
```

---

## Performance

### Token Reduction (Measured)

**Test doc:** MEMORY_ARCHITECTURE_MASTER_PLAN.md (45KB, 10,896 tokens)

| Tier | Tokens | Reduction |
|------|--------|-----------|
| L0 | 87 | 99.2% |
| L1 | 555 | 95.0% |
| L2 | 10,896 | 0% (full) |

**Smart query (2 docs):**
- Without Cortex: 12,481 tokens (both L2)
- With Cortex: 616 tokens (1×L1 + 1×L0)
- **Reduction: 95%**

### Retrieval Speed

| Operation | Latency | Notes |
|-----------|---------|-------|
| L0 search (10 results) | <200ms | ChromaDB query |
| L1 expansion | <50ms | SQLite + disk read |
| L2 load | <100ms | Filesystem read |
| Smart query (total) | <300ms | All tiers |

### Storage Efficiency

| Data Type | Format | Size | Compression |
|-----------|--------|------|-------------|
| Episodic entries | JSONL | ~200 bytes/entry | gzip: 3:1 |
| L0 abstracts | SQLite | ~100 tokens | - |
| L1 overviews | SQLite | ~2K tokens | - |
| L2 content | Markdown | Original size | - |
| Vector embeddings | ChromaDB | ~1KB/doc | Built-in |

---

## Scalability

### Current Limits

- **Episodic entries:** No practical limit (JSONL append-only)
- **Cortex documents:** 10,000+ (SQLite + ChromaDB handles this easily)
- **Concurrent requests:** 100+ (FastAPI async)
- **Memory footprint:** ~100MB (service + ChromaDB)

### Scaling Strategy

If needed:
1. **Horizontal:** Run multiple AOMS instances (partition by tier)
2. **Vertical:** Migrate SQLite → PostgreSQL (same schema)
3. **Sharding:** Partition by date/category
4. **Caching:** Add Redis for hot queries

---

## Security

### Current Posture

- **Network:** Localhost only (127.0.0.1:9100)
- **Auth:** None (trusted local access)
- **Encryption:** None (local filesystem)

### Production Hardening (If Needed)

1. **Auth:** Add API key header validation
2. **Encryption:** TLS for API, encrypt-at-rest for SQLite
3. **Network:** Firewall rules (iptables)
4. **Audit:** Request logging, access control

---

## Backup & Recovery

### Backup Strategy

**Daily automated backup:**
- Cron: 4 AM daily
- Script: `backup_to_vps.sh`
- Target: `root@178.156.239.16:/root/backups/openclaw-memory/`

**What's backed up:**
- All JSONL files
- SQLite databases
- ChromaDB collections
- Module tree (Markdown, YAML)

**Retention:**
- Local: 7 days
- VPS: Indefinite (manual cleanup)

### Recovery

**Full restore:**
```bash
scp root@178.156.239.16:/root/backups/openclaw-memory/aoms-*.tar.gz /tmp/
cd /home/dhawal
tar -xzf /tmp/aoms-*.tar.gz
systemctl --user restart openclaw-memory
```

**Partial restore (live sync):**
```bash
rsync -avz root@178.156.239.16:/root/backups/openclaw-memory/live/ \
    /home/dhawal/openclaw-memory/
```

---

## Monitoring

### Health Checks

**Systemd:**
```bash
systemctl --user status openclaw-memory
```

**HTTP:**
```bash
curl http://localhost:9100/health
```

**Expected response:**
```json
{
  "status": "ok",
  "uptime_seconds": 3600,
  "tiers": {
    "episodic": 50,
    "semantic": 10,
    "procedural": 5
  }
}
```

### Metrics to Monitor

- Service uptime (systemd)
- API response time (<300ms target)
- Disk usage (JSONL growth)
- Backup success (daily logs)
- Ollama availability (L0/L1 generation)

---

## Design Principles

1. **Append-only** — Never delete, only deprecate/supersede
2. **Local-first** — No external dependencies (Ollama local)
3. **Progressive disclosure** — Load only what's needed
4. **Weighted retrieval** — Quality improves over time
5. **Fail gracefully** — Service survives Ollama/ChromaDB issues
6. **Zero-downtime migration** — Dual-write, shadow-read patterns

---

**Built:** 2026-02-23  
**Version:** 1.1.0  
**Status:** Production-ready  
**Docs:** USAGE.md, INTEGRATION.md
