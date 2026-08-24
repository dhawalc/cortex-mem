# AOMS Launch Plan — The Relay Gauntlet

**Date:** 2026-08-23. **Author:** Codex launch-strategy research, curated by orchestrator.
**Strategic frame (the one-liner):** launch a **falsifiable interoperability event**, not a
memory feature list. The relay creates the attention; the artifact and the 1,000-token
teardown convert attention into technical credibility.

## The lead claim

> Claude Code, Codex, and OpenClaw can start cold and resume one another's work — with no
> shared chat or hand-written handoff — using one local AOMS memory whose recalled facts
> are scoped, provenance-linked, and token-accounted.

Narrow enough to prove. Avoid "agents never forget" / "agents get smarter" / "universal
memory" — unfalsifiable claims that invite benchmark wars before the product is understood.

## Flagship demo: cold-start three-agent relay

1. **Planner (Claude Code):** gets several non-obvious user constraints, investigates the
   repo, rejects one tempting approach, records a plan.
2. **Implementer (Codex):** starts cold with only the task name + project scope; recalls
   constraints and plan; implements.
3. **Reviewer/fixer (OpenClaw):** starts cold, gets a newly revealed regression clue,
   recalls both prior stages, finishes.
4. **Verifier:** checks behavior, hidden constraints, scope isolation, provenance
   completeness, token ceilings.

First 10 seconds of the clip: three empty context windows, then agent two correctly
stating the inherited constraints. The rest establishes how.

## The proof artifact: AOMS Relay Protocol

The launch artifact is a **runnable harness**, not a video (the video is just a compressed
execution of the public protocol):

```
aoms demo relay --agents claude,codex,openclaw --seed 7319 --with-baseline
```

Emits an immutable bundle: scenario + seed, fixture repo hash, versions, each agent's
exact initial prompt (hashed pre-run), proof of fresh sessions, all MCP request/response
JSONL, recall receipts (scope, provenance, token count, latency), diffs, deterministic
test results, memory-disabled baseline, verifier output, manifest hashes.
Three modes: full 3-client live; any-2-client; deterministic replay (no model accounts).

## Supporting content: "Anatomy of a 1,000-token handoff"

Static generated teardown of one flagship recall: query + scope, candidate set, selected
vs rejected memories, superseded events, provenance paths, exact serialized token count,
latency + hardware, final model context, and ablations (vector-only / no-scope /
no-provenance / no-budget). This answers the most dangerous dismissal: "it's just a
vector DB."

## Concept scoreboard (visceral / honest / feasible / repeatable, 1-5)

| Concept | V | H | F | R |
|---|--:|--:|--:|--:|
| 1. Cold-start three-agent relay — **FLAGSHIP** | 5 | 5 | 4 | 4 |
| 2. Kill the agent; continue the work | 5 | 5 | 3 | 4 |
| 3. 1,000-token pressure cooker — **SUPPORTING** | 4 | 5 | 5 | 5 |
| 4. Memory ON/OFF longitudinal league (post-launch research) | 4 | 4 | 2 | 3 |
| 5. Six months of agent memory (privacy work gates it) | 4 | 4 | 2 | 3 |
| 6. Scope-firewall collision (strong 2nd demo) | 4 | 5 | 4 | 5 |
| 7. Corruption-and-recovery forensic case (launch content) | 4 | 5 | 3 | 4 |
| 8. Offline brain transplant | 4 | 5 | 3 | 4 |
| 9. Provenance courtroom | 3 | 5 | 4 | 5 |

## Anti-dismantling defenses (publish objections under the demo, linked to artifact fields)

- "Handoff hidden in the prompt" → publish + hash initial prompts; capture fresh-process
  commands; record all context inputs.
- "Agents read the answer from git" → runtime-injected constraints that don't exist in
  the fixture repo, revealed in the final artifact.
- "Sabotaged baseline" → identical prompts/tools/repo/settings; only memory availability
  changes.
- "Cherry-picked run" → fixed seeds, batch runner, per-run data incl. failures.
- "Just a vector DB" → ablations show scoping, provenance, supersession, and budget
  packing each change a measurable outcome.
- "Local-first except the model calls" → state precisely: AOMS storage/retrieval are
  local; model clients are not claimed offline.
- "Scope demo hides results in the UI" → prove prohibited memories never enter the
  serialized model context (canary facts).

## Build plan (~11–14 eng days, P3/P4 workstream)

| Component | Est. |
|---|--:|
| Scenario fixture (real repo, hidden runtime constraints, deterministic tests) | 1–1.5d |
| Relay runner (fresh-process orchestration, 3 client adapters) | 2–3d |
| Recall receipt (stable JSON: query, scope, candidates, selections, provenance, tokens, latency) | 1.5–2d |
| Artifact capture (prompts, MCP JSONL, diffs, hashes, manifest) | 1d |
| Baseline + ablations | 1–1.5d |
| Independent verifier | 1–1.5d |
| Reproduction packaging (preflight, pinned versions, 2-client + replay modes) | 1–1.5d |
| Static "Anatomy" report generator | 1d |
| Hardening, clean-machine dry runs, compat matrix | 1.5–2d |

**Key product decision:** the recall-receipt schema is a PRODUCT capability (late P2/early
P3), not demo-only code.

## Roadmap placement

- **Early P3:** freeze relay protocol + verifier before collecting results; receipt schema;
  fixture + deterministic scoring; 2-client adapters.
- **Late P3:** third client; dogfood-derived scenarios; multi-seed runs keeping failures;
  replay mode; clean-machine install.
- **P4:** tagged artifact + compat matrix; generate teardown; record split-screen video
  from the tagged protocol; publish limitations + expected objections alongside.

## Launch exit criteria (all required before scheduling the public moment)

- Clean installer reaches the demo in <10 minutes.
- All agents demonstrably start without upstream transcripts.
- ≥3 hidden constraints cross each handoff correctly, each with a valid source.
- Serialized recall stays under the declared token ceiling.
- Out-of-scope canary facts never enter model context.
- Deterministic repo tests pass.
- Memory-disabled + ablation results included unfiltered.
- **Another person reproduces the result from the public instructions.**
