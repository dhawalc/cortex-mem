# MCB-1.0 — Governance

Rules that bind how this benchmark is run and published. They were written after
a published result turned out to have measured the wrong thing, and they exist
to make that class of error visible rather than merely less likely.

## §9 — Currency evidence (new; retroactive)

**Every adapter ships a `CURRENCY.md` carrying dated vendor evidence.**

At minimum it records, each with the date it was established:

1. The exact package or release measured, with a verifiable integrity hash.
2. The version string the software reports about itself when run.
3. The execution mode measured, and whether that mode is one the vendor
   presents as current, deprecated, experimental, or gated.
4. Whether the vendor has ratified the adapter's definition of durable state —
   and if not, that it has not, stated plainly.

**If currency cannot be evidenced, the qualifier goes in the title of the
result, not in a footnote.** A reader who quotes only the headline must not be
able to quote a claim the evidence does not support.

This rule is retroactive. Existing adapters need a `CURRENCY.md` too, and where
the evidence shows a published result measured a deprecated or non-current
target, the correction is an added note and a re-titled result — never an edit
to the published numbers.

Rationale: the failure this repository actually suffered was not a coding error
and not a scoring error. It was measuring a version the vendor no longer shipped
and publishing the result under the vendor's bare name. No amount of care inside
the measurement would have caught it, because the measurement was internally
correct. Only dated external evidence catches it.

## §10 — Mandatory bare-model control

**Every model-driven adapter publishes a bare-model control alongside its
result**: the same corpus, the same prompts, the same model, with the framework
removed from the stack entirely.

The framework's contribution is *(framework score − control score)*. A framework
score published without its control is a claim about a model wearing a
framework's name.

**If the control matches the framework within run-to-run spread, the published
headline is "the framework's contribution is indistinguishable from zero on this
corpus" — not a system score.** This binds regardless of which framework the
result embarrasses, AOMS included.

Controls are non-conforming by construction — there is no system under test in
the MCB sense — so they are always labelled `NON-CONFORMING CONTROL` and never
appear in a conforming results table without it.

## §11 — Pre-registration

Any run intended for publication is pre-registered in a committed file whose
commit is a **git ancestor** of the commit publishing the results. The
pre-registration fixes, before case 1: the pinned system, the durable-state
definition, the isolation and latency boundaries, artifact hashes, every prompt
string verbatim, the number of runs, numeric predictions, and the outcome
paragraphs for each direction the result could go.

**Editing the adapter, prompts, or config after case 1 voids that attempt.** A
voided attempt is published as a numbered abandoned attempt, not deleted.

Every completed run is published, including runs that are bad for us. A run may
be discarded only for a documented infrastructure failure, and the discard and
its partial artifact are published too.

## §12 — Published results are append-only

A published result is never edited, re-scored, or deleted — not to fix it, not
to improve it, and least of all to remove an embarrassment. Corrections are new
files that link back to what they correct, so the size of any error stays
checkable by anyone who reads the repository later.

## §13 — The benchmark's author does not appear in its comparison tables

AOMS is written by MCB's author. It is published as a **reference adapter** — a
worked example of the adapter contract, and a scored artifact — and not as a
competitor. It does not appear in a comparison table, a ranking, or a
bolded-winner column.

The conflict-of-interest disclosure requirement mitigates the situation; this
rule removes it, which is stronger. Adopted 2026-08-25 alongside the retirement
of the cross-system comparison (`CORRECTIONS.md` entry #2). Before that date AOMS
did appear in comparison tables; those tables are preserved in git history rather
than pretended away.

## §10 in practice — the first application, against ourselves

§10 was written on 2026-08-24, in the aftermath of discovering the benchmark had
measured a deprecated product. It was first *applied* on 2026-08-25, to MCB's own
headline result, and it retired that result: a bare-model control reproduced the
published Letta column with no framework in the stack, so the framework's
measured contribution was indistinguishable from zero.

Recorded here because a rule that has never cost its author anything is not yet
evidence of anything. This one cost the repository its comparison table on the
first occasion it was applied.
