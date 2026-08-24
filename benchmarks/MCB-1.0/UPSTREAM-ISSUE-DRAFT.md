# Draft: upstream issue for letta-ai/letta

Status: DRAFT — not posted. Prepared 2026-08-24. All links verified publicly reachable.

**Title:** External memory-conflict benchmark: request for validation of Letta adapter semantics

---

I've been developing MCB-1.0, an implementation-independent benchmark for one narrow
persistent-memory problem: how durable agent state behaves when a subsequent observation is
consistent, contradictory, legitimately superseding, or insufficiently supported.

I implemented a Letta adapter and ran the frozen case set. Before drawing comparative
conclusions from it, I'd like to check that the adapter actually represents Letta's intended
memory semantics — I'd rather be corrected than publish a confidently wrong reading of your
architecture.

**Artifacts** (immutable commit links):

- Adapter: https://github.com/dhawalc/cortex-mem/blob/7edb3d1d5a0d046b64e7f41f2dd25fae6d9b2fc7/benchmarks/MCB-1.0/adapters/letta/adapter.py
- Raw results: https://github.com/dhawalc/cortex-mem/blob/3df82b07269660c8ef8489d772a95048bd3efb7a/benchmarks/MCB-1.0/adapters/letta/results.json
- Specification: https://github.com/dhawalc/cortex-mem/blob/b10a3f5111e4101ac7173a8b7d86bba168b5c272/benchmarks/MCB-1.0/SPEC.md
- Frozen cases: https://github.com/dhawalc/cortex-mem/blob/b10a3f5111e4101ac7173a8b7d86bba168b5c272/benchmarks/MCB-1.0/cases.json
- Write-up: https://github.com/dhawalc/cortex-mem/blob/mcb-1.0/benchmarks/MCB-1.0/RESULTS-LETTA.md

**Environment:** letta 0.16.8 (tag commit `1131535716e8a31c9a437f8695e25ac98f203a24`),
letta-client 1.12.1, fully local — Ollama `qwen3:8b` for the LLM and `nomic-embed-text` via
the OpenAI-compatible endpoint for embeddings, isolated PostgreSQL. One agent per case,
sleeptime disabled. Scoring reads programmatic durable-state readback only, never the
conversation, since messages are themselves persisted.

The adapter contains no benchmark-specific decision policy — it maps four operations
(establish durable state / provide observation / let the system process / retrieve durable
state) onto Letta's API and hands the resulting state to a deterministic scorer. Every
add/replace/delete in the run was chosen by the Letta agent, not by the adapter.

**The three things I'd most like corrected:**

1. **Durable-state target.** I scored against core memory blocks rather than archival
   passages, reasoning that MCB requires obsolete statements to *cease being current*, and
   `memory_replace` is the only primitive where that transition is expressible — archival
   has insert and search but no delete or replace. I also ran archival as a secondary
   (results-archival.json) and it scores far worse, which I read as confirming the choice
   rather than as a finding about Letta. Is core memory the right target, or is there an
   intended composition of both I've missed?
2. **State retrieval.** I read back via `client.agents.blocks.list/retrieve`. Does that
   accurately reflect what Letta considers the agent's durable state at that point?
3. **Case semantics.** Do any cases assume a model of memory that conflicts with Letta's
   design? MCB-U-10 produced a structural failure in my run (two current values under one
   topic) and that may be my modelling rather than yours.

**Security-adjacent observation.** One case in the run produced behaviour I judged security-adjacent. Per your SECURITY.md I have emailed the details to support@letta.com rather than describing them here. The raw per-case transcript is present in the linked results.json, which was already public before I read your policy — flagging that so you can judge urgency.

**Disclosure:** I'm the author of MCB-1.0 and also of AOMS, one of the systems it evaluates,
so this is not a neutral comparison and I don't present it as one. On the headline metric
Letta scored materially better than my own system (75.0% vs 50.0% decision accuracy, and
12/12 vs 0/12 on autonomous supersession); my system scored better on unauthorized overwrite
(15.6% vs 40.6%). Both systems scored 0/12 on insufficiently-supported observations —
neither has a write-side evidence gate — which I think is the more interesting result and is
a statement about the state of the art rather than about either implementation.

MCB measures one constrained property. It is not an overall ranking of memory frameworks,
and individual metrics will matter more or less depending on architecture.

If the adapter is wrong, I'll preserve the original run and publish a corrected one
alongside it rather than replacing it.

---

## Notes for the poster (not part of the issue)

- Check Letta's CONTRIBUTING / SECURITY policy before posting; if they have a security
  disclosure process, consider sending the MCB-U-05 paragraph there first and linking it
  here instead.
- Consider Discussions rather than Issues if their repo routes non-bug topics there.
- Archive the issue URL and timestamp once posted; preserve every maintainer response.
- If a maintainer identifies an adapter error: keep the original adapter commit, their
  correction, your correcting commit, and both runs. The correction trail is worth more
  than a favourable number.
