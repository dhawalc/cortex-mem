# Draft: upstream issue for letta-ai/letta

> # ⚠ SUPERSEDED — DO NOT POST
>
> **This draft is obsolete and must not be posted in its current form.** It asks
> `letta-ai/letta` to validate an adapter for a product they have retired.
>
> Upstream contact has since happened, by a different route. **Sarah Wooders of
> Letta wrote on 2026-08-24 at 20:46:**
>
> > Hi - the letta repo is deprecated. If you are looking to benchmark letta
> > code, please use the agents SDK or letta code directory
> > https://docs.letta.com/agent-sdk
> > https://github.com/letta-ai/letta-code
>
> That answers this draft's premise rather than its questions. The three
> questions below were asked about V1 memory semantics; the corresponding
> questions for Letta's current architecture are restated as Q1–Q6 in
> [`RERUN-PLAN-LETTA-SDK.md`](RERUN-PLAN-LETTA-SDK.md).
>
> Retained verbatim as the record of what we were about to ask. See
> [`CORRECTIONS.md`](CORRECTIONS.md).

Status: SUPERSEDED — never posted. Original status line follows.

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

---

## POSTED — evidence record

- **Public issue:** https://github.com/letta-ai/letta/issues/3437
  Posted 2026-08-24 by dhawalc. Title: "External memory-conflict benchmark: request for
  validation of Letta adapter semantics". Contains no security detail.
- **Security disclosure:** emailed support@letta.com 2026-08-24 per letta-ai/letta
  SECURITY.md ("Do not open a public issue for security vulnerabilities"). Gmail thread
  id 1a035b35b4981950. Covers MCB-U-05 only; states plainly that the transcript was
  already public before their policy was read, and offers takedown/redaction on request.
- **Artifact SHAs cited:** adapter 7edb3d1, results 3df82b0, spec+cases b10a3f5.
  Frozen files unchanged: cases.json d5d9db63…, score.py 7565863b….

### If a maintainer responds
Preserve the original adapter commit, their correction, the correcting commit, and BOTH
runs side by side. Never replace a published result — the correction trail is the evidence,
and it is worth more than a favourable number.

### If no maintainer responds
Freeze this as-is. Do not manufacture further self-validation; take MCB-1.0 to a different
independent framework instead.

### OUTCOME: issue 3437 auto-closed 2026-08-24 — venue was wrong

github-actions[bot] closed it for missing required disclosures (repository acknowledgment
phrase, anti-spam checkbox, third-party product disclosure + relationship, AI policy
acknowledgment, authorship option, AI tools used).

Root cause was mine and it was venue, not wording: letta-ai/letta sets
`blank_issues_enabled: false` and ships NO issue templates — only a config.yml routing
harness/CLI issues to letta-ai/letta-code, questions to Discord, and docs to docs.letta.com.
I checked ISSUE_TEMPLATE, saw only config.yml, and wrongly concluded "no templates, so a
plain issue is fine." The correct reading was "this repo does not take issues."

Do NOT refile the same request into letta-ai/letta-code: that repo is for the current agent
harness/CLI/App Server, its templates are bug_report and feature_request, and an
adapter-semantics validation request is neither. Refiling after an auto-close would read as
spam.

CORRECT REMAINING VENUE: Discord (https://discord.gg/letta), per their own routing.
Requires a human account.

NOTE FOR ANY REFILING: Letta requires an AI disclosure naming every AI tool used. This
request was AI-assisted — drafted by Claude (Claude Code) under Dhawal's direction. Any
resubmission must say so plainly.

STILL VALID AND UNAFFECTED: the security disclosure to support@letta.com (thread
1a035b35b4981950) went through their documented channel and stands on its own.

### RESUBMITTED VIA THE OPEN CHANNEL — 2026-08-24

The adapter-semantics request was sent to support@letta.com (Gmail thread 1a035ee43aae4b74),
the channel Letta themselves opened for the security report. Rationale: letta-ai/letta does
not accept issues; letta-code is the wrong product; Discord needs a human account. Asking in
an already-open thread with a human on the other end beats forcing a closed venue, and the
email explicitly invites them to redirect it if they prefer Discord.

The email carries a truthful AI DISCLOSURE per Letta's AI policy — AI-assisted, tools named
(Claude / Claude Code, OpenAI Codex CLI) — and states which judgements were the author's.
Claiming human authorship was declined: their policy asks the question directly, and a false
answer would discredit the benchmark rather than just the message.
