# Remote streamable-HTTP authentication

AOMS uses locally managed bearer tokens for its streamable-HTTP transport. The
default stdio transport is unchanged and never requires a token.

## What a token's identity does not constrain

> **Read this before minting a token for a remote client.** A token's
> `workspace_id` binding does **not** bound what that token can read.

Each token is bound to one `agent_id` and one `workspace_id`, and the server
derives both from the token on every request. That binding constrains:

- **Writes** — `remember` attributes new records to the bound agent and workspace.
- **`agent-private` reads** — only records owned by the bound agent.
- **`workspace` reads** — only records in the bound workspace.

It does **not** constrain `user-global` reads. The visibility predicate applied
to every read (`SQLiteMemoryRepository._scope_access_filter`) is:

```sql
(
  scope = 'user-global'                                  OR
  (scope = 'workspace'      AND scope_workspace_id = ?)  OR
  (scope = 'agent-private'  AND scope_agent_id     = ?)
)
```

The first clause takes no parameter. **Every token reads every `user-global`
record in the store, whatever workspace it is bound to.** That is what
`user-global` means — deliberately fleet-wide — and it is working as designed.
But it means the practical read reach of any token is:

```text
all user-global records  +  one workspace  +  one agent
```

and the first term is decided by your data, not by the token you minted. A
token bound to a fresh, empty workspace is **not** a token with a small reach.
If most of your store is `user-global`, a "scoped" remote token has effectively
unrestricted read.

### Measure the reach of your own store

The number that matters is how much of your store is `user-global`. Read-only:

```console
sqlite3 "file:$HOME/.local/share/aoms/aoms.sqlite3?mode=ro" \
  "SELECT scope, COUNT(*) FROM memories GROUP BY scope;"
```

Adjust the path if `AOMS_DATA_DIR` is set. Whatever the `user-global` count is,
that is the floor on what any bearer token you mint can read — before adding
its workspace and its agent.

### If you need a bounded remote surface

Narrowing the token further does not help; the `user-global` clause is
unconditional. The only way to bound a remote client's reach to a set you
choose is to serve it a **different database**:

```console
AOMS_DATA_DIR=/srv/aoms-remote cortex-mem init
AOMS_DATA_DIR=/srv/aoms-remote cortex-mem token create remote-client --scope read
```

The token store lives in the same database as the memories it authorizes, so a
token minted there cannot address your canonical store at all. Seed that
database with only the records the remote client should see.

## Create and manage tokens

Initialize the store, then create a token bound to one agent and workspace:

```console
cortex-mem init
cortex-mem token create laptop-agent \
  --scope read --scope write \
  --agent-id laptop --workspace-id project-zephyr
```

The bearer secret is printed once. AOMS stores only a random salt and an
`scrypt` hash of its secret portion. `token list` displays non-secret metadata,
including status, scopes, identity, creation/last-use times, and expiry. Revoke
access with `cortex-mem token revoke TOKEN_ID`.

`read` authorizes `recall` and `search`; `write` authorizes `remember`. The
`admin` scope is reserved for future maintenance endpoints and currently grants
no model-facing operation. Token management itself remains a local CLI action,
protected by access to the AOMS data directory; there is no remote token-admin
endpoint.

## Run a remote listener

Non-loopback listeners require at least one active token and direct TLS:

```console
cortex-mem mcp --streamable-http \
  --host 0.0.0.0 --port 8443 \
  --tls-certfile /path/to/fullchain.pem \
  --tls-keyfile /path/to/private-key.pem \
  --allowed-host memory.example.com \
  --allowed-origin https://console.example.com
```

The client sends `Authorization: Bearer TOKEN`. AOMS derives `agent_id` and
`workspace_id` exclusively from that token on each authenticated request. Tool
schemas contain no identity fields, so a tool call cannot override its tenant.

Host and Origin checks are enabled for every HTTP listener. Requests without an
Origin header (normal for non-browser MCP clients) are accepted; any supplied
Origin must be explicitly allowed. Repeat `--allowed-host` and
`--allowed-origin` for multiple values. The corresponding environment settings
are `AOMS_MCP_ALLOWED_HOSTS` and `AOMS_MCP_ALLOWED_ORIGINS` as comma-separated
lists.

A loopback listener may run without tokens for local development and logs a
notice that authentication is disabled. If any active token exists, the HTTP
listener requires bearer authentication even on loopback.

## Limits

The default maximum POST body is 1 MiB. Configure it with
`--max-request-bytes` or `AOMS_MCP_MAX_REQUEST_BYTES`.

Authenticated tool calls use an in-process token bucket per token. Defaults are
10 calls/second with a burst of 20. Configure these with
`--rate-limit-per-second`, `--rate-limit-burst`,
`AOMS_MCP_RATE_LIMIT_PER_SECOND`, and `AOMS_MCP_RATE_LIMIT_BURST`. Bucket state
is intentionally process-local and resets on restart.
