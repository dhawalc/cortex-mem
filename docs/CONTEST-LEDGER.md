# The contest ledger — and exactly what opting in costs you

AOMS can tell the difference between "here is a correction to what you already
know" and "here is a second, conflicting answer to a question you already
answered." The second one used to win silently. Now it is kept in full and
held aside until a person decides.

This document is mostly about the **cost**, because the cost is real and you
should meet it here rather than in production.

## The one-paragraph version

Set `claim_key` on a write to name the proposition that record answers. If a
record already answers it and your write does not declare what it replaces,
your write is stored in full, stays searchable, and is listed for review — but
the existing record stays current. Two dispositions exist, `admitted` and
`contested`. Nothing is ever refused, deleted, or truncated.

## It is off unless you turn it on, per write

`claim_key` defaults to `None`, and a record without one cannot be contested
by anything. No importer, recipe, or host integration in this repository sets
it. Every record written before this feature shipped has `claim_key IS NULL`
and behaves exactly as it always did — that is not a promise, it is measured:
the benchmark suite produces case-for-case identical results on the new code
until a caller opts in.

So the question is never "should I turn this off." It is "on which
propositions is a silent second answer unacceptable to me."

## What it costs when you do turn it on

Measured on the frozen MCB-1.0 corpus (`benchmarks/MCB-1.0/`):

| Caller behaviour | False rejection | Valid supersession | Decision accuracy |
| --- | ---: | ---: | ---: |
| **Declares what it replaces** | 0% | 100% | 75% (unchanged) |
| **Does not declare** | **82.35%** | 0% | 50% |

Read that table twice, because it is the whole design. **Where the caller
declares its replacement, the gate costs nothing at all.** Where it does not,
roughly four out of five valid revisions are held instead of applied.

Note carefully what that table does and does not say. It says declaring is
free. It does **not** say that our tool descriptions cause declaring — we
tested that separately and it is not supported. See "Will your agent actually
declare?" below.

The gate reads the *shape* of a write — an occupied slot, different content,
no declared supersession — not the quality of its evidence. It cannot tell a
well-supported undeclared revision from an unsupported one, and it does not
try. That is deliberate: AOMS never judges whether your content is true.

## So: pair `claim_key` with `supersedes`

```python
# First answer to the question. Nothing occupies the slot yet.
remember(kind="fact", content="Catalog price is 100 USD",
         claim_key="catalog-price")            # -> admitted

# A correction that declares what it replaces.
remember(kind="fact", content="Catalog price is 120 USD",
         claim_key="catalog-price",
         supersedes="<id of the record above>")  # -> admitted

# The same correction without declaring.
remember(kind="fact", content="Catalog price is 120 USD",
         claim_key="catalog-price")            # -> CONTESTED, 100 USD stays current
```

If you cannot know the incumbent's id at write time, either read it first
(`search`) or do not set `claim_key` on that write. Setting `claim_key`
without ever declaring replacement is the configuration that produces the
82%, and it is not a configuration we recommend to anyone.

## Will your agent actually declare? Read before writing

**An agent that writes blind cannot declare supersession at all**, because it
has no incumbent id to name. Declaring requires having read first. If your
writer does not `recall` or `search` before it writes, `claim_key` will
contest nearly everything it does, and no amount of instruction will fix that
— there is nothing for "the id of the record you are replacing" to refer to.

We A/B tested the tool descriptions against real models
(`docs/experiments/declare-ab/`). What we found:

- **Claude Code already declares without being told.** 8/8 trials on the
  surface that mentions nothing set the matching `claim_key` and declared
  `supersedes` with the correct id. It reads first, so it has the id. There
  was no gap for guidance to close.
- **qwen3:8b never declared, in either arm.** 0/20 both. It never read before
  writing. The guidance did move `claim_key` adoption (0/20 → 7/20,
  p=0.008) *without* moving declaration — inducing precisely the
  configuration this document warns against. It escaped producing contests
  only by inventing a key that happened not to collide.

So the prerequisite is a capability, not a prompt: **adopt `claim_key` only
for writers that read before they write.**

### Honest limits of that experiment

n=8 and n=4 on Claude Code; the arm difference on write cleanliness was
p=0.061, **not significant**. One task shape, one domain, one seeded fact, and
correction-of-a-known-fact is the friendliest possible case for declaring.

**Known unmeasured:** long sessions where the incumbent's id has fallen out of
the agent's context. That is where we would expect declaration rates to drop
most, and it is the obvious next experiment. Nobody has run it.

## What draining actually costs

The inbox grows with **distinct (claim slot × writing agent) pairs**, not with
write volume. Repeated undeclared writes to the same proposition by the same
agent collapse into one entry with an occurrence count, so a looping agent
cannot bury the queue. Measured:

| Distinct slots | Undeclared revisions each | Agents | Contested records | Inbox rows |
| ---: | ---: | ---: | ---: | ---: |
| 10 | 1 | 1 | 10 | 10 |
| 10 | 10 | 1 | 100 | **10** |
| 10 | 50 | 1 | 500 | **10** |
| 10 | 10 | 3 | 100 | 30 |
| 50 | 10 | 1 | 500 | 50 |

Two consequences worth planning around:

- **Loops are free; breadth is not.** Fifty propositions revised without
  declaration is fifty decisions, however many times each was rewritten.
- **Coalescing is per agent.** A fleet of N agents touching the same slot
  produces N entries, not one, because who wrote it is part of the record.

Every entry needs a verdict, and a verdict is a human act. Budget for that
before opting in a high-breadth writer.

## Resolving

```
cortex-mem contest list [--state open] [--slot KEY] [--by-agent A] [--json]
cortex-mem contest show CONTEST_ID          # both sides, side by side
cortex-mem contest drain [--limit N]        # oldest first; writes nothing
cortex-mem doctor --contests                # projected slot map; writes nothing
```

One entry at a time:

```
cortex-mem contest resolve CID --admit                     # it wins the slot
cortex-mem contest resolve CID --supersede INCUMBENT_ID    # appends a successor
cortex-mem contest resolve CID --set-aside --reason "..."  # decline, reversibly
cortex-mem contest resolve CID --split --claim-key OTHER   # it was a different question
```

A batch, when a misconfigured writer floods the queue:

```
cortex-mem contest resolve-many --set-aside --reason "..." \
    [--slot KEY] [--by-agent A] [--from-source SRC]
```

`--set-aside` is the only bulk verdict, deliberately. Bulk admission would let
one command make many contested claims current at once, which is the shape of
the thing this feature exists to prevent. Set-aside changes nothing about what
is currently true, deletes nothing, is receipted per entry, and is reversible
one entry at a time. The command refuses to run without a narrowing filter.

**Nothing resolves on a timer.** Past `AOMS_CONTEST_SLA_DAYS` (default 14)
`doctor` starts failing; past `AOMS_CONTEST_EXPIRY_DAYS` (default 30) entries
report as `expired-held`. Both are reporting states computed when you look.
No background process has ever changed what AOMS believes, and none does now.

## Who should opt in

**Good fits.** A small set of propositions where two simultaneous current
answers would be actively harmful — a deployment target, a credential
location, an on-call owner, a pricing figure — written by callers that can
declare replacement.

**Poor fits.** Bulk importers (they create rather than revise; every write
lands on a fresh slot anyway, so the key buys nothing). Episodic capture,
where two records about the same topic are a sequence, not a conflict.
High-breadth writers that cannot read before writing.

**Never** set `claim_key` from untrusted content. It is a caller declaration
like any other, and while a hostile key cannot displace anything — that is the
entire point — it can fill your inbox.

## One trigger we removed, and why

An earlier build contested any write whose provenance cited `derived_from` —
intended to stop an agent laundering crafted memory back in as its own claim.
It is off by default now, because it never did that. `derived_from` is
caller-declared and optional, so a writer intent on displacing an occupant
omits it and is admitted; and a write that does *not* declare replacement is
contested anyway. Its only reachable effect was to contest writers honest
enough to record where they had read something.

That was not hypothetical. In the live trials above, **every** contest came
from this trigger and none from slot collision, and in one session the agent
responded by writing itself durable instructions to stop setting `claim_key`
on corrections. It found the escape hatch and documented it for its
successors.

`derived_from` is still recorded on every write receipt and contest entry, so
the audit trail is unchanged; only its power to block is gone. The trigger
remains implemented and can be enabled deliberately.

**Open problem.** A real defence here needs provenance a caller cannot omit:
the server would have to know that a write followed a recall and stamp that
link itself, rather than trusting a self-reported field. That is a new trust
root and a new attack surface, and it is not in this release.

### How we missed it, and what that says about benchmarks

Worth stating plainly, because it is the most transferable thing this feature
taught us.

The trigger survived five runs against our own frozen benchmark, MCB-1.0, and
twelve live model sessions killed it in an afternoon. The benchmark could not
have caught it: a conforming adapter never declares `derived_from`, so the
trigger could not fire on that corpus under any build, and the run measuring
its removal is a verbatim zero
(`benchmarks/MCB-1.0/results-derived-trigger-disabled.json`).

That is not a knock on MCB. We wrote it, we froze it before we ran it, and it
did exactly what it was built to do — it measured write-side state transitions
faithfully and it found real defects, including ones we have not fixed. The
general point is simply that **a benchmark can only measure what its
interchange format can express.** A defect living in a field the format has no
way to carry is invisible to it however many times you run it, and a green run
is not evidence a mechanism works — only that the benchmark could not see it
fail.

The practical rule we would give anyone building something like this: if a
mechanism's safety depends on how a real caller behaves, a frozen corpus with
a conforming adapter cannot tell you whether it works. Put it in front of a
live model before you call it a defence.

## What this does not do

It does not decide whether a claim is true, well-sourced, fresh, or
authorized. On MCB-1.0's insufficiently-supported class AOMS scores 0/6 in
instructed mode before and after this feature, and the same is true of every
other memory system measured on that corpus. This is a write-**authority**
gate: it governs who may displace what. It is not an evidence gate, and we do
not describe it as one. See `benchmarks/MCB-1.0/RESULTS-AOMS-CONTEST-LEDGER.md`
for the full measurement, including the metrics that did not move and the one
that got worse.
