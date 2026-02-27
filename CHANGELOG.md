# Changelog

All notable changes to cortex-mem (AOMS) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- (pending features for next release)

### Fixed
- (pending fixes)

### Changed
- (pending changes)

---

## [1.0.0] — 2026-02-23

### Added

**Core Memory System**
- 4-tier memory architecture: Episodic, Semantic, Procedural, Working
- JSONL-based storage engine with append-only writes
- Weighted retrieval with reinforcement learning (weight adjustments)
- Timestamp-based and category-based sorting

**Progressive Disclosure (Cortex)**
- L0/L1/L2 tiered retrieval system
- 95-99% token reduction for large documents
- Auto-escalation from abstracts to full content
- SQLite metadata database for tier tracking

**HTTP API (FastAPI)**
- `/memory/{tier}` — Write memory entries
- `/memory/search` — Keyword search with weighted scoring
- `/memory/browse/{path}` — Directory tree browsing
- `/memory/weight` — Adjust entry weights (RL reinforcement)
- `/cortex/query` — Smart query with L0/L1/L2 escalation
- `/cortex/ingest` — Ingest documents into progressive tiers
- `/cortex/documents` — List indexed documents
- `/health` — Service health and statistics

**CLI Interface**
- `cortex-mem start [--port] [--daemon]` — Start service
- `cortex-mem stop` — Stop service
- `cortex-mem status` — Health check
- `cortex-mem search QUERY` — Search memory
- `cortex-mem migrate SOURCE` — Import workspace data

**OpenClaw Integration**
- Auto-registration as OpenClaw plugin
- `CortexMemProvider` async context manager
- Memory logging helpers: `log_achievement`, `log_error`, `log_fact`
- Boot script for session startup context

**Deployment**
- Systemd service configuration
- Docker support (Dockerfile included)
- PyPI packaging (`pip install cortex-mem`)
- MIT license

**Migration Tools**
- `migrate_workspace.py` — Import from OpenClaw workspace
- `ingest_all_docs.py` — Batch document ingestion
- Schema validation for JSONL entries

### Initial Data
- Migrated 10,928 episodic entries from Daemon
- Migrated 22,551 semantic facts
- Migrated 1,527 procedural skills
- Indexed 19 Cortex documents with L0/L1/L2

---

## Version History Summary

| Version | Date | Highlights |
|---------|------|------------|
| 1.0.0 | 2026-02-23 | Initial release: 4-tier memory, L0/L1/L2, API, CLI |

---

## Upgrade Notes

### From Pre-Release → 1.0.0

This is the first public release. No upgrade path needed.

### Future Upgrades

Patch releases (1.0.x) are backward compatible. Simply:

```bash
pip install --upgrade cortex-mem
systemctl restart openclaw-memory
```

---

## Links

- **Repository:** https://github.com/dhawalc/cortex-mem
- **Issues:** https://github.com/dhawalc/cortex-mem/issues
- **PyPI:** https://pypi.org/project/cortex-mem/

[Unreleased]: https://github.com/dhawalc/cortex-mem/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/dhawalc/cortex-mem/releases/tag/v1.0.0
