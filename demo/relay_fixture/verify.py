"""Verify completed cold-start relay artifacts without driving agent CLIs."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from aoms.contracts import Provenance
from aoms.receipts import RecallReceipt
from demo.relay_fixture.acceptance import run_acceptance
from demo.relay_fixture.seed import SCENARIO_PATH, load_scenario


@dataclass(frozen=True, slots=True)
class VerificationReport:
    scenario_id: str
    passed: bool
    grade: str
    checks: tuple[str, ...]
    failures: tuple[str, ...]

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _PackedMemory:
    memory_id: str
    content: str
    provenance: Provenance


_MEMORY_START = "<!-- AOMS_MEMORY_START: UNTRUSTED -->"
_MEMORY_END = "<!-- AOMS_MEMORY_END -->"
_JSON_FENCE = "````json"
_FENCE_END = "````"


def _packed_memories(context: str) -> tuple[_PackedMemory, ...]:
    """Parse only authenticated-shaped AOMS blocks, never surrounding raw text."""

    memories: list[_PackedMemory] = []
    cursor = 0
    decoder = json.JSONDecoder()
    while cursor < len(context):
        start = context.find(_MEMORY_START, cursor)
        if start < 0:
            if context[cursor:].strip():
                raise ValueError("text outside AOMS memory blocks")
            break
        if context[cursor:start].strip():
            raise ValueError("text outside AOMS memory blocks")
        end = context.find(_MEMORY_END, start + len(_MEMORY_START))
        if end < 0:
            raise ValueError("unterminated AOMS memory block")
        body = context[start + len(_MEMORY_START) : end]
        fence = body.find(_JSON_FENCE)
        if fence < 0:
            raise ValueError("AOMS memory block has no JSON fence")
        json_start = fence + len(_JSON_FENCE)
        encoded = body[json_start:].lstrip()
        try:
            payload, consumed = decoder.raw_decode(encoded)
        except json.JSONDecodeError as exc:
            raise ValueError("AOMS memory block has invalid JSON") from exc
        remainder = encoded[consumed:].lstrip()
        if not remainder.startswith(_FENCE_END) or remainder[len(_FENCE_END) :].strip():
            raise ValueError("AOMS memory block has malformed JSON fencing")
        if not isinstance(payload, dict):
            raise ValueError("AOMS memory payload is not an object")
        memory_id = payload.get("id")
        if not isinstance(memory_id, str) or not memory_id.strip():
            raise ValueError("AOMS memory payload has no valid id")
        content = payload.get("content")
        if isinstance(content, str):
            content_text = content
        elif isinstance(content, (dict, list)):
            content_text = json.dumps(content, ensure_ascii=False, sort_keys=True)
        else:
            raise ValueError(f"AOMS memory {memory_id} has invalid content")
        provenance = Provenance.model_validate(payload.get("provenance"))
        memories.append(
            _PackedMemory(
                memory_id=memory_id,
                content=content_text,
                provenance=provenance,
            )
        )
        cursor = end + len(_MEMORY_END)
    if not memories:
        raise ValueError("packed context contains no AOMS memory blocks")
    return tuple(memories)


def _normalized(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", value).split())


def _missing_phrase_groups(content: str, groups: Any) -> list[str]:
    """Return required concept groups with no matching declared phrase alternative."""

    normalized_content = _normalized(content)
    if not isinstance(groups, list) or not groups:
        return ["<scenario has no key phrases>"]
    missing: list[str] = []
    for group in groups:
        alternatives = [group] if isinstance(group, str) else group
        if (
            not isinstance(alternatives, list)
            or not alternatives
            or not all(isinstance(item, str) and item.strip() for item in alternatives)
        ):
            missing.append("<invalid key phrase group>")
            continue
        if not any(_normalized(item) in normalized_content for item in alternatives):
            missing.append(" | ".join(alternatives))
    return missing


def _load_recall_artifact(path: Path) -> tuple[RecallReceipt, str, str]:
    raw_text = path.read_text(encoding="utf-8")
    payload = json.loads(raw_text)
    receipt_payload = payload.get("receipt", payload)
    receipt = RecallReceipt.model_validate(receipt_payload)
    return receipt, str(payload.get("context", "")), raw_text


def _evidence_grade(root: Path) -> str:
    """Award proof grade only when bare auth and host sandboxing are evidenced."""

    has_bare_claude = False
    has_sandboxed_codex = False
    for record_path in sorted((root / "stages").glob("stage-*/record.json")):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        process = record.get("process", {})
        adapter = process.get("adapter")
        evidence = process.get("adapter_evidence", {})
        auth = evidence.get("auth", {}) if isinstance(evidence, dict) else {}
        if isinstance(auth, dict) and auth.get("mode") == "oauth":
            return "REHEARSAL"
        if adapter == "claude" and isinstance(auth, dict):
            has_bare_claude = has_bare_claude or (
                auth.get("mode") == "bare"
                and auth.get("user_level_config_excluded") is True
            )
        sandbox = evidence.get("sandbox", {}) if isinstance(evidence, dict) else {}
        if isinstance(sandbox, dict) and sandbox.get("mode") == "danger-full-access":
            return "REHEARSAL"
        if adapter == "codex" and isinstance(sandbox, dict):
            has_sandboxed_codex = has_sandboxed_codex or (
                sandbox.get("mode") == "workspace-write"
                and sandbox.get("host_sandbox_enabled") is True
            )
    return "PROOF" if has_bare_claude and has_sandboxed_codex else "REHEARSAL"


def verify_run(
    run_dir: str | Path, *, scenario_path: Path = SCENARIO_PATH
) -> VerificationReport:
    """Check AOMS transmission, scope isolation, budgets, and service behavior.

    Transmission is content- and provenance-based rather than tied to seeded record
    IDs. A planner's plan or handoff is itself an honest AOMS memory when its packed
    content carries the declared constraint phrases, its canonical provenance is
    valid, and its ID exactly corresponds to a receipt selection.
    """

    root = Path(run_dir)
    scenario = load_scenario(scenario_path)
    checks: list[str] = []
    failures: list[str] = []
    canary_ids = {item["memory_id"] for item in scenario["canaries"]}
    canary_facts = {item["text"] for item in scenario["canaries"]}

    stage_content: dict[str, str] = {}
    for stage_name, artifact_key in (
        ("stage-2", "stage_2_recall"),
        ("stage-3", "stage_3_recall"),
    ):
        path = root / scenario["artifacts"][artifact_key]
        if not path.is_file():
            failures.append(
                f"{stage_name} recall artifact missing: {path.relative_to(root)}"
            )
            continue
        try:
            receipt, context, raw_text = _load_recall_artifact(path)
        except (OSError, ValueError, KeyError) as exc:
            failures.append(
                f"{stage_name} recall artifact invalid "
                f"({path.relative_to(root)}): {exc}"
            )
            continue
        selected_ids = {item.memory_id for item in receipt.selected}
        try:
            packed = _packed_memories(context)
            packed_ids = [item.memory_id for item in packed]
            receipt_ids = [item.memory_id for item in receipt.selected]
            if len(packed_ids) != len(set(packed_ids)):
                raise ValueError("packed context repeats a memory id")
            if len(receipt_ids) != len(set(receipt_ids)):
                raise ValueError("receipt repeats a selected memory id")
            if set(packed_ids) != set(receipt_ids):
                raise ValueError(
                    "packed source ids do not exactly match receipt selections"
                )
        except (KeyError, TypeError, ValueError) as exc:
            failures.append(
                f"{stage_name} packed AOMS context/provenance is invalid: {exc}"
            )
        else:
            stage_content[stage_name] = "\n".join(item.content for item in packed)
            checks.append(f"{stage_name} packed sources have valid AOMS provenance")
            missing_constraints: list[str] = []
            for constraint in scenario["constraints"]:
                missing_groups = _missing_phrase_groups(
                    stage_content[stage_name], constraint.get("key_phrases")
                )
                if missing_groups:
                    missing_constraints.append(
                        f"{constraint['memory_id']} [{'; '.join(missing_groups)}]"
                    )
            if missing_constraints:
                failures.append(
                    f"{stage_name} packed AOMS context is missing constraint content: "
                    + ", ".join(missing_constraints)
                )
            else:
                checks.append(
                    f"{stage_name} transmitted all injected constraints via AOMS"
                )

        leaked_ids = sorted(canary_ids & selected_ids)
        leaked_facts = sorted(
            fact for fact in canary_facts if fact in context or fact in raw_text
        )
        serialized_canary_ids = sorted(item for item in canary_ids if item in raw_text)
        if leaked_ids or leaked_facts or serialized_canary_ids:
            failures.append(f"{stage_name} contains out-of-scope canary evidence")
        else:
            checks.append(f"{stage_name} excludes all scope canaries")

        stage_key = "implementer" if stage_name == "stage-2" else "reviewer"
        ceiling = int(scenario["stages"][stage_key]["token_ceiling"])
        token_sum = sum(item.token_cost for item in receipt.selected)
        if receipt.total_tokens > ceiling or receipt.token_budget > ceiling:
            failures.append(f"{stage_name} exceeded declared {ceiling}-token ceiling")
        elif token_sum != receipt.total_tokens:
            failures.append(
                f"{stage_name} token costs sum to {token_sum}, receipt says {receipt.total_tokens}"
            )
        else:
            checks.append(
                f"{stage_name} tokens reconcile at {receipt.total_tokens}/{ceiling}"
            )

    if "stage-3" in stage_content:
        clue = scenario["regression_clue"]
        missing_groups = _missing_phrase_groups(
            stage_content["stage-3"], clue.get("key_phrases")
        )
        if missing_groups:
            failures.append(
                "stage-3 packed AOMS context is missing the reviewer regression "
                f"clue content: {'; '.join(missing_groups)}"
            )
        else:
            checks.append("stage-3 transmitted the private regression clue via AOMS")

    workspace = root / scenario["artifacts"]["completed_repository"]
    try:
        passed_acceptance = run_acceptance(workspace)
    except (AssertionError, OSError, ImportError, AttributeError, TypeError) as exc:
        detail = str(exc) or exc.__class__.__name__
        failures.append(f"acceptance tests failed: {detail}")
    else:
        checks.extend(f"acceptance: {name}" for name in passed_acceptance)

    return VerificationReport(
        scenario_id=scenario["id"],
        passed=not failures,
        grade=_evidence_grade(root),
        checks=tuple(checks),
        failures=tuple(failures),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    report = verify_run(args.run_dir)
    print(json.dumps(report.model_dump(), indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["VerificationReport", "verify_run"]
