"""Verify completed cold-start relay artifacts without driving agent CLIs."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

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


def _load_recall_artifact(path: Path) -> tuple[RecallReceipt, str, str]:
    raw_text = path.read_text(encoding="utf-8")
    payload = json.loads(raw_text)
    receipt_payload = payload.get("receipt", payload)
    receipt = RecallReceipt.model_validate(receipt_payload)
    return receipt, str(payload.get("context", "")), raw_text


def _evidence_grade(root: Path) -> str:
    """OAuth-backed Claude runs are useful rehearsals, not isolation proofs."""

    for record_path in sorted((root / "stages").glob("stage-*/record.json")):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        process = record.get("process", {})
        evidence = process.get("adapter_evidence", {})
        auth = evidence.get("auth", {}) if isinstance(evidence, dict) else {}
        if isinstance(auth, dict) and auth.get("mode") == "oauth":
            return "REHEARSAL"
    return "PROOF"


def verify_run(
    run_dir: str | Path, *, scenario_path: Path = SCENARIO_PATH
) -> VerificationReport:
    """Check receipt evidence, scope isolation, budgets, and service behavior."""

    root = Path(run_dir)
    scenario = load_scenario(scenario_path)
    checks: list[str] = []
    failures: list[str] = []
    constraint_ids = {item["memory_id"] for item in scenario["constraints"]}
    canary_ids = {item["memory_id"] for item in scenario["canaries"]}
    canary_facts = {item["text"] for item in scenario["canaries"]}

    stage_receipts: dict[str, RecallReceipt] = {}
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
        stage_receipts[stage_name] = receipt
        selected_ids = {item.memory_id for item in receipt.selected}
        missing = sorted(constraint_ids - selected_ids)
        if missing:
            failures.append(
                f"{stage_name} receipt is missing constraints: {', '.join(missing)}"
            )
        else:
            checks.append(f"{stage_name} selected all injected constraints")

        leaked_ids = sorted(canary_ids & selected_ids)
        leaked_facts = sorted(fact for fact in canary_facts if fact in context or fact in raw_text)
        serialized_canary_ids = sorted(item for item in canary_ids if item in raw_text)
        if leaked_ids or leaked_facts or serialized_canary_ids:
            failures.append(f"{stage_name} contains out-of-scope canary evidence")
        else:
            checks.append(f"{stage_name} excludes all scope canaries")

        stage_key = "implementer" if stage_name == "stage-2" else "reviewer"
        ceiling = int(scenario["stages"][stage_key]["token_ceiling"])
        token_sum = sum(item.token_cost for item in receipt.selected)
        if receipt.total_tokens > ceiling or receipt.token_budget > ceiling:
            failures.append(
                f"{stage_name} exceeded declared {ceiling}-token ceiling"
            )
        elif token_sum != receipt.total_tokens:
            failures.append(
                f"{stage_name} token costs sum to {token_sum}, receipt says {receipt.total_tokens}"
            )
        else:
            checks.append(
                f"{stage_name} tokens reconcile at {receipt.total_tokens}/{ceiling}"
            )

    if "stage-3" in stage_receipts:
        clue_id = scenario["regression_clue"]["memory_id"]
        selected = {item.memory_id for item in stage_receipts["stage-3"].selected}
        if clue_id not in selected:
            failures.append("stage-3 receipt is missing the reviewer regression clue")
        else:
            checks.append("stage-3 selected the private regression clue")

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
