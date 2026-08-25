# Outreach — Letta Code cycle

Three messages the publication plan requires. **None has been sent.** The run
that drafted them had no authority to send email, so they are committed here as
drafts for whoever does. Their unsent status is stated in
`PREREGISTRATION-LETTA-CODE.md` §2 and in `adapters/letta-code/CURRENCY.md`, and
it is the reason every result in this cycle carries the *unratified execution
mode* qualifier in its title rather than in a footnote.

Message 2 was meant to go out **before case 1**. It did not, so the independent
timestamped copy of the plan that it was supposed to create does not exist. The
weaker substitute is the git history of this repository: commit `055792b`
contains the full pre-registration and is an ancestor of every results commit.
That is worth less than an outside party holding a copy, and the difference
should be stated rather than glossed.

---

## Message 1 — now (acknowledgement)

> Subject: Our MCB benchmark measured the wrong Letta — correction published
>
> Thank you for the correction. The error is ours.
>
> We benchmarked Letta server 0.16.8 and published the result under the
> unqualified name "Letta". That version is a deprecated architecture, and
> labelling it that way misrepresented what you ship. The correction is recorded
> in `CORRECTIONS.md`, crediting you. Nothing has been deleted or edited — the
> original numbers stay published so that the size of our error stays checkable.
>
> We are re-running against Letta Code 0.30.31 with MemFS. Before we publish
> anything, four questions gate whether that measurement is fair, and we would
> rather have your answer than our guess:
>
> 1. Is `letta-code --backend local` (gated by `LETTA_LOCAL_BACKEND_EXPERIMENTAL`)
>    a fair measurement target, or would you consider only the cloud backend
>    representative of what you ship?
> 2. Which MemFS surface should count as the system's durable state?
> 3. Can an obsolete statement be made non-current there — and if so, by what
>    operation?
> 4. Would you veto or ratify the adapter we have written? It is committed at
>    `benchmarks/MCB-1.0/adapters/letta-code/`.
>
> Until we have your answer to (1), every number we publish from this cycle is
> titled as measuring an unratified, vendor-gated experimental execution mode.

## Message 2 — before case 1 (NOT SENT; window missed)

> Subject: Pre-registration for the Letta Code run, before we execute it
>
> Attached is the pre-registration for the run, committed before the first case
> executes: the pinned package and integrity hashes, our durable-state
> definition, the isolation and latency boundaries, every prompt string
> verbatim, the number of runs, our numeric predictions, and the paragraph we
> will publish for each direction the result could go.
>
> sha256 of `PREREGISTRATION-LETTA-CODE.md`: `<fill in at send time>`
> git commit: `055792b`
>
> We are sending it now so that someone outside our repository holds a
> timestamped copy of the plan, and can tell later whether we moved the
> goalposts after seeing the numbers.

## Message 3 — with results, before publication

> Subject: Letta Code MCB results — 7 days before we publish
>
> Full results and raw per-case JSON attached, including the runs that are bad
> for us and the bare-model control that shows how much of any framework's score
> on this corpus is attributable to the model rather than the framework.
>
> We will publish on schedule in 7 days regardless of whether you reply. If you
> do reply, we will publish your response verbatim at equal prominence with our
> own findings, and we will run and publish any adapter you prefer.
>
> The specific claims we would most like you to dispute: our definition of
> durable state as the MemFS working tree, our use of the experimental local
> backend, and our persona, which we wrote and you have never seen.
