# AOMS Build State — Orchestration Ledger

## P4 — OSS launch — GITHUB SHIPPED 2026-08-24

This section supersedes the pre-build phase labels retained below as historical
planning context. GitHub launch execution completed at `2026-08-24T04:53:49Z`.

| Deliverable | State |
|---|---|
| Repository | Public at <https://github.com/dhawalc/cortex-mem>; default branch `main`; v2 README and corrected description live. |
| History | True `v2`-into-`main` merge preserved v1 first-parent history. Release tag `v2.0.0` points to `4226a69`; post-tag CI workflow fix is on `main`/`v2`. |
| Product | SQLite/WAL canonical store; hard agent/workspace scopes; budgeted local hybrid recall; provenance-rich receipts; three-tool MCP; guided setup; importers; Recall Observatory; truth timelines. |
| Evidence | Tag-built wheel, five unfiltered eval configurations, complete scripted ablation, and canonical live `rehearsal-008` attached to <https://github.com/dhawalc/cortex-mem/releases/tag/v2.0.0>. All published relay artifacts are labeled **REHEARSAL**. |
| Verification | Local `193 passed` plus fixture `3 passed`; GitHub CI passed Python 3.11/3.12, clean-wheel acceptance, and relay fixture after one workflow-only dependency fix-forward. |
| ClawHub | v2 package prepared at `packaging/clawhub/aoms`; publish blocked because `DhawalA4` has not accepted ClawHub's MIT-0 publishing terms. Live listing remains retired v1.1.0. |

Remaining post-launch: a **PROOF**-grade bare-auth run on a bwrap-capable host
with Codex `workspace-write` (and OpenClaw credentials for the full trio), an
independent clean-machine reproduction watch, ClawHub terms acceptance and v2
publication, and social posts by Dhawal.

Plan: docs/PRODUCT_PLAN.md. Orchestrator: Claude (Fable) session. Builders: Codex first;
Opus subagents when Codex weekly limit is hit (per Dhawal, 2026-08-23).
Decisions locked by Dhawal 2026-08-23: name = AOMS, license = MIT, own eval before
public benchmarks, ambition decision deferred to P4.

## Rules of engagement
- Builders never restart services, never commit, never touch modules/memory/ or index/.
  Orchestrator reviews diffs, runs tests, commits, restarts, verifies.
- Live service: aoms.service runs from THIS working tree (master). P1+ refactor work
  happens in a separate git worktree/branch so master stays deployable.
- Every completed item gets a line here with date + commit hash.

## P0 — Stabilize — COMPLETE 2026-08-23 02:45
Blob recovery executed: 5,023,727 objects → 165,321 unique records (96.71% re-ingest
dup removed), swap verified, service healthy, oldest queryable entry back to 2026-02-10.
Tool committed as 1a251a7. Blobbed originals: ~/openclaw_archives/aoms-pre-recovery-
blobs-20260823 (3.8G). Follow-ups → P1: reconcile vector index IDs vs recovered winner
IDs (reindex); catch-up sweep for unindexed_ids.jsonl; decide fate of nightly decay job
(endpoint is CUT in plan — recommend disabling the OpenClaw 03:01 job); reclaim ~7G
(May .bak files + archived blobs) after a week of stability; untrack data files from git.
- [x] Decay corruption fix + atomic writes — commit 572860c (2026-08-23, verified live)
- [x] Emergency freeze — ~/openclaw_archives/aoms-freeze-2026-08-22_2312.tar.zst (1.9G)
- [x] Versioned backups — backup-aoms-versioned.sh, cron 04:30 daily, 7 local/3 VPS
      generations (stopgap until P1 SQLite makes deltas small)
- [x] /stats non-blocking + TTL cache — commit 1ad370e (2026-08-23 01:53). Verified:
      /health 14–35ms DURING scan; 300s single-flight cache works. Cold scan now 110s
      because the new streaming parser reads inside blobs — drops after recovery.
- [x] Embed-on-write + unindexed marker — commit 1ad370e. Verified live: test entry
      7cea308e top hit in semantic search ~30s after write. First new index write
      since 2026-05-26. Catch-up sweep for unindexed_ids.jsonl still TODO (P1).
- [ ] Blob recovery — IN PROGRESS. Facts established 2026-08-23 02:00-02:30:
      * Blobs hold 5,023,727 objects, ALL with unique IDs (Codex count pass) — IDs
        are regenerated per re-ingest, so ID-dedup is useless.
      * Content probe (200k samples): experiences 75.0% dup, facts 47.8%, skills
        96.3%; skills' 7,365 unique contents ≈ index's 7,364 procedural chunks →
        true corpus is ~100-300k records; 5M is daemon re-ingest bloat (same fact
        written up to 54x/day under fresh UUIDs, Feb-May era).
      * Tool: scripts/recover_blobs_v2.py (Codex Task B, 36 tests green) — streaming,
        output-dir-only, verify mode. Task C dispatched: --dedup-mode content
        (sha1 of record minus volatile fields, keep-newest).
      * Cutover plan: stage recovery to output dir → verify → stop aoms.service +
        pause during a window clear of decay (03:01-03:07) and hourly sync (:00),
        re-run on frozen input, swap, restart, verify. Rollbacks: freeze archive
        (22 Aug 23:12) + versioned generation (23 Aug 01:50).
- [ ] Decay job sanity: fixed code deployed; ALSO note Codex found compounding
      over-decay (rate**total_age applied to already-decayed weight) — decay endpoint is
      CUT in the product plan; consider disabling the nightly OpenClaw decay job after
      blob recovery instead of fixing further

## P1 — Core refactor (weeks 1–3) — not started
Contracts + application layer; SQLite/WAL source of truth; portable settings; scopes.
Work in worktree (suggest: ~/cortex-mem/aoms-v2, branch v2).

## P2 — MCP adapter + packaging (weeks 3–5) — not started
FastMCP stdio (recall/remember/search); uvx one-liner; doctor; migration.

## P3 — Dogfood (weeks 5–7) — not started
Multi-client concurrency proof; host recipes; retrieval eval harness.

## P4 — OSS launch — not started
## P5 — Monetization (only after pull) — not started

## Builder log
- 2026-08-23 ~01:00 Codex task A (P0 stats + embed-on-write) dispatched — PENDING

## POST-LAUNCH DAY — 2026-08-24 (final state: v2 @ e79bd74, 326 tests)

Launched, then spent the day finding what launch had shipped.

SECURITY
- Public repo was serving the author's real memory corpus (modules/memory/procedural/
  skills.jsonl, 1.44MB, VPS IP x8) + modules/identity/*. Removed from HEAD, verified 404
  (a9da4ee/50c5b57). Still in git history — purge script at packaging/ops/history-purge.sh,
  mirror backup at ~/openclaw_archives/cortex-mem-mirror-pre-purge-20260824-120421.git.
- Observatory had no Host/Origin validation while SECURITY.md claimed it did; MCP search
  interpolated ids/provenance unfenced; requires-python lied (3.10 cannot import the CLI).
  All fixed (c120c36).
- VPS: unauthenticated root LLM proxy on 0.0.0.0:8000 for 19.5 days, no firewall, password
  auth on, no fail2ban, ~10k failed logins/42h, 60 pending updates, 202d uptime. Hardened
  and verified externally: proxy loopback-only, ufw default-deny, fail2ban active, password
  auth off, patched, rebooted. SSH key NOT rotated (never leaked — only the IP).

CORRECTNESS
- remember(id=<existing>) silently replaced retained content, no lineage — model-facing.
  Guard + atomic conditional write (02ab917, 86d210b). Forensic sweep of the live store:
  NO evidence of silent replacement (all updated_at!=created_at rows are legacy-import).
- O(N^2) FTS write path: 12.985 -> 3,914.8 rec/s (301x). Migration 6 applied to the live
  store deliberately after backup: 5.2s, counts/integrity/query results identical.
- Contest Ledger (write-side AUTHORITY gate, not an evidence gate) + T3 removal. See
  docs/CONTEST-LEDGER.md and the ERRATUM atop docs/design/WRITE-CORRECTNESS-DECISION.md.

MEASUREMENT (benchmarks/MCB-1.0, branch mcb-1.0, NOT YET PUSHED)
- MCB-1.0 authored + frozen BEFORE running it against AOMS. Six verbatim result artifacts.
- AOMS baseline 50% DA. Letta (independent, local Ollama) 75%. Letta archival target 27%
  - **⚠ CORRECTED 2026-08-24: the Letta figures measure `letta` 0.16.8, the RETIRED
    LETTA V1 SERVER, not current Letta. Sarah Wooders of Letta identified this. Stacked
    on the existing model confound, the AOMS-vs-Letta comparison is not a valid
    architecture comparison on either axis. Do not cite these as Letta numbers.
    See benchmarks/MCB-1.0/CORRECTIONS.md.**
  (demonstrates why core memory was the right target). AOMS+ledger 62.5%, structural
  errors 18->0, but false rejection 0->41.2% and the improvement is NOT detection: all 18
  changed cases changed identically.
- Neither system has a write-side EVIDENCE gate. That claim survives all of today's work.

THE LESSON WORTH KEEPING
Five runs against the frozen benchmark showed zero delta from the T3 defect; twelve live
agent sessions found it immediately. A benchmark only measures what its interchange format
can express. One agent, contested twice for honestly citing its source, wrote itself a
durable memory explaining how to bypass the gate.

OPEN / OWNER-ONLY
- push mcb-1.0; merge v2 -> main; ClawHub MIT-0 terms; git history purge decision.
- Host recipes still not installed (cortex-mem setup claude|codex|openclaw) — automatic
  recall is packaged but not switched on.
- Legacy v1 (aoms.service :9100 + its cron jobs) still running in parallel as fallback.
- Unmeasured: whether declaration rates hold in long sessions where the incumbent id has
  fallen out of context. Next experiment.
