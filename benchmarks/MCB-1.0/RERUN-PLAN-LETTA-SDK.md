# Re-run plan — MCB-1.0 against the Letta Agent SDK

> # ⚠ SUPERSEDED — 2026-08-25
>
> **This plan is superseded, not pending.** It is preserved unedited below as the
> record of what we intended to do; it must not be read as scheduled work, and
> its premise is void.
>
> The plan's purpose was to make the AOMS-vs-Letta comparison citable by fixing
> two defects in one run: the deprecated target and the model confound. On
> 2026-08-25 a bare-model control was run — the frozen corpus fed straight to
> `ollama/qwen3:8b` with the Letta adapter's own persona and two local function
> stubs, no memory framework of any kind in the stack — and it reproduced the
> published Letta V1 per-case result on 46 of 48 cases. The framework's measured
> contribution on this corpus is indistinguishable from zero.
>
> That does not correct the comparison. It removes the thing the comparison was
> measuring. **The cross-system comparison has been retired**, so there is no
> longer a comparison for this plan to repair. See [`CORRECTIONS.md`](CORRECTIONS.md)
> entry #2 and [`adapters/null-ollama/`](adapters/null-ollama/).
>
> Three specific claims in the text below are now known to be false, and are
> listed here rather than edited out:
>
> - **"Status: PLAN ONLY. NOT EXECUTED."** — false in this repository from the
>   moment `adapters/letta-code/` was written. Six 48-case letta-code runs exist
>   here as untracked artifacts with no write-up. They are not cited anywhere and
>   must not be until they are published under [`GOVERNANCE.md`](GOVERNANCE.md)
>   §11, each with the §10 bare-model control the rule now requires.
> - **"A frontier model is needed"** and the $30–100 costing in §7. The decisive
>   experiment needed no frontier model, no hosted API and no budget. It needed
>   the framework removed instead of the model upgraded. Money was never the
>   binding constraint; asking the wrong question was.
> - **Any statement that executing this plan would make a Letta figure citable.**
>   Under §10 a model-driven adapter's result is publishable only alongside its
>   own bare-model control, and only as *(framework score − control score)*. A
>   re-run of this design without that control would reproduce the original error
>   against a newer target.
>
> **What is still worth keeping** is §1–§6: the reading of what current Letta
> actually is, the durable-state question, and the six open questions for Sarah
> Wooders. Those survive because they are about identifying the target, which is
> a problem this correction does not touch. Any future Letta measurement starts
> there and adds a control.

**Status: PLAN ONLY. NOT EXECUTED. No adapter has been written and no case has
been run.** Everything below is desk research against public documentation and
published package source. Nothing here has been tested against a running system.

This plan exists because of the correction logged in [`CORRECTIONS.md`](CORRECTIONS.md):
the published Letta results measured PyPI `letta` 0.16.8, the retired V1 server,
after Sarah Wooders of Letta told us that repository is deprecated and pointed us
at the Agent SDK and letta-code.

The plan is scoped to fix **both** defects in the published comparison in a
single run: the deprecated target *and* the model confound. Fixing only one still
leaves an invalid comparison.

---

## 1. What the current target actually is

Read from `docs.letta.com` and from the published packages.

| | |
| --- | --- |
| Agent SDK | `@letta-ai/letta-agent-sdk`, **npm, TypeScript/Node only**, `0.7.5` at time of writing, Apache-2.0, requires Node ≥ 22.19.0 |
| Harness | `@letta-ai/letta-code`, `0.30.31`, Apache-2.0 — both a CLI and a library |
| REST client | `@letta-ai/letta-client` `1.12.1` (npm **and** PyPI) |
| Relationship | The SDK depends on letta-code at an exact pin (`0.30.28` in SDK 0.7.5) and resolves the `letta` binary at runtime. **The Agent SDK is a programmatic wrapper that drives the letta-code harness over a WebSocket.** The docs do not state this; it is read from the SDK's `package.json` and `src/cli-resolver.ts`. |

**There is no Python Agent SDK.** `letta-agent-sdk` and `letta-code` do not exist
on PyPI. PyPI `letta-client` gives only the cloud REST surface, not the harness.
This is the single largest structural consequence for us — see §4.

Three backends (`docs.letta.com/agent-sdk/deployment`):

- `backend: "cloud"` — api.letta.com, needs `LETTA_API_KEY`, state in Letta Cloud.
- `backend: "local"` — **no account, no API key**; the SDK spawns a local App
  Server subprocess and all state lives on disk. **This is the one we want.**
- `backend: "remote"` — your own App Server (`letta server --listen`) over WebSocket.

Deprecation confirmed independently: `letta-ai/letta`'s README now calls itself
"a landing page for the Letta project" and says the V1 server source is preserved
on the `archive` branch; PyPI `letta` has shipped nothing since 2026-05-14.

## 2. The durable-state equivalent — this is the real change

**Core memory blocks are no longer the default storage primitive. The primitive
is MemFS: a git repository projected onto the agent's filesystem at `$MEMORY_DIR`.**

```
$MEMORY_DIR/
├── system/          # loaded into the system prompt EVERY turn  ← in-context durable state
│   ├── persona.md
│   └── human.md
├── reference/       # out of context; only the tree + descriptions are in prompt
└── skills/
```

Files are markdown with YAML frontmatter. **Every memory edit is committed to
git**, authored as `<agent_id>@letta.com`, with the agent's stated reason as the
commit message.

Consequences for MCB:

- **The core-vs-archival distinction is gone.** The V1 run had to choose between
  two stores and justify it at length; that choice does not exist here. The new
  split is `system/` (in-context) versus everything else (out-of-context but
  navigable). MCB's "logical current durable state" maps most naturally onto
  `system/`, but this is a judgement call of exactly the kind that produced the
  last error, so it is question Q2 in §6 rather than a decision made here.
- **A "block" is now a file.** The vocabulary survives — letta-code's own docs
  call `system/human/prefs/coding.md` a block — but the storage is filesystem
  and git, not database rows.
- **`SPEC.md`'s durable-state definition is satisfiable.** MCB requires obsolete
  statements to *cease to be current*, and the file-based memory tool has genuine
  replace and delete. The structural argument that forced core memory in V1 does
  not force anything here; both in-context and out-of-context files support the
  full transition set.
- **Legacy block mode may still be reachable.** `CreateAgentOptions` has
  `memfs?: boolean` (default `true`) and deprecated `memory`/`persona`/`human`
  fields. But `src/agent/create.ts` carries a comment that subagents are "the
  ONLY supported way to create a non-memfs agent on a memfs-capable backend;
  there is no user-facing opt-out," which contradicts the public option. **Do not
  plan around legacy mode.** Benchmarking a deprecated code path inside the
  current product would repeat this correction's exact mistake.

## 3. Programmatic readback

MCB scores only programmatic durable-state readback, never model-generated text.
Three candidate paths, in preference order.

**(a) Read the files off disk — preferred.**
`await session.getDeviceStatus()` returns `memoryDirectory` ("Agent memory
checkout on the computer executing this session", typed `string | null`). On the
local backend this is a real directory; parse the markdown. No network, fully
deterministic, and **the git log is a free bonus** — every write carries the
agent's own stated `reason`, which is strictly richer evidence than the V1 block
diff. Local state lives under `<storageDir>/memfs/<agentId>/memory`, with
`storageDir` defaulting to `~/.letta/lc-local-backend` and overridable via
`LETTA_LOCAL_BACKEND_DIR`.

**(b) CLI export.** `letta memory export --agent <id> --out <dir>` (alongside
`memory status|diff|pull|tokens`). Deterministic and scriptable. Unverified
against local-backend agents — the documented example is a cloud agent (Q3).

**(c) The V1 block endpoint still exists.** `letta-client` 1.12.1 still ships
`GET /v1/agents/{agent_id}/core-memory/blocks/{block_label}` — literally the old
`client.agents.blocks.retrieve` call — and letta-code's own bundled tooling still
curls the list form. **But it is unconfirmed whether a MemFS agent's `system/*.md`
files surface through it.** What is confirmed is that memfs agents carry a
read-only `memory_filesystem` block rendering the directory *tree*. Path (c) is a
fallback, not a plan.

## 4. What the adapter's four operations map onto

MCB's contract is four framework-neutral operations. Current mapping, with
confidence marked.

| MCB operation | Letta Agent SDK | Confidence |
| --- | --- | --- |
| **1. Establish durable state** from `{topic, text}` list | Write `system/*.md` files into a fresh `MEMORY_DIR` before the session starts, one statement per line or per file | Plausible, untested. Whether pre-seeding files out-of-band is respected, or whether seeding must go through the agent, is **Q1** |
| **2. Deliver one observation** | `client.prompt(message, agentId, opts)` — the SDK's own type describes it as a "One-shot convenience for scripts, smoke tests, and **evals**" | High. This is close to purpose-built for us |
| **3. System performs its normal write-side processing** | Built-in `memory` tool, invoked by the agent | High — see below |
| **4. Retrieve current durable state** | `getDeviceStatus().memoryDirectory` + parse markdown | High, path (a) above |
| **Isolation / teardown** | `client.agents.delete(agentId)`, plus per-case `LETTA_LOCAL_BACKEND_DIR` and per-session `env` scoping of `MEMORY_DIR` | High |

**Operation 3 maps almost too neatly.** The V1 pair `memory_insert` /
`memory_replace` has been consolidated into one stock tool named `memory` whose
`command` argument *is* the state transition:

```ts
type MemoryCommand = "str_replace" | "insert" | "delete" | "rename"
                   | "update_description" | "create";
```

It is built-in, it auto-commits to git, and its required `reason` argument
becomes the commit message. MCB's four transitions map directly:
`extend` → `insert`/`create`, `revise` → `str_replace`, `reject` → the agent not
calling the tool, `preserve` → likewise. As in V1, **the adapter must make no
write decision of its own** — it delivers the observation and records whatever
the agent chose.

One mechanic to respect: `MEMORY_TOOL_NAMES` (`memory`, `memory_apply_patch`,
`memory_insert`, `memory_replace`, `memory_rethink`) are **all detached when
memfs is enabled**, replaced by the client-side filesystem `memory` tool. The old
tool names still exist server-side for non-memfs agents. An adapter that looks for
`memory_insert` on a current agent will find nothing.

**Isolation** is well supported: `client.agents` exposes `list`, `retrieve`,
`update`, and `delete`; session options include an `env` field documented as
scoping `MEMORY_DIR` per session; and `filesystemConfinement: "memory"` confines
the harness to the memory root. No PostgreSQL is involved any more — the V1 run's
disposable Postgres cluster has no equivalent and is not needed.

**The adapter language problem.** MCB's adapter contract is a Python module
exposing `create(config, run_dir) -> object`. There is no Python Agent SDK. Three
options, in preference order:

1. **Python adapter shelling out to a Node driver script.** Keeps the MCB
   contract unchanged; the Node script is a thin per-operation CLI. Recommended —
   smallest change to frozen infrastructure.
2. Python adapter driving the App Server WebSocket directly. Most control, most
   protocol risk, and the protocol is not publicly documented.
3. Extend MCB to accept TypeScript adapters. Cleanest long-term, but it changes
   the benchmark's own contract, which is a governance change and should not ride
   along with a correction.

## 5. Resolving the model confound in the same run

**Yes, and it should be considered mandatory, not optional.**

The SDK supports 40+ providers with BYO keys on every plan, including
**first-class Ollama and LM Studio entries** plus a generic `openai-compatible`
provider. Model is set at `client.createAgent({ model })` and swappable at
runtime via `session.updateModel()`. So a **model ladder is directly
expressible**: run the identical adapter and identical frozen corpus across
several models and publish the slope of score against model capability.

Recommended ladder: `qwen3:8b` (the exact V1 model, so the two runs share one
comparable point) → a mid-tier hosted model → a frontier model. That yields
something the V1 run could not: separation of architecture from model capability,
which is the outstanding gap already named as a live confound in the published
write-ups.

**A frontier model is needed — and the answer is yes, for two independent reasons.**

1. **To resolve the confound at all.** AOMS's deterministic write path was
   measured against qwen3:8b's judgement. Only a frontier point on the ladder
   establishes whether Letta's architectural advantage survives when model
   quality stops being the variable — which is the whole question.
2. **Because Letta's own docs say weak models misbehave.** The configuration
   docs recommend frontier models for first-time users and warn that "weaker
   models can cause the agent to behave in unexpected ways." A benchmark run on a
   model the vendor warns against is not a fair reading of the system, and the
   V1 run has exactly that weakness.

**Constraint:** provider tests assert Ollama is **local-backend-only**; a cloud
agent needs a publicly reachable endpoint. So the qwen3:8b rung must run on
`backend: "local"`. If frontier rungs use hosted models with BYO keys, they can
also run locally — but *whether the local backend and cloud backend produce
comparable agent behaviour is unverified* (Q4). Running the entire ladder on one
backend is strongly preferred; mixing backends would introduce a third confound
while fixing two.

## 6. What is unknown and must be confirmed with the maintainer

These are the questions to put to Sarah Wooders **before** writing the adapter.
Asking rather than inferring is the specific step whose absence caused this
correction.

- **Q1 — Seeding.** Is writing `system/*.md` files directly into a fresh
  `MEMORY_DIR` a legitimate way to establish an agent's starting durable state,
  or must seeding go through the agent? MCB needs a known, exact starting state.
- **Q2 — Scored surface.** Which part of MemFS is "the agent's current durable
  memory" for evaluation purposes — `system/` only, or the whole repository
  including `reference/`? **This is the direct successor to the core-vs-archival
  choice, and in V1 that choice moved the headline number from 27% to 75%.** It
  must be Letta's call, not ours.
- **Q3 — Readback.** Is parsing the memory checkout the right programmatic
  readback? Does `letta memory export` work against local-backend agents? Do a
  MemFS agent's `system/*.md` files surface through
  `/v1/agents/{id}/core-memory/blocks`, or only the `memory_filesystem` tree block?
- **Q4 — Backend equivalence.** Do `backend: "local"` and `backend: "cloud"`
  produce equivalent agent behaviour, such that a ladder split across them would
  be comparable? (Preference is to avoid needing this.)
- **Q5 — Canonical configuration.** There are at least four system-prompt presets
  (`letta.md`, `letta_local_memfs.md`, `letta_no_memfs.md`, and `source_claude.md`
  which the repo explicitly labels "for benchmarking"). **Which configuration
  does Letta consider canonical for an evaluation like this?** Picking wrongly
  makes results non-comparable and would be a fresh version of the same error.
- **Q6 — Version pin.** Which exact `@letta-ai/letta-agent-sdk` and
  `@letta-ai/letta-code` versions should be pinned? Release cadence is very fast
  — the SDK shipped 0.7.1 through 0.7.5 between 12 and 24 August 2026 — so
  reproducibility requires an exact pin and a recorded date. This is also where
  MCB-1.1 governance should require a positive currency statement.

Beyond these: **offer Letta the chance to write or ratify the adapter.**
The published limitations already concede that the V1 numbers are "this
adapter's numbers for Letta, not Letta's numbers," because a competitor wrote
the adapter.
A re-run is the natural moment to fix that too.

## 7. Cost

**Letta-side cost can be zero.** `backend: "local"` needs no account and no API
key. Pricing (`docs.letta.com/letta-code/pricing`) matters only if we go cloud:
free tier allows 3 stateful agents — **which makes per-case fresh agents
impossible**, so the free tier cannot run MCB at all; the API plan is $20/mo base
+ $0.10 per active agent per month + $0.00015/sec tool execution + pay-as-you-go
LLM, or BYOK. A 48-agent cloud run would be roughly $20 + $4.80 ≈ **$25/month
plus tokens**.

**Model tokens are the real cost, and this figure is an estimate, not a quote.** A
MemFS agent carries a heavy system prompt (memory tree plus all `system/` files
plus tool schemas), so a multi-step episode plausibly runs tens of thousands of
input tokens per turn. 48 cases lands in the low single-digit millions of input
tokens per rung: order **$5–20 on a Sonnet-class model** and several times that
on an Opus-class one. A three-rung ladder is therefore roughly **$30–100 total**,
with the qwen3:8b rung free.

**Compute and time.** The local backend needs Node ≥ 22.19.0 and disk for
per-agent git checkouts; no PostgreSQL. The V1 core-memory run took 1014 s of
wall clock for 48 cases on local qwen3:8b. Hosted rungs should be faster per
step but involve network round-trips; budget an hour per rung and treat that as
unvalidated.

**Effort, not money, is the binding constraint.** The adapter must be rewritten
from scratch — different language, different memory model, different readback —
and the V1 adapter is not a starting point beyond its operation structure.
Realistically several days of work, and it should not begin until Q1, Q2 and Q5
have answers.

## 8. Sequence

1. Send Q1–Q6 to Sarah Wooders; offer Letta adapter authorship or ratification.
2. On answers, pin versions and write the Node driver + Python adapter shim.
3. Commit adapter and configuration **before** any frozen case runs — same
   discipline as V1, which held and is not what failed.
4. Debug against synthetic statements that appear nowhere in the frozen corpus —
   same discipline as V1.
5. Run the ladder. Publish the first configured run per rung, unadjusted.
6. Publish as a **new** result file. `RESULTS-LETTA.md` is not edited; it stays
   as the V1 historical record with its correction banner. Add the outcome to
   `CORRECTIONS.md` and close that entry.
7. Fold the currency-verification requirement into MCB-1.1 governance (the
   standalone `mcb-benchmark` distribution carries the governance text).

---

**Reminder on citation.** Until this plan is executed, no Letta figure in this
repository may be cited as a measurement of Letta's current system. See
[`CORRECTIONS.md`](CORRECTIONS.md).
