# Migration Guide

## From OpenClaw Workspace

If you have an existing OpenClaw workspace (`~/.openclaw/workspace/`), cortex-mem can import it:

```bash
cortex-mem migrate ~/.openclaw/workspace
```

This will:
- Parse markdown files and extract structured entries
- Convert `USER.md` to identity/values
- Convert daily logs to episodic entries
- Convert learned facts to semantic entries
- Preserve all original files (copy, never move)

### What Gets Migrated

| Source | Destination | Format |
|--------|------------|--------|
| `USER.md` | `modules/identity/values.yaml` | YAML |
| `daily-logs/*.md` | `modules/memory/episodic/experiences.jsonl` | JSONL |
| `facts/*.md` | `modules/memory/semantic/facts.jsonl` | JSONL |
| `skills/*.md` | `modules/memory/procedural/skills.jsonl` | JSONL |

### Verify Migration

```bash
cortex-mem status
# Check entry counts increased

cortex-mem search "your recent task"
# Verify migrated data is searchable
```

## From Daemon Memory

For migrating Daemon's Cortex memory (episodic, semantic, procedural) to AOMS:

### 1. Run the Export Script

```bash
cd /path/to/cortex-mem
python scripts/export_daemon_memory.py
```

The script:
- Reads from Daemon's `memory_data/` directory
- Batches writes (100 entries at a time)
- Tracks migrated entry IDs for idempotency (safe to re-run)
- Stores checkpoint in `scripts/migrated_ids.json`

### 2. Verify

```bash
cortex-mem status
cortex-mem search "consciousness"
```

### 3. Enable Dual-Write

In the Daemon configuration:

```bash
export ULTRON_AOMS_ENABLED=1
```

This enables the Daemon to write to both its local memory stores and AOMS simultaneously. The dual-write is fire-and-forget — if AOMS is down, the Daemon continues using local stores.

### 4. Monitor

Watch for dual-write confirmations in Daemon logs:

```
HTTP Request: POST http://localhost:9100/memory/episodic "HTTP/1.1 200 OK"
```

After 7 days of stable dual-write, you can switch the Daemon to read from AOMS exclusively.

## From Custom Sources

### JSONL Import

If you have data in JSONL format matching the AOMS schema, write directly:

```python
import json
import httpx

with open("my_episodes.jsonl") as f:
    for line in f:
        entry = json.loads(line)
        httpx.post("http://localhost:9100/memory/episodic", json={
            "type": "experience",
            "payload": entry,
        })
```

### Bulk Import

For large datasets, batch your writes:

```python
import httpx
import json

async def bulk_import(filepath: str, tier: str, entry_type: str, batch_size: int = 100):
    async with httpx.AsyncClient(timeout=30.0) as client:
        entries = [json.loads(line) for line in open(filepath)]
        for i in range(0, len(entries), batch_size):
            batch = entries[i:i + batch_size]
            for entry in batch:
                await client.post(
                    f"http://localhost:9100/memory/{tier}",
                    json={"type": entry_type, "payload": entry},
                )
            print(f"Imported {min(i + batch_size, len(entries))}/{len(entries)}")
```

### JSONL Schema

Episodic entries:
```json
{
  "ts": "2026-02-23T12:00:00Z",
  "type": "achievement|decision|failure|observation",
  "title": "Short description",
  "outcome": "What happened",
  "tags": ["tag1", "tag2"]
}
```

Semantic entries:
```json
{
  "ts": "2026-02-23T12:00:00Z",
  "subject": "Entity",
  "predicate": "relationship",
  "object": "Target",
  "confidence": 0.95,
  "source": "origin"
}
```

Procedural entries:
```json
{
  "ts": "2026-02-23T12:00:00Z",
  "skill_name": "Skill description",
  "category": "category",
  "success_rate": 0.85,
  "when_to_use": "Context for usage"
}
```
