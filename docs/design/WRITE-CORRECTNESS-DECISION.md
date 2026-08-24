# Provenance

> Opus design panel, 2026-08-24. Simulator-verified against the frozen MCB-1.0 baseline.

I verified every load-bearing claim against the tree and ran a simulator that reproduces the frozen baseline exactly. Two judge-level facts were wrong and one proposal-level fact was wrong in all five proposals. The decision document follows.

---

# AOMS WRITE-SIDE CORRECTNESS — DECISION DOCUMENT

**Decider's note on evidence.** Every code claim below was re-verified in the `v2` worktree. Every MCB number was produced by local scratch simulators that reproduce the committed baseline to four decimals (DA 50.00/75.00/25.00, UOR 15.62/29.41/0.00, VSR 50.00/100.00/0.00, FRR 0.00, 24/48 passed, 18 structural errors) before projecting anything. The scratch simulators were not committed.

---

## 1. THE VERDICT

### Winner: the Contest Ledger (Lens 4), with the Policy Engine's structural discipline grafted into it.

The two finalists across all three judges were the Policy Engine and the Contest Ledger. I simulated both. **They produce byte-identical MCB results**, because the entire conforming delta in both designs comes from one mechanism: a caller-declared proposition key plus withholding on an undeclared collision. The Policy Engine's additional apparatus — a TOML DSL, four record states, a 200-rule cap, `lint`/`diff`/`explain`, three partial unique indexes — buys **zero** additional correctness on the benchmark and adds the largest conceptual surface of any proposal to an 8,234-line codebase.

The Contest Ledger wins on four grounds I can defend to a builder:

1. **Equal correctness at lower conceptual cost.** Verified: identical numbers.
2. **Strictly better on constraint 1.** Two dispositions — `admitted` and `contested`. There is no `refuse` and no `drop`. The Policy Engine retains a `refuse` outcome with a `retain_payload` flag that can be set false: a configurable evidence-discard path in a product whose credibility rests on never discarding evidence. The custodian flagged this and is right. The Contest Ledger proves the product does not need that door at all.
3. **It is the published roadmap.** `docs/launch/FEATURE_GAPS.md` already commits to a contradiction inbox with "conflict suggestions... as a review queue with provenance and not-a-truth-judgment labeling" and "Suggestions require human review." This ships the thing we already promised. It requires the least README rewriting, which is the custodian's actual test.
4. **The Policy Engine is its natural v2.** The Contest Ledger's `T3 policy-hold` trigger is exactly the seam a declarative rule layer plugs into later, with no rework of the disposition vocabulary. We are sequencing, not discarding.

### Grafted, non-negotiable

| From | Graft | Why |
|---|---|---|
| **Minimalist (L1)** | **The in-place upsert guard.** Ships **first, standalone, as a bug fix.** | Verified live at `aoms/repositories/sqlite.py:463` — `ON CONFLICT(id) DO UPDATE SET ... record_json = excluded.record_json`, reached from `remember()` via `_remember(create_only=False)`. `_parameter_signature` (`mcp_server.py:168-188`) reflects `RememberRequest.model_fields` into the flat tool signature, so `id` **is** a model-settable argument. `remember(id=<existing>, content=<anything>)` replaces a retained record's content in place today — no predecessor, no lineage, invisible to `diagnose_chains`. Every gate in every other proposal is one tool argument away from irrelevant until this closes. Only L1 found it. |
| **Policy Engine (L2)** | **Content-free decision function, enforced by signature.** `decide(intent, slot, *, now)` where `WriteIntent` carries `content_sha256` and never record text. Plus a **ruleset digest stamped on `RecallReceipt`, not only on write receipts.** | Makes constraints 1 and 4 structurally true rather than promised, and permanently forecloses the keyword-matching hack. The `RecallReceipt` catch is the sharpest single insight in the exercise: once anything is withheld from packing, the same store under two configurations packs different context, and a recall receipt that does not name the configuration in force has silently stopped being a complete explanation of its own output — breaking `README:11`. `receipts.py:5-7` expressly permits additive v1 fields. |
| **PAM (L3)** | **`derived_from` can never displace.** A write whose provenance cites recall receipt ids or memory ids contests instead of displacing. | The only mechanism proposed anywhere that *blocks* rather than *reports* the laundering attack: an agent reads crafted memory, re-asserts it as its own write. Constraint 4 on the write side. Taken **without** PAM's grade lattice and registry (see rejections). |
| **Evidence-graded (L5)** | **The non-comparable migration sentinel.** New participation columns default to a value that *opts the row out of the gate*, never to the bottom of an order. | Defaulting 165k legacy rows to a comparable weak value would let the first post-upgrade write dominate everything written before the feature existed — the migration becomes the overwrite vector. This is the 2026 decay incident with a new trigger. Best migration-safety observation in the set. Here: `claim_key IS NULL` means "not participating," and today's semantics apply unchanged. |
| **Contest Ledger (L4, its own)** | **Notice-channel hygiene.** Any id surfacing into a recall payload is server-generated `uuid4`, never derived from caller input; the notice on a surviving incumbent carries integers, server UUIDs and one timestamp — zero challenger prose. | `RememberRequest.id` accepts 256 arbitrary characters (`models.py:113-115`, verified). L4 found an injection vector inside its own design and closed it. Note `_memory_payload` (`recall.py:344`) emits `record.provenance.model_dump(mode="json")` straight into the model's context — so this rule binds any new provenance field too. |

### Explicitly rejected, with reasons

**1. Any claim that UOR moves on MCB-1.0. Rejected as unreachable.**

I dumped what actually arrives at the AOMS boundary for all 24 INSTRUCTED cases. The five unauthorized overwrites (U-01/03/07/09/11) and the twelve valid revisions (X-01…11 odd, S-01…11 odd) are **structurally identical**: `explicit=True, displacements=1`, one `supersede(old_id, content)` call with clean assertional text and no source. The discriminator exists **only** in observation prose. Reading it is either AOMS judging content (violates constraint 1) or the adapter making the write decision (violates `SPEC.md:121-122`). There is no third option. **UOR stays at 15.62% / 29.41% and we will publish it that way.**

**2. The Minimalist's `disclaimer_markers` re-run. Rejected as non-conforming.** I ran the proposed list against the corpus: **10/12 U-case hits, 0/36 false positives.** A flawless discriminator with no false positives anywhere in 36 non-target cases is the fingerprint of a list reverse-engineered from an answer key. `SPEC.md:121-122` permits an adapter to translate "an explicit INSTRUCTED operation into the system's documented write primitive" — that is precisely and only what the existing `instruction_markers` list does (choose `supersede` vs `remember`). Mapping prose sentiment to an evidentiary field manufactures a verdict in the adapter, and that verdict is the sole cause of the rejection. L1's own honest delta is zero, as it stated first.

**3. PAM's attribution extraction and its 72.9% headline. Rejected as non-conforming and unsubstantiated.** PAM's empirical reading of the corpus is *correct* and worth recording — I verified 18/18 AUTONOMOUS cases carry a third-party attribution clause and 0/12 INSTRUCTED-revise cases do. But that binary is computed by the adapter from prose, and in an empty registry `attributed → refuse` / `unattributed → accept` *is* the write decision. PAM also claims U-03 has "two independent reasons"; both reduce to parsing `as of 2025-01-10` out of statement text (verified: the dates live inside `initial_state[0].text`). Adopt PAM's mechanics; do not publish PAM's number.

**4. PAM's authority registry and Evidence-graded's 5-level ordinal lattice. Rejected for v1.** A registry is a new trust root, a new high-value attack surface, and a permanent curation burden, with no conforming benchmark payoff. An ordinal credibility grade is the most truth-score-shaped artifact proposed, it will be averaged and thresholded by someone eventually, and it renders directly into the model's context via `_memory_payload`'s provenance dump. Both are deferrable; neither is needed for the delta.

**5. The Policy Engine's TOML DSL and `refuse` disposition. Deferred to v2 / rejected respectively.** See above.

**6. Storing declined writes only in a receipt. Rejected — and this is the fix for the custodian's disqualification, which I verified.** `_save_recall_receipt_sync` (`sqlite.py:1342-1373`) executes a `DELETE FROM recall_receipts WHERE receipt_id NOT IN (... LIMIT ?)` with `self.receipt_retention` (default 1000) **inside the same transaction as every single insert**. Receipts are a self-trimming ring buffer, on write, unattended — not on `cortex-mem maintain` as L1 assumed. Under L1 as specified, the only surviving copy of a refused claim is silently destroyed after 1000 subsequent receipts by a background mechanism. That is the decay-endpoint shape wearing a receipt. In this design the record is **admitted to `memories`** and the receipt carries only the decision, and `write_receipts` is additionally **exempt from ring-buffer retention**.

### Correction that overrides all three judges and all five proposals

> **`LATEST_SCHEMA_VERSION` is 6, not 5. The new migration is 7, not 6.**

`sqlite.py:56` reads `LATEST_SCHEMA_VERSION = 6`. `MIGRATIONS` has keys 1–6, where `6: ""` is a deliberate placeholder dispatched to `_migrate_fts_rowids` by a `if version == 6:` branch in `_initialize_sync`. Every proposal specified "`LATEST_SCHEMA_VERSION` 5 → 6, new `MIGRATIONS[6]`" and all three judges "confirmed" it.

A builder who follows that instruction overwrites the FTS-rebuild placeholder **and** — because every existing store has already recorded version 6 in `schema_version` — the new schema is **never applied to any existing database**, while `LATEST_SCHEMA_VERSION` claims it was. Silent, permanent, and exactly the failure class this work exists to prevent. **Use `MIGRATIONS[7]` and `LATEST_SCHEMA_VERSION = 7`.**

---

## 2. THE DESIGN

### 2.1 The primitive

A **claim slot** is `(scope, scope_agent_id | scope_workspace_id, claim_key)`. `claim_key` is a caller-declared, non-semantic identity for the *proposition* a record answers — not the answer. It is the topic-shaped sibling of the record-shaped `supersedes`: the same class of declaration AOMS already accepts, at coarser granularity. **AOMS never derives `claim_key` from content.**

`claim_key IS NULL` ⇒ the record does not participate. No trigger can fire. Behavior is byte-identical to today. Every existing record and every existing caller is unaffected, with no backfill.

### 2.2 Two dispositions. There is no third.

| Disposition | Stored in `memories` | Searchable (CLI/operator) | Packs into recall | Holds the slot |
|---|---|---|---|---|
| `admitted` | yes | yes | yes | yes |
| `contested` | **yes, in full** | **yes** | no | no |

`contested` does not mean false. It means *not yet adjudicated by a human*. Nothing is refused, nothing is deleted, nothing is truncated, nothing is rewritten.

### 2.3 Contest triggers — all structural, none reads content

Evaluated by `decide(intent: WriteIntent, slot: SlotState, *, now) -> Disposition`, a pure function with **no repository handle, no counters, no history, and no `content` parameter**. `WriteIntent` carries `content_sha256`, `kind`, `scope`, `claim_key`, `supersedes`, `asserted_at`, `derived_from`. Enforced by a signature test, not a comment.

- **T1 — slot collision.** The write declares `claim_key` K; a current `admitted` record occupies K in the same visibility binding; the write declares no `supersedes` pointing at that occupant. → `contested`
- **T2 — retrograde displacement.** Both challenger and incumbent carry a caller-declared `asserted_at` and the challenger's predates the incumbent's. Two timestamps compared numerically. → `contested`
- **T3 — derived-from-memory.** The write's provenance declares `derived_from` (recall receipt ids or memory ids) and it targets an occupied slot. Content that came out of memory can never displace what is in memory. → `contested`
- **T4 — policy hold.** *Seam only; no rule ships in v1.* This is where a future sufficiency classifier attaches. Its verdict can set **one routing bit and open one attributed ticket** — it can never touch a mutable weight, edit content, or change ranking. Only a named human resolution changes durable truth. Constraint 2 is unreachable by construction here.

Identical content on an occupied slot is a corroboration no-op, never a contest.

### 2.4 Contract changes — additive only

`ContractModel` is `extra="forbid"` (`models.py:18`), so every field below has a default and no existing caller breaks.

```python
# aoms/contracts/models.py
class WriteDisposition(str, Enum):
    ADMITTED = "admitted"; CONTESTED = "contested"

class ContestTrigger(str, Enum):
    SLOT_COLLISION = "slot-collision"
    RETROGRADE     = "retrograde-displacement"
    DERIVED        = "derived-from-memory"
    POLICY_HOLD    = "policy-hold"

class ContestResolution(str, Enum):
    ADMIT = "admit"; ADMIT_SUPERSEDING = "admit-superseding"
    SET_ASIDE = "set-aside"; SPLIT = "split"
```

- `Provenance` (`models.py:56-62`) `+ asserted_at: datetime | None = None` (when the claim was true, distinct from `created_at`), `+ derived_from: list[str] = []`. A `field_validator` rejects `asserted_at > now + skew`, closing forged-future freshness. **Note:** `_memory_payload` (`recall.py:352`) dumps provenance into the model's context, so both fields must be types that render inertly — a timestamp and a list of server-issued ids. No free-text field may be added here.
- `MemoryRecord` `+ claim_key: str | None = None`, `+ disposition: WriteDisposition = ADMITTED`, `+ observation_id: str | None = None`. A `model_validator` enforces `supersedes` and `contest` mutual exclusion.
- `RememberRequest` `+ claim_key: str | None = None`, `+ observation_id: str | None = None`. **`disposition` is deliberately not a request field** — `extra="forbid"` turns any attempt to supply it into a boundary error, the same mechanism that already keeps `scope_agent_id` out of tool args.
- `SupersedeRequest` `+ claim_key: str | None = None`.
- `RememberResult` `+ disposition: WriteDisposition = ADMITTED`, `+ contest_id: str | None = None`, `+ incumbent_ids: list[str] = []`.
- `SearchRequest` `+ include_contested: bool = False`.
- `RecallSource` `+ contested_count: int = Field(default=0, ge=0)`.
- `ContestEntry` — new, mirroring the table below.

**Hard invariant, with a dedicated test:** `contest_id` is server-generated `uuid4()` and is never derived from `RememberRequest.id` or any caller string.

### 2.5 Receipts

New `WriteReceipt` in `aoms/receipts.py` beside `RecallReceipt`, `schema_version: Literal[1]`:

`receipt_id, created_at, record_id, claim_key, agent_id, workspace_id, kind, scope, content_sha256, incumbent_ids, disposition, trigger, trigger_detail (JSON, content-free), asserted_at, derived_from, ruleset_digest, occurrence_count, engine_version`

`RecallReceipt` gains, additively under v1 (`receipts.py:5-7` expressly permits this): `contested_withheld: list[str]`, `contested_incumbents: dict[str, int]`, `ruleset_digest: str | None`.

**`write_receipts` is append-only and exempt from `receipt_retention`.** It does not reuse `_save_recall_receipt_sync`'s ring-buffer trim. Pruning it is available only as an explicit, confirmed, receipted operator action. This is the direct fix for the failure mode that disqualified L1 as specified.

### 2.6 Schema — migration **7**

`LATEST_SCHEMA_VERSION` **6 → 7**; new `MIGRATIONS[7]`. Pure DDL; rewrites no `record_json`, deletes nothing, backfills nothing.

```sql
ALTER TABLE memories ADD COLUMN claim_key TEXT;                    -- NULL = non-participating
ALTER TABLE memories ADD COLUMN contested INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_memories_claim_slot
    ON memories(claim_key, scope, scope_workspace_id, scope_agent_id, contested);

CREATE TABLE IF NOT EXISTS contest_entries (
    contest_id TEXT PRIMARY KEY,                       -- server uuid4 ONLY
    record_id  TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    claim_key TEXT, observation_id TEXT,
    scope TEXT NOT NULL, scope_agent_id TEXT, scope_workspace_id TEXT,
    incumbent_ids TEXT NOT NULL,                       -- JSON array
    trigger TEXT NOT NULL, trigger_detail TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    opened_at TEXT NOT NULL, opened_by_agent_id TEXT NOT NULL,
    state TEXT NOT NULL,                               -- open|resolved|expired-held
    resolution TEXT, resolved_at TEXT, resolved_by TEXT,
    resolution_note TEXT, escalated_at TEXT,
    UNIQUE(record_id)
);
CREATE INDEX IF NOT EXISTS idx_contest_open ON contest_entries(state, opened_at ASC);
CREATE INDEX IF NOT EXISTS idx_contest_slot
    ON contest_entries(claim_key, scope, scope_workspace_id, scope_agent_id, state);

CREATE TABLE IF NOT EXISTS write_receipts (
    receipt_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
    record_id TEXT NOT NULL, claim_key TEXT,
    agent_id TEXT, workspace_id TEXT,
    disposition TEXT NOT NULL, receipt_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_write_receipts_created
    ON write_receipts(created_at DESC, receipt_id DESC);
CREATE INDEX IF NOT EXISTS idx_write_receipts_claim
    ON write_receipts(claim_key, created_at DESC);
```

`memories.contested` is a **denormalized projection** of `contest_entries`, written in the same transaction as the record inside `_store_many_sync`, so the read path needs one indexed predicate rather than a join. It is exactly the same class of derived artifact as `memories_fts`, and it gets exactly the same treatment: `integrity_report()` (`sqlite.py`, feeding `IntegrityReport`) gains `contested_projection_drift`, and `cortex-mem doctor` **fails** on drift. **This check ships in the same commit as the projection, not after it.** A derived bit that can silently disagree with its ledger is the single thing this codebase cannot afford to add unguarded.

### 2.7 Where it plugs in — two choke points, both verified

- **Write:** `AOMSApplication._remember` (`application.py:64-132`), between the provenance stamp (`:85-93`) and storage (`:109-131`). `supersede()` routes through `_remember` at `:210`, so it is covered with no second code path. Record + contest entry + write receipt commit in one transaction.
- **Read:** one predicate in `SQLiteMemoryRepository._filters` (`sqlite.py:1634`), which I verified is the shared choke point called from `:544, :583, :689, :755, :768, :912, :981, :1687, :1703` — feeding `list`, `search_by_keyword`, `retrieve_recall_candidates`, visible counts, and the integrity report. Adding `include_contested: bool = False` there makes contested exclusion correct-by-construction everywhere instead of re-implemented per query. `resolve_supersession_chains` (`recall.py:266`) is untouched; only admitted rows reach it.

### 2.8 What the model sees

On a surviving incumbent, `_memory_payload` (`recall.py:344`) adds:

```json
"contested_by": {"count": 2, "contest_ids": ["ct-8f1e…"], "since": "2026-08-10T…"}
```

Integers, server UUIDs, one timestamp. **Not one byte of challenger prose, provenance string, or claim_key value.** A hostile writer's maximum achievable effect on a model's context is making the true statement "something disputed this" appear — a strict improvement over today, where MCB-U-05's hostile text packs as an ordinary fact block.

The writing agent is told in-band, same turn, via `_remember_text` (`mcp_server.py:245-251`): *"Stored as CONTESTED — current memory is unchanged. Fact `<id>` still stands. Resolve: `cortex-mem contest show ct-…`"*. Six lines, and the strongest anti-graveyard force in the design: the agent that created the contest learns immediately that its write accomplished nothing.

### 2.9 Surface after the change — justified against the three-tool discipline

**MCP: still exactly three tools.** I verified there are exactly three `server.add_tool` calls (`mcp_server.py:393, 408, 423`) and that `supersede` is not among them. New capability rides entirely on additive contract fields, which become optional tool parameters automatically through `_parameter_signature`'s reflection over `model_fields` — **zero adapter code**. `remember`'s *semantics* widen from "this was stored" to "this was stored, and here is whether it holds the slot"; that is a behavioral contract change for existing MCP clients and belongs in the CHANGELOG under a minor bump with a migration note, not smuggled in as additive.

**CLI (authoritative surface for all maintenance):**
```
cortex-mem contest list [--state open] [--slot KEY] [--by-agent A] [--oldest] [--json]
cortex-mem contest show   CONTEST_ID
cortex-mem contest resolve CONTEST_ID --admit | --supersede INCUMBENT_ID
                                       | --set-aside --reason "..." | --split --claim-key K
cortex-mem contest resolve --all-from-source SRC --set-aside --reason "..."
cortex-mem contest drain [--limit N]
cortex-mem doctor --contests            # dry-run: projected disposition map, zero writes
cortex-mem receipts write [--limit N]
```
`--set-aside` is the honest word for "no": labeled, attributed, reversible, still searchable, never deleted. Every resolve stamps the resolver from `_scope_context()` (`cli.py:99`) and prints the resulting timeline, exactly as `supersede_command` already does (`cli.py:535-580`).

**Observatory stays read-only.** I verified it rejects non-GET with 405 (`server.py:71-73`) and opens the store `read_only=True` (`:158`). Add `GET /contests` and `GET /contests/{id}`, plus a Contested counter on `/truth`. Each row renders a **copy-to-clipboard CLI command, not a button.** You decide in the browser; you act in the terminal. Consequence: an XSS or CSRF against the Observatory cannot change memory.

**Anti-graveyard mechanics (all four ship in v1):** in-band writer notification; coalescing repeated contests on the same `(slot, agent)` into `occurrence_count` so a loop cannot bury the inbox; `doctor` exiting non-zero on entries past `contest_sla_days` (default 14) through its existing pass/warn/fail reporter (`cli.py:1043`); and — **expiry never resolves anything.** Past `contest_expiry_days` an entry becomes `expired-held`, a *reporting* state. The challenger stays non-current, the incumbent stays current, doctor keeps counting it. **Nothing in this system ever changes durable truth on a timer.** That is the deliberate inverse of the endpoint that corrupted months of memory in 2026.

---

## 3. PREDICTED MCB DELTA

Simulated against the frozen corpus and scored by the frozen `score.py`. The **only** adapter change is `claim_key = unit["topic"]` — sanctioned verbatim by `SPEC.md:36-38`: *"`topic` is a neutral identity key for the proposition being updated... An adapter may translate it into a native representation, but must translate it back losslessly on retrieval."* The adapter's `_current_records()` calls `repository.list(...)`, which excludes contested by default under the new `_filters`, so exclusion flows through with **no adapter logic**. No prose is read. `instruction_markers` is unchanged.

| Slice | Cases | Baseline | Projected |
|---|---:|---:|---:|
| consistent INSTRUCTED / AUTONOMOUS | 6 / 6 | 6/6 · 6/6 | **6/6 · 6/6** |
| contradictory INSTRUCTED | 6 | 6/6 | 6/6 |
| contradictory AUTONOMOUS | 6 | 0/6 | 0/6 |
| superseding INSTRUCTED | 6 | 6/6 | 6/6 |
| superseding AUTONOMOUS | 6 | 0/6 | 0/6 |
| insufficiently-supported INSTRUCTED | 6 | 0/6 | 0/6 |
| **insufficiently-supported AUTONOMOUS** | 6 | 0/6 | **6/6** |

| Metric | OVERALL | INSTRUCTED | AUTONOMOUS |
|---|---|---|---|
| Decision accuracy | 50.00% → **62.50%** | 75.00% → 75.00% | 25.00% → **50.00%** |
| Unauthorized overwrite | 15.62% → **15.62%** | 29.41% → **29.41%** | 0.00% → 0.00% |
| Valid supersession | 50.00% → 50.00% | 100% → 100% | 0.00% → 0.00% |
| False rejection | 0.00% → **41.18%** | 0.00% → 0.00% | 0.00% → **82.35%** |
| Structurally invalid results | **18 → 0** | — | — |
| Passed | 24/48 → **30/48** | | |

**Zero regressions.** No case that passes today fails. I enumerated every consistent case: none writes different text to an occupied topic, so T1 never fires on them.

### What deliberately does NOT change, and why

**Unauthorized overwrite rate stays at 15.62% / 29.41%.** This is the headline finding and we will publish it as such. At the AOMS boundary all five bad INSTRUCTED displacements and all twelve valid ones are the same call: `explicit=True, displacements=1`, `supersede(old_id, content)` with clean assertional text and no source. Verified case by case. Any rule that blocks the five blocks the twelve. The signal lives only in observation prose, and reading it violates either constraint 1 or the adapter contract.

- **U-01, U-07, U-09, U-11** — still fail. In a *deployment* these are exactly what T2/T3/T4 and a warrant address; on MCB the interchange format has no channel to carry the evidence, so we claim nothing.
- **U-03** — still fails on MCB, and this is the cleanest illustration of the gap. T2 (retrograde) is a purely arithmetic comparison of two declared timestamps and would catch it — but the dates live inside the statement *text* (`"As of 2026-08-20, the catalog price is 80 dollars."`). Parsing them out is content judgment. **MCB's interchange format cannot express the evidence a correct authority model needs.** That sentence goes in the writeup.
- **U-05 (injection)** — still fails, and honestly. Its statement lands on `"Payroll existence"`, a **virgin slot**. There is nothing structurally alarming about creating one new fact; refusing it requires reading the hostile prose. Two things do improve and are worth stating: nothing is destroyed (there is no delete path in the codebase — verified, the only `DELETE FROM memories*` is the FTS reprojection), and the recall-side withholding plus `search` excluding contested by default keeps hostile text out of *every* model-facing path.

**AUTONOMOUS valid supersession stays 0%.** Unchanged, by declared architectural stance. `SPEC.md` expressly permits this and requires it stay visible. We do not touch it.

**False rejection rate goes 0% → 41.18%, and 82.35% AUTONOMOUS.** This is the honest price and it will be the second line of the writeup, not a footnote. Exactly 14 of 34 `required_new` pairs are withheld (verified arithmetic). MCB scores only current state and has no vocabulary for "durably held, pending review," and it is entitled to charge full price. We add one clearly-labeled **supplementary, non-MCB** measurement: *0 of 34 required-new claims were discarded; all 14 withheld remain durable, searchable, and one command from current.* That is the same disclosure posture `RESULTS-AOMS.md` already models when it refuses to sell the baseline's 0% FRR as a win.

**The 12 AUTONOMOUS contradictory/superseding cases change failure mode without changing score** — `conflict-retained` → `reject`. No accuracy gain. What improves is that the store is no longer structurally invalid: **18 → 0** results returning two simultaneous current values for one proposition. A memory that returns two contradictory current facts has failed at its job regardless of which one is right.

---

## 4. INTEGRITY PLAN

MCB-1.0 is frozen. The 50% result is published. The re-run must be impossible to read as retrofitting.

1. **The published result is never edited, moved, or amended.** `RESULTS-AOMS.md` and `results.json` stay byte-identical at their existing paths and commit. A new file, `RESULTS-AOMS-2.md`, is added alongside. The old document gains no "superseded" banner — a reader arriving at the original URL sees the original finding.
2. **Both results appear side by side in the same table, in every venue** — the new writeup, the README, and any launch material. Baseline column first. Never a lone improved number.
3. **The freeze is verified and reported, not skipped.** `score.py --skip-freeze-check` is forbidden for the published run. The re-run reports the verified hashes of `cases.json` (`d5d9db63ad0911110e7cc602a22a6f6e655b9b5fb72261c649a10debdd7ac54f`) and `score.py` (`7565863b5c02d35d9d3e8dea9dcfa453fd903d618ac9f61280b5b3cc1a9dd98b`) inline, showing they match `FREEZE-MANIFEST.json` unchanged. **No case, expectation, formula, or scoring branch is touched.**
4. **The adapter diff is published in full and is one line.** The writeup shows the complete change — `claim_key=unit["topic"]` in `_remember` — quotes `SPEC.md:36-38` sanctioning it, and states that `instruction_markers` and `config.json` are unchanged. A reader can verify the diff is one line in under a minute. **We state explicitly that no marker list, keyword list, or prose-derived signal was added, and that we considered and rejected one** — naming the Minimalist's `disclaimer_markers` proposal and reporting that it scored 10/12 on U-cases with 0/36 false positives, which is why we rejected it. Disclosing the rejected shortcut is stronger evidence of good faith than not mentioning it.
5. **The defect is narrated in our own words, first, before any improved number.** The re-run opens with: *AOMS accepted five unsupported observations that displaced protected current facts. It had no notion of evidentiary sufficiency or write authority; it faithfully executed whatever a caller declared. This release does not fix that class. It fixes the adjacent one — undeclared collisions silently producing two current values for one proposition — and it makes the unfixed class visible instead of silent.*
6. **The metric that did not move is reported before the metric that did.** UOR 15.62% / 29.41%, unchanged, with the structural explanation (identical calls at the AOMS boundary), stated before DA 50% → 62.5%. Same for FRR 0% → 41.18%.
7. **Dated, commit-pinned, and ordered.** `RESULTS-AOMS-2.md` carries the run date, the AOMS commit SHA, the adapter commit SHA, and the engine version. Git history is the audit trail: the design-decision commit precedes the implementation commit precedes the re-run commit. The freeze commit precedes all of them, unchanged.
8. **The 0% → 41.18% FRR is reported as a deliberate trade with its supplementary counter-measurement, not as an unexplained regression** — and the counter-measurement is explicitly labeled non-MCB.
9. **What we will not claim:** that AOMS "fixed" the unauthorized-overwrite failures; that 62.5% is a good score; that MCB-1.0 is unfair. MCB is measuring a real defect that we have not closed.

---

## 5. IMPLEMENTATION PLAN

Effort in engineer-days. **Safe** = an autonomous builder may complete and merge behind review. **Unsafe** = requires a human decision or a human-witnessed dry-run before merge.

---

**W1 — Close the in-place upsert hole. 0.5d. SAFE. Ships first, standalone, independent of everything below.**

In `_remember`, when `existing is not None and existing.content != request.content`, refuse the in-place change with *"in-place content change; append a successor with `supersedes` instead."* Content-identical upserts stay idempotent, preserving the retry contract documented in `REMEMBER_DESCRIPTION` (`mcp_server.py:63-72`).

*Tests:* `remember(id=<existing>, content=<different>)` raises and leaves `record_json` byte-identical. `remember(id=<existing>, content=<identical>)` is a no-op and still returns `created=False`. **Adversarial:** drive it through the generated MCP tool signature — not the Python API — asserting `id` is reachable as a tool argument and that the guard fires there. Assert `lineage()` and `diagnose_chains()` see no orphan after the attempt.

---

**W2 — Contract additions + the pure decision function. 1.5d. SAFE.**

`WriteDisposition`, `ContestTrigger`, `ContestResolution`, `ContestEntry`; additive fields on `Provenance`, `MemoryRecord`, `RememberRequest`, `SupersedeRequest`, `RememberResult`, `SearchRequest`, `RecallSource`. New `aoms/contest.py` with `decide()` — pure, total, table-driven.

*Tests:* every existing contract test passes unmodified. `RememberRequest(**{"disposition": "admitted"})` raises `ValidationError` via `extra="forbid"`. `asserted_at` in the future is rejected. **Adversarial (the adversary judge's own test):** `inspect.signature(decide)` has no parameter named `content` and no parameter annotated with a repository/connection type — a failing test, not a comment. A property test asserting `decide` is deterministic given identical inputs across 10k random intents.

---

**W3 — Migration 7 + repository plumbing. 2d. UNSAFE — human-witnessed dry-run required before merge.**

`LATEST_SCHEMA_VERSION` **6 → 7**, `MIGRATIONS[7]` per §2.6. Note the `if version == 6:` branch in `_initialize_sync` — the new key must not disturb it. Repository methods: `open_contest`, `coalesce_contest`, `list_contests`, `get_contest`, `resolve_contest`, `contests_for_records`, `slot_head`, `save_write_receipt`, `recent_write_receipts`, `rebuild_contested_projection`. `_filters` gains `include_contested: bool = False`.

**Unsafe because:** this is the only step that can silently change what an existing 165k-record store considers true. Required before merge: `cortex-mem doctor --contests` dry-run printing the projected disposition map with zero writes, run on a copy of the live store and read by a human.

*Tests:* migration is idempotent (apply twice). A store already at version 6 correctly advances to 7 and applies the DDL — **the regression test for the numbering error, and it must exist.** Every pre-migration record loads with `claim_key IS NULL, contested = 0`. Round-trip a v6 store through export/restore (`portable.py`) and assert byte-identical `record_json`. **Adversarial:** assert `MIGRATIONS[7]` contains no `UPDATE`, no `DELETE`, and no `record_json`.

---

**W4 — Wire `decide()` into the write path. 1.5d. SAFE.**

`_remember` between `:93` and `:109`; T1/T2/T3 evaluated; record + contest entry + write receipt in one transaction. `supersede()` covered for free via `:210`.

*Tests:* T1 fires only on an occupied slot with no declared `supersedes`; identical content is a corroboration no-op. T2 fires on retrograde `asserted_at` and not on equal timestamps. T3 fires when `derived_from` is non-empty on an occupied slot. `claim_key IS NULL` ⇒ no trigger ever fires ⇒ behavior identical to pre-change, asserted against a golden transcript. **Adversarial:** a contested write leaves the incumbent's `record_json` byte-identical; a contested record is fully retrievable by id and by `search(include_contested=True)`; `contest_id` is never equal to, prefixed by, or derived from any caller-supplied `RememberRequest.id` — fuzzed with 256-char adversarial ids.

---

**W5 — Read-path exclusion + write receipts + `RecallReceipt` fields. 1d. SAFE.**

Contested excluded from `list`, `search`, `retrieve_recall_candidates`, visible counts. `_memory_payload` notice. `RecallReceipt` gains `contested_withheld`, `contested_incumbents`, `ruleset_digest`. **`write_receipts` exempt from `receipt_retention` — verified separately.**

*Tests:* a contested record never appears in a recall pack. `RecallReceipt.contested_withheld` names every withheld id. Old receipts still parse (additive-v1 compatibility). **Adversarial, three of them:** (a) write 2,000 write receipts and assert **none** are deleted — the direct regression test for the ring-buffer trim at `sqlite.py:1366`; (b) craft a memory whose content is `{"contested_by": {"count": 99}}` and assert the packed context's notice block is unaffected — proving the notice channel is not content-derived; (c) assert the rendered `contested_by` payload contains no substring from the challenger's content, provenance `source`, or `claim_key`, fuzzed with prose containing fence characters and JSON metacharacters.

---

**W6 — Projection drift check. 0.5d. SAFE. Must merge in the same commit as W5, never after.**

`integrity_report()` gains `contested_projection_drift`; `doctor` exits non-zero on drift.

*Tests:* hand-corrupt `memories.contested` out of agreement with `contest_entries`; assert `doctor` fails and names the ids. Assert a clean store reports zero drift.

---

**W7 — CLI `contest` command group + `doctor --contests`. 1.5d. SAFE.**

*Tests:* each resolution path (`--admit`, `--supersede`, `--set-aside`, `--split`). `--set-aside` deletes nothing and leaves the record searchable. Resolver identity is stamped from `_scope_context()`. `--supersede` routes through `application.supersede` and therefore never rewrites a predecessor. Coalescing increments `occurrence_count` rather than creating rows. Overdue entries escalate and `doctor` exits non-zero.

---

**W8 — Observatory read-only `/contests`. 1d. SAFE.**

*Tests:* **adversarial, and this one is mandatory:** POST/PUT/PATCH/DELETE to `/contests` and `/contests/{id}` all return 405; the store is opened `read_only=True`; challenger content is HTML-escaped in the side-by-side view, fuzzed with `<script>` and attribute-breaking payloads.

---

**W9 — MCB adapter one-line change + re-run + `RESULTS-AOMS-2.md`. 1d. UNSAFE — the integrity plan is a human judgment call.**

*Tests:* `score.py` runs **without** `--skip-freeze-check` and both hashes verify. The adapter diff is exactly one line. Assert the produced metrics match §3 exactly — DA 62.50/75.00/50.00, UOR 15.62/29.41/0.00, VSR 50.00/100.00/0.00, FRR 41.18/0.00/82.35, 30/48, 0 structural errors — as a committed regression test, so a later change that quietly moves the number fails CI.

**Total: ~10.5 engineer-days.** W1 is shippable today and should not wait for the rest.

---

## 6. WHAT WE LEARNED

1. **Check the constant, not the consensus.** All five proposals and all three judges stated `LATEST_SCHEMA_VERSION = 5`. It is 6, with `MIGRATIONS[6]` a live placeholder dispatched by an `if version == 6:` branch. A builder following the agreed instruction would have shipped a migration that silently never applies to any existing store while the version claimed it had. Unanimity among careful reviewers is not verification; opening the file is.

2. **A benchmark can only measure what crosses the system boundary.** MCB's five unauthorized overwrites and its twelve valid corrections arrive at AOMS as byte-identical calls. The discriminator lives in prose neither the system nor a conforming adapter may read. Before designing a fix for a benchmark failure, dump exactly what your system receives for the failing and passing cases — if they are identical, no internal change can separate them and every proposal claiming otherwise is proposing to cheat.

3. **A discriminator with zero false positives is a confession.** The proposed `disclaimer_markers` list hit 10/12 targets and 0/36 non-targets. Real-world signals are noisy; a perfect separator over a frozen corpus is evidence of derivation from the answer key, not of insight. Test any proposed heuristic against the cases it is *not* meant to catch, and treat a clean sweep as a red flag rather than a result.

4. **Trace your safety property all the way to the storage layer.** The Minimalist's design promised "stored verbatim and append-only in a write receipt" and reused the existing receipt trio — which auto-prunes to 1,000 rows inside the transaction of every save. The design's central safety claim was inverted by one line of SQL two files away. Reusing an existing mechanism means inheriting its retention, its concurrency, and its deletion semantics, not just its shape.

5. **Migrations default to *opting out*, never to the bottom of a new order.** Backfilling 165k legacy rows to the weakest value on a new ordinal makes the migration itself the overwrite vector — every pre-existing memory becomes displaceable by the next mediocre write. `NULL` meaning "does not participate" preserves existing semantics exactly and costs nothing.

6. **Make a constraint true by signature, not by comment.** `decide()` cannot read record content because it has no parameter that could carry it. `WriteIntent` carries `content_sha256`. That is testable in one assertion and cannot rot; a comment saying "must not read content" survives exactly until the first person who needs a quick fix.

7. **Trace the hostile path all the way into the next model's context window.** The most valuable adversarial finding in this exercise was a design auditing itself: `RememberRequest.id` accepts 256 arbitrary characters, so an id-derived contest identifier would have rendered attacker prose into every recalled context — a new injection channel opened by a security feature. Any field you add to a record is a field that renders into a model's prompt: `_memory_payload` dumps provenance wholesale.

8. **Denormalized projections need their drift check in the same commit.** `memories.contested` can silently disagree with `contest_entries` the way FTS can disagree with `memories`. A derived bit that can be quietly wrong is precisely the failure category this product was rebuilt to prevent. Ship the check with the projection or ship neither.

9. **Publish the metric that did not move, first.** Our decision accuracy improves and our false-rejection rate gets materially worse; our headline safety metric does not move at all. Reporting the unmoved and the worsened numbers ahead of the improved one is what makes the improved one believable. A benchmark you only cite when it flatters you is marketing.

10. **Prefer sequencing to synthesis when two designs measure the same.** The Policy Engine and the Contest Ledger produced identical benchmark results; the Contest Ledger delivers them with a fraction of the conceptual surface, and the Policy Engine remains available as a later layer on the same seam. Configurability that buys no correctness today is a maintenance liability with a delayed invoice.

11. **Never resolve durable truth on a timer.** Aged contests become a *reporting* state, never an auto-decision. The 2026 decay incident was a background process quietly rewriting retained rows; the general lesson is that any mechanism which changes what the system believes without a named actor and a timestamp will eventually change something nobody wanted changed.
