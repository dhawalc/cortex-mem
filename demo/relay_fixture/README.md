# AOMS relay fixture

This directory contains the deterministic scenario used by the cold-start
three-agent relay. The actual agent CLI runner is intentionally not part of
this fixture.

The tiny repository under `repository/` does not contain the injected
constraints or canary values. Seed those runtime memories into a disposable
store:

```console
python -m demo.relay_fixture.seed --db /tmp/relay-aoms.sqlite3
```

A completed-run directory consumed by the verifier has this shape:

```text
completed-run/
├── stage-2/recall.json
├── stage-3/recall.json
└── workspace/
    └── relay_service/service.py
```

Each recall artifact is `{"receipt": <RecallReceipt>, "context": "..."}`.
The context is retained only so canary fact strings can be checked at the
actual serialization boundary. Run independent verification with:

```console
python -m demo.relay_fixture.verify completed-run
```

The verifier checks injected constraint IDs in both receipts, the stage-3
regression clue, canary absence, exact token reconciliation and ceilings, then
runs four black-box acceptance checks against the completed workspace.
