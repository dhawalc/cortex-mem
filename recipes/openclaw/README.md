# OpenClaw: automatic AOMS memory

OpenClaw's `agent:bootstrap` event fires before workspace context is injected.
Install this recipe as a managed hook:

```sh
mkdir -p ~/.openclaw/hooks
cp -R recipes/openclaw/hooks/aoms-recall ~/.openclaw/hooks/
openclaw hooks enable aoms-recall
openclaw hooks check
```

The hook runs `cortex-mem recall` directly and injects its output as a virtual
bootstrap file. It replaces the legacy pattern of an HTTP-coupled
`boot_aoms.py`; no service URL, stats scan, or hand-maintained response mapping
is involved. The handler binds the OpenClaw agent and workspace identities in
the child-process environment.

Source for the lifecycle contract: [OpenClaw hooks](https://docs.openclaw.ai/automation/hooks#event-types),
accessed 2026-08-23. It documents `agent:bootstrap` as firing before workspace
bootstrap files are injected and exposes a mutable `context.bootstrapFiles`
array.

For MCP access from the agent, configure the same stdio server used by other
hosts:

```sh
openclaw config set mcp.servers.aoms '{"command":"uvx","args":["cortex-mem","mcp"]}' --strict-json
```

Install `session_sync_v2.py` and its systemd units to capture explicit durable
learnings hourly. That sync is deliberately narrower than OpenClaw's bundled
full-session memory: it stores marked decisions, failures, and learnings only.

## Hourly selective capture

The sync recognizes only one-line markers at the beginning of user or assistant
text: `Decision:` / `Decided:`, `Failure:` / `Failed:`, and `Learning:` /
`Learned:` / `Lesson:`. Thinking blocks, tool calls, ordinary prose, malformed
JSONL, and marker lines that resemble credentials are skipped. Each write gets
an idempotency key derived from the session ID, source byte offset, and marker
position.

Install the user units after replacing the service template's recipe path:

```sh
recipe_dir="$(cd recipes/openclaw && pwd)"
mkdir -p ~/.config/systemd/user
sed "s|@RECIPE_DIR@|$recipe_dir|g" \
  recipes/openclaw/openclaw-session-sync-v2.service \
  > ~/.config/systemd/user/openclaw-session-sync-v2.service
cp recipes/openclaw/openclaw-session-sync-v2.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now openclaw-session-sync-v2.timer
systemctl --user list-timers openclaw-session-sync-v2.timer
```

Run one foreground check before relying on the timer:

```sh
AOMS_WORKSPACE="$HOME/.openclaw/workspace" \
  python3 recipes/openclaw/session_sync_v2.py \
  --workspace "$HOME/.openclaw/workspace"
```

The cursor lives at
`~/.local/state/aoms/openclaw-session-sync-v2.json`. If that file is lost, old
eligible lines are replayed with the same keys and update existing memories.
