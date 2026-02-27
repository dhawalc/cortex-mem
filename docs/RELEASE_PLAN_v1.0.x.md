# AOMS Release Plan — v1.0.x Series

**Package:** `cortex-mem`  
**Repository:** https://github.com/dhawalc/cortex-mem  
**Current Version:** v1.0.0 (tagged)  
**Service Version:** 1.1.0 (running)

---

## Overview

The v1.0.x series focuses on stability, bug fixes, and incremental improvements to the core AOMS (Always-On Memory Service) functionality shipped in v1.0.0.

### Versioning Strategy

- **v1.0.x** — Patch releases: bug fixes, security updates, minor improvements
- **v1.1.0** — Next minor: new features (already running internally)
- **v1.x.0** — Minor releases: backward-compatible features
- **v2.0.0** — Major: breaking API changes (not planned)

---

## Release Checklist

### Pre-Release
- [ ] Ensure all tests pass: `pytest tests/`
- [ ] Update version in `cortex_mem/__version__.py`
- [ ] Update CHANGELOG.md
- [ ] Run `ruff check .` for linting
- [ ] Test CLI commands: `cortex-mem start/stop/status/search`
- [ ] Test OpenClaw plugin integration
- [ ] Verify health endpoint: `curl localhost:9100/health`

### Release Process
```bash
# 1. Bump version
echo '__version__ = "1.0.x"' > cortex_mem/__version__.py

# 2. Commit and tag
git add -A
git commit -m "Release v1.0.x"
git tag v1.0.x
git push origin main --tags

# 3. Build and publish to PyPI
python -m build
twine upload dist/cortex_mem-1.0.x*

# 4. Create GitHub Release
gh release create v1.0.x --title "AOMS v1.0.x" --notes-file docs/CHANGELOG.md
```

### Post-Release
- [ ] Verify PyPI package: `pip install cortex-mem==1.0.x`
- [ ] Update AOMS_INTEGRATION.md in workspace
- [ ] Announce in relevant channels

---

## Planned Releases

### v1.0.1 — Stability Patch
**Target:** TBD  
**Focus:** First patch release, bug fixes discovered in production

**Candidates:**
- [ ] Fix edge cases in JSONL parsing
- [ ] Improve error handling in search endpoint
- [ ] Add request timeout handling
- [ ] CLI help text improvements
- [ ] Documentation corrections

### v1.0.2 — Performance Patch
**Target:** TBD  
**Focus:** Performance improvements for large memory stores

**Candidates:**
- [ ] Optimize search query performance (36K+ entries)
- [ ] Add index hints for frequent queries
- [ ] Memory usage improvements
- [ ] Connection pooling for HTTP client

---

## Feature Backlog (For v1.1.x+)

These are NOT in scope for v1.0.x but tracked for future releases:

1. **Memory Compaction** — Archive old entries, reduce storage
2. **Export/Import CLI** — Bulk migration tools
3. **Multi-tenant Support** — Isolated memory spaces
4. **Vector Search** — ChromaDB integration for semantic search
5. **Webhooks** — Push notifications on memory events
6. **Admin Dashboard** — Web UI for memory browsing

---

## Current Statistics (Production)

| Metric | Value |
|--------|-------|
| Episodic entries | 12,622 |
| Semantic facts | 22,581 |
| Procedural skills | 1,539 |
| Total entries | ~36,742 |
| Uptime | 69+ hours |
| Token reduction | 98% (L0/L1/L2) |

---

## Compatibility Matrix

| cortex-mem | Python | OpenClaw | FastAPI |
|------------|--------|----------|---------|
| v1.0.x | ≥3.10 | Any | ≥0.104 |
| v1.1.x | ≥3.10 | Any | ≥0.104 |

---

## Support Policy

- **v1.0.x:** Active support, receives security fixes
- **v0.x.x:** Deprecated, no support
- **Latest:** Always recommended for new installations

---

*Last updated: 2026-02-26*
