# openclaw-memory

**Always-On Memory Service (AOMS) for AI Agents**

Standalone FastAPI service providing unified 4-tier memory (Episodic, Semantic, Procedural) with weighted retrieval and reinforcement learning.

## Quick Start

```bash
pip install -r requirements.txt
python run.py
# → http://localhost:9100
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/memory/{tier}` | POST | Write a memory entry |
| `/memory/search` | POST | Keyword search with weighted scoring |
| `/memory/browse/{path}` | GET | Browse module tree |
| `/memory/weight` | POST | Adjust entry weight (reinforcement) |
| `/health` | GET | Service health check |

## Architecture

```
openclaw-memory/
├── modules/
│   ├── identity/        # Persona, values
│   ├── memory/
│   │   ├── episodic/    # experiences, decisions, failures (.jsonl)
│   │   ├── semantic/    # facts, relations (.jsonl)
│   │   └── procedural/  # skills, patterns (.jsonl)
│   ├── operations/      # Workflows, checklists
│   ├── projects/        # Active projects
│   └── research/        # Papers, notes
├── schemas/             # JSONL schema definitions
├── service/             # FastAPI app + client library
└── run.py               # Entry point
```
