<!-- DRAFT public README. Replace the repository README only after Dhawal's launch review. -->

# AOMS — one governed brain for your agent fleet

AOMS is a local-first memory router that gives MCP agents shared, scoped, provenance-rich context packed to the caller's token budget.

Run one memory service on your machine and connect Claude Code, Codex, OpenClaw, or any other MCP client. AOMS stores canonical memories in SQLite, recalls only what the caller is allowed to see, and returns a receipt showing what was selected, why it ranked, where it came from, and how many tokens entered the model context.

This is infrastructure for people running several agents and sessions—not a per-assistant chat-history plugin.

## Install from Git

Until a PyPI release is available, initialize AOMS directly from the repository:

```console
uvx --from git+https://github.com/dhawalc/cortex-mem cortex-mem init
```

Run the MCP server over local stdio with the same source install:

```console
uvx --from git+https://github.com/dhawalc/cortex-mem cortex-mem mcp
```

For example, register that command with Claude Code:

```console
claude mcp add aoms -- uvx --from git+https://github.com/dhawalc/cortex-mem cortex-mem mcp
```

Python 3.11 or 3.12 is recommended. `cortex-mem init` creates the local SQLite store but does not download an embedding model. Run `cortex-mem doctor` to inspect the installation and model-cache state.

## Three tools, one contract

| Tool | Purpose |
|---|---|
| `recall` | Pack relevant memory for the current task under an explicit token ceiling, with structured sources and retrieval diagnostics. |
| `remember` | Store a fact, decision, failure, procedure, or other memory with provenance and an optional idempotency key. |
| `search` | Inspect typed records and scores with filters and pagination; no context packing. |

Maintenance is deliberately not model-facing. Import, export, restore, diagnostics, token management, embedding backfill, and sweeps remain CLI operations.

## The scope model

Every AOMS process or authenticated HTTP token is bound to an agent ID and workspace ID. Identity is not accepted in tool arguments.

| Scope | Visible to |
|---|---|
| `agent-private` | Only the bound agent that owns the memory. |
| `workspace` | Agents bound to the same workspace. This is the default. |
| `user-global` | Every agent using that AOMS store. |

Scope policy is applied in repository queries before records can be packed into context. Recall receipts report the bound identity, filtering counts, selected records, and a bounded rejected sample so isolation can be tested at the actual serialization boundary.

## Local-first, with precise privacy claims

AOMS stores its canonical database, vector index, embedding queue, and recall receipts locally. The default embedding provider runs locally, and lexical-only operation is available with `AOMS_EMBEDDING_PROVIDER=none`. JSONL is used for reviewed import/export rather than as a mutable database.

The default MCP transport is stdio, so it opens no listening socket. Optional streamable HTTP binds to loopback by default. A non-loopback bind is refused unless direct TLS and an active bearer token are configured; token secrets are stored as salted `scrypt` hashes, and their agent/workspace identity is applied server-side. See [remote authentication](../REMOTE_AUTH.md).

Local-first does not mean every connected model runs offline. A cloud-backed MCP client may send recalled context to its model provider under that client's own privacy terms. AOMS makes storage and retrieval local; it does not conceal what a client does with tool output.

## The relay rehearsal

The launch demo is a cold-start relay: a planner records non-obvious constraints, an implementer starts in a fresh process without the planner's transcript, and a reviewer starts cold again with a new regression clue. Their shared input is scoped AOMS memory.

The runnable protocol captures initial prompts, process freshness, MCP JSONL traffic, recall receipts, source provenance, token ceilings, repository diffs, deterministic tests, a memory-disabled baseline, and a SHA-256-sealed manifest. Deterministic scripted replay requires no model account:

The v2.0.0 release bundles are **REHEARSAL** grade. A **PROOF**-grade upgrade
requires bare provider authentication and a bwrap-capable host with Codex
`workspace-write`; the full three-client claim also requires OpenClaw provider
credentials.

```console
python -m demo.relay.runner run \
  --output /tmp/aoms-relay-7319 \
  --agents scripted,scripted,scripted \
  --seed 7319 --with-baseline
python -m demo.relay.runner validate /tmp/aoms-relay-7319
```

The goal is a falsifiable handoff, not an “agents never forget” claim. Hidden runtime constraints must cross the handoff, out-of-scope canaries must never enter model context, packed recall must stay under its declared budget, and the fixture's black-box tests must pass.

## Read the evidence

- [My agents' memory was silently corrupted for months](silent-corruption-essay.md) — the incident, recovery, and reasons for the rebuild.
- [Anatomy of a token-budgeted handoff](../../aoms/anatomy.py) — the static report generator for candidate scores, exclusions, provenance chains, supersession, and exact token accounting.
- [AOMS Relay Protocol](../../demo/relay/README.md) — runner commands, client isolation, MCP capture, and the sealed bundle schema.

## Develop

```console
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
```

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the development workflow and [SECURITY.md](../../SECURITY.md) for the local/remote threat model and private disclosure process.

MIT licensed.
