# Task: Build openclaw-memory AOMS (Always-On Memory Service)

## Status: IN_PROGRESS

## Mission
Build the standalone memory service from MEMORY_ARCHITECTURE_MASTER_PLAN.md, incorporating weighted memory patterns from the weighted-memory-poc we already built.

## What to Build

**openclaw-memory AOMS:**
- Standalone FastAPI service (port 9100, local only)
- 4-tier memory (Working, Episodic, Semantic, Procedural)
- Module tree structure with JSONL storage
- Progressive disclosure (L0/L1/L2 hierarchical retrieval)
- Dual interface: OpenClaw workspace sync + Daemon direct API
- Publishable as npm/pip package

## Resources

**Foundation (already built):**
- `~/projects/weighted-memory-poc/` — Weighted memory PoC with reinforcement learning
- `~/.openclaw/workspace/docs/MEMORY_ARCHITECTURE_MASTER_PLAN.md` — Complete blueprint
- `~/.openclaw/workspace/docs/memelord-analysis.md` — Weighting patterns to incorporate

**Current workspace:**
- `/home/dhawal/.openclaw/workspace/` — Files to migrate into AOMS structure

## Implementation Steps

### 1. Scaffold Repository
- [ ] Create `/home/dhawal/openclaw-memory/` Git repo
- [ ] Build module tree (Part 2.3 of master plan):
  - modules/identity/
  - modules/memory/ (episodic, semantic, procedural)
  - modules/operations/
  - modules/projects/
  - modules/research/
  - modules/content/
  - schemas/
  - service/

### 2. Define JSONL Schemas
- [ ] Experience schema (episodic/experiences.jsonl)
- [ ] Decision schema (episodic/decisions.jsonl)
- [ ] Fact schema (semantic/facts.jsonl)
- [ ] Skill schema (procedural/skills.jsonl)
- [ ] Include schema validation headers

### 3. Build FastAPI Service
- [ ] service/api.py with endpoints:
  - POST /memory/{tier} (write)
  - POST /memory/search (search)
  - GET /memory/browse/{path} (directory listing)
  - GET /health (status)
- [ ] service/client.py (Python client library)
- [ ] service/config.yaml (configuration)

### 4. Incorporate Weighted Memory Patterns
From weighted-memory-poc, add:
- [ ] Weight adjustment from task outcomes
- [ ] Category-based initial weights
- [ ] Reinforcement learning loop
- [ ] Time decay (0.995^days)

From Memelord analysis, add:
- [ ] Memory contradiction (active deletion)
- [ ] Recency scoring in retrieval

### 5. Implement Progressive Disclosure (L0/L1/L2)
- [ ] L0: 100-token abstracts (fast scan)
- [ ] L1: 2K overviews (structured summary)
- [ ] L2: Full content (load on demand)
- [ ] Auto-generation via Ollama (deepseek-r1:7b)
- [ ] PostgreSQL schema (cortex_tiers)
- [ ] ChromaDB collections (cortex_l0, cortex_l1)

### 6. Migration Script
- [ ] Convert workspace files → AOMS structure
- [ ] USER.md → modules/identity/values.yaml
- [ ] MEMORY.md → modules/memory/MEMORY.md
- [ ] memory/2026-02-*.md → episodic/experiences.jsonl
- [ ] HEARTBEAT.md → operations/checklists.yaml

### 7. Testing
- [ ] Write to AOMS via API
- [ ] Search returns correct results
- [ ] Browse directory tree works
- [ ] Health check passes
- [ ] Weighted retrieval prioritizes correctly

### 8. Documentation
- [ ] README.md (installation, usage)
- [ ] ARCHITECTURE.md (system design)
- [ ] API.md (endpoint reference)
- [ ] Migration guide

## Success Criteria

- [ ] Service runs on localhost:9100
- [ ] Health endpoint returns OK
- [ ] Can write/read all 4 tiers
- [ ] Search works across tiers
- [ ] Weighted retrieval boosts helpful memories
- [ ] L0/L1/L2 reduces token usage by >80%
- [ ] No data loss during migration
- [ ] Documentation complete

## Constraints

- Local only (no external access)
- Use Ollama for embeddings/generation (nomic-embed-text, deepseek-r1:7b)
- PostgreSQL for metadata, JSONL for content
- Append-only (no in-place edits)
- Must work with both OpenClaw and Daemon

## Key Decisions Already Made (from master plan)

1. FastAPI (Python) vs Express → **FastAPI**
2. Embeddings in Phase 1 → **Keyword-only first, embeddings later**
3. Migrate existing Daemon memory → **Yes**
4. Run as systemd service → **Yes**
5. Repo location → **Standalone** (`/home/dhawal/openclaw-memory/`)
6. Daily logs format → **Hybrid** (Markdown + JSONL extract)
7. Personal info → **Split** (identity/values.yaml + memory/MEMORY.md)

---

**Build this. Make it work. 🧠**
