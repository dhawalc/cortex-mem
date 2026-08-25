# SUPERSEDED by `../null-ollama/` — 2026-08-25

`control.py` in this directory is the first draft of the bare-model control. It
has been superseded by [`../null-ollama/`](../null-ollama/), which is the
published version: same experiment, same prompts, same model, with the five-file
adapter discipline, an environment record, a conflict-of-interest disclosure, the
scored artifact and the verbatim console output of the run.

**`control.py` is left in place unedited.** Nothing here modifies it.

## Why it was superseded — a bug worth recording

`control.py` never emits the `inputs` echo that the frozen `score.py` requires of
every result row:

```python
"inputs": {
    "initial_state": case["initial_state"],
    "observation": case["observation"],
}
```

`score.score_document` checks that echo per case and raises
`ScoreError: input echo mismatch for MCB-C-01` when it is absent. The check
exists so a result document cannot be silently detached from the corpus it claims
to answer, and it is doing its job here.

The failure mode is expensive rather than dangerous. Scoring happens **after all
48 cases have run**, so a full run completes — roughly 25 minutes of local
inference, including one case that took 771 seconds — and then aborts at the
scoring step with no artifact written and every row discarded. It produces no
wrong number; it produces no number at all.

`../null-ollama/adapter.py` adds the echo, and the fix was verified against the
frozen scorer before the run: the scorer accepts the document shape, and the
freeze hashes are unchanged.

**Any figure attributed to `control.py` should be treated as unsubstantiated
until it is reproduced by `../null-ollama/adapter.py`**, because this harness
cannot have produced a scored artifact.
