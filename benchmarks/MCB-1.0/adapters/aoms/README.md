# AOMS reference adapter

This adapter exercises the real transport-independent `AOMSApplication` over
`SQLiteMemoryRepository`. It does not call MCP, write the normal AOMS data
directory, run a service, or use a model. Embeddings are disabled with
`NullProvider`.

Every benchmark case receives a new SQLite database beneath a runner-created
directory under `/tmp`; the adapter refuses any other storage root. Initial and
observation statements are stored as AOMS fact content with their neutral
`topic` and `text` unchanged.

## Translation policy

AOMS deliberately does not infer semantic conflict. This adapter therefore
maps an explicit natural-language replacement/correction instruction to
`AOMSApplication.supersede` when exactly one current statement has the same
topic. With no explicit instruction, each novel observation statement is
passed to `AOMSApplication.remember` as an independent durable fact. Identical
statements are a logical no-op. The explicit marker list is configuration, was
written before execution, and is committed with the result.

Retrieval lists records through the repository boundary and computes current
declared-lineage heads: any record named as a predecessor by a visible record
is historical, while independent records remain current. Exact duplicates are
collapsed. Conflicting independent current values are both returned so the
frozen scorer can reject the state; the adapter does not choose between them.

This translation is intentionally thin. It gives AOMS credit for declared
replacement, leaves AUTONOMOUS conflict inference to AOMS (which does not
perform it by design), and does not add an adapter-side authority, freshness,
or injection filter that AOMS itself lacks.

## Run

From the repository root, with the required interpreter:

```sh
/home/dhawal/cortex-mem/cortex-mem/.venv/bin/python \
  benchmarks/MCB-1.0/runner.py \
  --adapter benchmarks/MCB-1.0/adapters/aoms/adapter.py \
  --config benchmarks/MCB-1.0/adapters/aoms/config.json \
  --output benchmarks/MCB-1.0/results.json
```

The runner prints the scratch directory. It may be removed after auditing; the
committed `results.json` is the benchmark artifact.
