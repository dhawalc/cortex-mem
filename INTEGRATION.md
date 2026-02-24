# OpenClaw Integration Guide

## Quick Start

### 1. Service is Already Running

AOMS runs as systemd service on port 9100:
```bash
systemctl --user status openclaw-memory
curl http://localhost:9100/health
```

### 2. Use in OpenClaw

Add to your OpenClaw agent code:

```python
import sys
sys.path.insert(0, "/home/dhawal/openclaw-memory")
from openclaw_integration import log_achievement, log_error, log_fact, sync_to_aoms

# Log achievements
await log_achievement(
    title="Task completed",
    outcome="Successfully deployed feature X",
    tags=["deployment", "success"]
)

# Log errors
await log_error(
    title="API call failed",
    error="Connection timeout after 30s",
    tags=["api", "error"]
)

# Log facts
await log_fact(
    subject="Dhawal",
    predicate="prefers",
    object="Ollama models for cron jobs",
    confidence=1.0,
    source="USER.md"
)

# Direct API call (advanced)
await sync_to_aoms(
    tier="episodic",
    entry_type="experience",
    payload={
        "ts": "2026-02-23T20:00:00Z",
        "type": "decision",
        "title": "Switched to AOMS",
        "outcome": "Unified memory across systems",
        "tags": ["architecture", "memory"]
    }
)
```

### 3. Dual-Write Pattern

**Current workflow (before AOMS):**
```python
# Write to workspace
with open("~/.openclaw/workspace/memory/2026-02-23.md", "a") as f:
    f.write(f"\n## {title}\n{content}\n")
```

**New dual-write workflow:**
```python
# Write to workspace (keep this)
with open("~/.openclaw/workspace/memory/2026-02-23.md", "a") as f:
    f.write(f"\n## {title}\n{content}\n")

# ALSO write to AOMS (add this)
await log_achievement(title, content, tags=["daily-log"])
```

**Benefits:**
- Workspace files unchanged (legacy compatibility)
- AOMS gets structured data (searchable, weighted)
- Gradual migration (can switch later)

### 4. Check It's Working

```bash
# Query AOMS
curl -X POST http://localhost:9100/memory/search \
  -H "Content-Type: application/json" \
  -d '{"query":"deployment","limit":5}' | jq .

# Browse structure
curl http://localhost:9100/memory/browse/memory/episodic | jq .
```

## Migration Complete

Workspace files already copied to AOMS:
- ✅ USER.md → modules/identity/values.yaml
- ✅ MEMORY.md → modules/memory/MEMORY.md
- ✅ SOUL.md → modules/identity/voice.md
- ✅ IDENTITY.md → modules/identity/IDENTITY.md
- ✅ memory/2026-02-*.md → episodic/experiences.jsonl (28 entries)
- ✅ docs/*.md → modules/research/ (17 files)

**Original files untouched** — still at `~/.openclaw/workspace/`

## API Reference

### Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Service status |
| `/memory/{tier}` | POST | Write entry |
| `/memory/search` | POST | Search across tiers |
| `/memory/weight` | POST | Adjust weights (reinforcement) |
| `/memory/browse/{path}` | GET | Browse directory tree |

### Tiers

- **episodic** — experiences, decisions, failures
- **semantic** — facts, relations
- **procedural** — skills, patterns

### Python Client

Full async client available:

```python
from service.client import MemoryClient

memory = MemoryClient()
await memory.write("episodic", "experience", {"ts": "...", "title": "..."})
results = await memory.search("query text", tier=["episodic"], limit=5)
```

## Systemd Service

Auto-starts on boot:
```bash
systemctl --user enable openclaw-memory
systemctl --user start openclaw-memory
systemctl --user status openclaw-memory
journalctl --user -u openclaw-memory -f  # Follow logs
```

## Backup

Daily backups to VPS (planned):
```bash
# Add to crontab
0 4 * * * rsync -avz /home/dhawal/openclaw-memory/ root@178.156.239.16:/root/backups/openclaw-memory/
```

## Next Steps

1. **Test dual-write** — Add `log_achievement()` calls to OpenClaw
2. **Verify search** — Query AOMS, check results
3. **Monitor service** — Check systemd logs for errors
4. **Add to Daemon** — Daemon can also use AOMS API

---

**Built:** 2026-02-23  
**Status:** Production-ready  
**Location:** `/home/dhawal/openclaw-memory/`
