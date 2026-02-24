# Memory Layer Detach Plan (Always-On, Shared)

## Goal
Create a **standalone memory product/module** that both **OpenClaw (ULTRON)** and **Daemon** can read/write, even when Daemon is offline. This decouples memory from Daemon runtime while preserving 4-tier semantics and **does not break current architecture** (backward-compatible, additive).

---

## Why
- Daemon is heavy and sometimes offline; memory should not vanish with it.
- OpenClaw needs reliable read/write regardless of Daemon health.
- Shared memory enables consistent context across both systems.

---

## Target Architecture (High Level)

### 0) Standalone Package / Repo
**Name (placeholder):** `openclaw-memory`
- Runs as its own service or library
- Provides a stable API for memory read/write/search
- Can be embedded in Daemon or OpenClaw, but can also run independently

### 1) Always-On Memory Service (AOMS)
A lightweight service that manages the memory store and exposes a local API.

**Responsibilities**
- Read/write operations for all tiers
- Append-only logs + schemas
- Indexing for retrieval
- Health checks + backups

**Interfaces**
- Local HTTP API (fast, local only)
- CLI helper for manual ops

### 2) Shared Memory Store
A file-first + index hybrid so it survives restarts and can be audited.

**Storage Layout**
```
memory/
  working/               # fast, volatile state
  episodic/              # append-only events
  semantic/              # facts + relations
  procedural/            # learned skills / patterns
  index/                 # lightweight retrieval indices
  snapshots/             # periodic tar/zip backups
```

**Formats**
- JSONL for append-only logs
- YAML for configs / schemas
- Markdown for human-readable notes

### 3) OpenClaw Integration
- OpenClaw reads/writes via AOMS API
- Boot sequence queries memory service first
- Daily logs written directly to AOMS

### 4) Daemon Integration
- Daemon uses same AOMS API
- On boot, Daemon syncs into its internal structures (optional)
- If Daemon is down, memory still available to OpenClaw

---

## 4-Tier Mapping

| Tier | File Store | API Endpoint | Notes |
|------|------------|--------------|-------|
| Working | `memory/working/` | `/memory/working` | Short-lived, last N tasks |
| Episodic | `memory/episodic/*.jsonl` | `/memory/episodic` | Append-only events |
| Semantic | `memory/semantic/*.jsonl` | `/memory/semantic` | Facts, relations |
| Procedural | `memory/procedural/*.jsonl` | `/memory/procedural` | Skills + patterns |

---

## File-System Context Architecture (from article)

### Progressive Disclosure
- **Level 1:** Router file always loaded (task → module)
- **Level 2:** Module instruction file (40–100 lines)
- **Level 3:** Data logs (JSONL/YAML/MD) loaded only when needed

### Instruction Hierarchy
- **Repo onboarding file** (always loaded)
- **Agent rules file** (decision table + global policies)
- **Module rules** (domain-specific constraints)

### Format–Function Mapping
- **JSONL**: append-only logs (episodic memory)
- **YAML**: configs, schemas, priorities
- **Markdown**: narrative, voice, explanations

### Why this matters
- Prevents context bloat
- Keeps model focused on relevant memory
- Allows safe append-only history

---

## API Sketch

**Write**
```
POST /memory/{tier}
{
  "type": "event|fact|skill",
  "payload": {...},
  "tags": ["tag1","tag2"],
  "ts": "2026-02-22T11:00:00Z"
}
```

**Search**
```
POST /memory/search
{
  "query": "daemon restart status",
  "tier": ["episodic","semantic"],
  "limit": 5
}
```

---

## Retrieval Layer
- Minimal local embedding index (optional)
- Default fallback: keyword + tag search
- Embed only episodic + semantic for relevance

---

## Reliability & Persistence
- Append-only JSONL with schema header lines
- Daily snapshots to VPS
- Compact/rollup job for episodic logs
- Integrity checks on start

---

## Migration Plan

### Phase 1: Externalize Writes (OpenClaw)
- OpenClaw writes daily logs + MEMORY.md to AOMS
- Continue existing filesystem writes (dual-write)

### Phase 2: Daemon Reads from AOMS
- Daemon reads from AOMS on boot
- Keep Daemon local JSON fallback if AOMS unavailable

### Phase 3: Single Source of Truth
- Stop dual-write
- AOMS becomes canonical store

---

## Concrete Implementation Path

1. **Create memory service** (Python FastAPI or Node)
2. **Define schemas** for each tier (JSONL headers)
3. **Add OpenClaw adapter** (simple client wrapper)
4. **Add Daemon adapter** (sync layer)
5. **Create daily backup job** to VPS

---

## Risks
- Sync conflicts if both write without ordering rules
- Index drift if embeddings not updated

**Mitigation**
- Server-side append timestamps
- Lock per tier on write
- Daily index rebuild

---

## Next Actions
- Decide on service stack (FastAPI vs Node)
- Agree on storage format + schemas
- Implement minimal AOMS prototype
- Wire OpenClaw to AOMS first

---

## Questions
1) Do you want AOMS to run as a systemd service?
2) Should it expose embeddings or keep it keyword-only at first?
3) Do you want to migrate existing Daemon memory_data into this store?
