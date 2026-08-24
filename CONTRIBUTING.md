# Contributing to AOMS

Thanks for helping improve AOMS. Changes are welcome across the core contracts, SQLite repository, retrieval and evaluation code, MCP adapter, CLI, host recipes, relay protocol, tests, and documentation.

## Set up a development environment

The package supports Python 3.10 and newer. Python 3.11 or 3.12 is recommended for development and matches the primary CI matrix:

```console
git clone https://github.com/dhawalc/cortex-mem.git
cd cortex-mem
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Run the canonical suite from the repository root:

```console
python -m pytest
```

The tiny repository under `demo/relay_fixture/repository` has a separate internal harness and is intentionally excluded from the root suite. Run it independently when changing the fixture:

```console
cd demo/relay_fixture/repository
python -m pytest
```

The CI-safe credibility harnesses are deterministic and require no model account or network access at runtime:

```console
python -m aoms.eval run --records 78 --output-dir /tmp/aoms-eval-runs
python -m demo.relay.runner run --output /tmp/aoms-relay \
  --agents scripted,scripted,scripted --seed 7319 --with-baseline
python -m demo.relay.runner validate /tmp/aoms-relay
```

These commands write only to the paths you provide. Do not point tests, demos, or recovery experiments at a real AOMS data directory.

Build and inspect the distributable wheel with:

```console
python -m build --wheel
```

## Make focused changes

- Keep transport adapters behind `AOMSApplication` and the canonical Pydantic contracts. Do not create a second transport-specific model layer.
- Treat scope identity as trusted process or authentication context. Never accept an agent or workspace identity from a model-facing tool argument.
- Preserve deterministic token packing and versioned recall receipts when changing retrieval.
- Add negative isolation tests for scope changes and regression cases for ranking, supersession, import idempotency, or recovery changes.
- Keep local operation usable without API keys. Tests and deterministic relay replay must not require secrets or network access.
- Never commit memory databases, exports containing user data, tokens, model credentials, or relay artifacts that contain private prompts.
- Keep maintenance and destructive operations out of the MCP tool surface unless a separate design and security review explicitly changes that policy.

## Pull requests

A good pull request explains the behavior being changed, why the existing behavior is insufficient, and how the new behavior was verified. Include relevant test output and call out changes to contracts, receipt schemas, storage migrations, privacy boundaries, or command-line compatibility.

Keep commits reviewable and avoid mixing unrelated cleanup into a behavioral change. Update user-facing documentation when commands, defaults, schemas, or security assumptions change.

By contributing, you agree that your contribution is licensed under the repository's MIT License.

## Report security issues privately

Do not open a public issue for a suspected vulnerability. Follow the private disclosure process in [SECURITY.md](SECURITY.md).
