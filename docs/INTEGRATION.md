# Integration Guide

cortex-mem integrates with any system that can make HTTP requests. This guide covers the built-in integrations for OpenClaw and Daemon, plus how to build your own.

## OpenClaw Integration

### Auto-Configuration

If you install cortex-mem while OpenClaw is present, it auto-configures:

```bash
pip install cortex-mem
python -m cortex_mem.openclaw_plugin
```

This will:
1. Start the cortex-mem service
2. Update `~/.openclaw/config.yaml` to use cortex-mem as the memory provider
3. Offer to migrate existing workspace data

### Manual Setup

```python
import sys
sys.path.insert(0, "/path/to/cortex-mem")

from openclaw_integration import (
    log_achievement,
    log_error,
    log_fact,
    sync_to_aoms,
    is_aoms_available,
)

# Check availability
if await is_aoms_available():
    # Log an achievement
    await log_achievement("Task completed", "Deployed v2.0", tags=["deploy"])

    # Log a fact
    await log_fact("AOMS", "runs_on", "port 9100", confidence=1.0)

    # Log an error
    await log_error("Build failed", "Missing dependency: numpy", tags=["ci"])

    # Generic write
    await sync_to_aoms("episodic", {
        "ts": "2026-02-23T12:00:00Z",
        "type": "observation",
        "title": "Custom entry",
        "outcome": "Details here",
        "tags": ["custom"],
    })
```

### OpenClaw Provider Interface

For structured integration, use the provider class:

```python
from cortex_mem.openclaw_provider import CortexMemProvider

async with CortexMemProvider("http://localhost:9100") as provider:
    await provider.log("achievement", "Shipped feature", "Auth module complete")
    results = await provider.search("authentication", limit=5)
    health = await provider.health()
```

## Daemon Integration

The Daemon uses a dedicated client with Cortex L0/L1/L2 smart query support.

### Setup

```python
from daemon_integration import AOMemoryClient

aoms = AOMemoryClient("http://localhost:9100")
```

### Writing Memory

```python
# Episodic (experiences, decisions)
episode_id = await aoms.write_episode(
    episode_type="consciousness_cycle",
    title="INTERVENE phase",
    outcome="Created 3 new goals",
    tags=["consciousness", "intervene"],
    metadata={"duration_ms": 1500},
)

# Semantic (facts)
fact_id = await aoms.write_fact(
    subject="BTC",
    predicate="current_trend",
    object="bullish",
    confidence=0.85,
)

# Procedural (skills)
skill_id = await aoms.write_skill(
    skill_name="RSI divergence detection",
    category="technical_analysis",
    success_rate=0.78,
    when_to_use="When price makes new highs but RSI doesn't",
)
```

### Smart Queries (Cortex L0/L1/L2)

The Cortex engine provides progressive disclosure — start with summaries (L0), expand to key sections (L1), or get full content (L2):

```python
results = await aoms.smart_query(
    "trading strategies with Sharpe > 1.4",
    token_budget=2000,
    directory="/research",
)

for doc in results["results"]:
    print(f"[{doc['tier']}] {doc.get('title', 'untitled')}: {doc['content'][:100]}...")

print(f"Total tokens used: {results['total_tokens']}")
```

### Reinforcement Learning

After task execution, adjust memory weights so useful memories surface more:

```python
# Task succeeded — boost the memories that contributed
await aoms.adjust_weight(entry_id="abc123", task_score=0.9)

# Task failed — decay the memories
await aoms.adjust_weight(entry_id="def456", task_score=0.2)
```

### Dual-Write Pattern

For safe migration, write to both old and new stores simultaneously:

```python
# Write locally (existing behavior)
self.episodic.add(episode)

# Also write to AOMS (fire-and-forget)
asyncio.create_task(aoms.write_episode(
    episode_type=episode.type,
    title=episode.title,
    outcome=episode.outcome,
))
```

### Cleanup

```python
await aoms.close()
```

## HTTP API (Any Language)

### Write

```bash
POST /memory/{tier}
Content-Type: application/json

{
  "type": "experience",
  "payload": { ... },
  "tags": ["optional"],
  "weight": 1.5
}
```

### Search

```bash
POST /memory/search
Content-Type: application/json

{
  "query": "search terms",
  "tier": ["episodic", "semantic"],
  "limit": 10,
  "min_weight": 0.5
}
```

### Cortex Query (L0/L1/L2)

```bash
POST /cortex/query
Content-Type: application/json

{
  "query": "memory architecture",
  "token_budget": 4000,
  "top_k": 10,
  "directory": "/research"
}
```

### Weight Adjustment

```bash
POST /memory/weight
Content-Type: application/json

{
  "entry_id": "abc-123",
  "tier": "episodic",
  "task_score": 0.85
}
```

### Health Check

```bash
GET /health
```

### Browse Module Tree

```bash
GET /memory/browse/{path}
```
