# Launch assets

These assets are reproducible captures of real AOMS product paths using only a synthetic, publishable corpus. No canonical AOMS store, private memory, model account, or real model output is used.

## Included assets

| Asset | What it visibly proves |
|---|---|
| `recall-observatory-receipt-light.png` | The real Observatory receipt inspector in light mode: provenance-fenced packed context, a March predecessor labeled as superseded, a 12 → 10 → 9 → 4 candidate funnel, and exact 200 + 267 + 189 + 186 = 842 token arithmetic under a 1,000-token budget. |
| `recall-observatory-receipt-dark.png` | The same receipt and evidence in the product's dark theme. |
| `aoms-60-second-proof.html` | An accessible annotated transcript built from a real `init` → `remember` → new-process `recall --format json` CLI run. |
| `aoms-60-second-proof.png` | The browser-rendered terminal transcript used in the root README. |

Every raster asset is a 2x HiDPI PNG and is kept below 1.5 MB.

## Regenerate

From the repository root, use the project interpreter:

```console
/path/to/cortex-mem/.venv/bin/python docs/launch/assets/generate.py
```

The interpreter needs the project's normal runtime dependencies plus Pillow. Capture prefers a `playwright` CLI and an installed Google Chrome channel; it falls back to headless Chrome/Chromium with a tall fixed viewport. On the machine used for the committed captures, Playwright CLI, Google Chrome, Chromium, ImageMagick, and ffmpeg were available. `asciinema`, `agg`, and `svg-term` were not, so the terminal proof uses the requested annotated HTML/PNG fallback.

The generator:

1. creates a disposable database under `/tmp/aoms-launch-assets-*`;
2. seeds fixed-time `MemoryRecord` fixtures for a fictional Atlas launch, including an early-March release gate, its current successor, realistic project filler, and two deliberately invisible scope matches;
3. performs lexical-only recall through `AOMSApplication` and `RecallEngine` with `NullProvider`—there is no embedding download or model run;
4. starts the real loopback `ObservatoryHTTPServer` and captures its receipt URL in light and dark schemes with a HiDPI browser device profile;
5. invokes the real `cortex-mem` console entry point in separate writer and reader processes for the cold-recall proof; and
6. asserts the receipt/context reconciliation, supersession, scope-filter count, private-canary absence, 842-token total, HiDPI dimensions, and file-size ceiling before cleaning the disposable directory.

Pass `--keep-work-dir` only when you want to inspect the synthetic disposable stores locally. The script never resolves or opens the platform's canonical AOMS data directory.

## Privacy and evidence boundary

All names, memories, paths inside provenance fields, decisions, IDs, and command content in these assets are synthetic. The private-scope fixture contains an explicit publishable canary sentence, but its content and ID are asserted absent from the returned context, receipt page, and candidate table. The generator does not read `~/.local/share/aoms` or any other user-memory location.

These are real product outputs, not UI mockups, with four deliberate determinism/presentation controls:

- the demo clock, receipt UUID, and displayed latency are fixed;
- retrieval is lexical-only, so the screenshot shows 0% vector coverage and does not claim a model run;
- the terminal PNG labels itself as an annotated view and displays selected fields from the real JSON response while omitting the long packed context already demonstrated in the hero; and
- the proof uses two local CLI processes, not a cloud model, host UI, or the repository's separate **REHEARSAL**-grade multi-agent relay.

Those controls make regeneration stable; they do not alter scope enforcement, candidate retrieval, supersession resolution, context packing, receipt persistence, Observatory rendering, or the CLI process boundary being demonstrated.
