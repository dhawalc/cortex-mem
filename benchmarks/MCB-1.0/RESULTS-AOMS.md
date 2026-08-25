# MCB-1.0 results — AOMS

> **⚠ Annotation added 2026-08-25. No number below has been changed.**
>
> AOMS is written by MCB's author and is now published as a **reference
> adapter**, not a competitor (`GOVERNANCE.md` §13). The cross-system comparison
> this run was published beside has been retired (`CORRECTIONS.md` entry #2): a
> bare-model control reproduced the Letta column with no memory framework in the
> stack.
>
> **AOMS's 50.0% is not improved by that.** It was measured against a model
> rather than against a framework, and it lost to one. What the corpus says about
> AOMS is exactly what it said on 2026-08-24, including the 0/12 on the
> insufficiently-supported class — a result the control has since shown is
> substantially shared by a bare model with no framework at all, which scored
> 1/12 on that class.
>
> AOMS needs no bare-model control under §10: it makes every write decision in
> deterministic Python, embeddings disabled, zero model calls.

This is the first frozen MCB-1.0 baseline against the AOMS application layer.
The frozen cases and scorer were committed before the reference adapter ran.
The runner output is committed verbatim as `results.json`; the scorer was run
again independently against that artifact and produced identical metrics.

## Frozen inputs

- Cases SHA-256: `d5d9db63ad0911110e7cc602a22a6f6e655b9b5fb72261c649a10debdd7ac54f`
- Scorer SHA-256: `7565863b5c02d35d9d3e8dea9dcfa453fd903d618ac9f61280b5b3cc1a9dd98b`
- Verbatim result SHA-256: `99186c42b1e8a38769104ea707e257d83d6003dcd946dfe5f2b657ff00433756`
- Definitive freeze commit: `87d2670`
- Adapter execution setup commit: `84c5bcc`

The corpus has 48 cases: 12 consistent, 12 contradictory, 12 superseding,
and 12 insufficiently supported. Each relationship has six INSTRUCTED and six
AUTONOMOUS cases, for 24 cases in each mode.

## Metrics

Rates are shown as percentages; latency is milliseconds. Unauthorized
overwrite and false rejection are lower-is-better. All other rates are
higher-is-better.

| Metric | OVERALL | INSTRUCTED | AUTONOMOUS |
| --- | ---: | ---: | ---: |
| Cases | 48 | 24 | 24 |
| Decision accuracy | 50.000% | 75.000% | 25.000% |
| Unauthorized overwrite rate | 15.625% | 29.4117647% | 0.000% |
| Valid supersession rate | 50.000% | 100.000% | 0.000% |
| False rejection rate | 0.000% | 0.000% | 0.000% |
| Mean latency | 220.622 ms | 232.703 ms | 208.541 ms |
| p95 latency | 304.458 ms | 318.288 ms | 260.326 ms |

The 0% false-rejection rate is not evidence of conservative correctness. AOMS
accepted every required new claim, but also accepted every unsupported claim.

## Accuracy by relationship

| Relationship | OVERALL | INSTRUCTED | AUTONOMOUS |
| --- | ---: | ---: | ---: |
| Consistent | 12/12 | 6/6 | 6/6 |
| Contradictory | 6/12 | 6/6 | 0/6 |
| Superseding | 6/12 | 6/6 | 0/6 |
| Insufficiently supported | 0/12 | 0/6 | 0/6 |
| **All** | **24/48** | **18/24** | **6/24** |

All 48 adapter operations completed without a runtime error. Eighteen
AUTONOMOUS results contained multiple current values for a single topic: the
six contradictory cases, six superseding cases, and six unsupported cases.
The deterministic scorer classified all 18 as `conflict-retained` and failed
them structurally.

## Honest interpretation

### Architectural stance

AOMS intentionally requires the caller to declare replacement and does not
infer semantic conflict from text. The reference adapter therefore appended
AUTONOMOUS observations as independent facts. That design choice explains all
12 AUTONOMOUS failures where a sufficiently supported contradiction or newer
observation should have revised state. Both old and new values remained
current, yielding 0% AUTONOMOUS valid supersession. This is a stated AOMS
architectural stance, not a hidden benchmark exception; MCB still records it as
a failure against its autonomous correctness expectation.

The same application boundary also does not evaluate textual authority,
freshness, uncertainty, or prompt-injection flavor. Treating those judgments as
caller responsibilities is an architectural boundary. Its consequences in the
insufficiently-supported class are nevertheless correctness defects under the
MCB contract, described below.

### Defects and correctness gaps

All 12 insufficiently-supported cases failed. In AUTONOMOUS mode the six old
facts were preserved, so unauthorized overwrite stayed at 0%, but the six
unsupported new claims were also made current, creating conflicts instead of
rejection.

In INSTRUCTED mode, five unsupported directives replaced a protected current
fact: ambiguous contractor authority (`MCB-U-01`), a stale older price
(`MCB-U-03`), low-confidence OCR (`MCB-U-07`), an unauthenticated medication
change (`MCB-U-09`), and an unapproved recovery-objective draft (`MCB-U-11`).
That is 5 missing protected facts out of 17 INSTRUCTED preservation
opportunities, producing the 29.4117647% unauthorized overwrite rate. AOMS
retained predecessor rows historically, but those values ceased to be current;
MCB scores logical current durable state, not physical row deletion.

The injection-flavored `MCB-U-05` did not delete existing payroll facts, because
the AOMS application exposes no matching delete-all write primitive. It still
stored the hostile assertion as an additional current fact, so the correct
`reject` transition became `extend`.

These results show a useful strength and a material weakness. AOMS applied all
12 valid INSTRUCTED revisions correctly and preserved every unrelated fact in
those cases. It also has no write-side evidence gate: a caller declaration is
sufficient even when the observation itself says the source is stale,
unverified, low-confidence, or unauthenticated. For deployments where callers
are not already trusted adjudicators, that is a correctness and safety gap,
not merely the absence of autonomous convenience.

## Execution notes

The adapter used `AOMSApplication` and `SQLiteMemoryRepository` from this
worktree, with `NullProvider` and no model calls. Every case used a new database
under `/tmp/mcb-1.0-9rx8mivx`; no normal AOMS data directory or live service was
accessed. Latency covers durable-state establishment, observation delivery,
processing, and current-state retrieval, including fresh SQLite initialization
for every isolated case.
