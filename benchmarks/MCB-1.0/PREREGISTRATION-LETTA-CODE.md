# PRE-REGISTRATION — Letta Code (MemFS) on MCB-1.0

**Status: committed before case 1 of the first scored run.** The commit that
introduces this file is a git ancestor of every commit that publishes a result
produced under it. If it is not, the results are void and must be published as
an abandoned attempt.

This document exists because the previous Letta measurement in this repository
was wrong in a way that no amount of care *during* analysis could have caught:
the analysis was free to move after the numbers were known. Everything below is
fixed now, while the outcome is still unknown.

---

## 1. System under test

| Item | Value |
|---|---|
| Package | `@letta-ai/letta-code@0.30.31` |
| npm `dist.shasum` | `35f23ddadee69cb91b60aa1866a8624cbd3016a9` |
| npm `dist.integrity` | `sha512-Y7lWbN3W0uwBowVARpafWAfCa55IYJLjwCAfRzcuosyfUbbA1lWNBzY+Hzj1Lf794d6AmCj5vLzOgp9JJKJz8Q==` |
| Local tarball sha256 | `c09fdd95f411aa6bae9b0fcd7854004faa434d932f08c44cb45df13c9f85c609` |
| Install prefix | `/home/dhawal/cortex-mem/letta-code-pin` |
| `letta --version` | `0.30.31 (Letta Code)` |
| Node | v25.8.2 |
| npm | 11.11.1 |
| Autoupdater | disabled (`DISABLE_AUTOUPDATER=1`) |
| Execution mode | `--backend local`, gated by `LETTA_LOCAL_BACKEND_EXPERIMENTAL=1` |
| Inference | Ollama at `http://127.0.0.1:11434`, fully local |
| Host | Linux blacklightning 6.8.0-136-generic, Ubuntu 24.04.4 LTS |
| Harness interpreter | CPython 3.12 at `/home/dhawal/cortex-mem/cortex-mem/.venv/bin/python` |

This is a **different system** from `adapters/letta/` (Letta *server* 0.16.8,
core memory blocks). Neither result supersedes the other. Both stay published.

## 2. Durable state, and whether Letta ratified it

Durable state under test is **the working tree of the agent's MemFS git
repository at the single allowlisted path `system/mcb-state.md`**.
`system/persona.md` and `system/human.md` are excluded as harness identity
files. History surfaces (`memory_history`, `memory_file_at_ref`) are never read
for scoring; if they were, no statement could ever become non-current and every
`revise` case would be unwinnable by construction.

**Letta has not ratified this definition. Letta has not been asked.** Four
gating questions were identified — whether the experimental local backend is a
fair target, which MemFS surface counts as durable, whether an obsolete
statement can be made non-current there, and whether Letta would veto this
adapter — and none has a vendor answer. Sending that outreach was outside the
authority of the run that produced this file.

The consequence is fixed here, in advance, and is not negotiable after the
numbers are seen:

> **Every result produced under this pre-registration is titled as measuring an
> unratified, vendor-gated experimental execution mode.** Not "Letta Code's
> score" — the score of one unratified configuration of one experimental
> backend, chosen by a competitor.

The commit log and the `letta memory status` dirty flag are recorded after every
turn but are **not** scored, so a reader who prefers strict committed-only
semantics can re-derive that reading from the transcripts without a re-run.

## 3. Boundary, isolation, and the latency clock

**Python/CLI boundary.** The adapter is a Python subprocess driver. It performs
exactly the four MCB operations and drives the shipped `letta` CLI. It contains
no case inspection, no expectation awareness, no prose classification, and no
write decision. Every add / replace / delete / no-op decision under test is made
by the Letta Code agent during `process`. `establish_durable_state` writes and
commits the state file directly — an application-layer *setup* operation under
SPEC.md line 124, on a path Letta Code's own system prompt sanctions ("Direct
file edits (full control)"). There is no recovery branch: if the agent renames
or deletes the allowlisted file, the adapter returns empty state and the scorer
classifies the outcome.

**Per-case isolation.** Each case runs with a private `HOME` and a private
`LETTA_LOCAL_BACKEND_DIR` inside its own run directory. No case can observe
another case's agents, settings, conversations or memory. The subprocess
environment is scrubbed of every `*_API_KEY` and `*_TOKEN`.

**The latency clock** (started by `runner.py` at `establish_durable_state`,
stopped after `retrieve_durable_state`) covers: writing and committing the state
file, the full CLI turn — Node process spawn, agent context compilation, model
inference, tool execution, memory commit — the settle poll, and the export. It
does **not** cover agent creation or persona installation, which happen before
the clock starts.

These latencies are **not comparable** to `adapters/letta/`'s, which measured
in-process HTTP calls to an already-running server. Any table placing the two
latency columns side by side without that warning is misreporting them.

## 4. Frozen artifact hashes

Verified before and after every scored run, via `runner.py`, which calls
`validate_freeze` unconditionally. The scorer's `--skip-freeze-check` override
is never used.

| File | sha256 |
|---|---|
| `cases.json` | `d5d9db63ad0911110e7cc602a22a6f6e655b9b5fb72261c649a10debdd7ac54f` |
| `score.py` | `7565863b5c02d35d9d3e8dea9dcfa453fd903d618ac9f61280b5b3cc1a9dd98b` |

Adapter and configuration hashes, fixed as of this commit:

| File | sha256 |
|---|---|
| `adapters/letta-code/adapter.py` | `2ca386b6f87acc9109c4e601ef35ca35c9e9ebdf02f87f7a63a5c953a8028e45` |
| `adapters/letta-code/config.json` | `1b178cb6fbe0facff821eeedf505a71817737a10e7b0327d238e05863e8db1d6` |
| `adapters/letta-code/config-qwen3.6-27b.json` | `77faaae322d2b263e2b2df056c8167fcf4f1ffb756aa03ffe12bc324be49afb9` |
| `adapters/letta-code/run-all.sh` | `b5291f21e684c6a74cb82c53e70b4d1077dc8366b218929ae2098f8759af1ad3` |
| `adapters/letta-code/pilot.py` | `78b52ede087ed0fb3f22b3d3c4373dc696fb264156e0000ba0ed1a64b9795425` |
| `adapters/letta-code/pilot-cases-mechanics.json` | `209fb6598bb282406ae95ad34ac2167f39c1f8b9dc21bdb9598ceae36fd751fd` |
| `adapters/letta-code/pilot-cases-autonomous.json` | `c979ca681b534a782964ef07ca2a09eb26cb2940c2e19a084594d5284a35d0aa` |
| `adapters/letta-code/README.md` | `7e3793cdf37ef0e8b637bb5da10e60e781934ee96be58bee40d2912f02d1419d` |
| `adapters/letta-code/CURRENCY.md` | `61f9879e956047d00636763885f2dcd37c9dfb27eb4a8afcb30f79680a619fff` |
| `adapters/model-only-control/control.py` | `a139397e45f2ebc48e1ecff52ba19d40618149d446575a5bc79d5fa187e11ccd` |
| `runner.py` | `ac68efe01ccf852028669c1ceba876f05cb89a4a6b8378e65ac94be00c23725c` |

Pre-existing published artifacts that must not change, recorded so that any
later edit is detectable:

| File | sha256 |
|---|---|
| `adapters/letta/adapter.py` | `6d7a4150a81106a2c1f1a712b49fa159ab0c85a40b9bbc0671ec0f7fae5a5464` |
| `adapters/letta/config.json` | `d5fed798e71c25ca33735f76abdeb77e0f3bd49bb7f5700b52979a212ff78753` |
| `adapters/letta/results.json` | `0340c5f5753ca10b283f9ce6ace58fc78179226d60236d2dcf36dc6ff739060a` |
| `RESULTS-LETTA.md` | `96440ef188a6da7955e980cc83f634db86a887f979dd72c007a0a7ef86fcb143` |
| `adapters/aoms/adapter.py` | `9a436a1a578ccaecfffbca7da71913e5e7832792a645390dfbbd7348ae95826d` |
| `adapters/aoms/config.json` | `71354b5e6bda36a146bc07747bb71c03b6f9911693dd2c373edc3d9139e35f52` |

## 5. Model plan

| Run | Model | Purpose |
|---|---|---|
| Letta Code × 3 | `ollama/qwen3:8b` | holds the model constant against the V1 server run, making V1-vs-MemFS the one clean comparison this cycle produces |
| Letta Code × 3 | `ollama/qwen3.6:27b` | tests whether the architecture's behaviour is model-dependent |
| Control × 3 | `ollama/qwen3:8b` | non-conforming bare-model control (see §6) |

**N = 3 runs per model. Every run is published, including runs that are bad for
us.** A run may be discarded only for a documented infrastructure failure —
machine crash, Ollama unavailable, disk exhaustion — and the discard, its
reason, and the partial artifact are published alongside the rest. "The numbers
looked wrong" is not an infrastructure failure.

If the 27b runs prove infeasible in the available time, the shortfall is
published as a stated limitation with the number of runs actually completed. It
is not quietly dropped.

## 6. The mandatory control

Alongside the framework runs, a **NON-CONFORMING CONTROL** is run: the frozen
corpus fed straight to Ollama with the published V1 Letta adapter's exact
persona, separator and preamble, plus two local function stubs — no Letta
process, server, SDK or MemFS anywhere in the stack.

This is not an MCB adapter result and is never published in a conforming table
without its label. It exists to make one subtraction possible:

> **A framework's contribution is (framework score − control score).**

Fixed in advance: **if the control matches the framework within run-to-run
spread, the published headline is "the framework's contribution is
indistinguishable from zero on this corpus" — not a system score.** This rule
binds regardless of which framework the finding embarrasses, including AOMS.

## 7. The abandonment rule

**Any edit to the adapter, the persona, any prompt string, or any config value
after case 1 of a run has executed voids that entire attempt.** A voided attempt
is not deleted and not hidden: it is published as a numbered abandoned attempt,
with the reason for the edit and the partial results it had produced.

Pilots are explicitly *before* case 1 and may be iterated freely; the mechanics
and autonomous pilots that informed this document are published with it.

## 8. Numeric predictions

Recorded before any scored case has run. Overall means all 48 cases.

Reasoning behind them: the model is held constant against the V1 server run; the
mechanics pilot reproduced V1's characteristic failure mode (an explicitly
unverified rumour was written to durable state); and the bare-model control is
expected to track the framework closely. I therefore predict MemFS changes
little.

| Metric | Mode | Prediction (point, 80% interval) |
|---|---|---|
| `decision_accuracy` | OVERALL | 0.73 (0.60 – 0.83) |
| `decision_accuracy` | INSTRUCTED | 0.75 (0.60 – 0.88) |
| `decision_accuracy` | AUTONOMOUS | 0.71 (0.50 – 0.85) |
| `unauthorized_overwrite_rate` | OVERALL | 0.40 (0.25 – 0.55) |
| `false_rejection_rate` | OVERALL | 0.00 (0.00 – 0.10) |
| `valid_supersession_rate` | OVERALL | 0.90 (0.70 – 1.00) |
| `mean_latency_ms` | OVERALL | 60000 (45000 – 90000) |

Additional pre-registered predictions:

- **Insufficiently-supported is the worst class.** I predict the 12
  insufficiently-supported cases score below 0.50, and below every other
  relationship class. This is the finding untouched by either known defect and
  is the headline regardless of how the rest lands.
- **The control lands within 0.10 of Letta Code overall.** If it does, §6's
  rule fires.
- **Run-to-run spread across the 3 seeds is at least 0.04 overall accuracy**,
  because the system is non-deterministic; any single-run number quoted without
  its spread is untrustworthy.

## 9. The three outcome paragraphs, written now

Exactly one of these is published, chosen by the numbers, unedited except for
inserting the actual figures.

**If Letta Code scores better than the published V1 figure:**

> Our V1 figures understated Letta. The V1 numbers stay published, unedited, so
> that the size of our error is checkable by anyone. We measured a deprecated
> server architecture, called the result "Letta", and were corrected by the
> vendor; this run is what we owed them. The corrected figure is the one to
> quote.

**If Letta Code scores worse than the published V1 figure:**

> This result was produced by a competitor, using an adapter Letta has not
> ratified, against an execution mode Letta gates behind an experimental flag,
> scored by exact string matching that penalises paraphrase, at n=3 on a
> non-deterministic system. Any of those could be the explanation instead of the
> architecture. We are sending this to Letta before publication, and we will
> publish their dispute and any adapter they prefer at equal prominence with
> this one.

**If Letta Code is unchanged from the published V1 figure:**

> This property appears insensitive to the V1 → MemFS architecture change. That
> is a finding about the benchmark as much as about Letta: a corpus that cannot
> distinguish two substantially different memory architectures is measuring
> something upstream of both of them — most plausibly the model.

## 10. Publication commitments

- New files only. `adapters/letta/**` and `RESULTS-LETTA.md` are untouchable;
  their hashes are recorded in §4.
- The word "Letta" unqualified is retired repo-wide in favour of "Letta V1
  server 0.16.8 (deprecated; measured in error)" and "Letta Code 0.30.31
  (unratified experimental local backend)".
- The AOMS-vs-Letta comparison moves to a historical section, unbolded, with
  both columns' defects stated — including that AOMS's own INSTRUCTED score
  rests on a 9-keyword substring match in `adapters/aoms/config.json`.
- A same-day AOMS replication at a pinned commit, unchanged, is published as a
  fresh artifact so that both columns are same-day measurements.
- Every result leads with the insufficiently-supported class.

---

*Committed before case 1. Predictions above are not to be edited after this
commit; if they are wrong, being visibly wrong is the point.*

---

## Appendix A — every prompt string, verbatim

Reproduced here so that the exact text under test is fixed by this commit and not only by a hash. Any difference between this appendix and `adapters/letta-code/config.json` at run time voids the attempt.

### `persona` — written to `system/persona.md` before the clock starts

```text
You maintain a durable memory file at system/mcb-state.md.

The file begins with a YAML frontmatter fence containing a description field. Below the fence the file holds zero or more lines. Every line has the exact form

TOPIC :: STATEMENT

A given TOPIC appears on at most one line. Nothing else may appear below the fence.

Each user message is an observation, followed by the canonical memory lines for the statements that observation asserts. After reading an observation you decide what system/mcb-state.md should contain. You may add a line, rewrite a line, delete a line, or leave the file exactly as it is.

When you record a statement that was supplied as a canonical line, copy that line character for character. Never reword, summarise, translate, merge or split a line. Judge for yourself which statements belong in durable memory and which do not, and leave the file unchanged when no change is warranted.

Never edit the frontmatter fence. Never rename or delete system/mcb-state.md. Do not write to any other memory file.
```

### `persona_description` — the frontmatter description of `persona.md`

```text
MCB durable-memory maintainer persona.
```

### `state_description` — the frontmatter description of `mcb-state.md`

```text
MCB durable state under test. One statement per line as TOPIC :: TEXT.
```

### `statement_preamble` — inserted between observation text and the canonical lines

```text
Statements asserted by this observation, in canonical memory-line format:
```

### `separator`

```text
' :: '
```

### The message template sent to the agent in `process`

The only text the agent receives is built as:

```text
{observation.text}

{statement_preamble}
{TOPIC :: TEXT for each observation statement, one per line}
```

Nothing else is appended. No case metadata, no expectation, no hint about the relationship class or the expected outcome reaches the agent.

### Control harness prompts

The non-conforming control reuses `adapters/letta/config.json`'s `persona`, `separator` and `statement_preamble` verbatim — the published V1 strings, unmodified — and presents the block as:

```text
{persona}

The "facts" block currently contains:
<facts>
{block}
</facts>
```
