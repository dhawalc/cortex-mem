# Corrections

This is the standing correction log for MCB. It is append-only. Entries are
added when a published result is found to be wrong, misleading, or measured
against the wrong thing — whether the error is found by us, by a maintainer of a
benchmarked system, or by a third party.

**No published result file is ever edited or deleted.** Results are preserved
verbatim as the historical record of what was actually run, and corrected by
annotation only. If a number in this repository is wrong, the number stays and a
correction is attached to it. The correction trail is the credibility, not the
original number.

Anyone who finds an error in a published result should open an issue or email
the maintainer. Corrections from the maintainers of benchmarked systems are
especially welcome and will be credited by name.

---

## 2026-08-24 — Letta results measured a deprecated product

**Status:** OPEN. Annotation complete; re-run outstanding.

**Identified by:** **Sarah Wooders**, Letta (letta-ai). Reported by email on
2026-08-24 at 20:46, the same day the results were published.

### What she said

Quoted verbatim and in full:

> Hi - the letta repo is deprecated. If you are looking to benchmark letta code,
> please use the agents SDK or letta code directory
> https://docs.letta.com/agent-sdk
> https://github.com/letta-ai/letta-code

### What was wrong

MCB-1.0 was run against PyPI `letta` 0.16.8 — upstream tag commit
`1131535716e8a31c9a437f8695e25ac98f203a24` from `github.com/letta-ai/letta` —
and the results were published as "Letta". That package is the **retired Letta
V1 server**. It is not Letta's current system.

Letta's current product surface is the Agent SDK
(`@letta-ai/letta-agent-sdk`) and letta-code (`@letta-ai/letta-code`), which are
a materially different architecture: durable memory is **MemFS**, a git-backed
markdown filesystem, not the V1 core-memory blocks the adapter was written
against.

So every published Letta figure in this repository measures a deprecated
product. The measurement is real and was performed correctly against the thing
it was pointed at. The thing it was pointed at was the wrong thing.

### Why we missed it

This is the part worth recording, because the evidence was in front of us.

Letta's `SECURITY.md` distinguishes a "legacy Letta V1 server preserved on the
archive branch" from "current Letta products." We read that file and correctly
noted the distinction — and then failed to apply it to the artifact we had
actually installed. We treated "the current PyPI release of the package named
`letta`" as equivalent to "current Letta," and those are not the same thing. A
package can remain installable, importable, and functional long after it stops
being the product.

Two signals we did not weight: PyPI `letta` had not shipped a release since
2026-05-14, and the `letta-ai/letta` README now describes itself as a landing
page for the project with the V1 server source preserved on an `archive` branch.
Neither is conclusive alone. Together they were enough, and we did not check.

**The generalisable failure:** we verified *reproducibility* (versions pinned,
hashes recorded, environment documented — all of which held) but never verified
*currency* — that the pinned artifact was the thing the vendor would recognise
as their system. MCB's governance had a freeze discipline and no
target-validation discipline. See the process change below.

### What was done

Both repositories carrying these results — this one and the standalone
`mcb-benchmark` distribution — were annotated on 2026-08-24. Nothing was deleted or rewritten.

- A correction banner was placed at the top of `RESULTS-LETTA.md`.
- Every Letta figure in every README and results table was annotated inline, and
  every table column carrying a Letta number was relabelled so the column header
  itself names the correction. It is not possible to read a Letta number in this
  repository without meeting this correction.
- The compounding effect described below is recorded in the correction
  banner on `RESULTS-LETTA.md` and in this entry. (The standalone
  distribution at `mcb-benchmark` additionally records it in its
  `KNOWN-LIMITATIONS.md` and `GOVERNANCE.md`.)
- `RERUN-PLAN-LETTA-SDK.md` was written: a costed, unexecuted plan for
  re-running MCB-1.0 against the Agent SDK.
- The frozen `cases.json` and `score.py` were verified by SHA-256 against
  `FREEZE-MANIFEST.json` before and after all annotation work, and were
  unchanged. The Letta adapter under `benchmarks/MCB-1.0/adapters/letta/` was not touched;
  it is preserved exactly as it ran.

### The compounding effect — read this before citing anything

The Letta result now carries **two independent invalidating defects, on two
different axes**:

1. **Model confound** (previously disclosed, still unresolved). AOMS decided
   every write in deterministic Python with no model at all. Letta decided every
   write with `ollama/qwen3:8b`, an 8.2B-parameter local model at Q4_K_M. These
   are not comparable amounts of computation, and no frontier-model control run
   exists.
2. **Deprecated target** (this correction). The Letta side measured the retired
   V1 server, not Letta's current architecture.

These do not average out and they do not cancel. They mean the AOMS-vs-Letta
comparison **is not currently a valid architecture comparison on either axis**:
the model differs *and* the system under test is not the system named. Correcting
either defect alone still leaves an invalid comparison. Both must be fixed in the
same run, which is exactly what `RERUN-PLAN-LETTA-SDK.md` is scoped to do.

The specific figures this invalidates as architecture claims include: Letta
75.0% overall decision accuracy against AOMS's 50.0%; Letta 100% autonomous
valid supersession against AOMS's 0%; Letta 40.6% unauthorized overwrite against
AOMS's 15.6%; and the entire archival-target secondary run.

**What survives.** One finding is untouched by both defects: **both systems
scored 0/12 on insufficiently-supported observations.** That is the absence of a
write-side evidence gate — a missing mechanism, not a judgement failure — so it
does not depend on which model drives the write path. It remains a true
statement about the specific artifacts measured. Note the narrowed scope: it is
now a statement about AOMS and Letta V1, and whether current Letta has an
evidence gate is **unmeasured and unknown**.

The prompt-injection result (`MCB-U-05`, where the agent deleted both protected
payroll facts on request) is likewise a true and reproducible fact about Letta
V1. It must not be repeated as a statement about Letta's current system, which
has a different memory architecture and different tools.

### What remains outstanding

1. **Re-run MCB-1.0 against the Letta Agent SDK**, resolving the model confound
   in the same run. Plan written, not executed. See `RERUN-PLAN-LETTA-SDK.md`.
2. **Confirm the six open questions in that plan with Sarah Wooders** before
   writing the new adapter — in particular which memory configuration Letta
   considers canonical for evaluation. Getting the target right this time means
   asking the maintainer rather than inferring from docs, which is precisely the
   step whose absence caused this correction.
3. **Rewrite `UPSTREAM-ISSUE-DRAFT.md`**, which was drafted against the
   deprecated repository and asks upstream to validate an adapter for a product
   they have retired. It should not be posted in its current form.
4. **Process change for MCB-1.1 governance** (tracked in the standalone
   `mcb-benchmark` distribution's `GOVERNANCE.md` and `CONTRIBUTING.md`): an
   adapter submission must record
   a positive statement that the pinned artifact is the system's *current*
   product, with the evidence for that claim, and where practical the target
   should be confirmed with the system's maintainers before results are
   published. Freezing the corpus proved sufficient for integrity and
   insufficient for validity.

### Credit

Sarah Wooders identified this within hours of publication and told us directly.
The error was ours. This repository is more accurate because a maintainer of a
benchmarked system took the time to correct it, and that is recorded here by
name deliberately.
