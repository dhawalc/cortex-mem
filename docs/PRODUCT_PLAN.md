# AOMS Product Plan — The Shared Brain for Agent Fleets

**Date:** 2026-08-23
**Inputs:** market research track (Claude, web research) + code/architecture track (Codex, full repo audit) + this week's operational audit findings.
**Status:** Draft for Dhawal's review.

---

## 1. Thesis

> **A local-first memory router that gives any MCP agent shared, scoped, provenance-rich context packed to the caller's token budget.**

One memory service on your machine. Every MCP-speaking agent — Claude Code, OpenClaw, Codex CLI, IDEs — mounts it with one command. Memory is scoped (agent-private / project / user-global), captured automatically (session sync + host hooks, not agent goodwill), and recalled as a **packed context artifact under an explicit token budget** with full provenance.

The customer is not "a developer who wants their coding assistant to remember." It is **the person who runs a fleet of always-on agents** — the OpenClaw demographic, the multi-session Claude Code power user — and needs one governed brain across all of them.

## 2. Why now, and why us

- **Mem0 vacated local-first** (OpenMemory deleted from their monorepo July 2026; consolidating on managed cloud). The biggest brand left the position.
- **The category's named gaps map to our strengths:** across the 13 compared memory MCP servers, reviewers flag missing multi-client/tenant isolation, missing fully-local semantic search (most require external API keys), missing observable retrieval, and sparse temporal/contradiction tracking. Nobody owns "fleet memory."
- **We have six months of production evidence** — a 26-session agent fleet sharing one AOMS instance (105k indexed chunks), including the failure stories (silent corruption, drifted client contracts, dead reinforcement loops) that make the design credible. The scars are the moat: we know what breaks because it broke on us.

## 3. Competitive reality (do not self-deceive)

| Player | Position | Our stance |
|---|---|---|
| **agentmemory** (~27k★) | Local memory server for coding agents, MCP+REST, plugins for Claude Code/Codex/Cursor/OpenClaw | The incumbent for the *generic* version of this product. Do not compete generically. Differentiate on fleet scopes, provenance/observability, packed recall. |
| **claude-mem** (~90k★) | Coding-session compression, $30/mo sync | Owns session-compression for Claude Code. Not our battle. |
| **Mem0** (~63k★) | Managed extraction/profile memory, $19/mo | Cloud-first; ceded local. Their SDK ergonomics set the bar for onboarding. |
| **Zep/Graphiti, Letta, Hindsight, Cognee** | Temporal KG / agent-OS / reflective / graph camps | Different camps; steal ideas (supersession links, reflection), don't chase their architecture. |
| **ClawHub memory plugins** (mem0 official, Memory Tools v2, MemClaw, OB1) | Per-platform plugins | The losing pattern we already lived. Our MCP-first approach obsoletes per-platform plugins — that's the pitch to OpenClaw users. |

**Table stakes (must have, not differentiators):** token-budgeted recall, hybrid search, MCP transport, local storage.
**Differentiators (win here):** fleet scopes + isolation, provenance/audit-grade observable retrieval, automatic capture with idempotency, fully-local embedding default, packed-context quality (measured).

## 4. What we keep, rework, and cut (Codex code audit)

**Reality check accepted:** the "4-tier cortex" is 3 implemented tiers ("working" doesn't exist), and today's codebase contains two parallel, non-communicating memory systems (JSONL+Chroma tiers vs Cortex L0/L1/L2 documents). Unify them behind one contract; stop selling tier taxonomy as UX.

- **KEEP (2):** `POST /recall` — the flagship; `GET /health`.
- **REWORK (8):** search (unify keyword+semantic, typed responses), write→`remember` (no agent-facing tier selection; classification inferred), cortex ingest/query (fold progressive disclosure into the one recall engine), document dereference, documents listing, stats (maintained counters, not 41s scans), plus storage (SQLite/WAL as source of truth, JSONL as import/export), vector layer (embed-on-write), embeddings (provider boundary with zero-setup local default; Ollama optional).
- **CUT from public surface (9):** weight/reinforcement, browse ×2 (path-traversal risk), regenerate, separate semantic-search, decay (compounding over-decay bug on top of the corruption bug), consolidate (O(n²) prototype), entity extract, deduplicate (doesn't dedupe), index (must be automatic). Maintenance survives as internal jobs/CLI only.

## 5. Product shape

### MCP tool surface (three tools, curated by hand)
1. **`recall`** — `{task, token_budget, scope?}` → packed context + structured sources + exact token count + truncation status + retrieval diagnostics. The product.
2. **`remember`** — `{content, kind?, tags?, scope?, provenance?, idempotency_key?}` → record ID + inferred classification. Agents never pick storage tiers.
3. **`search`** — inspection/exact retrieval with typed records, scores, provenance, pagination. Distinct from recall (no packing).

`forget`/update/export/import/doctor live in the CLI first (autonomous deletion is high-risk). Health/stats/index/maintenance are never model-facing.

### Architecture (drift-proof by construction)
```
FastAPI REST ─┐
              ├─> AOMSApplication ─> repositories (SQLite/WAL, FTS, vectors, docs)
FastMCP     ──┘          │
                         └─ ONE set of canonical Pydantic contracts
```
- Hand-written FastMCP server (official SDK), **not** a fastapi-mcp auto-bridge (would expose maintenance endpoints and untyped dicts) and **not** an HTTP shim (reintroduces the mapping layer where drift lives).
- Transports: **stdio default** (zero-config local: `uvx cortex-mem mcp`), **streamable-HTTP secondary** (shared server/remote; bearer tokens → OAuth 2.1 later; never accept tenant identity from tool arguments).
- Drift prevention as CI policy: JSON-schema snapshots, REST↔MCP parity tests against shared fixtures, SemVer with a single version source (today the API says 1.2.0 while the package says 1.0.0 — that ends).

### Scopes & trust
- Scopes: `agent-private` / `workspace` / `user-global`, bound from authenticated principal or process config — never from spoofable tool args.
- Recalled memory is **untrusted input**: delimited, provenance-stamped, injection-mitigated. Observable retrieval (why did this surface?) is a first-class feature — it's also a named market gap.

## 6. The riskiest assumption, and its mitigation

**Codex's verdict, adopted:** MCP compatibility makes memory *callable*, not *used well*. A universally installable server that agents rarely call correctly is shelfware.

Mitigation is a deliverable, not a hope: ship **host recipes** as part of the product — Claude Code hooks/skills, OpenClaw bootstrap + session-sync capture policies (we already run these in production), Codex/IDE instructions — that wire `recall` into session start and `remember` into session end with idempotent capture. Our six months of boot-script + sync-timer experience is exactly this know-how, productized.

## 7. Roadmap

**Phase 0 — Stabilize the foundation (this week, already queued):** blob recovery (~105k records), embed-on-write, /stats fix, versioned backups. Non-negotiable prereq: don't build a product on a corrupting store.

**Phase 1 — Core refactor (~wks 1–3):** contracts + application layer extraction; SQLite/WAL source of truth with JSONL import/export; portable settings (XDG paths, no `/home/example` hardcodes); scope/namespace model.

**Phase 2 — MCP adapter + packaging (~wks 3–5):** FastMCP stdio server (3 tools); `uvx cortex-mem mcp` one-liner; first-run auto-init with bundled local embeddings; `doctor`; migration/import from the current live instance.

**Phase 3 — Dogfood the wedge (~wks 5–7):** mount ONE store from Claude Code + OpenClaw + Codex concurrently (the multi-client concurrency proof); ship host recipes; build the retrieval eval harness (relevance, stale-rate, contradiction-rate, token utilization, latency) — measurement is the credibility play.

**Phase 4 — OSS launch:** GitHub + uvx install; MCP registries; ClawHub listing ("replaces per-platform memory plugins"); launch content: *"My agents' memory was silently corrupted for months — here's what we rebuilt"* (the audit story is the best marketing asset we have).

**Phase 5 — Optional monetization (only after pull):** remote streamable-HTTP with auth → multi-machine sync → hosted/team tier at the market's $15–30/mo band. Local stays free forever (that's the position mem0 abandoned).

**Effort (Codex estimate, one engineer):** 24–35 days to local stdio beta (5–7 focused weeks); +4–7 days for trustworthy remote.

## 8. Open decisions (Dhawal's call)

1. **Name consolidation** — one name only (this week proved why). Recommendation: **AOMS** as the product ("Always-On Memory Service" matches fleet positioning); repo/package follows. Check npm/PyPI availability before committing.
2. **License** — MIT/Apache-2.0 recommended (AGPL demonstrably suppresses adoption in this category).
3. **Benchmarks** — enter LoCoMo/LongMemEval publicly, or lead with our own fleet-memory eval? (Recommendation: own eval first; public benchmarks are mem0/Zep's home turf.)
4. **Scope of ambition** — personal infra that happens to be open-source, or a real product push with launch effort? The plan above works for either; Phase 4+ is where they diverge.

## 9. Success criteria

- **Phase 3 gate:** all of Dhawal's fleet on one store through MCP only; boot scripts and per-platform plugins retired; recall quality measurably ≥ current boot-script context.
- **Launch gate (the stranger test):** one command to install → `remember` → immediately findable via `search` and `recall` → restart + second client with zero corruption → `doctor` gives useful diagnosis → full export/restore works.
- **6-months-post-launch signal:** external contributors, ClawHub installs, and at least one "switched from agentmemory because of scopes/provenance" testimonial.
