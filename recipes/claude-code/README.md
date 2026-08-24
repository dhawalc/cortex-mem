# Claude Code: automatic AOMS memory

Start in the project to bind and run the pinned installer:

```console
uvx --from git+https://github.com/dhawalc/cortex-mem@v2.0.0 cortex-mem setup claude
```

Setup registers AOMS at Claude's local project scope, binds the absolute
workspace and `agent=claude`, verifies a real MCP handshake and scoped recall,
and prints the materialized recipe directory. Use the files from that printed
directory, not the unbound templates in a source checkout.

Install `jq`, then merge the materialized `hooks.json` into
`.claude/settings.json`. If that file already contains hooks, merge the
`SessionStart` array instead of replacing it. Append the materialized
`CLAUDE.md.snippet` to the project's `CLAUDE.md`.

The hook calls the private `cortex-mem-bound` launcher created by setup, so it
uses the same pinned source, agent, workspace, and store that passed activation.
Start a new Claude Code session and run with debug logging if the hook does not
appear:

```sh
claude --debug
```

The hook intentionally exits quietly when recall is unavailable, so a memory
outage cannot prevent a session from starting.

## Hook contract source

Source: [Claude Code hooks reference](https://code.claude.com/docs/en/hooks#sessionstart),
accessed 2026-08-23. The reference says `SessionStart` runs when a session
starts or resumes and that structured output must put a string at
`hookSpecificOutput.additionalContext`, with
`hookSpecificOutput.hookEventName` set to `SessionStart`. Claude adds that
string before the first prompt. It also says stdout that begins with `{` is
parsed as JSON and stdout must contain only the JSON object. The template uses
`jq -nc` so quotes, backslashes, and newlines in recalled memory are escaped
correctly.
