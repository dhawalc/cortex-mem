# AOMS Usage Guide

**openclaw-memory** — Always-On Memory Service with Progressive Disclosure

---

## Quick Reference

### Service Control

```bash
# Status
systemctl --user status openclaw-memory

# Logs
journalctl --user -u openclaw-memory -f

# Restart
systemctl --user restart openclaw-memory

# Health check
curl http://localhost:9100/health | jq .
```

---

## Core Memory (Episodic/Semantic/Procedural)

### Write Memory

```python
import asyncio
import httpx

async def write_memory():
    async with httpx.AsyncClient() as client:
        # Write episodic experience
        response = await client.post(
            "http://localhost:9100/memory/episodic",
            json={
                "tier": "episodic",
                "type": "experience",
                "payload": {
                    "ts": "2026-02-23T21:00:00Z",
                    "type": "achievement",
                    "title": "Deployed AOMS",
                    "outcome": "Service running, all tests pass",
                    "tags": ["deployment", "success"]
                }
            }
        )
        print(response.json())

asyncio.run(write_memory())
```

### Search Memory

```bash
curl -X POST http://localhost:9100/memory/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "deployment success",
    "tier": ["episodic"],
    "limit": 5
  }' | jq .
```

### Browse Structure

```bash
curl http://localhost:9100/memory/browse/memory/episodic | jq .
```

---

## Cortex L0/L1/L2 (Progressive Disclosure)

### Ingest Document

```python
import asyncio
import httpx
from pathlib import Path

async def ingest_doc():
    content = Path("/path/to/doc.md").read_text()
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "http://localhost:9100/cortex/ingest",
            json={
                "title": "My Research Paper",
                "content": content,
                "hierarchy_path": "/research/paper",
                "doc_type": "research",
                "tags": ["ai", "memory"]
            }
        )
        
        data = response.json()
        print(f"Ingested: {data['doc_id']}")
        print(f"L0: {data['l0_tokens']} tokens (99% reduction)")
        print(f"L1: {data['l1_tokens']} tokens (95% reduction)")
        print(f"L2: {data['l2_tokens']} tokens (full doc)")

asyncio.run(ingest_doc())
```

### Smart Query (Auto-Escalation)

```python
import asyncio
import httpx

async def smart_query():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:9100/cortex/query",
            json={
                "query": "memory architecture with weighted retrieval",
                "token_budget": 2000,
                "directory": "/research"  # Optional filter
            }
        )
        
        data = response.json()
        print(f"Results: {len(data['results'])}")
        print(f"Total tokens: {data['total_tokens']} (budget: 2000)")
        
        for result in data['results']:
            tier = result['tier']
            tokens = result.get('tokens', 0)
            score = result.get('score', 0)
            print(f"  - {result['title']} (tier={tier}, tokens={tokens}, score={score:.3f})")

asyncio.run(smart_query())
```

**How it works:**
- Query searches L0 abstracts first (fast, ~100 tokens each)
- High-scoring results (>0.4) auto-expand to L1 (~2K tokens)
- Very high scores (>0.7) expand to L2 (full document)
- Stays within token budget

### Get Specific Tier

```bash
# Get L0 abstract (fast)
curl "http://localhost:9100/cortex/document/DOC_ID?tier=l0" | jq .

# Get L1 overview
curl "http://localhost:9100/cortex/document/DOC_ID?tier=l1" | jq .

# Get L2 full content
curl "http://localhost:9100/cortex/document/DOC_ID?tier=l2" | jq .
```

### List Documents

```bash
curl http://localhost:9100/cortex/documents | jq '.documents[] | {title, l0_tokens, l1_tokens, l2_tokens}'
```

---

## OpenClaw Integration

### In OpenClaw Agent Code

```python
import sys
sys.path.insert(0, "/home/dhawal/openclaw-memory")
from openclaw_integration import log_achievement, log_error, log_fact

# Log achievements
await log_achievement(
    "Task completed",
    "Success",
    tags=["openclaw", "task"]
)

# Log errors
await log_error(
    "API timeout",
    "Connection refused after 30s",
    tags=["api", "error"]
)

# Log facts
await log_fact(
    subject="AOMS",
    predicate="runs_on",
    object="port 9100",
    confidence=1.0
)
```

---

## Daemon Integration

### In Daemon Consciousness Loop

```python
import sys
sys.path.insert(0, "/home/dhawal/openclaw-memory")
from daemon_integration import AOMemoryClient, log_consciousness_cycle

# Initialize client
aoms = AOMemoryClient()

# Smart query (replaces Daemon's Cortex queries)
results = await aoms.smart_query(
    "trading strategies with Sharpe > 1.4",
    token_budget=2000,
    directory="/strategies"
)

# Log consciousness cycle
await log_consciousness_cycle(
    phase="INTERVENE",
    outcome="Created 3 new goals",
    duration_ms=4200,
    model="deepseek-r1:7b"
)

# Write episode
await aoms.write_episode(
    episode_type="achievement",
    title="Profitable trade",
    outcome="+2.4% on SPX 0DTE",
    tags=["trading", "success"],
    metadata={"pnl": 1200, "strategy": "momentum"}
)

# Adjust weight (reinforcement learning)
await aoms.adjust_weight(
    entry_id="abc-123-def",
    task_score=0.85  # >0.7 = boost weight
)

await aoms.close()
```

---

## Weighted Memory (Reinforcement Learning)

### Boost Helpful Memories

```bash
curl -X POST http://localhost:9100/memory/weight \
  -H "Content-Type: application/json" \
  -d '{
    "entry_id": "abc-123-def",
    "task_score": 0.9
  }'
```

**Scoring:**
- `score > 0.7` → weight × 1.1 (boost)
- `score < 0.3` → weight × 0.9 (decay)
- `0.3 ≤ score ≤ 0.7` → weight × 0.995 (time decay)

**Weight range:** 0.1 – 5.0

---

## Backup & Recovery

### Manual Backup

```bash
/home/dhawal/openclaw-memory/backup_to_vps.sh
```

**Backs up to:** `root@178.156.239.16:/root/backups/openclaw-memory/`

### Cron Schedule (Recommended)

```bash
# Add to crontab
crontab -e

# Daily at 4 AM
0 4 * * * /home/dhawal/openclaw-memory/backup_to_vps.sh
```

### Restore from VPS

```bash
# Download latest snapshot
scp root@178.156.239.16:/root/backups/openclaw-memory/aoms-*.tar.gz /tmp/

# Extract
cd /home/dhawal
tar -xzf /tmp/aoms-*.tar.gz

# Restart service
systemctl --user restart openclaw-memory
```

---

## Monitoring

### Health Check

```bash
curl http://localhost:9100/health | jq .
```

**Expected response:**
```json
{
  "status": "ok",
  "service": "openclaw-memory",
  "version": "1.1.0",
  "uptime_seconds": 3600,
  "memory_root": "/home/dhawal/openclaw-memory",
  "tiers": {
    "episodic": 50,
    "semantic": 10,
    "procedural": 5
  }
}
```

### Service Logs

```bash
# Follow logs
journalctl --user -u openclaw-memory -f

# Last 100 lines
journalctl --user -u openclaw-memory -n 100 --no-pager
```

### Backup Logs

```bash
tail -f /home/dhawal/openclaw-memory/snapshots/backup.log
```

---

## Performance

### Token Reduction

| Tier | Typical Size | Use Case |
|------|--------------|----------|
| L0 | 50-100 tokens | Fast scan, "what exists?" |
| L1 | 500-2K tokens | Overview, "tell me more" |
| L2 | Full document | Deep dive, "all details" |

**Measured reduction:** 95-99% for large documents (10K+ tokens)

### Auto-Escalation Thresholds

- L0 → L1: score > 0.4
- L1 → L2: score > 0.7

Stays within token budget automatically.

---

## Troubleshooting

### Service Won't Start

```bash
# Check logs
journalctl --user -u openclaw-memory -n 50 --no-pager

# Check port
lsof -i:9100

# Kill stuck process
lsof -ti:9100 | xargs kill -9
systemctl --user restart openclaw-memory
```

### Ingestion Fails

```bash
# Check Ollama is running
ollama list

# Check models are available
ollama list | grep -E "deepseek-r1:7b|nomic-embed-text"

# Pull if missing
ollama pull deepseek-r1:7b
ollama pull nomic-embed-text
```

### Database Issues

```bash
# SQLite database location
ls -lh /home/dhawal/openclaw-memory/cortex/cortex.db

# ChromaDB location
ls -lh /home/dhawal/openclaw-memory/cortex/chroma/

# Reset (WARNING: deletes all data)
rm -rf /home/dhawal/openclaw-memory/cortex/*.db
rm -rf /home/dhawal/openclaw-memory/cortex/chroma/
systemctl --user restart openclaw-memory
```

---

## API Reference

Full API: http://localhost:9100/docs (FastAPI auto-docs)

**Core endpoints:**
- POST `/memory/{tier}` — Write
- POST `/memory/search` — Search
- POST `/memory/weight` — Adjust weights
- GET `/memory/browse/{path}` — Browse tree
- GET `/health` — Status

**Cortex endpoints:**
- POST `/cortex/ingest` — Ingest doc
- POST `/cortex/query` — Smart query
- GET `/cortex/document/{doc_id}?tier=l0|l1|l2` — Get tier
- POST `/cortex/regenerate/{doc_id}` — Regenerate L0/L1
- GET `/cortex/documents` — List all

---

**Built:** 2026-02-23  
**Status:** Production-ready  
**Support:** See INTEGRATION.md for more examples
