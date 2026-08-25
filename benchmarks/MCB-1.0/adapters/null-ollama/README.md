# NON-CONFORMING CONTROL — bare `qwen3:8b`, no memory system

**This is not a memory system, not an adapter, and not a competitor. It must
never appear as a row in a comparison table.**

It exists to answer one question about a published MCB-1.0 result: how much of a
framework's score is the framework, and how much is the model underneath it?

The published Letta V1 column scored 75.0% decision accuracy with
`ollama/qwen3:8b` making every write decision. This control removes Letta from
the stack entirely — no server, no SDK, no MemFS, no database, no store — feeds
the same frozen corpus to the same model with the same prompt, and gives it two
local Python function stubs to edit a plain string.

## Result

**Reproduced the published Letta V1 per-case result on 46 of 48 cases, and
matched its headline metric exactly.**

| Metric (OVERALL, 48 cases) | Letta V1 0.16.8 | This control | Framework contribution |
| --- | ---: | ---: | ---: |
| Decision accuracy | 75.000% | 75.000% | **0.000 pp** |
| Cases passed | 36/48 | 36/48 | **0** |
| Unauthorized overwrite rate ↓ | 40.625% | 40.625% | **0.000 pp** |
| False rejection rate ↓ | 0.000% | 0.000% | **0.000 pp** |
| Valid supersession rate | 100.000% | 95.833% | −4.167 pp |
| Mean latency | 20 846.9 ms | 24 612.0 ms | — |

By relationship class:

| Relationship | Letta V1 | This control |
| --- | ---: | ---: |
| Consistent | 12/12 | 12/12 |
| Contradictory | 12/12 | 12/12 |
| Superseding | 12/12 | 11/12 |
| Insufficiently supported | 0/12 | 1/12 |

By mode: both 18/24 INSTRUCTED and 18/24 AUTONOMOUS.

Per-case agreement is **46/48** on pass/fail and **46/48** on derived outcome
class. The two disagreements point in opposite directions and cancel:

| Case | Class | Mode | Letta V1 | This control |
| --- | --- | --- | --- | --- |
| `MCB-S-06` | superseding | AUTONOMOUS | `revise` ✓ | `conflict-retained` ✗ |
| `MCB-U-10` | insufficiently-supported | AUTONOMOUS | `conflict-retained` ✗ | `reject` ✓ |

**The framework's measured contribution on the headline metric is zero
percentage points.** On this corpus, MCB could not detect that Letta was in the
stack.

### The one case worth reading closely

`MCB-U-10` is the only case where this control outscored the framework, and it
is not a win. The model produced **no tool call at all** after **766 seconds** of
generation — by a wide margin the longest case in the run, and roughly thirty
times the run's mean. The durable state survived because nothing happened to it.

The scorer records `reject` because it measures the state transition, not the
reasoning that produced it. That is the right design for a deterministic scorer
and it is the reason this case must be described accurately here: **1/12 on the
insufficiently-supported class is one accidental abstention, not an evidence
gate.** Reporting it as "the bare model also has no evidence gate, 0/12" would be
tidier and would be wrong by one case.

## What this does and does not show

**It does show** that MCB-1.0's cross-system comparison was substantially
measuring `qwen3:8b`. That comparison has been retired — see
[`../../CORRECTIONS.md`](../../CORRECTIONS.md) entry #2.

**It does not show** that memory frameworks are worthless. MCB measures one
narrow property: what a system does to durable state when a later observation
arrives, over 48 single-turn cases starting from an empty store. Retrieval,
ranking, scale, eviction, multi-turn behaviour, concurrency and contention are
all things MCB explicitly does not measure, and they are most of what a framework
exists for. The honest reading is a limit on **this benchmark**: 48 single-turn
write decisions could not resolve a framework's contribution above zero.

**It does not vindicate AOMS either.** AOMS scored 50.0% against this control's
75.0%. Retiring the comparison withdraws the claim that the gap said something
about architecture; it does not move AOMS's number.

## How it works

The corpus is fed to Ollama's `/api/chat` one case at a time, up to 8 agent steps
per case, temperature 0.

**Nothing about the prompt is authored here.** `config.json` names
`adapters/letta/config.json` as its `persona_source`, and `adapter.py` reads that
file's `persona`, `separator` and `statement_preamble` verbatim at runtime. The
framework is the only difference between the two stacks. Holding the prompt fixed
is not the same as the prompt being neutral — see `DISCLOSURE.md`.

The durable "memory block" is a Python string. The three tools the model sees:

| Tool | Behaviour |
| --- | --- |
| `memory_insert(label, new_string)` | appends one line |
| `memory_replace(label, old_string, new_string)` | verbatim line rewrite; empty `new_string` deletes. Returns `error: old_string not found verbatim` on a miss, matching the real tool's failure mode |
| `send_message(message)` | ends the turn |

That is the entire memory system: about thirty lines in `adapter.py`.

Scoring uses the frozen `score.py` unchanged, through `score_document` — the same
function the conforming runner calls. `validate_freeze` runs before case 1 and
aborts on a hash mismatch.

## Reproducing it

Requires Ollama with `qwen3:8b` pulled. No other dependencies; `adapter.py` is
standard library only.

```sh
cd MCB-1.0
python adapters/null-ollama/adapter.py \
  --model qwen3:8b \
  --output adapters/null-ollama/results-null-ollama-qwen3-8b.json
```

Expect roughly 25 minutes on a local GPU, dominated by a small number of very
long cases. `runner-output.txt` in this directory is the verbatim console output
of the published run, per-case timings included, so you can compare case by case
as it goes.

**It is deliberately not runner-compatible.** `runner.py` accepts a module that
exposes a callable `create(config, run_dir)`; this file defines one that raises
with an explanation. A control is not an adapter and must not be able to produce
a result document that sits alongside conforming ones.

## Files

| File | |
| --- | --- |
| `adapter.py` | the harness. Not an adapter; refuses `runner.py` |
| `config.json` | model, endpoint, step budget, and the `persona_source` pointer |
| `environment.txt` | model digest, host, freeze hashes, isolation |
| `DISCLOSURE.md` | conflict of interest — this control was written by MCB's author |
| `results-null-ollama-qwen3-8b.json` | the scored artifact, verbatim |
| `runner-output.txt` | the console output of the run, verbatim |

Run of 2026-08-25. Model `qwen3:8b`, digest
`500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`, 8.2B
parameters at Q4_K_M. Frozen inputs verified before and after:
`cases.json` = `d5d9db63ad0911110e7cc602a22a6f6e655b9b5fb72261c649a10debdd7ac54f`,
`score.py` = `7565863b5c02d35d9d3e8dea9dcfa453fd903d618ac9f61280b5b3cc1a9dd98b`.

**Single run, temperature 0. No variance study.** Read 46/48 as a strong
qualitative result about where the score comes from, not as a precise
coefficient. `GOVERNANCE.md` §10 requires a control like this from every
model-driven adapter; it does not yet require a repeated one.
