# MCB-1.0 adapter — Letta

This adapter executes the frozen MCB-1.0 case set against
[Letta](https://github.com/letta-ai/letta), an independent open-source agent
memory framework with no affiliation to AOMS or to this benchmark's author.

The adapter is a portability test of MCB-1.0 as much as it is a measurement of
Letta. Nothing in `benchmarks/MCB-1.0/` outside this directory was modified,
and the frozen `cases.json` / `score.py` hashes in `FREEZE-MANIFEST.json` are
unchanged.

## What the adapter does, and what it deliberately does not do

The adapter implements exactly the four MCB operations from `SPEC.md` and holds
no benchmark knowledge:

| MCB operation | Letta call |
| --- | --- |
| Establish durable state | `client.agents.blocks.update(label, agent_id=…, value=…)` (primary) or `client.agents.passages.create(agent_id, text=…)` (secondary) |
| Provide a subsequent observation | buffered; no call |
| Allow the system to process it | `client.agents.messages.create(agent_id, input=…, max_steps=8)` |
| Retrieve resulting durable state | `client.agents.blocks.retrieve(label, agent_id=…)` (primary) or `client.agents.passages.list(agent_id)` (secondary) |

It does not read `cases.json`, does not receive `mode`, `relationship`, `tags`,
or any `expected` field, and never branches on the content of an observation.
There is no instruction-marker matching, no conflict detection, no authority or
freshness heuristic, and no pass/fail or class reporting. Every decision to add,
replace, delete, or do nothing is made by the Letta agent when it processes the
observation, using Letta's own stock memory tools.

This is a stronger separation than the AOMS reference adapter has. That adapter
matches configured instruction markers in the observation text and chooses
between `remember` and `supersede` itself, which `SPEC.md` permits as
"translating an explicit INSTRUCTED operation into the system's documented write
primitive". The Letta adapter needs no such branch, because Letta's write
primitive is an LLM agent.

## Translation policy

MCB exchanges state as `{"topic": …, "text": …}` pairs. Letta has no native
topic key, so the adapter serialises each statement as one line:

```
TOPIC :: STATEMENT
```

The same form is used in both directions. This is the adapter's entire
representation logic, and it was fixed before any frozen case ran (commit
`7edb3d1`).

**Parsing back.** Split the stored value on newlines; drop blank lines; strip
surrounding whitespace and at most one leading list marker (`- `, `* `, `+ `,
`• `); split on the first ` :: `; the left side is the topic and the right side
is the text. Exactly identical pairs are collapsed. Two different texts under
one topic are **both** returned, because that is the durable state the system
actually holds — the scorer is what decides that this is a `conflict-retained`
failure, not the adapter. A line with no separator cannot be expressed as a
topic/text pair, so it is surfaced verbatim under a unique `<unparsed-N>` topic
rather than silently discarded.

No text of the corpus contains `::` or a newline, so the separator is
unambiguous over the frozen case set.

**The agent is told the storage schema, not the answer.** The persona block in
`config.json` states the line format, states that a topic appears on at most one
line, and lists the memory edits available to it. That is the same data model
the scorer uses and the same one AOMS's supersession primitive encodes
structurally. It tells the agent nothing about which statements to keep, replace,
or reject. Readers should nevertheless treat the uniqueness sentence as a
translation choice that is generous to Letta: without it, an agent that appends
every observation would score `conflict-retained` on contradiction cases for a
formatting reason rather than a judgement reason.

**Exact text is supplied; the decision is not.** The observation message is the
case's verbatim `observation.text`, followed by the canonical lines for
`observation.statements`. The agent is instructed to copy a line character for
character *if* it decides to record it. Without this, MCB's exact-match scoring
would measure an 8B model's ability to reproduce a sentence verbatim rather than
its write-side decisions. AOMS's adapter likewise writes `statements` verbatim.
The template is a constant; it is identical for every case and every mode.

## Which store counts as durable state

Letta has two memory targets, and `SPEC.md` does not disambiguate them for a
foreign architecture. This adapter supports both, selected only by the
`durable_state_target` config key.

**Primary: core memory blocks** (`config.json`). `SPEC.md` defines the unit under
test as "the logical current durable statements, excluding merely
historical/inactive versions", and requires that obsolete statements *cease to
be current*. Core memory blocks are the only Letta store where that transition
is expressible: `memory_replace` removes an exact string and puts another in its
place. They are also the store Letta's own documentation describes as the
agent's persistent, self-edited memory of the world. Archival memory has
`archival_memory_insert` and `archival_memory_search` and no delete or replace
primitive at all, so `revise` and `reject` outcomes are unrepresentable there by
construction. Core memory is therefore the honest target for a write-side state
transition benchmark.

**Secondary: archival passages** (`config-archival.json`), reported so the choice
is transparent rather than convenient. See `RESULTS-LETTA.md`.

## Running it

Prerequisites are the prepared environment in `/tmp/letta-probe`: an isolated
PostgreSQL 16 cluster on 127.0.0.1:15432, the patched Letta venv, and Ollama
serving `qwen3:8b` and `nomic-embed-text`. See `environment.txt` here and
`/tmp/letta-probe/REPRODUCE.md`.

```sh
/tmp/letta-probe/start-postgres.sh &
/tmp/letta-probe/run-server.sh &

cd benchmarks/MCB-1.0
/tmp/letta-probe/venv/bin/python runner.py \
  --adapter adapters/letta/adapter.py \
  --config  adapters/letta/config.json \
  --output  adapters/letta/results.json \
  --run-dir /tmp/mcb-letta-core
```

`runner.py` itself is stdlib-only but must run in the venv that provides
`letta_client`. Each case writes a `letta-transcript.json` into its own
directory under `--run-dir` containing the created agent id, the attached tool
list, the exact message sent, the full agent response including every tool call,
and the raw stored value read back. That transcript is the evidence that the
adapter made no write decision.

## Configuration

`config.json` is the primary (core memory) configuration and `config-archival.json`
the secondary. Both pin the model handles, the loopback server URL, `max_steps`,
`enable_sleeptime: false`, the separator, the persona text, and the observation
preamble. The adapter refuses a non-loopback `base_url`.

`embedding_config_override` in the archival config applies the probe's
documented Ollama workaround: the stock handle posts to `/embeddings` and gets
404, while the OpenAI-compatible `/v1` route works. It is supplied by config and
never inferred by the adapter.
