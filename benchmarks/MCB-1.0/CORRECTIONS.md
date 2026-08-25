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

**Status:** OPEN. Annotation complete.

> **Annotation added 2026-08-25 (entry #2).** "Re-run outstanding" is superseded.
> There is no re-run outstanding: entry #2 retires the comparison the re-run was
> meant to repair. Statements inside this entry that are now false are annotated
> in place rather than edited out.

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

   > **⚠ FALSE as of 2026-08-25.** A control run exists. It is not a
   > frontier-model run — that was the wrong instrument — but a *bare-model*
   > control that removes the framework instead of upgrading the model, and it
   > reproduced the Letta column on 46 of 48 cases. This defect is therefore not
   > "unresolved": it is resolved, and the resolution retires the comparison
   > rather than repairing it. See entry #2.
2. **Deprecated target** (this correction). The Letta side measured the retired
   V1 server, not Letta's current architecture.

These do not average out and they do not cancel. They mean the AOMS-vs-Letta
comparison **is not currently a valid architecture comparison on either axis**:
the model differs *and* the system under test is not the system named. Correcting
either defect alone still leaves an invalid comparison. Both must be fixed in the
same run, which is exactly what `RERUN-PLAN-LETTA-SDK.md` is scoped to do.

> **⚠ FALSE as of 2026-08-25.** There were three axes, not two, and fixing all
> three fixes nothing. `RERUN-PLAN-LETTA-SDK.md` is **SUPERSEDED**, not scoped
> work: the comparison it was scoped to repair has been retired. See entry #2.

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

> **Annotation, 2026-08-25.** This paragraph is still true, and the bare-model
> control extends it: the control scored **1/12** on this class, not 0/12. The
> one pass is not an evidence gate — on `MCB-U-10` the model made no tool call at
> all after 766 seconds, leaving durable state unchanged by non-response rather
> than by refusal. So the absence of a write-side evidence gate covers a language
> model with no framework too, with that one honest asterisk. See entry #2,
> "What remains valid".

The prompt-injection result (`MCB-U-05`, where the agent deleted both protected
payroll facts on request) is likewise a true and reproducible fact about Letta
V1. It must not be repeated as a statement about Letta's current system, which
has a different memory architecture and different tools.

### What remains outstanding

> **⚠ Superseded 2026-08-25 by entry #2.** Item 1 below is withdrawn: the
> comparison it would repair has been retired, and `RERUN-PLAN-LETTA-SDK.md` is
> marked **SUPERSEDED**, not pending. Items 2–4 stand. Item 4 is implemented in
> `GOVERNANCE.md` §9–§13.
>
> Item 1 is also false on its own terms in *this* repository, and that is worth
> stating plainly: an adapter against letta-code was written here and six 48-case
> runs exist as untracked artifacts. They carry no write-up and no bare-model
> control, so under `GOVERNANCE.md` §10 and §11 they are not publishable and are
> cited nowhere.

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

---

## 2026-08-25 — The cross-system comparison is retired

**Status:** CLOSED by retirement. The comparison is withdrawn, not pending a
better run. Nothing further is outstanding on it.

**Identified by:** MCB's own author, by running the control that
`KNOWN-LIMITATIONS.md` had described as necessary and then treated as
unaffordable. Nobody reported this. It was found by finally measuring a confound
we had been carefully disclosing for a day.

### What we claimed

MCB-1.0 published a table ranking memory systems by decision accuracy on a frozen
48-case corpus. Its headline row was **Letta 0.16.8 at 75.0% against AOMS 2.0.0
at 50.0%**, with Letta at 100% autonomous valid supersession against AOMS's 0%.

We surrounded it with caveats. We said in three separate places that the
comparison was confounded by model capability — that AOMS decided every write in
deterministic Python with no model at all while Letta decided every write with
`ollama/qwen3:8b` — and that the ranking must not be cited as an architecture
result. We then published the ranking, with the winning cells in bold.

We also said the control run that would settle it was **"OUTSTANDING, and blocked
on API credits rather than on design,"** and wrote a costed $30–100 plan
(`RERUN-PLAN-LETTA-SDK.md`) to re-run the Letta adapter across a ladder of model
sizes up to a frontier model.

### What the control showed

On 2026-08-25 we ran a different experiment, which cost nothing.

The frozen corpus was fed straight to `ollama/qwen3:8b` over Ollama's `/api/chat`
— the same model handle, the same digest
`500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`, the same
Q4_K_M quantisation and the same 8-step budget as the published Letta run. The
persona, separator and statement preamble were read verbatim at runtime out of
the published Letta adapter's own `config.json`, so the prompt was held fixed.
In place of Letta's `memory_insert` and `memory_replace` it was given two local
Python function stubs, about thirty lines, editing a plain string.

**There was no Letta process, server, SDK, MemFS, database or store anywhere in
the stack. There was no memory system of any kind.** Scoring used the frozen
`score.py` unchanged, with the freeze hashes verified before the first case ran.

**The bare model reproduced the published Letta V1 per-case result on 46 of the
48 cases, and matched its headline metric exactly.**

| Metric (OVERALL, 48 cases) | Letta V1 0.16.8 | Bare `qwen3:8b` control | Framework contribution |
| --- | ---: | ---: | ---: |
| Decision accuracy | 75.000% | 75.000% | **0.000 pp** |
| Cases passed | 36/48 | 36/48 | **0** |
| Unauthorized overwrite rate | 40.625% | 40.625% | **0.000 pp** |
| False rejection rate | 0.000% | 0.000% | **0.000 pp** |
| Valid supersession rate | 100.000% | 95.833% | −4.167 pp |
| Insufficiently supported | 0/12 | 1/12 | −1 case |

Per-case agreement is 46/48 on pass/fail and 46/48 on derived outcome class. The
two disagreements point in opposite directions and cancel: on `MCB-S-06` Letta V1
revised where the control retained a conflict; on `MCB-U-10` the control left
state unchanged where Letta V1 retained a conflict. Every other case landed the
same way with no framework present.

**The framework's measured contribution on the headline metric is zero
percentage points.** Not small — absent.

### What we are withdrawing

**The cross-system comparison, in full.** Every ranking, every bolded winner,
every statement of the form "system A scored higher than system B" published from
MCB-1.0. Specifically withdrawn as claims about any system's design:

- Letta 75.0% overall decision accuracy against AOMS's 50.0% and against the
  contest-ledger build's 62.5%
- Letta 100% autonomous valid supersession against AOMS's 0%
- Letta 40.6% unauthorized overwrite against AOMS's 15.6%
- the entire archival-target secondary run
- every prose claim attributing autonomous conflict inference, supersession
  behaviour, or overwrite behaviour to **Letta's architecture** — including
  "Letta V1's advantage is autonomous conflict inference, and it is real", which
  is the single sentence this correction most directly falsifies

The reason is not that the numbers are wrong. They are correct measurements,
correctly scored, and they are preserved verbatim in the committed artifacts
exactly as published. The reason is that **the published "Letta" column was
substantially a measurement of qwen3:8b**, and the framework's measured
contribution on this corpus is indistinguishable from zero. A column that a
framework-free control reproduces on 46 of 48 cases is not a measurement of the
framework.

This is materially worse than the 2026-08-24 correction, and it is worth being
precise about why. That one said we had measured the wrong version of the right
kind of thing, and implied a re-run against the right version would fix it. This
one says the benchmark could not see a framework's contribution at all on this
corpus. **There is no re-run of this design that rescues the ranking.** Retiring
it is not a delay; it is the finding.

We are also withdrawing the conflict-of-interest argument built on it. The standalone distribution's `README.md`
argued that the author's conflict was mitigated because "Letta — a system the
benchmark's author did not write — scores higher than AOMS." An adapter that
turns out to measure the underlying model can produce a
flattering-to-the-competitor number without being unbiased, so the direction of
that result was never evidence of good faith. That was the strongest
conflict-of-interest argument this repository made and it was structurally empty.

### What remains valid

**The insufficiently-supported class finding is untouched, and this correction
does not depend on it or bear on it in either direction.**

**No system tested has a write-side evidence gate.** AOMS 2.0.0, AOMS with a
contest ledger, and Letta V1 driven by qwen3:8b each scored **0/12** on the
insufficiently-supported class. The bare-model control scored **1/12**. None has
any notion of authority, freshness, or evidentiary sufficiency in the write path.

**The control's single pass is not an evidence gate and must not be reported as
one.** On `MCB-U-10` the model emitted no tool call at all after 766 seconds of
generation — the longest case in the run by a wide margin — so the durable state
survived by non-response rather than by refusal. The scorer records a `reject`
because it measures the state transition, not the reasoning behind it. One
accidental abstention in twelve is the honest description, and stating it as
"the bare model also scores 0/12" would be the same kind of convenient rounding
this correction exists to record.

This finding does not depend on the cross-system comparison in any way. It is not
a ranking, it is not a difference between systems, and it does not require any
two columns to be comparable. It is a missing mechanism rather than a judgement
failure, so it does not matter which model drives the write path or whether any
model does. **The control extends it rather than damaging it:** the class of
things with no evidence gate now includes a language model on its own, given
memory-editing tools and told to use its judgement.

Its scope, stated precisely: it holds for AOMS 2.0.0, Letta **V1** 0.16.8, and
qwen3:8b unaided, on this corpus. Whether current Letta has an evidence gate is
**unmeasured and unknown**.

Two smaller things also remain true. The prompt-injection result (`MCB-U-05`,
where both protected payroll facts were deleted on request) is a real and
reproducible fact — about a model with memory-edit tools, not about a memory
architecture. And the asymmetry between the two AOMS columns stands: the
contest-ledger figure is post-hoc, produced by an author who had already seen the
baseline results.

### What was done

- **`RERUN-PLAN-LETTA-SDK.md` is marked SUPERSEDED, not pending**, in both
  repositories, with its three now-false claims listed in the banner rather than
  edited out. Its §1–§6 target research survives; its premise does not.
- **The control is published as a first-class adapter** at
  `adapters/null-ollama/`, with the same five-file discipline as the
  conforming adapters — `adapter.py`, `config.json`, `DISCLOSURE.md`,
  `environment.txt`, `README.md` — plus the scored artifact and the verbatim
  console output of the run. It is labelled `NON-CONFORMING CONTROL`, is not a
  memory system, must never appear as a competitor row, and refuses to execute
  through `runner.py`.
- **AOMS has been removed from every competitive table** in the standalone
  distribution, where the comparison tables live. It is now a reference adapter
  in a clearly non-competing appendix. `GOVERNANCE.md` §13 makes this a rule
  rather than a gesture: the benchmark's author's own system does not appear in
  a comparison the author also scores.
- **`GOVERNANCE.md` §10 already made the bare-model control mandatory** for every
  model-driven adapter, with results reported as *(framework score − control
  score)*. This entry is the first time that rule was applied, and it was applied
  retroactively to the repository's own headline result. §13 was added alongside
  it. These bind AOMS exactly as they bind everyone else.
- **No published result file was edited, re-scored or deleted.** The false
  statements inside the 2026-08-24 entry above are annotated in place with dated
  markers rather than rewritten.
- **The frozen `cases.json` and `score.py` were verified by SHA-256 against
  `FREEZE-MANIFEST.json` before and after this work, and were unchanged**
  (`d5d9db63ad0911110e7cc602a22a6f6e655b9b5fb72261c649a10debdd7ac54f` and
  `7565863b5c02d35d9d3e8dea9dcfa453fd903d618ac9f61280b5b3cc1a9dd98b`). The Letta
  adapter under `adapters/letta/` and `RESULTS-LETTA.md` were not
  touched; they are preserved exactly as they ran.

### Specific to this repository

Six 48-case letta-code runs and a same-day AOMS replication exist here as
untracked result artifacts with no write-up. **They are not published, are cited
nowhere, and must not be cited.** Under `GOVERNANCE.md` §10 each needs its own
bare-model control before it can be published at all, and under §11 each needs a
pre-registration that is a git ancestor of its publication. Running a new adapter
against a current target without a control is precisely the error this entry
records; having the artifacts on disk does not change that.

### A correction inside the correction

The first figure circulated internally for this control was **47 of 48**. It is
46. The number is recorded here because the way the wrong one arose is the same
failure this entry is about.

The control's first harness ran all 48 cases and then **failed at the scoring
step**: it never emitted the per-case `inputs` echo that the frozen `score.py`
requires, so `score_document` refused the document with
`input echo mismatch for MCB-C-01`. Scoring happens after the last case, so the
run burned roughly 25 minutes of local inference — including one case that took
766 seconds on its own — and then discarded every row without writing an
artifact. **It could not have produced a scored figure at all.** Any number
attributed to it was not measured.

The published figure comes from a re-run of the fixed harness
(`adapters/null-ollama/adapter.py`), whose echo fix was verified against the
frozen scorer before the run started, and whose console output is committed
verbatim as `adapters/null-ollama/runner-output.txt`. The freeze hashes were
checked before and after and are unchanged.

The same re-run also corrected a second claim that had already been written into
these documents: that the bare model, like the frameworks, scored 0/12 on the
insufficiently-supported class. It scored 1/12. That is a worse number for the
retirement argument, not a better one, and it is what the artifact says.

Two lessons, both small and both the same shape as the large one:

- **A harness that cannot produce an artifact has not produced a result.** The
  scorer's echo check is exactly the guard that stopped an unscoreable document
  from being published, and it worked.
- **A figure that has not been reproduced from a committed artifact is a rumour,
  including our own.** This entry retires a published comparison for resting on
  an unmeasured assumption; it would have been absurd to do so on an unmeasured
  number.

### The generalisable failure

The 2026-08-24 correction concluded that MCB had a freeze discipline and no
target-validation discipline. This one is narrower and sharper:

**We disclosed a confound instead of measuring it, and treated the disclosure as
the work.**

The confound was correctly identified, described accurately, and stated in three
places in careful language. Then the ranking was published with bold cells
anyway, and the experiment that would have settled it was reclassified as a
funding problem. It was not a funding problem. It was thirty lines of Python and
an afternoon, and the reason it went unrun for a day is that a costed plan to run
a more impressive experiment felt like progress.

A disclosed confound that is never measured is a caveat protecting the author,
not the reader. `GOVERNANCE.md` §10 exists so that this specific move — publish
the ranking, disclose the confound, defer the control — is no longer available.

MCB's claim on anyone's attention is that it corrects itself faster than anyone
catches it. On 2026-08-24 that claim was carried by someone else's email. This
entry is the first time it was carried by our own measurement, and the
measurement cost the repository its headline table.
