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
`claude -p`, `--bare`, disabled slash commands/browser integration,
`--mcp-config`, `--strict-mcp-config`, verbose stream JSON output, an explicit
fresh session ID, and `--no-session-persistence`. Codex uses `codex exec
--json`, `--ephemeral`, `--ignore-user-config`, `--ignore-rules`, `-C`,
workspace-write sandboxing, `-a never`, and `-c mcp_servers.aoms.*` values
derived from the same stdio server config. The OpenClaw adapter intentionally
raises a TODO until the user supplies and confirms its headless invocation
contract.

## MCP capture

The injected client config points at `demo.relay.mcp_proxy`, not directly at
the server. The proxy launches the equivalent of `cortex-mem mcp` through the
selected Python interpreter (`python -m aoms.cli mcp`), forwards stdio without
changing it, and records every JSON-RPC frame in `mcp-traffic.jsonl`. Each line
contains a monotonic sequence, UTC capture time, direction, and parsed message.
Server stderr stays off protocol stdout and is retained in the stage stderr log.

## Bundle schema

`manifest.json` hashes every other regular file and fixes the exact inventory.
The bundle includes protocol inputs and seed, source/fixture/version metadata,
per-stage prompt/process/MCP/git evidence, the final workspace, canonical stage
2 and 3 recall artifacts, a portable records-and-receipts export, and verifier
output. `--with-baseline` adds a mirrored memory-disabled run plus
`comparison.json`; the scripted baseline receives no MCP config. Output paths
are write-once: the runner refuses to reuse an existing destination and seals a
staging tree before atomically publishing it.
