# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Added the **contest ledger**: an optional `claim_key` on a write declares which proposition the record answers, and a write that collides with the record already holding that slot is stored as `contested` rather than displacing it. There are exactly two dispositions, `admitted` and `contested`. Nothing is refused, deleted, truncated, or rewritten; a contested record is retained in full, stays retrievable by id and by `search(include_contested=True)`, and is one operator command from current.
- Added three structural contest triggers, none of which reads record content: an undeclared slot collision, a retrograde `asserted_at` compared numerically against the incumbent's, and a write whose provenance declares `derived_from`. The last blocks laundering, where an agent reads crafted memory and re-asserts it as its own write.
- Added `WriteReceipt`, an append-only decision log that is deliberately **exempt from `receipt_retention`** and is never trimmed by any background mechanism.
- Added `contested_withheld`, `contested_incumbents`, and `ruleset_digest` to `RecallReceipt`, additively under schema version 1. Once anything can be withheld from packing, a recall receipt that does not name the configuration in force has stopped being a complete explanation of its own output.
- Added the `cortex-mem contest` command group (`list`, `show`, `drain`, `resolve`) and `cortex-mem receipts`. Resolution is always a named human act: `--admit`, `--supersede`, `--set-aside`, `--split`. Nothing resolves on a timer.
- Added `cortex-mem doctor --contests`, a zero-write projection of which record holds which slot, and contest checks in `cortex-mem doctor` that fail on projection drift or on entries past the review window.
- Added the read-only Observatory contradiction inbox at `GET /contests` and `GET /contests/{id}`, with a contested counter on `/truth`. Each row offers a copy-able CLI command rather than a resolve button, so an XSS or CSRF against the Observatory cannot change memory.
- Added `AOMS_CONTEST_SLA_DAYS` (default 14) and `AOMS_CONTEST_EXPIRY_DAYS` (default 30). Both are reporting thresholds only.
- Added `cortex-mem contest resolve-many --set-aside`, a filtered bulk decline for when a misconfigured writer floods the review queue. Set-aside is deliberately the only bulk verdict: bulk admission would make many contested claims current at once, which is the shape of the thing this feature prevents. It refuses to run without a narrowing filter, receipts every entry individually, and deletes nothing.
- Added `docs/CONTEST-LEDGER.md` and a README section stating what opting into `claim_key` costs, measured: 0% false rejection where the caller declares what it replaces, 82.35% where it does not.
- Portable export bundles now carry `contests.jsonl` and `write_receipts.jsonl`. A backup that dropped the ledger would have discarded the only durable record of a contested write, and a restored store would have withheld a record from recall with nothing left to explain why. Bundles written before this restore unchanged.

### Changed

- The `remember` tool description and the `supersedes`, `claim_key`, `id` and `observation_id` parameters now carry guidance telling a caller to declare what it replaces. No parameter was added; only documentation. Note the measured claim: **declaring costs nothing** (0% false rejection where the caller declares, 82.35% where it does not). We do not claim the guidance is what causes declaring — an A/B against real models found Claude Code already declares correctly without it, and a smaller model did not declare in either arm. See `docs/experiments/declare-ab/`.
- **Behavioral contract change for MCP clients.** `remember`'s semantics widen from "this was stored" to "this was stored, and here is whether it holds the slot." `RememberResult` gains `disposition`, `contest_id`, and `incumbent_ids`; a contested write reports itself in-band, the same turn, and names the record still standing. Clients that never send `claim_key` see no behavior change at all.
- Schema `LATEST_SCHEMA_VERSION` moves 6 to 7. Migration 7 is pure DDL: it rewrites no `record_json`, deletes nothing, and backfills nothing. `memories.claim_key` is nullable with no default, so **every record written before this release is non-participating** and keeps exactly the semantics it had. Defaulting existing rows to a comparable weak value would have let the first post-upgrade write dominate everything written before the feature existed.
- Contested records are excluded from `list`, `search`, recall candidates, visible counts, and lineage by one predicate at the shared read choke point, rather than by a filter re-implemented per query.

### Removed

- The `derived-from-memory` contest trigger is no longer enabled by default. It was specified as the block against laundering and it never blocked anything: `derived_from` is caller-declared and optional, so a writer intent on displacing an occupant omits it and is admitted, while a write that declares no replacement is contested regardless. Its only reachable effect was to contest writers honest enough to record where they had read something — measured live, where every contest across twelve Claude Code sessions came from this trigger and one agent responded by writing itself instructions to stop using `claim_key`. `derived_from` is still recorded on every write receipt and contest entry; only its power to block is gone, and the trigger remains implemented and configurable. `RULESET_VERSION` moves to 2, so every receipt's digest distinguishes the two behaviours. **Open problem:** a real defence needs provenance a caller cannot omit — server-stamped, session-linked — which is not in this release.

### Security

- `contest_id` is always a server-generated `uuid4` and is never derived from any caller string. `RememberRequest.id` accepts 256 arbitrary characters, so an id-derived contest identifier would have rendered attacker prose into every recalled context.
- The contest notice attached to a surviving incumbent carries a count, up to three server UUIDs, and one timestamp: zero challenger prose, provenance, or claim-key value. The UUID shape is re-validated at render time rather than trusted.
- `Provenance.derived_from` accepts only opaque identifier shapes and refuses prose at the boundary, because that field renders verbatim into a model's context through the recall provenance dump. An `asserted_at` in the future is refused, closing forged-freshness claims.

## [2.0.0] - 2026-08-23

### Added

- Rebuilt canonical memory around a local SQLite/WAL repository, portable settings, typed contracts, durable embedding work, and import/export/restore operations.
- Added agent-private, workspace, and user-global scopes enforced from trusted process or authentication context before recall serialization.
- Added deterministic token-budgeted recall with provenance fencing and versioned receipts that explain selection, rejection, scope filtering, supersession, vector coverage, and exact token accounting.
- Added the universal FastMCP adapter with the deliberately small model-facing `recall`, `remember`, and `search` tool contract, plus setup recipes for Claude Code, Codex, and OpenClaw.
- Added scoped bearer-token authentication, TLS and host/origin safeguards for optional remote MCP, while retaining stdio and loopback-local defaults.
- Added a deterministic retrieval evaluation harness and a cold-start relay fixture with sealed artifacts. The bundled v2.0.0 relay evidence is **REHEARSAL**, not production proof.
- Added the read-only, loopback-only Recall Observatory for inspecting records, retrieval scores, scope metadata, receipts, token accounting, and chain findings.
- Added preview-first Markdown/Obsidian and reviewed `claude-mem` SQLite importers with explicit destination scope, secret warnings, and execute-only writes.
- Added append-only supersession, `chain` and `--as-of` diagnostics, and declared truth timelines with cycle, dangling-target, branching-head, retrievable-pair, and scope-boundary findings.

### Changed

- Replaced the retired v1 JSONL/HTTP daemon architecture with an installable `cortex-mem` package centered on one canonical store and transport-independent application contracts.
- Made empty-store activation, local lexical-only operation, maintenance commands, portable backups, and source-correct MCP registration explicit CLI paths.
- Kept destructive maintenance, import, recovery, token administration, and other privileged operations out of the model-facing MCP tool surface.

### Fixed

- Stopped the v1 `/memory/decay` rewrite path from concatenating JSONL entries into giant blob lines; rewrites now newline-terminate records and use same-directory `fsync` plus atomic replacement.
- Added a streaming recovery tool for corrupted concatenated-JSON blobs with content-hash deduplication, separate output, and a verification pass.
- Suppressed superseded candidates during context packing and tightened relay recall contracts and token ceilings.

### Security

- Bound scope identity outside model-controlled tool arguments and added negative isolation tests at the final context boundary.
- Added hashed bearer-token storage, per-token permissions, public-bind fail-closed checks, request limits, and documented privacy boundaries for local storage and cloud-backed clients.

## [1.0.1] - 2026-02-26

> **Superseded by 2.0.0.** The v1.0.0/v1.0.1 JSONL service is retained in Git history for migration and incident context, but it is retired and should not be assumed to receive fixes.

### Changed

- Removed migrated personal memory data from the public release line and added the original release documentation.

[Unreleased]: https://github.com/dhawalc/cortex-mem/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/dhawalc/cortex-mem/compare/v1.0.1...v2.0.0
[1.0.1]: https://github.com/dhawalc/cortex-mem/compare/v1.0.0...v1.0.1
