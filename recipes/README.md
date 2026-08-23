# Make shared memory automatic

MCP makes AOMS callable. These recipes make agents actually recall it at the
start of work and make durable capture routine instead of aspirational. First
initialize one local store:

```sh
cortex-mem init
```

Every host process should bind a stable agent identity and an absolute workspace
identity. The same workspace value lets different agents share project memory;
different agent IDs preserve agent-private isolation.

## Claude Code

Add the user-scoped MCP server:

```sh
claude mcp add --scope user aoms -- uvx cortex-mem mcp
```

Merge [`claude-code/hooks.json`](claude-code/hooks.json) into
`~/.claude/settings.json`, install `jq`, and append
[`claude-code/CLAUDE.md.snippet`](claude-code/CLAUDE.md.snippet) to the project's
`CLAUDE.md`. The `SessionStart` hook recalls 2,000 task-relevant tokens on new,
resumed, cleared, compacted, and forked sessions and injects them through
Claude Code's structured `additionalContext` contract. Full setup and the
official contract source are in [`claude-code/README.md`](claude-code/README.md).

## OpenClaw

Install the native `agent:bootstrap` hook:

```sh
mkdir -p ~/.openclaw/hooks
cp -R recipes/openclaw/hooks/aoms-recall ~/.openclaw/hooks/
openclaw hooks enable aoms-recall
openclaw hooks check
```

It invokes the same `cortex-mem recall` CLI and injects a virtual bootstrap file,
replacing service-specific boot scripts. Add MCP access if desired:

```sh
openclaw config set mcp.servers.aoms '{"command":"uvx","args":["cortex-mem","mcp"]}' --strict-json
```

For capture, install the hourly `session_sync_v2.py` timer. It reads only new
JSONL bytes and writes only explicitly marked decisions, failures, and learnings
with stable replay keys. See [`openclaw/README.md`](openclaw/README.md) for the
copy-paste systemd installation.

## Codex

Merge this block into `~/.codex/config.toml`, using the real absolute workspace:

```toml
[mcp_servers.aoms]
command = "uvx"
args = ["cortex-mem", "mcp"]
env = { AOMS_AGENT_ID = "codex", AOMS_WORKSPACE = "/absolute/path/to/project" }
```

Append [`codex/AGENTS.md.snippet`](codex/AGENTS.md.snippet) to project
`AGENTS.md`. Codex loads it every session, so recall-at-start and selective
remember behavior travel with the repository. See
[`codex/README.md`](codex/README.md).

## Shell hooks and scripts

The host recipes use two transport-independent commands:

```sh
AOMS_AGENT_ID=my-agent AOMS_WORKSPACE=/absolute/project \
  cortex-mem recall --task "Prepare the release using prior constraints" \
  --budget 2000 --format markdown

printf '%s\n' 'Decision: deploy only after the amber canary passes.' | \
  AOMS_AGENT_ID=my-agent AOMS_WORKSPACE=/absolute/project \
  cortex-mem remember --content - --kind decision --tags release,canary \
  --idempotency-key release-amber-gate
```

Use `--format json` when a caller needs source metadata and diagnostics.

## Capture policy: conclusions, not exhaust

Automatic memory should be much smaller than the conversation that produced it.
Capture only a durable, self-contained conclusion that a future agent can act
on: a verified fact, a decision with rationale, a failure with root cause, or a
repeatable procedure/pattern. Skip status chatter, raw prompts and responses,
tool output, guesses, and facts already maintained in project files.

Every retryable producer must provide a stable idempotency key from its source
event identity. The OpenClaw recipe uses `session-id + byte-position + marker
position`; reruns update the same record even if cursor state is lost.

Never store passwords, API keys, tokens, private keys, credentials, personal
data, or secret-bearing logs. Pattern filters are only a backstop, not a secret
scanner: producers should select safe conclusions before calling `remember`,
and operators should periodically inspect captured records and provenance.
