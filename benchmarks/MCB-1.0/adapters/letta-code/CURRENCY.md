# CURRENCY — Letta Code adapter

Per GOVERNANCE §9, every adapter ships dated vendor evidence for the claim that
what was measured is what the vendor currently ships, and for the claim that the
execution mode measured is one the vendor considers fair.

## What is pinned

| Item | Value | Dated |
|---|---|---|
| Package | `@letta-ai/letta-code@0.30.31` | 2026-08-24 |
| npm `dist.shasum` | `35f23ddadee69cb91b60aa1866a8624cbd3016a9` | 2026-08-24 |
| npm `dist.integrity` | `sha512-Y7lWbN3W0uwBowVARpafWAfCa55IYJLjwCAfRzcuosyfUbbA1lWNBzY+Hzj1Lf794d6AmCj5vLzOgp9JJKJz8Q==` | 2026-08-24 |
| Local tarball sha256 | `c09fdd95f411aa6bae9b0fcd7854004faa434d932f08c44cb45df13c9f85c609` | 2026-08-24 |
| `letta --version` | `0.30.31 (Letta Code)` | 2026-08-24 |
| Node | v25.8.2 | 2026-08-24 |
| Execution mode | `--backend local`, gated by `LETTA_LOCAL_BACKEND_EXPERIMENTAL` | 2026-08-24 |

## Vendor ratification status: NOT OBTAINED

Four questions were identified as gating a fair measurement:

1. Is `letta-code --backend local` a fair measurement target, given that it is
   gated behind an `…_EXPERIMENTAL` environment variable?
2. Which MemFS surface counts as the system's durable state?
3. Can an obsolete statement be made non-current there?
4. Would Letta veto or ratify this adapter?

**None of these has a vendor answer as of 2026-08-24.** No outreach was sent
from the run that produced this file; sending it was outside that run's
authority. Therefore, per the pre-registration's own escalation rule, the
consequence is not a footnote:

> **Every result produced by this adapter is titled as measuring an unratified,
> vendor-gated experimental execution mode.** It is not "Letta Code's score". It
> is the score of one unratified configuration of one experimental backend.

If and when the vendor answers, the answers belong in this file with their date,
and the title qualifier may be revisited — by adding a new result, never by
editing a published one.

## Known measurement hazard found while building this adapter

The `letta` CLI truncates its stdout at exactly one pipe buffer (8192 bytes)
when stdout is a pipe, because the Node process exits before the pipe drains.
Measured on 2026-08-24: the identical `agents create` invocation produced 8192
bytes to a pipe and 19114 bytes to a regular file. Any harness that reads this
CLI's JSON over a pipe will silently receive truncated output. This adapter
redirects to regular files for that reason.

Earlier reconnaissance in this project read the number 8192 as evidence of an
8192-token model context limit and proposed changing the shared Ollama systemd
unit. That diagnosis was wrong, and acting on it would have modified shared
system state to fix a bug in output plumbing. The shared unit was not touched.
