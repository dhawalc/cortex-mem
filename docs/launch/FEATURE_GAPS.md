# AOMS GitHub launch feature-gap analysis

**Date:** 2026-08-23

**Decision horizon:** launch through launch + 2 weeks

**Thesis:** AOMS should launch as the **visible, trustworthy, universal memory for agent fleets**—not as another invisible vector store.

## Executive verdict

AOMS has the hard backend that most launch demos fake: one governed SQLite/WAL store, process-bound scopes, local hybrid retrieval, provenance-fenced packing, exact token ceilings, versioned recall receipts, supersession resolution, portable export/restore, an eval harness, and a falsifiable relay. The launch risk is the opposite of missing infrastructure: **the product's best evidence is almost completely invisible, while a new empty store has nothing rewarding to recall.**

The stranger path currently ends in an anti-demo. A user installs from Git, initializes successfully, is shown a registration command inconsistent with the Git install, connects under undifferentiated `default/default` identity, and asks an empty brain to recall. With default settings, that first empty recall can download/load the approximately 67 MB embedding model before returning no sources. The MCP response at least says “No relevant memory was found”; the CLI's default Markdown output is just an empty string. Meanwhile, the receipt proving safe behavior is buried in SQLite and the strongest visualizer is a developer-only anatomy generator requiring a database path and receipt ID.

The launch job is therefore not “add more intelligence.” It is:

1. make the first useful loop happen in under two minutes;
2. make the receipt and scope boundary visible;
3. let users bring an existing brain instead of waiting weeks to grow one; and
4. turn supersession into a legible truth history rather than an internal packing detail.

If only one substantial feature ships, ship a **local Recall Observatory** and use its receipt inspector as the README's first screenshot. But do not launch that screenshot until the install/identity/empty-store path beneath it is honest.

## Evidence boundary

This audit is grounded in `v2` at `bd134ee`. `docs/PRODUCT_PLAN.md` and `docs/LAUNCH_PLAN.md` are not in the current tree; their repository versions were read from commits `2a96b0d` and `0ee9816`. The current `docs/launch/README-public-draft.md`, `aoms/`, host recipes, eval harness, relay, anatomy generator, tests, packaging metadata, and operational docs were inspected at HEAD. Trend claims in the final section are strategic judgment as of mid-2026, not findings from a fresh market scrape.

## 1. Finish-line audit: the demanding stranger's first hour

### The actual funnel

| Minute / step | What exists now | What the stranger experiences | Launch judgment / required finish |
|---|---|---|---|
| 0: lands on GitHub | The public draft accurately describes v2, but the root `README.md` still sells the old daemon/HTTP/JSONL/Chroma product and commands such as `start`, `status`, and CLI `search` that v2 does not expose. Several operational docs are likewise v1-era. | They cannot tell which product is real. Copying the root quick start produces missing commands or sends them toward the retired architecture. | **P0 credibility blocker.** Replace the root README with the reviewed draft and quarantine or rewrite stale docs before launch. Broken documentation erases the value of every feature below. |
| 2: runs Git install | Draft command: `uvx --from git+https://github.com/dhawalc/cortex-mem cortex-mem init`. It does not pin a tag/ref. The package still carries legacy runtime dependencies (`fastapi`, `uvicorn`, `chromadb`, `aiosqlite`) in addition to the v2 stack. | Resolution is slower/heavier than the three-tool local product implies, and reproducibility depends on the repository's default branch at that moment. | Publish a v2 tag/commit-pinned command, test it on a clean machine, and remove dependencies not needed by the shipped v2 path. The launch gate is install-to-handshake time, not “works in the dev venv.” |
| 4: runs `init` | Store initialization is solid and explicit: schema 5, data path, deferred model download, and `doctor` guidance. | This is the first trustworthy moment. Then `init` prints `claude mcp add aoms -- uvx cortex-mem mcp`, while the user installed from Git with `uvx --from git+...`. | **P0 papercut with real blast radius.** Print the exact source/ref used, or provide `cortex-mem setup <host>` so the user never hand-reconciles install sources. |
| 5: chooses a host | Claude, Codex, and OpenClaw recipes exist. The Claude/OpenClaw recipes add automatic recall; OpenClaw adds selective capture. | The recipes live in the source tree, are not installed as a discoverable user asset by the current package configuration, require copying/merging snippets, and use commands that assume a published package. Codex still needs a placeholder replaced manually. | Package and expose the recipes through setup commands. A callable MCP tool is not activation. The product plan already identified this as the riskiest assumption; it remains only partially productized. |
| 8: registers MCP | Draft command registers stdio safely. The server initializes its store and exposes exactly `recall`, `remember`, `search`. | The draft command supplies no `AOMS_AGENT_ID` or `AOMS_WORKSPACE`, so every client and project becomes `default/default`. The product's flagship scope model silently collapses at the default quick start. | **P0 product-truth blocker.** Setup must derive, display, and test host + workspace identity. The success screen should say exactly which agent/workspace/scopes are bound. |
| 10: first MCP handshake | One versioned FastMCP server, structured outputs, strong tool descriptions, no model-facing maintenance. | This part is unusually good, but there is no friendly “connected, empty, next action” resource or status surface in the host. | Return/offer a scoped status resource and one next step without expanding the tool surface. Keep maintenance out of agent hands. |
| 12: first recall, empty store | Recall still creates a versioned zero-candidate receipt. MCP text says `0 source(s)` and “No relevant memory was found.” | Before candidate retrieval, default recall embeds the query. On a cold cache, an empty brain may first download/load the approximately 67 MB model, then return nothing. CLI `recall` prints only `result.context`, so its default empty result is blank. | **Worst first-use moment.** Check an empty visible store before embedding; make empty recall instant; print a useful empty state; offer import, one durable-memory prompt, or a disposable tour. Zero candidates should feel safe and actionable, not broken. |
| 15: tries to add value | `remember` supports eight kinds, three scopes, provenance, stable IDs, tags, and supersession. The CLI offers a simpler one-record write with an idempotency key. | The README has no human first-memory loop. MCP depends on the model choosing to call `remember`; no host-neutral automatic capture exists. A stranger must understand kinds/scopes before seeing payoff. | Give one opinionated seed flow: “save a decision your next agent must know,” then kill/restart and recall it. Default workspace scope is right; explain it after value, not before. |
| 20: asks “did it work?” | Search exists as an MCP tool; recall returns structured sources and a receipt ID. `doctor` verifies store/schema/FTS/vector queue/receipt counts. | There is no v2 CLI `search`, `list`, `show`, or receipt inspector. `doctor` says the empty store is healthy but cannot prove the first remembered item crossed the full serialization boundary. | Add an activation check that writes or imports, recalls through the real application path, and opens the corresponding receipt. Do not fake a health-only success. |
| 30: asks “why this memory?” | Receipts contain candidate scores, selected/rejected reasons, scope-filter count, vector coverage, superseded IDs, exact tokens, and latency. The anatomy generator renders an excellent static HTML teardown. | Neither is on the normal path. Anatomy requires `python -m aoms.anatomy --db ... --receipt-id ... --out ...`; the user first has to discover a receipt ID and database path. | Productize the anatomy, not a second observability implementation. One click from recall → receipt inspector → exportable static artifact. |
| 40: brings old history | Canonical import handles reviewed legacy AOMS tiered JSONL, upserts stable IDs, records provenance, and reports issues. Ownership assignment is deliberately explicit. | `cortex-mem import` does not import arbitrary Markdown, Obsidian, claude-mem, Mem0, or agentmemory. `docs/MIGRATION.md` still advertises removed `migrate`, HTTP, and old directory layouts. | A new user with no history gets no leverage; a user with history faces a format project. Migration is an adoption feature, not maintenance. Ship source-aware importers with dry-run and provenance. |
| 50: corrects a bad memory | Same-ID writes update; explicit `supersedes` links are retained and recall suppresses candidate-set predecessors. Cycles are guarded. | No friendly correction flow, history view, delete/quarantine UI, dangling-chain check, or conflict inbox exists. AOMS resolves declared supersession; it does **not** currently detect semantic contradictions. | Say this precisely. Add `correct/supersede` UX and chain diagnostics before marketing “contradiction detection.” Suggest semantic conflicts for review; never silently rewrite truth. |
| 60: decides whether to keep it | Export/restore is hash-verified, restore refuses non-empty targets, `doctor` is credible, local storage claims are precise, relay proof exists. | The user has seen almost none of this. There is no personal outcome (“three handoffs, 842 recalled tokens, two stale facts suppressed”), visual memory surface, or shareable proof card. | Close the hour with evidence sourced from receipts—not invented “tokens saved.” Visibility is the viral loop for an otherwise invisible daemon. |

### Empty-brain activation: what should happen instead

The empty state should branch, not dead-end:

| User state | Immediate path | Proof of value |
|---|---|---|
| Has another memory system | Detect or let them choose a source; run a read-only dry-run; show count, scopes, kinds, conflicts, and provenance before import. | Open the imported timeline, then perform one real recall with a visible receipt. |
| Has Markdown/Obsidian/project handoffs | Import only selected paths with an explicit mapping preview. Never vacuum an entire home directory or silently ingest secrets. | Show the source file attached to every selected recall block. |
| Has no history | Ask for one durable decision/constraint, or run an isolated disposable three-memory tour that demonstrates scope filtering and supersession. | Restart/cold-call recall and show that the current fact—not its superseded predecessor—fit under the token budget. |
| Wants automation | Install a reviewed host recipe, show exact agent/workspace binding, and test one session-start recall. | Setup reports the actual MCP call and receipt, not merely that a config file was edited. |

Do **not** seed the canonical store with generic tips or synthetic memories without consent. That pollutes the user's trust boundary. A disposable tour should use a separate temporary/demo store and clearly say so; a real activation should store one user-authored durable fact.

### What is already launch-grade

Do not obscure the parts that are done: the three-tool boundary is disciplined; scope identity is not accepted from tool arguments; recall serialization is provenance-fenced as untrusted data; the packer accounts exact serialized tokens; unavailable vectors degrade instead of failing the entire ranker; superseded predecessors are auditable even when suppressed; SQLite/WAL + FTS5 + sqlite-vec is one coherent backup boundary; export/restore is manifest-verified; remote non-loopback startup refuses insecure configurations; and the eval/relay/anatomy artifacts are materially more credible than generic “memory improved the answer” demos.

The gap is **product access to those strengths**, not replacement of them.

## 2. Feature candidates

### Scoring model

Scores are 1–5. **Effort is inverted: 5 = cheap/fast; 1 = expensive/risky.** Total is an intentionally simple sum out of 20; it is a forcing device, not roadmap math. Adoption pull asks whether the capability makes a stranger install **today**. Demo-ability asks whether it produces a legible README screenshot/GIF. Moat-fit asks whether it becomes stronger because AOMS already has scopes, provenance, receipts, budgets, and supersession—not merely because the category expects it.

| Rank | Candidate | Pull | Demo | Effort | Moat | Total | Opinionated verdict |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | **Guided activation + host setup** *(own candidate)* | 5 | 5 | 5 | 5 | **20** | The non-negotiable finish line. Preserve the three-tool surface; add `setup`/`tour`/empty-state UX around it. It should install a packaged recipe, bind a non-default identity, create/import one memory, execute real recall, and reveal the receipt. Cheap relative to its conversion impact. |
| 2 | **Local memory viewer / Recall Observatory** | 5 | 5 | 3 | 5 | **18** | Build a loopback, read-first dashboard: browse/search/timeline, scope/kind/source filters, memory detail, supersession chain, and receipt inspector. Reuse anatomy/receipt contracts. Defer a generic node graph: current relation content is not a normalized graph, so pretty edges would overclaim the data model. |
| 3 | **Contradiction + chain health surfacing** | 4 | 5 | 4 | 5 | **18** | First ship deterministic findings: cycles, dangling `supersedes`, multiple apparent heads, old/new pairs both retrievable, scope-boundary anomalies, and stale high-ranking records. Semantic conflict detection may suggest pairs for review, but must not claim certainty or mutate records. Natural home: `doctor` + Observatory inbox. |
| 4 | **Temporal / time-travel recall** | 4 | 5 | 4 | 5 | **18** | “What did workspace X believe on March 15?” is a memorable wedge. Records already retain timestamps and predecessor links, but current contracts lack `as_of` and history semantics. Define event-time vs ingestion-time explicitly and reconstruct only from retained evidence. This makes supersession visibly valuable. |
| 5 | **Receipt-backed usage analytics + share card** | 4 | 5 | 5 | 4 | **18** | Receipts already support recalls, selected sources, token utilization, latency, scope filtering, and superseded suppression. Show those. Do **not** say “saved ~Y tokens” unless a measured counterfactual exists; “842 tokens recalled across 7 handoffs” is honest and still shareable. Fold this into the Observatory rather than launching a separate analytics product. |
| 6 | **Migration importers / “bring your brain”** | 5 | 4 | 3 | 5 | **17** | The strongest adoption lever after setup. Start with plain Markdown/Obsidian plus one high-demand competitor format; then claude-mem, Mem0 export, and agentmemory behind versioned adapters. Every import needs dry-run, deterministic IDs, source provenance, scope choice, secret warnings, and a reversible export—not a lossy one-shot parser. |
| 7 | **Memory quality/lint doctor** *(own candidate)* | 4 | 4 | 4 | 5 | **17** | Extend existing operational `doctor` into content health without pretending to judge truth: duplicate candidates, unembedded/stale vectors, unscoped records, orphan chains, oversized memories, suspicious secret patterns, low-use records, and provenance gaps. This is the corruption story turned into a product promise. |
| 8 | **MCP resources + prompts** (`aoms://memory/{id}`, receipts, setup/recall prompts) | 3 | 3 | 5 | 5 | **16** | Cheap composability. Resources make stable IDs, provenance, and receipts inspectable without adding unsafe maintenance tools; prompts can encode the durable-write and recall policy. Enforce the exact same bound scope on every resource read. Useful infrastructure, not the hero. |
| 9 | **Team/shared workspace memory over streamable HTTP** | 4 | 4 | 2 | 5 | **15** | The secure transport and bearer-bound identity exist, which is a major head start. A real team product still needs tenant/admin boundaries, membership, workspace ACLs, audit/export policy, revocation UX, concurrency/retention operations, and a precise meaning for `user-global`. Do not relabel today's single-store remote mode as teams. |
| 10 | **Proactive memory surfacing (“whispers”)** | 5 | 4 | 2 | 4 | **15** | People want memory without remembering to call memory. MCP servers cannot universally push into hosts; this is host lifecycle integration. Extend the existing recipes with traceable, rate-limited suggestions and a visible receipt. Avoid interruptive notifications and do not inject when confidence is low. Host-neutral activation matters more than a clever daemon. |
| 11 | **Multi-machine sync (Git-based or E2E)** | 5 | 4 | 1 | 4 | **14** | Huge pull, huge trust risk. Never sync the live SQLite/WAL file through Git. Git can version reviewed exports; live sync needs an append/event protocol, deterministic conflict and supersession semantics, per-scope keys, tombstones, device identity, and E2E recovery. Earn this after local correction/history semantics are stable. |
| 12 | **At-rest encryption** | 3 | 2 | 2 | 4 | **11** | Valuable for laptops and remote stores, but “local” is not synonymous with encrypted. Prefer documented OS full-disk protection first; evaluate optional SQLCipher only with backup/export, key rotation, headless startup, lost-key, and performance stories. Field-level encryption would fight FTS/vector retrieval unless architecture changes. |
| 13 | **Memory decay / archival policies done right** | 2 | 3 | 2 | 4 | **11** | Never mutate canonical truth or compound a weight. AOMS already has non-destructive recency scoring. Add policy simulation, cold/archive views, pinning, retention by scope/kind, and hash-verified restore only when receipts show a real corpus-management need. The corruption incident makes restraint—not an early decay feature—the credible stance. |
| 14 | **Recall quality feedback loop (“thumbs”)** | 3 | 3 | 2 | 3 | **11** | A thumbs UI is easy; a valid learning loop is not. Never directly reinforce/decay record weights from sparse outcome signals—the dead-loop history is a warning. Capture labels with task, receipt, ranker version, and scope; use them in offline evals; deploy versioned rank changes with rollback and canary-leakage checks. |

### Notes on the named candidates

**Viewer:** the differentiator is not “we have a dashboard.” It is that a screenshot can show the exact context artifact, candidate funnel, scope exclusions, superseded predecessor, source provenance, and token arithmetic side by side. Browse/search alone is commodity. A receipt courtroom is not.

**Importers:** switching costs are data *and confidence*. A credible importer should preview “1,284 records → 923 proposed memories; 71 duplicate groups; 14 possible secrets; scope = workspace; no source files modified,” then let the user inspect mappings. Import into a new/empty store first, preserve original source references, and make re-runs idempotent. Plain Markdown/Obsidian has the widest universal appeal; claude-mem has the loudest competitor-conquest story. Mem0 and agentmemory follow once their export contracts are pinned and fixture-tested.

**Proactive surfacing:** AOMS already has the correct primitive—host recipes that call recall at lifecycle boundaries. Productize that before inventing ambient background inference. “Whispered because these two sources crossed a threshold; click receipt” is defensible. “AOMS knows what you need” is not.

**Temporal truth:** supersession currently operates only among scope-visible candidates retrieved for a query. That is safe recall behavior, but not a historical database query. Time travel needs explicit repository support so a chain predecessor that did not match today's lexical/vector candidate set can still be considered under an authorized `as_of` read. Scope must be evaluated at the historical read boundary without leaking inaccessible chain members.

**Contradiction detection:** today AOMS detects declared *links* and suppresses visible predecessors; it does not infer that two unrelated texts conflict. Launch deterministic chain health first. Add embedding/LLM-assisted conflict suggestions later as a review queue with provenance and “not a truth judgment” labeling.

**Decay:** archive is a view/policy; deletion is a separately authorized operation; recency is a rank signal. Keeping those three concepts separate is how AOMS turns its corruption story into credibility.

**Sync/team:** these are post-launch pull, not two-week garnish. They expand the threat model and authorization model. A local-first product loses its position fastest by shipping casual database copying or calling bearer-token remote access “collaboration.”

**Feedback:** receipts make AOMS unusually well positioned to collect valid labels, because a thumb can be attached to the exact candidate set and serialized context. That moat is squandered if the label directly bumps a mutable weight. The safe loop is label → offline eval → ranker version → shadow/canary comparison → explicit rollout.

## 3. The pick: launch + 2 weeks

Choose four items that form one compounding loop. Do not ship one feature per fashionable category.

| Order | Feature set | Scope for this window | Why it compounds |
|---:|---|---|---|
| 1 | **Activation finish line** | Replace stale public surfaces; pin/test the Git install; make `init` print source-correct host commands; package recipes; bind/show agent + workspace; skip embedding on an empty store; give CLI/MCP a useful empty response; run a one-memory cold-recall proof. | Converts installs into a populated, correctly scoped brain. Every later screenshot and metric becomes reproducible by a stranger. |
| 2 | **Recall Observatory** | Local loopback, read-first UI using existing application/repository boundaries. Views: memories, timeline, search, receipt list/detail, candidate funnel, scope badges, supersession chain, exact tokens, vector coverage, and exportable static receipt. No speculative graph and no broad edit surface in v1. | Makes trust visible. Every recall produces another inspectable artifact; every artifact teaches the product and can be shared. |
| 3 | **Bring Your Brain** | One framework for source adapters with dry-run/report/idempotency/provenance/scope; ship Markdown/Obsidian and one fixture-pinned high-demand competitor importer first. Label the remaining adapters beta as they gain fixtures. | Solves the empty-store problem for experienced users, populates the Observatory immediately, and turns competitor switching cost into AOMS's proof of universality. |
| 4 | **Truth Timeline + Contradiction Inbox** | Friendly supersede/correct flow; chain history; deterministic cycle/dangling/multiple-head diagnostics; `as_of` for declared chains if semantics can be completed safely; semantic conflict pairs are suggestions only. | Imported history becomes governed rather than merely copied. The Observatory shows why the current fact won and lets users inspect what was believed before. This is the strongest expression of trust. |

### The one hero feature

**Hero feature: the local Recall Observatory's receipt inspector.**

The README's first screenshot should not be a generic table of memories. Show one real handoff in a three-column view:

- left: task, bound `agent/workspace`, requested 1,000-token ceiling, and the final provenance-fenced context;
- center: selected memory cards on a timeline, including the current decision and its visibly superseded March predecessor;
- right: candidate funnel (`retrieved → scope-filtered → superseded → packed`), score components, exact `842 / 1,000` token accounting, vector coverage, and receipt ID.

The caption writes itself: **“Not just what your agent remembered—exactly what entered context, why, from where, and what was kept out.”** This is screenshot-worthy, technically honest, and difficult for a generic memory UI to copy without AOMS's receipt and scope architecture.

### The compounding launch loop

`setup/import → useful memories immediately → automatic scoped recall → receipt appears in Observatory → correction strengthens truth timeline → shareable proof attracts the next install`

That is a viral loop grounded in the product. “Agents remember forever” is a claim. A receipt screenshot another developer can reproduce is an artifact.

### Explicitly defer

- Defer live multi-machine sync and full team administration until identity, conflict, tombstone, and key semantics are designed.
- Defer mutable decay/reinforcement. Keep canonical records append/correct-oriented and ranking changes versioned.
- Defer a knowledge graph visualization until AOMS has normalized, queryable edges worth drawing.
- Defer autonomous semantic contradiction resolution. Suggestions require human review.
- Defer a separate analytics product; place honest receipt aggregates inside the Observatory.
- Defer encryption claims beyond the actual threat model and tested key lifecycle.

## 4. Trend check: where attention is flowing in mid-2026

### The loud missing layer

The whitespace is not another memory extraction algorithm. Individual incumbents ship pieces of the following, but no dominant product owns the coherent bundle:

> **Host-neutral, user-owned fleet memory with hard identity/scopes, automatic lifecycle use, a time-aware truth model, and proof of the exact context that crossed into the model.**

That combination matters. Local stores without sync/identity become per-machine silos. Graphs without serialization receipts cannot prove what influenced the agent. MCP servers without host hooks are callable shelfware. Automatic capture without correction/provenance becomes a garbage accumulator. Cloud profiles without portable export are not user-owned memory. AOMS is unusually close to joining these concerns without pretending one vector query solves them.

| Attention flow | What developers are loudly reacting to | Where incumbents remain incomplete | AOMS opening |
|---|---|---|---|
| **Context engineering over prompt engineering** | Context rot, compaction loss, tool-output bloat, cache economics, budget allocation, and deciding what *not* to inject. | Many memory products optimize storage/retrieval benchmarks but do not expose the final serialized artifact or its budget tradeoffs. | Lead with packed context + exact receipt, then add user-visible budget controls and ablations. AOMS should market the context boundary, not vector search. |
| **Agent orchestration and fleets** | Parallel subagents, background agents, planner/implementer/reviewer handoffs, resumable work, and cross-host continuity. | Orchestrators manage tasks and traces; memory tools often remain bound to one assistant, one app, or spoofable namespaces. | The relay, process-bound identities, workspace scopes, and one shared MCP brain are the wedge. Make setup truly multi-host and show scope isolation in the UI. |
| **Local-first / sovereign state** | Privacy, latency, offline capability, predictable cost, inspectable SQLite, and escape from cloud lock-in. | “Local” often means a local client with remote embeddings, or a single-machine store with no safe mobility story. | Keep local embeddings and one-file operations; make exports/imports excellent now. Pursue E2E device sync only when it preserves user-owned keys and scope semantics. |
| **Observability and evals** | Developers no longer accept “the agent used memory” without traces, regressions, canaries, and reproducible artifacts. | General agent tracing records calls but rarely proves which memory bytes entered context, which candidates were rejected, or whether scope filtering happened before serialization. | Receipt inspector + relay verifier + eval ablations can define “memory observability.” This may be the most defensible near-term category AOMS can own. |
| **Temporal truth, not timeless similarity** | Current-vs-obsolete facts, decision history, correction, provenance, and “what was believed when?” | Temporal graphs exist, but mainstream developer memory UX still presents a ranked pile of snippets; contradiction handling is often opaque extraction-time mutation. | Turn explicit supersession into a truth timeline and safe `as_of` semantics. Preserve evidence; never silently merge away disagreement. |
| **Automatic capture with governance** | Users want memory to work without repeatedly telling agents to remember, but fear secret ingestion, noise, and runaway profiles. | Session compressors capture aggressively; MCP tools wait to be called; feedback signals are frequently underspecified. | Productize selective host recipes, idempotency, provenance, scope preview, and a review inbox. AOMS can be automatic *and* governed if every capture remains inspectable. |
| **Portable protocols and composability** | MCP resources/prompts, stable URIs, interoperable artifacts, and moving state between tools. | MCP standardized calling faster than it standardized durable agent identity, tenancy, memory portability, or push/lifecycle behavior. | Add scoped resources for memories/receipts and own a portable import/export contract. Do not wait for MCP alone to solve host activation. |

### What could actually go viral

Viral developer tools produce a result that is instantly legible to someone who did not install them. For AOMS, that is not a database-size counter and not a benchmark leaderboard. It is one of these artifacts:

1. a split-screen relay where a cold agent states a hidden constraint, paired with the exact receipt that delivered it;
2. a Recall Observatory screenshot showing an obsolete belief suppressed, a private canary filtered, and 842 tokens packed under a 1,000-token ceiling;
3. a “brain transplant” import report showing thousands of memories moved locally with provenance intact and zero source files changed; or
4. a truth timeline answering “what did we believe in March, and why did it change?”

The first already exists as a rigorous bundle but is hard to consume. The next three make the same evidence visible and personally useful. That is the coherent launch story: **universal enough to ingest your history, visible enough to inspect every handoff, and trustworthy enough to correct rather than merely accumulate.**

## Bottom line

AOMS does not need more invisible capability before GitHub launch. It needs an honest first-run path and a visual surface that cashes the checks its backend already writes.

Ship activation, the Recall Observatory, a narrow but excellent importer framework, and the Truth Timeline. Make the receipt inspector the hero screenshot. Everything else—sync, teams, encryption, decay, feedback learning—should wait until it strengthens that same visible/trustworthy/universal story without widening the trust boundary faster than AOMS can prove it.
