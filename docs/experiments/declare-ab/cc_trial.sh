#!/usr/bin/env bash
# One Claude Code trial: seed a scratch store, run the task headless against
# that arm's MCP surface only, then dump what landed in the store.
#
# --strict-mcp-config guarantees the machine's real AOMS registration is not
# loaded, so ~/.local/share/aoms is unreachable from this run.
set -u

ARM="$1"          # armA | armB
TRIAL="$2"
CONDITION="${3:-unprompted}"
PY=/home/dhawal/cortex-mem/cortex-mem/.venv/bin/python
SRC="/tmp/decl/$ARM"
STORE="/tmp/decl/cc/$ARM-$CONDITION-$TRIAL"
CONFIG="$STORE/mcp.json"

mkdir -p "$STORE"
cat > "$CONFIG" <<EOF
{
  "mcpServers": {
    "aoms": {
      "command": "$PY",
      "args": ["-m", "aoms.adapters.mcp_server"],
      "env": {
        "PYTHONPATH": "$SRC",
        "AOMS_DATA_DIR": "$STORE",
        "AOMS_EMBEDDING_PROVIDER": "none",
        "AOMS_AGENT_ID": "claude-code-trial",
        "AOMS_WORKSPACE": "/trial"
      }
    }
  }
}
EOF

# Seed the incumbent through the same arm's application layer.
PYTHONPATH="$SRC" AOMS_DATA_DIR="$STORE" AOMS_EMBEDDING_PROVIDER=none \
  AOMS_AGENT_ID=seeder AOMS_WORKSPACE=/trial \
  "$PY" - <<'PYEOF'
import asyncio, os, sys
sys.path.insert(0, os.environ["PYTHONPATH"])
from aoms.application import AOMSApplication
from aoms.contracts import MemoryKind, RememberRequest, Scope, ScopeContext
from aoms.embeddings import NullProvider
from aoms.repositories import SQLiteMemoryRepository

async def main():
    repo = SQLiteMemoryRepository(os.environ["AOMS_DATA_DIR"] + "/aoms.sqlite3")
    app = AOMSApplication(repo, scope_context=ScopeContext(
        agent_id="claude-code-trial", workspace_id="/trial"),
        embedding_provider=NullProvider(), background_embeddings=False)
    await repo.initialize()
    await app.remember(RememberRequest(
        id="seed-staging-target", kind=MemoryKind.FACT,
        content="The staging environment deploys to Kubernetes cluster cluster-west-2.",
        scope=Scope.WORKSPACE, claim_key="staging-deploy-target"))
asyncio.run(main())
PYEOF

BASE="We finished migrating staging this morning. Staging no longer deploys to cluster-west-2; it now deploys to cluster-east-1. Nothing else about staging changed.

Make sure AOMS memory is correct for whoever picks this up next session."

SLOTS="$BASE

Our convention: every durable fact carries a claim_key naming the proposition it answers, so facts about the same thing share one key. Use the claim_key 'staging-deploy-target' for this."

if [ "$CONDITION" = "slots" ]; then TASK="$SLOTS"; else TASK="$BASE"; fi

cd "$STORE"
timeout 300 claude -p "$TASK" \
  --mcp-config "$CONFIG" \
  --strict-mcp-config \
  --allowedTools "mcp__aoms__recall,mcp__aoms__remember,mcp__aoms__search" \
  --permission-mode acceptEdits \
  > "$STORE/transcript.txt" 2>"$STORE/stderr.txt"
echo "exit=$?" > "$STORE/exit.txt"

# Report what actually landed.
"$PY" - "$STORE" <<'PYEOF'
import json, sqlite3, sys
store = sys.argv[1]
c = sqlite3.connect(f"{store}/aoms.sqlite3"); c.row_factory = sqlite3.Row
rows = [dict(r) for r in c.execute(
    "SELECT id, claim_key, contested, record_json FROM memories ORDER BY created_at")]
out = []
for r in rows:
    rec = json.loads(r["record_json"])
    out.append({"id": r["id"], "claim_key": r["claim_key"],
                "contested": r["contested"], "supersedes": rec.get("supersedes"),
                "content": rec.get("content")})
contests = c.execute("SELECT COUNT(*) FROM contest_entries").fetchone()[0]
c.close()
print(json.dumps({"records": out, "contest_entries": contests}, indent=2))
PYEOF
