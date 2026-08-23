# Claude Code: automatic AOMS memory

Install the MCP server at user scope:

```sh
claude mcp add --scope user aoms -- uvx cortex-mem mcp
```

Install `jq`, then merge `hooks.json` into `~/.claude/settings.json` (or into
`.claude/settings.json` for project scope). If that file already contains hooks,
merge the `SessionStart` array instead of replacing it. The command binds
`AOMS_AGENT_ID=claude-code` and uses `CLAUDE_PROJECT_DIR` as `AOMS_WORKSPACE`.

Append `CLAUDE.md.snippet` to the project's `CLAUDE.md`. Start a new Claude Code
session and run with debug logging if the hook does not appear:

```sh
claude --debug
```

The hook intentionally exits quietly when recall is unavailable, so a memory
outage cannot prevent a session from starting.

## Hook contract source

Source: [Claude Code hooks reference](https://code.claude.com/docs/en/hooks#sessionstart),
accessed 2026-08-23. The reference says `SessionStart` runs when a session starts
or resumes and that structured output must put a string at
`hookSpecificOutput.additionalContext`, with
`hookSpecificOutput.hookEventName` set to `SessionStart`. Claude adds that string
before the first prompt. It also says stdout that begins with `{` is parsed as
JSON and stdout must contain only the JSON object. The template uses `jq -nc` so
quotes, backslashes, and newlines in recalled memory are escaped correctly.
