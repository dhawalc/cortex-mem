# Codex: automatic memory instructions

Start in the project to bind and run the pinned installer:

```console
uvx --from git+https://github.com/dhawalc/cortex-mem@v2.0.0 cortex-mem setup codex
```

Setup registers the source-correct MCP server, binds the absolute workspace and
`agent=codex`, verifies a real MCP handshake and scoped recall, and prints the
materialized recipe directory. Append `AGENTS.md.snippet` from that directory
to the project's `AGENTS.md`. Codex loads it every session, so recall-at-start
and selective remember behavior travel with the repository.

Do not merge `config.toml` after setup: registration is already complete. The
materialized file is an inspectable record pointing at setup's private
`cortex-mem-bound` launcher. The checked-in `config.toml` is only an unbound
packaging template.
