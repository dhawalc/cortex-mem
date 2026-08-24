## What changed

Describe the problem, the chosen behavior, and the user-visible result.

## Verification

List the exact checks you ran and their results. Include focused tests plus `python -m pytest` when practical.

## Contract and safety review

- [ ] I added or updated tests for this behavior.
- [ ] I preserved server-bound agent/workspace identity and added negative isolation coverage if scope behavior changed.
- [ ] I updated recall receipts, snapshots, or migration handling if a contract or stored schema changed.
- [ ] I considered token ceilings, supersession, provenance fencing, and deterministic behavior where relevant.
- [ ] Tests and deterministic fixtures do not require model credentials or network access.
- [ ] I did not include memory databases, private prompts, tokens, credentials, or unredacted user data.
- [ ] I updated public documentation for changed commands, defaults, compatibility, or security assumptions.

## Compatibility notes

Call out any CLI, MCP schema, receipt schema, storage migration, importer, host recipe, or privacy-boundary impact. Write `None` when there is no compatibility impact.
