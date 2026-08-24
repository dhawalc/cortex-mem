# MCB-1.0 — Memory Correctness Benchmark

Status: **frozen**

MCB-1.0 is a portable, framework-neutral benchmark for one narrow property of
a memory system: what happens when durable state meets a later observation
that is consistent, contradictory, superseding, or insufficiently supported.
It evaluates write-side state transitions. It is not a retrieval-quality,
ranking, summarization, or general reasoning benchmark.

## Integrity statement

The case corpus and scoring rules were authored and frozen before the
reference AOMS adapter was executed. No case, expectation, formula, or scoring
branch was tuned after observing an AOMS result. Git history is the audit trail:
the freeze commit precedes the adapter execution and committed result commit.

MCB is deliberately not defined around AOMS's declared-lineage mechanism.
AUTONOMOUS cases require a system to infer conflicts without an explicit
replacement instruction, so the benchmark can produce evidence against systems
that intentionally require callers to declare replacement.

## Unit under test

Each case performs exactly four framework-neutral operations:

1. **Establish durable state.** Persist the case's initial statements.
2. **Provide a subsequent observation.** Deliver the observation text and its
   atomic natural-language statements.
3. **Allow the system to process it.** Invoke the system's normal write-side
   processing and wait until the write decision is durable.
4. **Retrieve resulting durable state.** Return the logical current durable
   statements, excluding merely historical/inactive versions.

The initial state and observation statements are pairs of `topic` and `text`.
`topic` is a neutral identity key for the proposition being updated; it is not
a storage identifier and need not be persisted by the tested system. Exact text
is the portable interchange representation. An adapter may translate it into a
native representation, but must translate it back losslessly on retrieval.

## Modes

- **INSTRUCTED**: the observation text explicitly says that it replaces,
  corrects, or updates prior state. This tests whether an explicit write intent
  is applied correctly.
- **AUTONOMOUS**: the observation supplies no replacement instruction. In the
  contradiction and supersession cases, the system must infer the conflict.

Every relationship class has six cases in each mode. Mode metrics are always
reported separately. A system may legitimately score 0% AUTONOMOUS valid
supersession as a declared architectural stance, but the score remains visible.

## Relationship classes and expected outcome classes

The four relationship classes describe the stimulus:

- `consistent`: the observation agrees with the durable state, and may add a
  compatible fact.
- `contradictory`: one or more observation statements cannot simultaneously be
  current with prior statements on the same topics.
- `superseding`: a later, sufficiently supported observation makes one or more
  prior statements obsolete, including partial and multi-fact changes.
- `insufficiently-supported`: the observation lacks adequate authority,
  freshness, specificity, or safety to change durable state.

The expected outcome classes describe the correct state transition:

- `preserve`: no logical change because the observation is identical.
- `extend`: add compatible statement(s) while preserving prior state.
- `revise`: remove obsolete current statement(s), add their replacements, and
  preserve unrelated state.
- `reject`: make no logical change because the observation is insufficiently
  supported or hostile.

The corpus includes ambiguous authority, partial contradiction, stale
timestamps, one observation contradicting two prior facts, identical
observations, and an injection-flavored request to delete everything.

## Case schema

`cases.json` is a JSON object with benchmark/version metadata and a `cases`
array. A case contains:

- `id`, `mode`, `relationship`, and descriptive `tags`;
- `initial_state`: natural-language `topic`/`text` statements;
- `observation`: the exact `text` delivered to the system plus atomic
  `statements` asserted by that observation;
- `expected.outcome_class` and the exact logical `final_state`;
- `expected.protected_state`: initial statements that must survive;
- `expected.obsolete_state`: initial statements that must cease to be current;
- `expected.required_new_state`: novel statements that must become current.

Expected fields are withheld from adapter calls. Conforming adapters must not
read the case file or infer expectations out of band.

## Adapter contract

`runner.py` loads a Python module from a filesystem path. The module must expose:

```python
def create(config: dict, run_dir: pathlib.Path) -> object: ...
```

The returned object must implement these methods; synchronous or asynchronous
methods are accepted:

```python
establish_durable_state(initial_state: list[dict[str, str]]) -> None
provide_observation(observation: dict) -> None
process() -> None
retrieve_durable_state() -> list[dict[str, str]]
close() -> None                         # optional
```

The runner creates a fresh per-case directory under its run directory and a
fresh adapter instance for every case. `config` is the parsed adapter config
plus `case_id`; no expected data is passed. `retrieve_durable_state` must return
only logical **current** state as unique `{"topic": ..., "text": ...}` pairs.
Historical/inactive versions must not be returned. If a native system cannot
represent topic keys, the adapter may maintain a lossless local mapping, but it
may not make the write decision itself except to translate an explicit
INSTRUCTED operation into the system's documented write primitive.

Adapters must use real application-layer operations, not direct database edits,
and must isolate benchmark storage from user/live storage. They must document
translation policy, dependencies, configuration, and environment. An adapter
must not report pass/fail, expected/actual class, or metrics.

## Deterministic scoring

State units are compared as exact `(topic, text)` pairs after structural JSON
validation. No model, embedding, fuzzy match, ordering, adapter verdict, or
adapter-provided score is used. Duplicate returned pairs or duplicate current
values for one topic are invalid and fail the case.

The scorer derives `actual_class` from the final state:

1. If final state equals initial state, the class is `preserve` when every
   observation statement was already present; otherwise it is `reject`.
2. If old and new text for any observation topic are both current, the class is
   `conflict-retained`.
3. If no initial statement was removed and at least one statement was added,
   the class is `extend`.
4. If initial statements were removed and statements on all removed topics were
   added, the class is `revise`.
5. If statements were removed and none added, the class is `erase`.
6. Every other delta is `mixed`.

A case passes iff processing produced no error, returned state is structurally
valid and unique by topic, the exact set equals `expected.final_state`, and the
derived actual class equals `expected.outcome_class`.

## Metrics

Let `C_m` be cases in metric slice `m` (OVERALL, INSTRUCTED, or AUTONOMOUS),
`pass(c)` be 1 for a passing case and 0 otherwise, and `L(c)` be end-to-end
latency in milliseconds covering operations 1–4.

**Decision accuracy**

`DA_m = sum(pass(c) for c in C_m) / |C_m|`

For each case, let `P(c)` be `protected_state` and `missing_P(c)` be those pairs
absent from retrieved final state.

**Unauthorized overwrite rate** (lower is better)

`UOR_m = sum(|missing_P(c)|) / sum(|P(c)|)` for cases with protected statements.

This is fact-weighted: every durable fact the expected result requires the
system to preserve is one opportunity for unauthorized destruction.

Let `R_m` be cases whose expected outcome is `revise`. A valid supersession has
the exact expected final state, all obsolete statements absent, all required
new statements present, all protected statements present, and no process error.

**Valid supersession rate**

`VSR_m = sum(valid_supersession(c) for c in R_m) / |R_m|`

Let `A_m` be all required-new statement pairs in `extend` and `revise` cases,
and `missing_A_m` be required-new pairs absent from final state.

**False rejection rate** (lower is better)

`FRR_m = |missing_A_m| / |A_m|`

This is claim-weighted. Retaining an obsolete conflicting statement does not by
itself count as rejection if the new claim was durably accepted; it can still
fail decision accuracy and valid supersession.

**Latency**

`mean_latency_m = sum(L(c)) / |C_m|`

`p95_latency_m` is the nearest-rank percentile: sort latencies ascending and
select the element at one-based rank `ceil(0.95 * |C_m|)`.

Rates are emitted as JSON fractions in `[0,1]`; presentation may multiply by
100. If a denominator is zero, the metric is JSON `null`. Latency is measured
with `time.perf_counter_ns()` and rounded to three decimal milliseconds only in
the serialized result.

## Runner and result artifact

The runner validates the frozen manifest before execution, runs cases in file
order, and writes one JSON object. Each per-case result contains the case ID,
mode, relationship, exact inputs, resulting durable state, expected class,
scorer-derived actual class, latency, pass/fail, and any error. It also embeds
the scorer-produced metric slices. Results are serialized with sorted keys and
two-space indentation. A benchmark report must commit the runner output
verbatim, including failures and unfavorable numbers.

## Freeze and versioning policy

`FREEZE-MANIFEST.json` pins SHA-256 hashes of `cases.json` and `score.py`. A
runner or scorer must refuse a hash mismatch unless an explicit diagnostic-only
override is used; overridden output is nonconforming and must not be reported as
MCB-1.0.

After freeze, MCB-1.0 case inputs, expectations, scoring logic, and formulas are
immutable. Documentation clarifications that cannot change outcomes may be
made only with an erratum entry and a patch-level documentation label. Any
change capable of changing a result requires a new benchmark version and new
directory, manifest, and baseline. Historical results remain bound to their
original hashes.
