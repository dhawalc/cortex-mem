# Does tool-description guidance make a model declare what it replaces?

The recommendation in `docs/CONTEST-LEDGER.md` rests on a claim that had never
been tested against a real model: that telling a caller to set `supersedes`
is what turns an 82% false-rejection rate into 0%. This is the test.

It found something else, which matters more.

## Design

Two arms, differing in nothing but the model-facing text:

| | Arm A | Arm B |
|---|---|---|
| AOMS source | `dfc68b6` | `bb4ee62` |
| `remember` description mentions supersedes/claim_key | no | yes |
| parameter descriptions | all `None` | present |
| tools, parameters, schema types, storage, task, temperature | identical | identical |

The task seeds one fact (`staging-deploy-target` → `cluster-west-2`) and then
describes a migration to `cluster-east-1`, asking only that "AOMS memory is
correct for whoever picks this up next session." **It never mentions
`supersedes`, `claim_key`, contesting, or how to write.** If the prompt had to
say it, the experiment would be measuring the prompt.

Measured per trial: whether the agent read before writing, set `claim_key`,
matched the incumbent's key, declared `supersedes` with the correct id, cited
`derived_from`, and produced a contested write — plus whether the store ended
with one clean admitted correction or with two current values.

Trial order alternates arms, and both arms get the same sampling seed.

## Subjects

- **qwen3:8b** via local Ollama, temperature 0.7, n=20 per arm, 80 model calls.
- **Claude Code** headless (`claude -p --strict-mcp-config`) against a scratch
  store, n=8 arm A / n=4 arm B, 12 sessions. `--strict-mcp-config` guarantees
  the machine's real AOMS registration is never loaded.

## Results

### Claude Code — the representative subject

| | Arm A (no guidance) | Arm B (guidance) | p |
|---|---:|---:|---:|
| declared `supersedes`, correct id | **8/8 (100%)** | **4/4 (100%)** | 1.00 |
| set the incumbent's `claim_key` | **8/8 (100%)** | **4/4 (100%)** | 1.00 |
| cited `derived_from` | 6/8 (75%) | 0/4 (0%) | 0.061 |
| one clean admitted correction | 2/8 (25%) | 4/4 (100%) | 0.061 |

**The premise was wrong.** Claude Code already declares what it replaces,
with the correct id, without any guidance at all — 8/8 in the arm that says
nothing. There was no gap for the guidance to close.

**And every contest came from T3.** Six contests were observed across all
trials; 6 of 6 fired `derived-from-memory`, 0 of 6 fired `slot-collision`.
The agent read the incumbent, corrected it, declared `supersedes` correctly,
honestly recorded in `derived_from` the record it had read — and was contested
*for the citation*.

In one trial the agent then wrote itself this, as durable memory:

> How to correct an already-admitted fact in this AOMS store: append a
> successor record with `supersedes: <old-record-id>` and DO NOT set the
> incumbent's `claim_key`. … If the successor carries the incumbent's
> `claim_key`, it enters claim adjudication, gets disposition "contested", and
> is WITHHELD from recall while the stale incumbent keeps being served.

It found the escape hatch and documented it for future sessions.

### qwen3:8b — a weaker model

| | Arm A | Arm B | p |
|---|---:|---:|---:|
| read before writing | 0/20 | 0/20 | 1.00 |
| set `claim_key` | 0/20 (0%) | 7/20 (35%) | **0.008** |
| …matching the incumbent's key | 0/20 | **0/20** | — |
| declared `supersedes` | **0/20 (0%)** | **0/20 (0%)** | 1.00 |
| left two current values | 20/20 | 19/20 | 1.00 |

The guidance moved `claim_key` adoption significantly and moved `supersedes`
declaration **not at all**. That is the configuration `docs/CONTEST-LEDGER.md`
explicitly warns against, and the guidance induced it.

The binding constraint is not knowing to declare — it is **reading before
writing**. This model never read, so it never had an id to declare, and the
conditional instruction ("set supersedes to the id of the record you are
replacing") had nothing to bind to. It was saved from contests only by key
drift: it invented `staging-deployment-cluster` rather than matching
`staging-deploy-target`, so nothing ever collided.

## Confidence

The Claude Code differences are **p = 0.061, not significant at 0.05** with
n=8/4. Treat "guidance produces cleaner writes" as suggestive only.

Two findings do not depend on sample size:

1. **Claude Code declares without guidance** — 8/8 and 4/4 are both at
   ceiling; there is no effect to detect.
2. **T3 punishes honest citation** — deterministic on the decision function,
   not a sampled rate:

   ```
   declares supersedes + cites derived_from  ->  contested
   declares supersedes, omits derived_from   ->  admitted
   ```

   `derived_from` is caller-declared and optional, so a writer that wants to
   displace an occupant omits it and is admitted. The only outcome T3 ever
   changes is to contest a writer honest enough to say where it read
   something.

## Reproducing

```
python harness.py --trials 20 --condition unprompted --output out.json   # Ollama
./cc_trial.sh armA 1 unprompted                                          # Claude Code
python analyze.py out.json ; python cc_analyze.py ; python stats.py
```

Arms are materialized with `git archive dfc68b6` and `git archive bb4ee62`
into `/tmp/decl/armA` and `/tmp/decl/armB`. No git worktree is modified, and
every store is a fresh scratch database under `/tmp`.
