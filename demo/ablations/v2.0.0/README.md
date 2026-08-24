# AOMS v2.0.0 unfiltered ablations

This committed launch archive contains the complete network-free retrieval
matrix and the complete scripted relay memory ablation. The five eval JSON
files and both relay variants are retained without case selection, metric
filtering, or removal of failed checks.

Generated from source revision `2d6b88c3cedca9a1842fe05de7167f051d7632c7`
with Python 3.12.3. `manifest.json` seals every other regular file in this
directory, including the relay's own nested manifest.

## Retrieval matrix

All configurations ran the same 36-case `starter-retrieval-credibility` suite
over the 160-record corpus generated with seed 7. Recall and safety rates are
reported exactly in `summary.json`; values below are rounded only for display.

| Configuration | Cases | R@k | Budget R | Non-gold | Contradiction | Canary leakage | Token use | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| lexical-only | 36 | 0.750 | 0.750 | 0.417 | 0.000 | 0.000 | 0.848 | 24.18 |
| vector-only | 36 | 0.648 | 0.519 | 0.681 | 0.000 | 0.000 | 0.846 | 48.42 |
| hybrid | 36 | 0.750 | 0.741 | 0.431 | 0.000 | 0.000 | 0.848 | 53.02 |
| no-supersession | 36 | 0.750 | 0.741 | 0.431 | 0.200 | 0.000 | 0.845 | 51.05 |
| no-scope | 36 | 0.750 | 0.741 | 0.431 | 0.000 | 0.083 | 0.850 | 49.84 |

Latency is host-sensitive; the safety deltas are the launch-relevant result.
The governed configurations have zero contradiction and canary-leakage rates.
Removing supersession resolution exposes contradictions, and removing scope
enforcement exposes six packed canary selections.

## Scripted relay ablation

| Variant | Prompts | Verifier | Checks | Stage 2 tokens | Stage 3 tokens |
|---|---|---:|---:|---:|---:|
| memory enabled | identical | PASS | 12 | 853 / 1000 | 910 / 1000 |
| memory disabled | identical | FAIL | 0 | no recall artifact | no recall artifact |

`relay-scripted/comparison.json` declares the only variable as MCP memory
availability and preserves the baseline's missing-recall and acceptance-test
failures. The scripted verifier's `PROOF` grade describes deterministic relay
protocol evidence only; it does not replace the launch's human-gated live
three-client proof on a funded, bwrap-capable host.

## Reproduce and validate

Run from a pinned v2.0.0 source checkout with development dependencies:

```console
python -m aoms.eval run --seed 7 --records 160 --output-dir eval
python -m demo.relay.runner run --output relay-scripted \
  --agents scripted,scripted,scripted --seed 7319 --with-baseline
python -m demo.relay.runner validate relay-scripted
python -m demo.relay.runner validate .
```

`summary.json` is the compact machine-readable index. The raw eval filenames
are their canonical run IDs; the archive manifest is the authoritative file
inventory and SHA-256 map.
