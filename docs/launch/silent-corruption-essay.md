# My agents' memory was silently corrupted for months — here's what we rebuilt

*Published 2026-08-24.*

## The audit was supposed to be about a deprecated plugin

I run a fleet of agents across Claude Code, Codex, and OpenClaw. For roughly six months, they shared an always-on memory service called AOMS. It stored decisions, facts, failures, procedures, and session history so a new agent session did not always have to begin from zero.

In August 2026, I started an audit because one of the platform-specific memory plugins was deprecated. I expected integration cleanup: identify which clients still called the old plugin, remove stale configuration, and make the contracts agree again.

Instead, the audit exposed a storage failure that had been running quietly every night for months.

The old service used JSONL files as its primary store. A scheduled decay endpoint read each tier file, adjusted weights on sufficiently old records, and rewrote the file. It was meant to make unused memories gradually less prominent. The rewrite looked ordinary:

```python
lines = filepath.read_text(encoding="utf-8").splitlines()
new_lines = []

for line in lines:
    # parse the record; maybe update its weight
    if record_was_changed:
        new_lines.append(json.dumps(entry) + "\n")
    else:
        new_lines.append(line)

filepath.write_text("".join(new_lines), encoding="utf-8")
```

The bug is in the interaction between two unremarkable calls. `splitlines()` was used without `keepends=True`, so it removed every newline. Most branches then appended the original `line` without putting the newline back. Finally, `"".join(new_lines)` glued those pass-through records together.

Only records whose weights actually changed received a new `\n`. Blank lines, schema headers, recent records, malformed records, records without timestamps, dry-run branches, and records whose computed weight barely moved did not. Every non-dry-run decay could therefore join adjacent JSON objects into a larger line. The next night did it again.

JSON parsers did not see “slightly bad JSONL.” They saw streams such as `}{` inside a single line. By the time I found it, `facts.jsonl` contained a 1.14 GB line. Across the tier files, millions of JSON objects had been fused into GB-scale blobs.

The immediate fix is commit `572860c`. Every branch restores its newline, and the replacement is written to a same-directory temporary file, flushed, `fsync`ed, and atomically installed with `os.replace`. That prevents the original corruption and also removes the separate risk of truncating the live store if the process dies halfway through a rewrite.

That patch stopped new damage. It did not recover what was already there.

## At 1 A.M., the right feature was a freeze

The incident crossed midnight. The first emergency archive was stamped 23:12 on August 22: a 1.9 GB frozen copy of the live data. At about 1 A.M. on August 23, I was still operating under an emergency freeze, not attempting clever in-place repairs. The rule was simple: preserve the input, make every recovery output-only, and keep a rollback path.

That discipline mattered because the old backup story was weaker than I had assumed. One VPS path was an unversioned live mirror driven by `rsync --delete`. A mirror is useful for machine loss, but it faithfully mirrors corruption too. There were timestamped archives, but recovery generations had not been treated as a verified, versioned product contract. During the incident I replaced that ambiguity with an explicit stopgap: seven local and three remote generations, written on a schedule and kept separately from the live mirror.

The service also had operational blind spots. `/stats` performed a huge synchronous scan and could starve health checks. Commit `1ad370e` moved that scan off the event loop, put it behind a 300-second single-flight cache, and taught the streaming parser to inspect objects inside blobbed lines. During a cold 110-second scan, `/health` still returned in 14–35 ms.

The same commit restored embed-on-write with a durable failure marker. Before that, the vector index had received no new writes since May 26. The system could accept a memory and still leave it absent from semantic recall. After the patch, a test record became the top semantic result in about 30 seconds, and failed indexing work landed in an `unindexed_ids.jsonl` queue instead of disappearing.

Those changes made the damaged service observable and stopped it getting worse. They still did not answer the central question: how much memory did I actually have?

## Five million objects were not five million memories

The recovery parser found 5,023,727 JSON objects inside the blobs. Every object had a unique ID.

That initially made ID-based deduplication look useless, because it was. The ingestion path had generated a fresh UUID each time it re-ingested the same content. Sampling showed that the same fact could be written as many as 54 times per day under different IDs. In a 200,000-object probe, duplicate content accounted for 75.0% of experiences, 47.8% of facts, and 96.3% of skills. The 7,365 unique skill contents almost exactly matched the 7,364 procedural chunks in the old vector index.

The apparent five-million-record corpus was mostly a re-ingestion loop.

Commit `1a251a7` is the recovery tool. It streams concatenated JSON rather than loading multi-gigabyte lines into memory. For each object, it computes a SHA-1 content hash after removing volatile fields such as regenerated IDs and ingestion timestamps. It keeps the newest record for each stable content hash, writes clean JSONL into a separate output directory, and runs an independent verification pass before any swap.

The final count was:

```text
5,023,727 parsed objects
  165,321 unique records
4,858,406 re-ingestion duplicates removed
    96.71% duplicate content
```

After the verified swap, the oldest queryable record went back to February 10. A later import into the new store contained 165,338 records—the recovered 165,321 plus 17 records written after the swap—and a second import was idempotent.

This changed how I think about memory metrics. “Records stored” had looked like growth. It was actually evidence of a missing idempotency boundary. Unique IDs proved only that the UUID generator worked. The useful measurement was stable content identity plus provenance.

## The old system failed in more than one place

The newline bug was dramatic, but treating it as the whole incident would let the architecture off too easily.

The reinforcement loop was dead. The daemon called the weight-adjustment endpoint without the required `tier`, received HTTP 422 responses, and never reinforced anything. Meanwhile, nightly decay kept running. Commit `47c1c8d` repaired that request in May, after months in which weights had flattened toward the floor. The audit then found a second decay defect: it applied `decay_rate ** total_age` to a weight that had already been decayed on prior nights, compounding decay from the original age repeatedly. In the rebuilt product, decay and reinforcement are removed from the public surface rather than cosmetically repaired.

The integrations had drifted too. Different platforms had their own plugins, hooks, boot scripts, and assumptions. The HTTP API reported version 1.2.0 while the package reported 1.0.0. The README described four memory tiers even though the “working” tier did not exist. Two memory systems—the JSONL/Chroma store and a separate L0/L1/L2 document system—lived beside each other without one contract.

This is what per-platform plugin drift looks like in practice: not one catastrophic incompatibility, but several plausible interfaces that stop describing the same system.

## Rebuilding the product in one day

Once the recovered corpus was stable, I stopped adding patches to the old shape. On August 23, the rebuild proceeded as a sequence of small contracts.

Commits `f4202a1`, `b9e6297`, and `f80222b` introduced canonical Pydantic models, an application layer, an idempotent importer, and a SQLite repository in WAL mode with FTS5. JSONL became an import/export format instead of the mutable source of truth. SQLite transactions replaced whole-file rewrites; WAL allowed concurrent readers while a writer committed.

Commits `e87f0af` and `a04b8a8` added recall as a deterministic packing operation. Retrieval combines lexical, vector, recency, and scope signals when available, then serializes only what fits under the caller's explicit token budget. Each result includes structured sources and a versioned recall receipt: query, bound scope, candidate scores, selected and rejected records, provenance, exact token costs, truncation, and latency.

Commits `5377424` and `06dee9b` made scope enforcement part of construction, not a filter an agent can ask to disable. A process or authenticated principal is bound to an agent ID and workspace. Reads distinguish `agent-private`, `workspace`, and `user-global` visibility. Canary tests verify that records outside that boundary never enter the serialized model context.

Commit `fe9a2b0` added fully local embeddings through FastEmbed, an optional Ollama provider, `sqlite-vec`, and a durable resumable embedding queue. Missing vectors degrade to the remaining scorers rather than turning recall into an all-or-nothing service.

Commits `8c59026` and `d9c3453` added a hand-written FastMCP adapter over the same application contracts. It exposes exactly three tools: `recall`, `remember`, and `search`. Identity is bound once from process configuration for stdio, or from bearer-token claims for HTTP; it is never accepted from a tool argument.

Finally, commits `97ecfe8`, `43b1535`, and `826f997` produced the `cortex-mem` 2.0.0 wheel and operational CLI: initialize, diagnose, import, export, restore, backfill, sweep, and run MCP. A fresh wheel passed initialization, `doctor`, and an MCP handshake reporting one package version and the same three tools.

This was not six months of reliability work compressed into a day. It was one day of replacing the specific boundaries the incident proved were missing: transactional storage, idempotency, one contract, scoped identity, observable retrieval, and portable recovery.

## The first eval failed the system it had just been written for

The new architecture was cleaner, but clean architecture can still return the wrong context.

Commits `877e0d5` and `38c6225` introduced a seeded 36-case evaluation suite. It measures recall at K, recall under the packed-token budget, stale and contradictory memories, canary leakage, token utilization, and latency across lexical, vector, hybrid, scope, and supersession ablations.

On its first day, the contradiction-rate metric returned `1.0`.

The recall engine knew that a newer record superseded an older one, but ranking and packing could still select both sides of the pair. An agent asking for the current decision received the current decision and its obsolete predecessor in the same context. Provenance made the error inspectable; the eval made it impossible to wave away.

Commit `f94f11f` changed packing to select only chain heads, including transitive supersession, with cycle guards. Suppressed IDs are retained in the receipt so exclusion stays auditable. Contradiction rate went from `1.0` to `0.0`.

That failure was encouraging in a narrow sense: the harness found a real retrieval defect on the day the harness existed. It also set the standard for future claims. “The memory was stored” is not success. The right current memory must cross the scope boundary, survive ranking, fit the token ceiling, and arrive with evidence of why it was selected.

## What AOMS is now

AOMS is now a local-first memory router for a fleet of MCP agents. It keeps one SQLite/WAL source of truth, provides local hybrid retrieval, binds reads and writes to agent/workspace scopes, packs recall to an explicit token budget, and emits provenance-rich receipts for what entered context. Stdio is the default. Streamable HTTP is optional and requires bearer identity plus TLS for non-loopback binds. Storage and retrieval stay local; no claim is made that the model clients themselves are offline.

The cold-start relay is the practical proof target: Claude Code plans, Codex starts without its transcript and continues from scoped AOMS memory, and OpenClaw reviews from another cold process. The v2.0.0 release artifact is explicitly **REHEARSAL** grade: it used Claude/Codex/Claude, Claude OAuth, and Codex `danger-full-access`, and it predates the final release revision. The upgrade path to **PROOF** grade is a new run with bare provider authentication on a bwrap-capable host using Codex `workspace-write` sandboxing, plus OpenClaw credentials for the full three-client claim. The artifact records prompts, MCP traffic, recall receipts, repository diffs, deterministic tests, and hashes. The point is not that agents “never forget.” The point is that a handoff can be inspected and falsified.

The old service taught me that persistence without integrity is just durable uncertainty. The rebuilt one is smaller in surface area, stricter about identity, and much more explicit about what it knows.

One-line install from Git:

```console
uvx --from git+https://github.com/dhawalc/cortex-mem cortex-mem init
```
