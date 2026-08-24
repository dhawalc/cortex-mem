# AOMS contest-ledger adapter

The published baseline adapter lives in `../aoms/` and is unchanged, so
`results.json` remains reproducible from this tree. This directory is a copy
with exactly one functional line added.

## The complete diff

```
$ diff adapters/aoms/adapter.py adapters/aoms-contest-ledger/adapter.py
```

- **one functional line**: `claim_key=unit["topic"]` inside `_remember`
- a docstring explaining the change
- two `ADAPTER_INFO` strings (`translation_policy`, `version`) so the emitted
  result artifact is self-describing

`config.json` is byte-identical, so `instruction_markers` is unchanged.

## Why this is conforming

`SPEC.md:36-38`:

> `topic` is a neutral identity key for the proposition being updated; it is
> not a storage identifier and need not be persisted by the tested system.
> Exact text is the portable interchange representation. An adapter may
> translate it into a native representation, but must translate it back
> losslessly on retrieval.

Declaring the interchange `topic` as the native claim slot is exactly that
translation. `retrieve_durable_state` is untouched and still reads the topic
back out of record content, so the round trip is lossless.

No prose is read anywhere in this change. The adapter still makes no write
decision beyond translating an explicit INSTRUCTED operation into
`supersede`, which is what the baseline adapter already did.

## What we considered and rejected

The Minimalist proposal's `disclaimer_markers` list would have mapped
observation prose to an evidentiary field. Measured against the corpus it hit
10/12 unsupported cases with 0/36 false positives. A perfect separator over a
frozen corpus is the fingerprint of a list derived from the answer key, not a
discriminator, and mapping prose sentiment to a write decision moves the
verdict into the adapter. It was rejected for that reason and is recorded here
so the rejection is auditable.
