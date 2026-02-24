# cortex-mem

Always-On Memory Service with Progressive Disclosure (L0/L1/L2) and Weighted Retrieval.

## Installation

```bash
pip install cortex-mem
```

Or from source:

```bash
git clone https://github.com/dhawalc/cortex-mem.git
cd cortex-mem
pip install -e .
```

## Quick Start (30 seconds)

```bash
# Start service
cortex-mem start --daemon

# Check status
cortex-mem status

# Search memory
cortex-mem search "deployment"

# Stop service
cortex-mem stop
```

## OpenClaw Integration

cortex-mem auto-configures OpenClaw on install. No manual setup needed.

```python
from cortex_mem.openclaw_provider import CortexMemProvider

async with CortexMemProvider() as mem:
    await mem.log("achievement", "Task completed", "Successfully shipped v1")
    results = await mem.search("deployment strategies")
```

## Features

- **Weighted Memory** — Important memories surface automatically via reinforcement learning
- **Progressive Disclosure** — 98% token reduction with L0/L1/L2 tiered retrieval
- **4-Tier Architecture** — Episodic, Semantic, Procedural, and Working memory
- **Cortex Engine** — Smart query with auto-escalation across disclosure levels
- **HTTP API** — Simple REST endpoints for any language / agent framework

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/memory/{tier}` | POST | Write a memory entry |
| `/memory/search` | POST | Keyword search with weighted scoring |
| `/memory/browse/{path}` | GET | Browse module tree |
| `/memory/weight` | POST | Adjust entry weight (reinforcement) |
| `/cortex/query` | POST | Smart query with L0/L1/L2 escalation |
| `/cortex/documents` | GET | List indexed documents |
| `/health` | GET | Service health check |

## CLI

```
cortex-mem start [--port 9100] [--daemon]   Start service
cortex-mem stop                              Stop service
cortex-mem status                            Health check
cortex-mem search QUERY [--limit 5]          Search memory
cortex-mem migrate SOURCE                    Import workspace data
```

## Architecture

```
cortex-mem/
├── cortex_mem/          # Python package + CLI
│   ├── cli.py           # Click CLI entry point
│   ├── openclaw_plugin.py
│   └── openclaw_provider.py
├── service/             # FastAPI application
│   ├── api.py           # Endpoints
│   ├── storage.py       # JSONL engine + weighted scoring
│   ├── models.py        # Pydantic schemas
│   └── client.py        # Async HTTP client
├── cortex/              # Progressive disclosure engine
│   ├── tiered_retrieval.py  # L0/L1/L2 query
│   ├── tier_generator.py    # Document ingestion
│   └── db.py            # SQLite metadata
├── modules/             # Module tree (JSONL data)
│   ├── memory/
│   │   ├── episodic/    # experiences, decisions, failures
│   │   ├── semantic/    # facts, relations
│   │   └── procedural/  # skills, patterns
│   ├── identity/        # Persona, values
│   ├── operations/      # Workflows
│   └── research/        # Papers, notes
├── schemas/             # JSONL schema definitions
├── setup.py
├── pyproject.toml
├── Dockerfile
└── run.py               # Direct entry point
```

## Docker

```bash
docker build -t cortex-mem .
docker run -p 9100:9100 cortex-mem
```

## License

MIT
