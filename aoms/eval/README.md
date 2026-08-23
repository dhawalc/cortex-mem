# AOMS retrieval evaluation

Run the built-in 36-case suite and all launch ablations:

```console
python -m aoms.eval run
python -m aoms.eval list
python -m aoms.eval compare BASELINE_RUN CURRENT_RUN
```

Every run prints a compact table and stores a complete JSON artifact under
`.aoms-eval/runs`. `--config` is repeatable; the presets are `lexical-only`,
`vector-only`, `hybrid`, and `no-scope`. Synthetic runs use a temporary fixture
database and deterministic network-free embeddings.

An orchestrator can evaluate an existing database without writing to it:

```console
python -m aoms.eval run --database snapshot.sqlite3 --suite suite.json \
  --manifest manifest.json --config lexical-only
```

Existing databases are always opened with SQLite `mode=ro`; recall receipts are
captured in memory. A supplied store must already contain vectors matching the
query provider profile for vector configurations.

## Metric definitions

For case `q`, let `Gq` be its gold IDs, `Tkq` the first `k` ranked candidate
IDs, and `Pq` the packed source IDs.

- `recall@k(q) = |Gq ∩ Tkq| / |Gq|`.
- `budget-recall(q) = |Gq ∩ Pq| / |Gq|`.
- For a negative case (`|Gq| = 0`), either recall is `1` exactly when its
  corresponding result set is empty, otherwise `0`.
- `non-gold share = Σq |Pq \ Gq| / Σq |Pq|` (zero when nothing is packed).
- For each supersession pair `(old, new)` touched by packed context, stale is
  counted when `old ∈ Pq` and `new ∉ Pq`; `stale-rate = stale counts / touched
  pair counts`.
- Contradiction is counted when both `old` and `new` are packed;
  `contradiction-rate = contradictory pair counts / touched pair counts`.
- `canary leakage = packed canary selections / all packed selections`; the
  artifact also stores the integer canary count, which must be zero.
- `token utilization = Σq packed_tokens(q) / Σq token_budget(q)`.
- Latency p50/p95/p99 use sorted per-query engine latency and linearly
  interpolated Hyndman-Fan type 7 percentiles.

Recall and budget-recall are macro-averaged across cases. Other rates above are
micro-averaged across their explicit opportunities, avoiding small-result
queries receiving disproportionate weight.
