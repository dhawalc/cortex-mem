# Remote streamable-HTTP authentication

AOMS uses locally managed bearer tokens for its streamable-HTTP transport. The
default stdio transport is unchanged and never requires a token.

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
