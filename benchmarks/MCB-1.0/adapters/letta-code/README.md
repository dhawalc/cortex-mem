# MCB-1.0 adapter — Letta Code (MemFS), local backend

This adapter measures `@letta-ai/letta-code` 0.30.31 driven through its shipped
`letta` CLI with `--backend local`. It is a different system from the one behind
`adapters/letta/`, which measured the Letta **server** 0.16.8 and its core-memory
blocks. Neither supersedes the other; both stay published.

Read `CURRENCY.md` before quoting any number produced here. In particular: the
execution mode is gated behind `LETTA_LOCAL_BACKEND_EXPERIMENTAL`, and no vendor
ratification has been obtained, so results carry the *unratified execution mode*
qualifier in their title rather than in a footnote.

## Durable state

Letta Code's memory is MemFS — a git-backed filesystem projection, one repo per
agent, at `$LETTA_LOCAL_BACKEND_DIR/memfs/<agent-id>/memory`.

Durable state under test is **the working tree of that repository at the single
allowlisted path `system/mcb-state.md`**. `system/persona.md` and
`system/human.md` are excluded — they are the harness's identity files, not
state under test.

The justification a maintainer should be able to accept: MemFS *is* the memory;
the working tree is current state and the commit log is its history. An obsolete
line that is edited away has genuinely ceased to be current, which is what
SPEC.md asks the benchmark to detect. History surfaces (`memory_history`,
`memory_file_at_ref`) are never read for scoring — otherwise nothing could ever
be superseded and every `revise` case would be unwinnable by construction.

The adapter records the commit log and the `letta memory status` dirty flag
after every turn without scoring them, so a reader who prefers strict
"committed-only" semantics can re-derive that reading from the transcripts
rather than having to re-run anything.

## Operation mapping

| MCB operation | Implementation |
|---|---|
| `create` | `letta --backend local agents create --personality blank`, then write `system/persona.md` and commit |
| `establish_durable_state` | write `system/mcb-state.md` (frontmatter fence + `TOPIC :: TEXT` lines), `git commit`, read back and assert equality |
| `provide_observation` | buffered in the adapter; nothing is sent |
| `process` | `letta --backend local -p <message> --agent <id> -m <handle> --yolo --output-format json`, then poll `letta memory status` until `dirty` is false |
| `retrieve_durable_state` | `letta memory export --out <fresh dir>`, strip the frontmatter fence, split each line on the first ` :: ` |

`establish_durable_state` writing the file directly is an application-layer
*setup* operation under SPEC.md line 124, not a write decision. Letta Code's own
system prompt sanctions the path explicitly ("Direct file edits (full
control)"). Every add / replace / delete / no-op decision under test is made by
the agent itself during `process`.

There is deliberately **no recovery branch**: if the agent renames or deletes
the allowlisted file, the adapter returns empty state and lets the scorer
classify the outcome.

## Isolation

Each case gets a private `HOME` and a private `LETTA_LOCAL_BACKEND_DIR` inside
its own run directory, so no case can observe another case's agents, settings,
conversations or memory. The subprocess environment is scrubbed of every
`*_API_KEY` and `*_TOKEN` before the CLI is launched.

## What the latency clock covers

The runner starts the clock at `establish_durable_state` and stops it after
`retrieve_durable_state`. It therefore covers: writing and committing the state
file, the full CLI turn (process spawn, model inference, tool execution, memory
commit), the settle poll, and the export. It does **not** cover agent creation
or persona installation, which happen in `create` before the clock starts.

These numbers are not comparable to `adapters/letta/`'s latencies: that adapter
made in-process HTTP calls to an already-running server, whereas this one pays
Node process startup and full agent-context compilation on every case.

## Reproducing

```
python runner.py \
  --adapter adapters/letta-code/adapter.py \
  --config  adapters/letta-code/config.json \
  --output  results-letta-code-<model>-run<N>.json \
  --run-dir <scratch>/letta-code-<model>-run<N>
```

`runner.py` verifies the freeze manifest on every run and there is no override
path through it. The freeze was verified before and after every published run;
the hashes are recorded in `PREREGISTRATION-LETTA-CODE.md`.
