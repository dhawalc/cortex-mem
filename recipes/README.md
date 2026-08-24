# Make shared memory automatic

MCP makes AOMS callable. These recipes make agents recall it at the start of
work and make durable capture routine instead of aspirational.

Run the pinned setup command from the project you want to bind:

```console
uvx --from git+https://github.com/dhawalc/cortex-mem@v2.0.0 cortex-mem setup claude
uvx --from git+https://github.com/dhawalc/cortex-mem@v2.0.0 cortex-mem setup codex
uvx --from git+https://github.com/dhawalc/cortex-mem@v2.0.0 cortex-mem setup openclaw
```

Choose the command for that host. `setup` initializes the store, binds the host
to the absolute current workspace, performs the
host's source-correct MCP registration, runs a real handshake and scoped
recall, and prints the materialized recipe directory. Do not replace that
registration with a bare `cortex-mem` or unpinned `uvx cortex-mem` command.

The emitted directory contains `aoms-binding.json` and a private
`cortex-mem-bound` launcher. Install lifecycle hooks only from that directory;
the checked-in files here are templates and are not workspace-bound.

## Claude Code

After `setup claude`, merge the materialized `hooks.json` into
`.claude/settings.json` for that project and append the materialized
`CLAUDE.md.snippet` to its `CLAUDE.md`. Install `jq` first. Setup deliberately
registers AOMS at Claude's local project scope, not user scope.

The `SessionStart` hook recalls 2,000 task-relevant tokens on new, resumed,
cleared, compacted, and forked sessions and injects them through Claude Code's
structured `additionalContext` contract. See
[`claude-code/README.md`](claude-code/README.md).

## OpenClaw

After `setup openclaw`, copy and enable `hooks/aoms-recall` from the
materialized recipe directory. It invokes the same bound launcher and injects a
virtual bootstrap file, replacing service-specific boot scripts.

For selective capture, install the materialized `session_sync_v2.py` and timer.
It reads only new session bytes and writes only explicitly marked decisions,
failures, and learnings with stable replay keys. See
[`openclaw/README.md`](openclaw/README.md).

## Codex

After `setup codex`, append the materialized `AGENTS.md.snippet` to the
project's `AGENTS.md`. Setup has already registered the bound MCP server; the
materialized `config.toml` is an inspectable record of that binding, not a
second configuration to merge. See [`codex/README.md`](codex/README.md).

## Shell hooks and scripts

For custom automation, use the materialized bound launcher so the source,
agent, workspace, and store remain the values setup verified:

```sh
"$RECIPE_DIR/cortex-mem-bound" recall \
  --task "Prepare the release using prior constraints" \
  --budget 2000 --format markdown

printf '%s\n' 'Decision: deploy only after the amber canary passes.' | \
  "$RECIPE_DIR/cortex-mem-bound" remember --content - --kind decision \
  --tags release,canary --idempotency-key release-amber-gate
```

Set `RECIPE_DIR` to the exact directory printed by setup. Use `--format json`
when a caller needs source metadata and diagnostics.

## Capture policy: conclusions, not exhaust

Automatic memory should be much smaller than the conversation that produced
it. Capture only a durable, self-contained conclusion that a future agent can
act on: a verified fact, a decision with rationale, a failure with root cause,
or a repeatable procedure/pattern. Skip status chatter, raw prompts and
responses, tool output, guesses, and facts already maintained in project files.

Every retryable producer must provide a stable idempotency key from its source
event identity. The OpenClaw recipe uses `session-id + byte-position + marker
position`; reruns update the same record even if cursor state is lost.

Never store passwords, API keys, tokens, private keys, credentials, personal
data, or secret-bearing logs. Pattern filters are only a backstop, not a secret
scanner: producers should select safe conclusions before calling `remember`,
and operators should periodically inspect captured records and provenance.
