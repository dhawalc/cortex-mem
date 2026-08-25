# AOMS — scoped memory for your whole agent fleet

[![CI](https://github.com/dhawalc/cortex-mem/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/dhawalc/cortex-mem/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](pyproject.toml)

**One local brain, hard workspace boundaries.** AOMS lets Claude Code, Codex, OpenClaw, and other MCP agents share durable memory without collapsing every client and project into one undifferentiated profile.

Every process is bound to an agent ID and a workspace ID. A workspace memory crosses agent boundaries only inside that workspace; an agent-private memory stays with its owner; a user-global memory is deliberately fleet-wide. Identity never comes from model-controlled tool arguments, and scope policy is applied before any memory can enter context.

AOMS stores canonical memory in one SQLite/WAL database, retrieves locally, packs the final context under an exact token ceiling, provenance-fences recalled text as untrusted data, and records a receipt showing what was selected, filtered, superseded, and serialized.

This is infrastructure for people running several agents and sessions—not a per-assistant chat-history plugin and not the retired v1 HTTP daemon.

## Why AOMS

Memory systems make different tradeoffs: some center one assistant, a hosted service, or retrieval alone. AOMS is aimed at local multi-agent work where the boundary and the explanation matter as much as the match. It combines hard agent/workspace scope isolation, inspectable recall receipts and a local Observatory, local-first SQLite storage, and preview-first importers so existing notes and reviewed memory stores can move in deliberately. It can complement agent frameworks and RAG stacks rather than requiring them to be replaced.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/launch/assets/recall-observatory-receipt-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/launch/assets/recall-observatory-receipt-light.png">
  <img src="docs/launch/assets/recall-observatory-receipt-light.png" alt="Recall Observatory receipt inspector showing packed provenance-fenced context, a March decision marked as a superseded predecessor, the candidate funnel, and exact token arithmetic totaling 842 of a 1,000-token budget.">
</picture>

<p align="center"><em>Not just what your agent remembered—exactly what entered context, why, from where, and what was kept out.</em></p>

## Quick start

> [!WARNING]
> Do not install `cortex-mem` 1.0.0 from PyPI. That release is the retired v1
> HTTP daemon, not AOMS v2. Until a reviewed v2 package is published, use the
> pinned Git release command below.

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

Python 3.11 through 3.13 is supported. The default local embedding model is downloaded only when a non-empty store first needs semantic retrieval. Empty-store recall returns immediately without loading it.

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

![Annotated terminal proof of init, remember, and cold recall in a fresh process, including the workspace-scoped source and receipt ID.](docs/launch/assets/aoms-60-second-proof.png)

The image is a deterministic, annotated rendering of a real two-process CLI run; [open the accessible HTML transcript](docs/launch/assets/aoms-60-second-proof.html) or [read how the assets are regenerated](docs/launch/assets/README.md).

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

## Contested writes, and what opting in costs

Set `claim_key` on a write to name the proposition it answers, and a later write landing on that same proposition without declaring what it replaces is kept in full but held aside for review, instead of silently becoming a second current answer. Two dispositions exist, `admitted` and `contested`; nothing is refused, deleted, or truncated.

It is off unless you turn it on, per write. `claim_key` defaults to `None`, no importer or recipe sets it, and every record written before the feature shipped is non-participating — measured on the frozen benchmark, not asserted.

The cost when you do turn it on is real, and worth meeting here rather than in production:

| Caller behaviour | False rejection | Valid supersession |
|---|---:|---:|
| Declares what it replaces (`supersedes`) | 0% | 100% |
| Does not declare | 82.35% | 0% |

Pair `claim_key` with `supersedes` and the gate costs nothing. Set `claim_key` without ever declaring replacement and roughly four out of five valid revisions are held for a human instead of applied.

The prerequisite is a capability, not a prompt: **an agent that writes blind cannot declare supersession at all**, because it has no incumbent id to name. Adopt `claim_key` only for writers that read before they write. Measured against real models in [docs/experiments/declare-ab/](docs/experiments/declare-ab/): Claude Code reads first and declares correctly 8/8 without being told, while a smaller local model never read, never declared, and adopted `claim_key` anyway — the one configuration to avoid.

See **[docs/CONTEST-LEDGER.md](docs/CONTEST-LEDGER.md)** for the full picture, including what draining the review queue costs, who should not opt in, and the limits of that experiment.

This is a write-**authority** gate, not an evidence gate: it governs who may displace what, and never judges whether a claim is true, fresh, or well-sourced.

## The scope model

| Scope | Visible to |
|---|---|
| `agent-private` | Only the bound agent that owns the memory. |
| `workspace` | Agents bound to the same workspace. This is the default. |
| `user-global` | Every agent using that AOMS store, including every remote bearer token regardless of the workspace it is bound to. |

For local processes, identity is bound in the registered MCP environment. For authenticated HTTP, the bearer token binds it server-side. The model cannot supply or switch identity through `recall`, `remember`, or `search` arguments.

A bound identity constrains writes, `agent-private` reads, and `workspace` reads. It does **not** constrain `user-global` reads, which are fleet-wide by definition. The practical read reach of any token is therefore *all `user-global` records plus one workspace plus one agent* — and the first term is set by your data, not by the token. Before exposing a remote listener, measure how much of your store is `user-global`, and serve a separate database via `AOMS_DATA_DIR` if a remote client should see less. See [remote authentication](docs/REMOTE_AUTH.md).

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

## Operations

Never copy a live WAL database directly. The shipped [v2 backup job](packaging/ops/backup-aoms-v2.sh) uses SQLite's online backup API for daily physical generations and `cortex-mem export` for weekly portable recovery bundles, verifies both locally and after VPS transfer, and enforces bounded daily/weekly retention. Use the [disaster-recovery runbook](docs/RECOVERY.md) for corrupted-store, machine-loss, and bad-write recovery; see [backup operations](docs/legacy/BACKUPS.md) for deployment and the temporary v1/v2 parallel-backup plan.

## Develop

```console
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow and [SECURITY.md](SECURITY.md) for the threat model and disclosure process.

MIT licensed.
