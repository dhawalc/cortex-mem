# AOMS — scoped memory for your whole agent fleet

[![CI](https://github.com/dhawalc/cortex-mem/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/dhawalc/cortex-mem/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](pyproject.toml)

**One local brain, hard workspace boundaries.** AOMS lets Claude Code, Codex, OpenClaw, and other MCP agents share durable memory without collapsing every client and project into one undifferentiated profile.

Every process is bound to an agent ID and a workspace ID. A workspace memory crosses agent boundaries only inside that workspace; an agent-private memory stays with its owner; a user-global memory is deliberately fleet-wide. Identity never comes from model-controlled tool arguments, and scope policy is applied before any memory can enter context.

AOMS stores canonical memory in one SQLite/WAL database, retrieves locally, packs the final context under an exact token ceiling, provenance-fences recalled text as untrusted data, and records a receipt showing what was selected, filtered, superseded, and serialized.

This is infrastructure for people running several agents and sessions—not a per-assistant chat-history plugin and not the retired v1 HTTP daemon.

## Why AOMS

Memory systems make different tradeoffs: some center one assistant, a hosted service, or retrieval alone. AOMS is aimed at local multi-agent work where the boundary and the explanation matter as much as the match. It combines hard agent/workspace scope isolation, inspectable recall receipts and a local Observatory, local-first SQLite storage, and preview-first importers so existing notes and reviewed memory stores can move in deliberately. It can complement agent frameworks and RAG stacks rather than requiring them to be replaced.

> **Demo GIF placeholder:** A captioned setup-to-cold-recall walkthrough is planned for [`docs/launch/assets/`](docs/launch/assets/README.md). The slot is intentionally marked as a placeholder until a synthetic-data capture is recorded and checked; no demo evidence is being claimed yet.

## Quick start

From the project you want to bind, run the pinned Git release:

```console
uvx --from git+https://github.com/dhawalc/cortex-mem@v2.0.0 cortex-mem setup claude
```

Use `codex` or `openclaw` instead of `claude` for another supported host. `setup`:

- detects whether it is running from the pinned Git source or an installed launcher;
- creates/checks the local store without downloading an embedding model;
- binds `agent=<host>` and `workspace=<current directory>` (override with `--workspace`);
- executes the source-correct MCP registration and materializes the packaged host recipe; and
- performs a real MCP handshake and scoped recall, then prints the recall receipt ID.

The success output names the binding explicitly—for example, `bound as agent=claude workspace=myproject`. It never silently registers `default/default`.

Python 3.11 or 3.12 is recommended. The default local embedding model is downloaded only when a non-empty store first needs semantic retrieval. Empty-store recall returns immediately without loading it.

## The 60-second check: remember, kill, cold-recall

Save one real decision that the next session must know. Do not seed your canonical store with demo data:

```console
uvx --from git+https://github.com/dhawalc/cortex-mem@v2.0.0 \
  cortex-mem remember \
  --content "Decision: release only after the amber canary passes." \
  --kind decision --tags release,canary \
  --idempotency-key release-amber-gate
```

The CLI binds this write to the resolved current workspace. Because workspace is the default scope, the Claude process registered there can see it even though the writer and reader are different agents.

Now end the host session completely. Start a fresh session in the same project and ask:

> Recall the release gate for this workspace. What must pass before release?

The new process has no prior transcript. Its answer should come from the workspace-scoped memory, and recall returns a receipt ID documenting the exact serialization path. That cold handoff—not a health check—is the activation check.

If you do not have a durable fact yet, run an isolated tour:

```console
uvx --from git+https://github.com/dhawalc/cortex-mem@v2.0.0 cortex-mem tour
```

The tour creates a disposable temporary store, seeds exactly three demo memories, demonstrates private-scope filtering and supersession, prints a real receipt, and auto-cleans. It never opens the canonical store. Use `--keep` only if you want to inspect the labeled demo database afterward.

## Bring existing memory deliberately

`import-from` accepts Markdown/Obsidian notes and reviewed `claude-mem` SQLite schemas. It previews by default, requires an explicit destination scope, warns about likely secrets without printing their values, and writes only when you add `--execute`:

```console
uvx --from git+https://github.com/dhawalc/cortex-mem@v2.0.0 \
  cortex-mem import-from markdown ./notes \
  --scope workspace --workspace "$PWD" --execute
```

Run `cortex-mem import-from --help` for source-specific choices. Import is never required for setup, and setup does not invent memories in your real store.

## Inspect recall locally

The Recall Observatory is a read-only browser for canonical memories, scope metadata, recall receipts, candidate scores, token accounting, retained provenance-fenced context, and declared truth timelines. Its **Truth** inbox reports deterministic chain findings—cycles, dangling targets, branching heads, retrievable old/new pairs, and scope-boundary anomalies—with record links and no auto-fix or semantic truth claims. Start it on IPv4 loopback, then open the printed local URL:

```console
uvx --from git+https://github.com/dhawalc/cortex-mem@v2.0.0 \
  cortex-mem observe
```

It does not expose a non-loopback bind option or alter the store.

Correct a retained record by appending a successor; the predecessor is never rewritten:

```console
cortex-mem supersede MEMORY_ID --content "The corrected durable fact"
```

The command prints the resulting validity timeline. `cortex-mem chain MEMORY_ID --as-of 2026-03-15T12:00:00Z` and `cortex-mem search QUERY --as-of ...` reconstruct declared lineage from retained timestamps while applying the bound scope to every chain member. This is explicitly not omniscient event history. Model-facing recall intentionally has no `as_of` option yet: safe temporal recall also requires candidate, semantic-retrieval, and receipt semantics to move together.

## Three model-facing tools, one contract

| Tool | Purpose |
|---|---|
| `recall` | Pack relevant memory for the current task under an explicit token ceiling, with structured sources and retrieval diagnostics. |
| `remember` | Store a fact, decision, failure, procedure, or other durable memory with provenance and an optional idempotency key. |
| `search` | Inspect typed records and scores with filters and pagination; no context packing. |

Maintenance is deliberately not model-facing. Setup, import, export, restore, diagnostics, token management, embedding backfill, sweeps, and the disposable tour remain CLI operations.

## The scope model

| Scope | Visible to |
|---|---|
| `agent-private` | Only the bound agent that owns the memory. |
| `workspace` | Agents bound to the same workspace. This is the default. |
| `user-global` | Every agent using that AOMS store. |

For local processes, identity is bound in the registered MCP environment. For authenticated HTTP, the bearer token binds it server-side. The model cannot supply or switch identity through `recall`, `remember`, or `search` arguments.

Receipts retain the bound agent/workspace, requested filters, content-free scope-filter count, selected and rejected candidates, supersession decisions, vector coverage, exact token total, and engine version. Scope isolation is therefore testable at the actual context boundary, not merely asserted in configuration.

## Empty stores are a path, not a dead end

An empty scoped recall says:

```text
Store is empty for your scopes. Next: cortex-mem remember / import / tour.
```

It still writes a zero-candidate receipt, but it checks visibility before embedding so a cold empty brain does not download a model just to return nothing. Choose one path: save one user-authored durable decision, use an available reviewed importer, or run the disposable tour.

## Local-first, with precise privacy claims

AOMS keeps the canonical database, vector index, durable embedding queue, and recall receipts locally. The default embedding provider runs locally; lexical-only operation is available with `AOMS_EMBEDDING_PROVIDER=none`. The default stdio transport opens no listening socket.

Optional streamable HTTP binds to loopback by default. A non-loopback bind is refused unless direct TLS and an active bearer token are configured; token secrets are stored as salted `scrypt` hashes, and token identity is enforced server-side. See [remote authentication](docs/REMOTE_AUTH.md).

Local-first does not mean every connected model runs offline. A cloud-backed MCP client may send recalled context to its model provider under that client's privacy terms. AOMS makes storage and retrieval local; it cannot conceal what a client does with tool output.

## Evidence, not “agents never forget”

The included cold-start relay has a planner record non-obvious constraints, then launches transcript-isolated implementer and reviewer processes. Its artifact bundle captures MCP traffic, recall receipts, provenance, token ceilings, scope canaries, repository diffs, tests, a memory-disabled baseline, and a SHA-256 manifest.

The v2.0.0 release bundles are explicitly **REHEARSAL** grade. The canonical
live bundle used Claude/Codex/Claude with Claude OAuth and Codex
`danger-full-access`; it is useful evidence, but it is not a three-client
OpenClaw proof and did not run from the final release revision. The upgrade path
to **PROOF** grade is a new run with bare provider authentication on a
bwrap-capable host using Codex `workspace-write` sandboxing, plus OpenClaw
provider credentials for the full three-client claim.

Deterministic scripted replay requires no model account:

```console
git clone --branch v2.0.0 --depth 1 https://github.com/dhawalc/cortex-mem.git
cd cortex-mem
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
python -m demo.relay.runner run \
  --output /tmp/aoms-relay-7319 \
  --agents scripted,scripted,scripted \
  --seed 7319 --with-baseline
python -m demo.relay.runner validate /tmp/aoms-relay-7319
```

Read the supporting evidence:

- [My agents' memory was silently corrupted for months](docs/launch/silent-corruption-essay.md) — the incident, recovery, and rebuild constraints.
- [Anatomy of a token-budgeted handoff](aoms/anatomy.py) — the static receipt report generator.
- [AOMS Relay Protocol](demo/relay/README.md) — the falsifiable handoff and sealed artifact schema.

## Develop

```console
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow and [SECURITY.md](SECURITY.md) for the threat model and disclosure process.

MIT licensed.
