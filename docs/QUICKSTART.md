# Quick Start (5 minutes)

## 1. Start the Service

```bash
cortex-mem start --daemon
cortex-mem status
```

Output:

```
cortex-mem: ok
Uptime: 2s
Entries: 0
```

The service is now running at `http://localhost:9100`.

## 2. Write Your First Memory

```bash
curl -X POST http://localhost:9100/memory/episodic \
  -H "Content-Type: application/json" \
  -d '{
    "type": "experience",
    "payload": {
      "ts": "2026-02-23T12:00:00Z",
      "type": "achievement",
      "title": "First memory entry",
      "outcome": "Successfully wrote to AOMS",
      "tags": ["quickstart"]
    }
  }'
```

## 3. Search Memory

```bash
cortex-mem search "first memory"
```

Or via API:

```bash
curl -X POST http://localhost:9100/memory/search \
  -H "Content-Type: application/json" \
  -d '{"query": "first memory", "limit": 5}'
```

## 4. Use from Python

```python
from service.client import MemoryClient

async with MemoryClient("http://localhost:9100") as mem:
    # Write
    result = await mem.write("episodic", "experience", {
        "ts": "2026-02-23T12:00:00Z",
        "type": "achievement",
        "title": "Python client test",
        "outcome": "Working!",
        "tags": ["python"],
    })
    print(f"Created: {result['id']}")

    # Search
    hits = await mem.search("Python client")
    for r in hits["results"]:
        print(f"  [{r['score']:.2f}] {r['entry']['title']}")

    # Health
    health = await mem.health()
    print(f"Status: {health['status']}, Entries: {sum(health['tiers'].values())}")
```

## 5. Explore the API Docs

Open `http://localhost:9100/docs` in your browser for the interactive Swagger UI.

## Memory Tiers

| Tier | What it stores | Entry types |
|------|---------------|-------------|
| **episodic** | Experiences, decisions, failures, observations | `experience`, `decision`, `failure` |
| **semantic** | Facts, relations, learned truths | `fact`, `relation` |
| **procedural** | Skills, patterns, workflows | `skill`, `pattern` |

## Next Steps

- [Integration Guide](INTEGRATION.md) — Connect to OpenClaw or Daemon
- [Migration Guide](MIGRATION.md) — Import existing memory data
- [Troubleshooting](TROUBLESHOOTING.md) — Common issues and fixes
