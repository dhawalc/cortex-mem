# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
