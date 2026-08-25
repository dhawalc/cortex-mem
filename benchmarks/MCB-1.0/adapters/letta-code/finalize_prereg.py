#!/usr/bin/env python3
"""Fill the pre-registration's hash tables and verbatim prompt appendix.

Run once, immediately before the pre-registration is committed and before case 1
of the first scored run. It only substitutes placeholder comments; it never
edits prose, predictions or outcome paragraphs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREREG = ROOT / "PREREGISTRATION-LETTA-CODE.md"

ADAPTER_FILES = [
    "adapters/letta-code/adapter.py",
    "adapters/letta-code/config.json",
    "adapters/letta-code/config-qwen3.6-27b.json",
    "adapters/letta-code/run-all.sh",
    "adapters/letta-code/pilot.py",
    "adapters/letta-code/pilot-cases-mechanics.json",
    "adapters/letta-code/pilot-cases-autonomous.json",
    "adapters/letta-code/README.md",
    "adapters/letta-code/CURRENCY.md",
    "adapters/model-only-control/control.py",
    "runner.py",
]

PUBLISHED_FILES = [
    "adapters/letta/adapter.py",
    "adapters/letta/config.json",
    "adapters/letta/results.json",
    "RESULTS-LETTA.md",
    "adapters/aoms/adapter.py",
    "adapters/aoms/config.json",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def table(names: list[str]) -> str:
    rows = ["| File | sha256 |", "|---|---|"]
    for name in names:
        path = ROOT / name
        if not path.exists():
            rows.append(f"| `{name}` | *(absent at pre-registration time)* |")
            continue
        rows.append(f"| `{name}` | `{sha256(path)}` |")
    return "\n".join(rows)


def appendix() -> str:
    config = json.loads(
        (ROOT / "adapters/letta-code/config.json").read_text(encoding="utf-8")
    )
    parts = [
        "\n---\n",
        "## Appendix A — every prompt string, verbatim\n",
        "Reproduced here so that the exact text under test is fixed by this "
        "commit and not only by a hash. Any difference between this appendix "
        "and `adapters/letta-code/config.json` at run time voids the attempt.\n",
        "### `persona` — written to `system/persona.md` before the clock starts\n",
        "```text",
        config["persona"],
        "```\n",
        "### `persona_description` — the frontmatter description of `persona.md`\n",
        "```text",
        config["persona_description"],
        "```\n",
        "### `state_description` — the frontmatter description of `mcb-state.md`\n",
        "```text",
        config["state_description"],
        "```\n",
        "### `statement_preamble` — inserted between observation text and the "
        "canonical lines\n",
        "```text",
        config["statement_preamble"],
        "```\n",
        "### `separator`\n",
        "```text",
        repr(config["separator"]),
        "```\n",
        "### The message template sent to the agent in `process`\n",
        "The only text the agent receives is built as:\n",
        "```text",
        "{observation.text}",
        "",
        "{statement_preamble}",
        "{TOPIC :: TEXT for each observation statement, one per line}",
        "```\n",
        "Nothing else is appended. No case metadata, no expectation, no hint "
        "about the relationship class or the expected outcome reaches the "
        "agent.\n",
        "### Control harness prompts\n",
        "The non-conforming control reuses `adapters/letta/config.json`'s "
        "`persona`, `separator` and `statement_preamble` verbatim — the "
        "published V1 strings, unmodified — and presents the block as:\n",
        "```text",
        '{persona}',
        "",
        'The "facts" block currently contains:',
        "<facts>",
        "{block}",
        "</facts>",
        "```\n",
    ]
    return "\n".join(parts)


def main() -> int:
    text = PREREG.read_text(encoding="utf-8")
    if "<!-- ADAPTER-HASHES -->" not in text:
        raise SystemExit("placeholders already filled; refusing to run twice")
    text = text.replace("<!-- ADAPTER-HASHES -->", table(ADAPTER_FILES))
    text = text.replace("<!-- PUBLISHED-HASHES -->", table(PUBLISHED_FILES))
    text = text.rstrip("\n") + "\n" + appendix()
    PREREG.write_text(text, encoding="utf-8")
    print(f"filled {PREREG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
