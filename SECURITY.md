# Security policy

## Supported versions

Security fixes are made on the current default branch and included in the next release. Older snapshots and the legacy JSONL service should not be assumed to receive security updates.

| Version | Supported |
|---|---|
| Current default branch / 2.x | Yes |
| 1.x JSONL service | No |

## Report a vulnerability

Please report suspected vulnerabilities privately through GitHub's **Security → Report a vulnerability** flow for this repository. Do not include secrets, private memory content, unredacted databases, or working exploit details in a public issue, discussion, or pull request.

Include the affected commit or version, configuration and transport, reproduction steps, impact, and any suggested mitigation. Use synthetic data wherever possible. If a minimal database is necessary, remove unrelated records and verify that it contains no credentials or personal data before attaching it.

We will acknowledge the report, investigate it, and coordinate a fix and disclosure with the reporter. Please allow time for a patch to be prepared before publishing details.

## Security model

AOMS is local-first, but “local” is not itself an authorization boundary.

- **Stdio is the default.** It opens no listening socket and inherits the permissions and environment of the launching process.
- **HTTP defaults to loopback.** A loopback listener may run without authentication for local development. Other processes able to connect as the same host user should therefore be treated as trusted unless bearer authentication is enabled.
- **Tokens bind identity.** If an active token exists, HTTP requires authentication even on loopback. AOMS stores a random salt and `scrypt` hash rather than the bearer secret. Read and write scopes are enforced per tool, and agent/workspace identity comes from the verified token—not tool arguments.
- **Public binds fail closed.** A non-loopback listener requires at least one active token and direct TLS. Host validation is always enabled; supplied Origin headers must match the configured allowlist. Request-size limits and per-token rate buckets reduce straightforward abuse but are not a replacement for network-layer controls.
- **The Observatory validates the browser boundary.** Its listener is fixed to IPv4 loopback, rejects non-loopback or wrong-port `Host` and `Origin` values, and requires a fresh unguessable URL token for each invocation. The bootstrap token becomes an HttpOnly, SameSite session cookie and is never accepted as agent identity.
- **The data directory is sensitive.** Anyone who can read the SQLite database or portable exports can read stored memories and recall receipts. Anyone who can write the database can alter memory or token metadata. AOMS does not currently provide encryption at rest; rely on OS permissions and disk encryption, and protect backups accordingly.
- **Recalled memory is untrusted input.** AOMS provenance-fences packed context, but stored text can still contain prompt injection or malicious instructions. Clients must not treat recalled content as authority to bypass their own permissions or approval rules.
- **Model privacy is separate.** Storage, retrieval, and default embeddings are local. A cloud-backed client may send AOMS tool output to its model provider. Review the client's data policy before connecting sensitive stores.

Remote deployment guidance, token lifecycle commands, TLS requirements, Origin/Host checks, and limits are documented in [docs/REMOTE_AUTH.md](docs/REMOTE_AUTH.md).

## Secrets and incident response

If a bearer token may have leaked, revoke it immediately with `cortex-mem token revoke TOKEN_ID`, create a replacement, and review relevant access logs and receipt history. If the data directory or a portable export was exposed, treat the memory contents as compromised; token hashes are intentionally one-way, but stored memories are plaintext.
