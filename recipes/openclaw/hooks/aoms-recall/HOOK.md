---
name: aoms-recall
description: "Inject task-packed AOMS context before every OpenClaw agent bootstrap"
metadata:
  { "openclaw": { "emoji": "🧠", "events": ["agent:bootstrap"], "requires": { "bins": ["cortex-mem"] } } }
---

# AOMS startup recall

Runs `cortex-mem recall` with a 2,000-token budget before OpenClaw injects its
workspace bootstrap context. This replaces an HTTP-specific `boot_aoms.py` and
uses the same scoped CLI contract as other hosts.
