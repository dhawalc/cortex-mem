# AOMS Relay runner

The runner starts a new process and a new private fixture-repository copy for
each stage. Deterministic replay is the safe default:

```console
python -m demo.relay.runner run \
  --output /tmp/aoms-relay-7319 \
  --agents scripted,scripted,scripted \
  --seed 7319 --with-baseline
python -m demo.relay.runner validate /tmp/aoms-relay-7319
```

Real adapters are available for orchestrator-supervised runs only. Claude uses
`claude -p`, disabled slash commands/browser integration,
`--mcp-config`, `--strict-mcp-config`, verbose stream JSON output, an explicit
fresh session ID, `--no-session-persistence`, and an explicit allow-list for
the three injected AOMS tools so headless recall is not left waiting for an
impossible approval. Codex uses `codex -a never
exec --json`, `--ephemeral`, `--ignore-user-config`, `--ignore-rules`, `-C`,
an explicitly selected sandbox mode, and `-c mcp_servers.aoms.*` values
derived from the same stdio server config.

Claude defaults to `AOMS_RELAY_CLAUDE_AUTH=bare`, which adds `--bare` and
excludes user-level configuration but requires API-key authentication. Set
`AOMS_RELAY_CLAUDE_AUTH=oauth` to omit only `--bare` and use the machine's
Claude OAuth session. OAuth runs record that user-level configuration was not
excluded, and the verifier grades their evidence as `REHEARSAL`; bare Claude
runs remain eligible for `PROOF` grade.

## Host prerequisites

A bwrap-capable Linux host is required for `PROOF`-grade Codex evidence. The
adapter defaults to `AOMS_RELAY_CODEX_SANDBOX=workspace-write`, which passes
`-s workspace-write` to `codex exec` and keeps host sandboxing in the isolation
proof. On hosts where bwrap cannot initialize (including nested environments
that cannot configure the loopback interface), set
`AOMS_RELAY_CODEX_SANDBOX=danger-full-access`. That mode preserves the relay's
fresh context, private working directory, and MCP capture, but disables the
orthogonal host sandbox; the evidence records the selected mode and the
verifier caps the bundle at `REHEARSAL` grade.

OpenClaw uses its embedded one-shot path so a relay run does not depend on or
modify the live Gateway configuration:

```text
OPENCLAW_CONFIG_PATH=<stage>/openclaw-config.json \
OPENCLAW_STATE_DIR=<stage>/openclaw-state \
openclaw agent --local --agent main --session-id <uuid> \
  [--model <provider/model>] --message <prompt> --json
```

The adapter creates the config, refuses a pre-existing private state path, sets
`agents.defaults.workspace` to the stage repository, disables workspace
bootstrap-file creation, and omits `--deliver`. Set
`AOMS_RELAY_OPENCLAW_MODEL` to add the optional `--model` override; otherwise
OpenClaw uses its embedded default and provider credentials must already be
available in the process environment. The documented `--json` contract keeps
stdout machine-readable; stdout, stderr, an exact `adapter-result.json` copy,
the private config/state, argv, timing, and adapter guarantees are retained in
the stage evidence.

OpenClaw has no `--ephemeral` or `--no-session-persistence` flag. Empty history
is instead guaranteed at adapter scope by the new `OPENCLAW_STATE_DIR` plus the
new UUID; the resulting transcript remains in that private directory as
evidence. This is fresh conversation state, not cron's internal
`sessionTarget=isolated` mechanism.

Discovery on OpenClaw 2026.6.10 used `openclaw --help`, `openclaw agent
--help`, `openclaw cron --help`, `openclaw cron run --help`, `openclaw cron
list --json`, `openclaw mcp --help`, and the bundled `docs/cli/agent.md`,
`docs/cli/mcp.md`, `docs/concepts/session.md`, and
`docs/concepts/multi-agent.md`. The CLI has no `run`/`ask` command, no agent
`--cwd` flag, and no per-turn MCP flag. Gateway mode therefore needs global
`mcp.servers` and a globally configured agent workspace. Embedded mode avoids
that limitation because `OPENCLAW_CONFIG_PATH` supplies both per run.

## MCP capture

The injected client config points at `demo.relay.mcp_proxy`, not directly at
the server. The proxy launches the equivalent of `cortex-mem mcp` through the
selected Python interpreter (`python -m aoms.cli mcp`) and records every
JSON-RPC frame in `mcp-traffic.jsonl`. For implementer and reviewer stages it
pins every recall call to that stage's scenario `token_ceiling`, regardless of
the model-requested value; the recorded message is the value actually
forwarded and an `enforcement` field preserves the originally requested value.
Each line contains a monotonic sequence, UTC capture time, direction, and
parsed message.
Server stderr stays off protocol stdout and is retained in the stage stderr log.
For OpenClaw, the adapter translates `mcpServers.aoms` to
`mcp.servers.aoms` in the private config. The proxy and server use absolute
paths/explicit cwd rather than an MCP `PYTHONPATH` entry because this OpenClaw
release rejects interpreter-startup environment overrides in stdio MCP config.

## Bundle schema

`manifest.json` hashes every other regular file and fixes the exact inventory.
The bundle includes protocol inputs and seed, source/fixture/version metadata,
per-stage prompt/process/MCP/git evidence, the final workspace, canonical stage
2 and 3 recall artifacts, a portable records-and-receipts export, and verifier
output. `--with-baseline` adds a mirrored memory-disabled run plus
`comparison.json`; the scripted baseline receives no MCP config. Output paths
are write-once: the runner refuses to reuse an existing destination and seals a
staging tree before atomically publishing it.

If a stage process fails, the runner seals the partial evidence tree and
atomically publishes it beside the requested output with a `-FAILED` suffix.
The failure bundle includes `failure.json`, all completed-stage evidence, and
the failing stage's complete stdout/stderr and process record. Claude
stream-JSON `api_error_status` and `result` fields are also included in the
raised error so an operator can diagnose API failures without replaying them.
Memory-enabled implementer and reviewer stages also fail immediately when no
recall reaches the proxy, instead of continuing to a predictably unverifiable
final bundle.
