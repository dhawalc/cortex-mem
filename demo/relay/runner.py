"""Run the cold-start AOMS relay and emit a hash-sealed proof bundle."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, NoReturn, Sequence

from aoms.contracts import ScopeContext
from aoms.portable import export_bundle
from aoms.repositories import SQLiteMemoryRepository
from aoms.version import __version__
from demo.relay.adapters import (
    ADAPTERS,
    AdapterRequest,
    AgentAdapter,
    launch_fresh_process,
)
from demo.relay.artifacts import (
    BundleValidation,
    sha256_file,
    sha256_tree,
    validate_bundle,
    write_manifest,
)
from demo.relay_fixture.seed import (
    RELAY_WORKSPACE,
    SCENARIO_PATH,
    load_scenario,
    seed_store,
)
from demo.relay_fixture.verify import VerificationReport, verify_run

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = PROJECT_ROOT / "demo" / "relay_fixture"
DEFAULT_SCRIPT = FIXTURE_ROOT / "scripted.yaml"
STAGE_ORDER = ("planner", "implementer", "reviewer")
STAGE_NUMBERS = {"planner": 1, "implementer": 2, "reviewer": 3}
RUNNER_SCHEMA_VERSION = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _text_tail(path: Path, *, limit: int = 2000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:].strip()
    except OSError:
        return ""


def _stream_json_error(path: Path) -> str | None:
    """Extract the useful error fields Claude emits on stream-json stdout."""

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    candidates: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            candidates.append(payload)
    for payload in reversed(candidates):
        status = payload.get("api_error_status")
        result = payload.get("result")
        if status is None and (result is None or result == ""):
            continue
        details: list[str] = []
        if status is not None:
            details.append(f"api_error_status={status}")
        if result is not None and result != "":
            rendered = result if isinstance(result, str) else json.dumps(result)
            details.append(f"result={rendered}")
        return ", ".join(details)
    return None


def _process_failure_message(request: AdapterRequest) -> str:
    details: list[str] = []
    stdout_error = _stream_json_error(request.stdout_path)
    if stdout_error:
        details.append(f"stdout stream-json: {stdout_error}")
    stderr_tail = _text_tail(request.stderr_path)
    if stderr_tail:
        details.append(f"stderr: {stderr_tail}")
    if not stdout_error:
        stdout_tail = _text_tail(request.stdout_path)
        if stdout_tail:
            details.append(f"stdout: {stdout_tail}")
    return "; ".join(details) or "no process diagnostic output"


def _run_git(workdir: Path, *arguments: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=workdir,
        check=check,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _git_version() -> str:
    return subprocess.run(
        ["git", "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()


def _initialize_fixture_repository(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination)
    _run_git(destination, "init", "-q", "-b", "main")
    _run_git(destination, "config", "user.name", "AOMS Relay")
    _run_git(destination, "config", "user.email", "relay-fixture@example.invalid")
    # Detached maintenance can race the next stage's copy of this disposable
    # repository (notably via .git/objects/maintenance.lock on Git 2.53).
    _run_git(destination, "config", "maintenance.auto", "false")
    _run_git(destination, "add", "-A")
    _run_git(destination, "commit", "-q", "-m", "fixture: pristine relay service")


def _copy_completed_workspace(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__", "*.pyc"),
    )


def _mcp_config(
    *,
    target: Path,
    traffic_path: Path,
    data_dir: Path,
    agent_id: str,
    recall_token_budget: int | None,
) -> None:
    server_command = [
        sys.executable,
        "-m",
        "aoms.cli",
        "mcp",
        "--log-level",
        "ERROR",
    ]
    environment = {
        "AOMS_AGENT_ID": agent_id,
        "AOMS_DATA_DIR": str(data_dir),
        "AOMS_EMBEDDING_PROVIDER": "none",
        "AOMS_LOG_LEVEL": "ERROR",
        "AOMS_WORKSPACE": RELAY_WORKSPACE,
        "PATH": os.environ.get("PATH", ""),
    }
    proxy_arguments = [
        str(PROJECT_ROOT / "demo" / "relay" / "mcp_proxy.py"),
        "--traffic",
        str(traffic_path),
        "--server-command-json",
        json.dumps(server_command),
        "--server-cwd",
        str(PROJECT_ROOT),
    ]
    if recall_token_budget is not None:
        proxy_arguments.extend(["--recall-token-budget", str(recall_token_budget)])
    payload = {
        "mcpServers": {
            "aoms": {
                "type": "stdio",
                "command": sys.executable,
                "args": proxy_arguments,
                "env": environment,
            }
        }
    }
    _write_json(target, payload)


def _traffic_recall(path: Path) -> dict[str, Any] | None:
    requests: dict[str, dict[str, Any]] = {}
    latest: dict[str, Any] | None = None
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        message = event.get("message", {})
        message_id = message.get("id") if isinstance(message, dict) else None
        if event.get("direction") == "client_to_server" and isinstance(message, dict):
            if message.get("method") == "tools/call":
                parameters = message.get("params", {})
                if parameters.get("name") == "recall" and message_id is not None:
                    requests[str(message_id)] = parameters
        elif (
            event.get("direction") == "server_to_client"
            and isinstance(message, dict)
            and message_id is not None
            and str(message_id) in requests
        ):
            result = message.get("result", {})
            structured = result.get("structuredContent")
            if isinstance(structured, dict):
                latest = structured
    return latest


async def _write_recall_artifact(
    *,
    run_root: Path,
    scenario: dict[str, Any],
    stage: str,
    traffic_path: Path,
    repository: SQLiteMemoryRepository,
) -> bool:
    if stage not in {"implementer", "reviewer"}:
        return False
    recalled = _traffic_recall(traffic_path)
    if recalled is None:
        return False
    receipt_id = recalled.get("diagnostics", {}).get("receipt_id")
    receipts = await repository.recent_recall_receipts(
        limit=100,
        scope_context=ScopeContext(
            agent_id=scenario["stages"][stage]["agent_id"],
            workspace_id=RELAY_WORKSPACE,
        ),
    )
    receipt = next((item for item in receipts if item.receipt_id == receipt_id), None)
    if receipt is None:
        raise RuntimeError(f"MCP recall receipt was not persisted: {receipt_id}")
    artifact_key = "stage_2_recall" if stage == "implementer" else "stage_3_recall"
    _write_json(
        run_root / scenario["artifacts"][artifact_key],
        {"receipt": receipt.model_dump(mode="json"), "context": recalled["context"]},
    )
    return True


@dataclass(frozen=True, slots=True)
class VariantResult:
    name: str
    memory_enabled: bool
    verifier: VerificationReport
    prompt_hashes: dict[str, str]
    wall_time_seconds: float

    def model_dump(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["verifier"] = self.verifier.model_dump()
        return payload


@dataclass(frozen=True, slots=True)
class RelayResult:
    bundle: Path
    manifest: Path
    verification: VerificationReport
    baseline_verification: VerificationReport | None


class RelayStageFailure(RuntimeError):
    """A stage process could not launch or returned unsuccessfully."""

    def __init__(
        self,
        message: str,
        *,
        variant: str,
        stage: str,
        adapter: str,
        returncode: int | None,
        stdout_path: Path,
        stderr_path: Path,
    ) -> None:
        super().__init__(message)
        self.variant = variant
        self.stage = stage
        self.adapter = adapter
        self.returncode = returncode
        self.stdout_path = stdout_path
        self.stderr_path = stderr_path


async def _run_variant(
    *,
    name: str,
    run_root: Path,
    working_root: Path,
    scenario: dict[str, Any],
    adapters: Sequence[AgentAdapter],
    script_path: Path,
    memory_data_dir: Path | None,
) -> VariantResult:
    started = perf_counter()
    memory_enabled = memory_data_dir is not None
    pristine = working_root / "pristine"
    _initialize_fixture_repository(FIXTURE_ROOT / scenario["repository"], pristine)
    previous = pristine
    prompt_hashes: dict[str, str] = {}
    repository = (
        SQLiteMemoryRepository(memory_data_dir / "aoms.sqlite3")
        if memory_data_dir is not None
        else None
    )

    for stage, adapter in zip(STAGE_ORDER, adapters, strict=True):
        number = STAGE_NUMBERS[stage]
        stage_label = f"stage-{number}-{stage}"
        workdir = working_root / stage_label
        shutil.copytree(previous, workdir)
        before_commit = _run_git(workdir, "rev-parse", "HEAD").strip()
        stage_root = run_root / "stages" / stage_label
        stage_root.mkdir(parents=True)
        prompt = str(scenario["stages"][stage]["prompt"]).rstrip() + "\n"
        prompt_path = stage_root / "initial-prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        prompt_hash = sha256_file(prompt_path)
        prompt_hashes[stage] = prompt_hash
        prompt_record = {
            "bytes": prompt_path.stat().st_size,
            "hashed_at": _utc_now(),
            "path": prompt_path.relative_to(run_root).as_posix(),
            "sha256": prompt_hash,
        }
        _write_json(stage_root / "prompt.json", prompt_record)

        traffic_path = stage_root / "mcp-traffic.jsonl"
        traffic_path.touch()
        mcp_config_path: Path | None = None
        if memory_enabled:
            assert memory_data_dir is not None
            mcp_config_path = stage_root / "mcp-config.json"
            _mcp_config(
                target=mcp_config_path,
                traffic_path=traffic_path,
                data_dir=memory_data_dir,
                agent_id=scenario["stages"][stage]["agent_id"],
                recall_token_budget=scenario["stages"][stage].get("token_ceiling"),
            )
        result_path = stage_root / "adapter-result.json"
        request = AdapterRequest(
            stage=stage,
            prompt=prompt,
            prompt_path=prompt_path,
            workdir=workdir,
            stdout_path=stage_root / "stdout.log",
            stderr_path=stage_root / "stderr.log",
            result_path=result_path,
            mcp_config_path=mcp_config_path,
            script_path=script_path if adapter.name == "scripted" else None,
        )
        try:
            process = await launch_fresh_process(
                adapter, request, project_root=PROJECT_ROOT
            )
        except Exception as exc:
            request.stdout_path.touch(exist_ok=True)
            request.stderr_path.touch(exist_ok=True)
            raise RelayStageFailure(
                f"{name} {stage} {adapter.name} process could not launch: {exc}",
                variant=name,
                stage=stage,
                adapter=adapter.name,
                returncode=None,
                stdout_path=request.stdout_path,
                stderr_path=request.stderr_path,
            ) from exc
        after_commit = _run_git(workdir, "rev-parse", "HEAD").strip()
        diff = _run_git(workdir, "diff", "--binary", before_commit, "--", ".")
        (stage_root / "changes.patch").write_text(diff, encoding="utf-8")
        commits_text = _run_git(
            workdir,
            "log",
            "--reverse",
            "--format=%H%x09%aI%x09%s",
            f"{before_commit}..{after_commit}",
        )
        commits = [
            {
                "commit": line.split("\t", 2)[0],
                "authored_at": line.split("\t", 2)[1],
                "subject": line.split("\t", 2)[2],
            }
            for line in commits_text.splitlines()
            if line
        ]
        record = {
            "schema_version": 1,
            "stage": stage,
            "memory_enabled": memory_enabled,
            "adapter": adapter.name,
            "prompt": prompt_record,
            "process": process.model_dump(),
            "git": {
                "before_commit": before_commit,
                "after_commit": after_commit,
                "commits": commits,
                "status_porcelain": _run_git(
                    workdir, "status", "--porcelain"
                ).splitlines(),
            },
            "mcp_traffic": {
                "capture": (
                    "stdio JSON-RPC proxy with configured recall-budget enforcement"
                ),
                "path": traffic_path.relative_to(run_root).as_posix(),
                "sha256": sha256_file(traffic_path),
            },
        }
        _write_json(stage_root / "record.json", record)
        if process.returncode != 0:
            raise RelayStageFailure(
                f"{name} {stage} {adapter.name} process failed with {process.returncode}; "
                f"{_process_failure_message(request)}",
                variant=name,
                stage=stage,
                adapter=adapter.name,
                returncode=process.returncode,
                stdout_path=request.stdout_path,
                stderr_path=request.stderr_path,
            )
        if repository is not None:
            recall_captured = await _write_recall_artifact(
                run_root=run_root,
                scenario=scenario,
                stage=stage,
                traffic_path=traffic_path,
                repository=repository,
            )
            if stage in {"implementer", "reviewer"} and not recall_captured:
                raise RelayStageFailure(
                    f"{name} {stage} {adapter.name} completed without the required "
                    "AOMS recall; no canonical recall artifact can be produced",
                    variant=name,
                    stage=stage,
                    adapter=adapter.name,
                    returncode=process.returncode,
                    stdout_path=request.stdout_path,
                    stderr_path=request.stderr_path,
                )
        previous = workdir

    _copy_completed_workspace(
        previous, run_root / scenario["artifacts"]["completed_repository"]
    )
    verifier_started = perf_counter()
    verifier = verify_run(run_root, scenario_path=run_root / "scenario.yaml")
    verifier_wall_time = perf_counter() - verifier_started
    _write_json(
        run_root / "verifier" / "report.json",
        {
            **verifier.model_dump(),
            "wall_time_seconds": verifier_wall_time,
        },
    )
    result = VariantResult(
        name=name,
        memory_enabled=memory_enabled,
        verifier=verifier,
        prompt_hashes=prompt_hashes,
        wall_time_seconds=perf_counter() - started,
    )
    _write_json(run_root / "run-record.json", result.model_dump())
    return result


def _copy_protocol_inputs(target: Path, scenario_path: Path, script_path: Path) -> None:
    shutil.copy2(scenario_path, target / "scenario.yaml")
    shutil.copy2(script_path, target / "scripted.yaml")


def _relative_evidence_path(bundle: Path, path: Path) -> str:
    try:
        return path.relative_to(bundle).as_posix()
    except ValueError:
        return str(path)


def _publish_failure_bundle(
    *,
    bundle: Path,
    destination: Path,
    failure: RelayStageFailure,
    scenario: dict[str, Any],
    seed: int,
    with_baseline: bool,
) -> Path:
    failure_record = {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "status": "failed",
        "failed_at": _utc_now(),
        "variant": failure.variant,
        "stage": failure.stage,
        "stage_number": STAGE_NUMBERS[failure.stage],
        "adapter": failure.adapter,
        "returncode": failure.returncode,
        "error": {
            "type": failure.__class__.__name__,
            "message": str(failure),
        },
        "evidence": {
            "stdout": _relative_evidence_path(bundle, failure.stdout_path),
            "stderr": _relative_evidence_path(bundle, failure.stderr_path),
        },
    }
    _write_json(bundle / "failure.json", failure_record)
    source_revision = _run_git(PROJECT_ROOT, "rev-parse", "HEAD").strip()
    fixture_hash = sha256_tree(FIXTURE_ROOT / scenario["repository"])
    manifest = write_manifest(
        bundle,
        metadata={
            "status": "failed",
            "scenario_id": scenario["id"],
            "seed": seed,
            "source_revision": source_revision,
            "fixture_repository_sha256": fixture_hash,
            "with_baseline": with_baseline,
            "failure": {
                "variant": failure.variant,
                "stage": failure.stage,
                "adapter": failure.adapter,
                "returncode": failure.returncode,
            },
        },
    )
    validation = validate_bundle(bundle)
    if not validation.valid:
        raise RuntimeError(
            f"new relay failure bundle failed validation: {validation.failures}"
        )
    os.replace(bundle, destination)
    return manifest


def _raise_published_failure(
    *,
    bundle: Path,
    destination: Path,
    failure: RelayStageFailure,
    scenario: dict[str, Any],
    seed: int,
    with_baseline: bool,
) -> NoReturn:
    _publish_failure_bundle(
        bundle=bundle,
        destination=destination,
        failure=failure,
        scenario=scenario,
        seed=seed,
        with_baseline=with_baseline,
    )
    raise RuntimeError(f"{failure}; failure bundle: {destination}") from failure


async def run_relay(
    output: str | Path,
    *,
    agent_names: Sequence[str] = ("scripted", "scripted", "scripted"),
    seed: int | None = None,
    with_baseline: bool = False,
    scenario_path: Path = SCENARIO_PATH,
    script_path: Path = DEFAULT_SCRIPT,
) -> RelayResult:
    """Run all stages and atomically publish a manifest-sealed output directory."""

    destination = Path(output).expanduser().resolve()
    failure_destination = Path(f"{destination}-FAILED")
    if destination.exists():
        raise FileExistsError(
            f"relay output already exists (write-once): {destination}"
        )
    if failure_destination.exists():
        raise FileExistsError(
            f"relay failure output already exists (write-once): {failure_destination}"
        )
    if len(agent_names) != len(STAGE_ORDER):
        raise ValueError(
            "exactly three adapters are required: planner, implementer, reviewer"
        )
    unknown = [name for name in agent_names if name not in ADAPTERS]
    if unknown:
        raise ValueError(f"unknown relay adapter(s): {', '.join(unknown)}")
    adapters = tuple(ADAPTERS[name] for name in agent_names)
    scenario = load_scenario(scenario_path)
    selected_seed = int(scenario["seed"] if seed is None else seed)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix=f".{destination.name}.building-", dir=destination.parent
    ) as temporary:
        build_root = Path(temporary)
        bundle = build_root / "bundle"
        bundle.mkdir()
        _copy_protocol_inputs(bundle, scenario_path, script_path)
        _write_json(
            bundle / "seed.json",
            {
                "scenario_seed": int(scenario["seed"]),
                "run_seed": selected_seed,
                "seed_source": "--seed" if seed is not None else "scenario.yaml",
            },
        )
        memory_data_dir = build_root / "shared-aoms-store"
        memory_data_dir.mkdir()
        seeded = await seed_store(
            memory_data_dir / "aoms.sqlite3", scenario_path=bundle / "scenario.yaml"
        )
        _write_json(
            bundle / "seed-result.json",
            {"memory_ids": list(seeded.memory_ids), "count": len(seeded.memory_ids)},
        )
        try:
            primary = await _run_variant(
                name="memory-enabled",
                run_root=bundle,
                working_root=build_root / "memory-enabled-workdirs",
                scenario=scenario,
                adapters=adapters,
                script_path=bundle / "scripted.yaml",
                memory_data_dir=memory_data_dir,
            )
        except RelayStageFailure as exc:
            _raise_published_failure(
                bundle=bundle,
                destination=failure_destination,
                failure=exc,
                scenario=scenario,
                seed=selected_seed,
                with_baseline=with_baseline,
            )
        await export_bundle(
            SQLiteMemoryRepository(memory_data_dir / "aoms.sqlite3"),
            bundle / "receipts-export",
        )

        baseline: VariantResult | None = None
        if with_baseline:
            baseline_root = bundle / "baseline"
            baseline_root.mkdir()
            _copy_protocol_inputs(baseline_root, scenario_path, script_path)
            try:
                baseline = await _run_variant(
                    name="memory-disabled-baseline",
                    run_root=baseline_root,
                    working_root=build_root / "baseline-workdirs",
                    scenario=scenario,
                    adapters=adapters,
                    script_path=baseline_root / "scripted.yaml",
                    memory_data_dir=None,
                )
            except RelayStageFailure as exc:
                _raise_published_failure(
                    bundle=bundle,
                    destination=failure_destination,
                    failure=exc,
                    scenario=scenario,
                    seed=selected_seed,
                    with_baseline=with_baseline,
                )
            _write_json(
                bundle / "comparison.json",
                {
                    "schema_version": 1,
                    "only_variable": "MCP memory availability",
                    "prompts_identical": primary.prompt_hashes
                    == baseline.prompt_hashes,
                    "memory_enabled": primary.model_dump(),
                    "memory_disabled": baseline.model_dump(),
                    "passed_delta": int(primary.verifier.passed)
                    - int(baseline.verifier.passed),
                    "check_count_delta": len(primary.verifier.checks)
                    - len(baseline.verifier.checks),
                },
            )

        versions = {
            "aoms": __version__,
            "python": platform.python_version(),
            "python_executable": sys.executable,
            "git": _git_version(),
            "runner_schema": RUNNER_SCHEMA_VERSION,
            "adapters": {
                name: ADAPTERS[name].version() for name in sorted(set(agent_names))
            },
        }
        source_revision = _run_git(PROJECT_ROOT, "rev-parse", "HEAD").strip()
        fixture_hash = sha256_tree(FIXTURE_ROOT / scenario["repository"])
        _write_json(
            bundle / "bundle-record.json",
            {
                "schema_version": RUNNER_SCHEMA_VERSION,
                "created_at": _utc_now(),
                "scenario_id": scenario["id"],
                "seed": selected_seed,
                "source_revision": source_revision,
                "fixture_repository_sha256": fixture_hash,
                "agents": dict(zip(STAGE_ORDER, agent_names, strict=True)),
                "versions": versions,
                "primary": primary.model_dump(),
                "baseline": baseline.model_dump() if baseline else None,
            },
        )
        manifest = write_manifest(
            bundle,
            metadata={
                "scenario_id": scenario["id"],
                "seed": selected_seed,
                "source_revision": source_revision,
                "fixture_repository_sha256": fixture_hash,
                "with_baseline": with_baseline,
            },
        )
        validation = validate_bundle(bundle)
        if not validation.valid:
            raise RuntimeError(
                f"new relay bundle failed validation: {validation.failures}"
            )
        os.replace(bundle, destination)

    return RelayResult(
        bundle=destination,
        manifest=destination / manifest.name,
        verification=primary.verifier,
        baseline_verification=baseline.verifier if baseline else None,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="run and seal a relay bundle")
    run_parser.add_argument("--output", required=True, type=Path)
    run_parser.add_argument(
        "--agents",
        default="scripted,scripted,scripted",
        help="comma-separated planner,implementer,reviewer adapters",
    )
    run_parser.add_argument("--seed", type=int)
    run_parser.add_argument("--with-baseline", action="store_true")
    run_parser.add_argument("--scenario", type=Path, default=SCENARIO_PATH)
    run_parser.add_argument("--script", type=Path, default=DEFAULT_SCRIPT)
    validate_parser = subparsers.add_parser("validate", help="verify bundle hashes")
    validate_parser.add_argument("bundle", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "validate":
        validation: BundleValidation = validate_bundle(args.bundle)
        print(json.dumps(validation.model_dump(), indent=2, sort_keys=True))
        return 0 if validation.valid else 1
    names = tuple(item.strip() for item in args.agents.split(",") if item.strip())
    result = asyncio.run(
        run_relay(
            args.output,
            agent_names=names,
            seed=args.seed,
            with_baseline=args.with_baseline,
            scenario_path=args.scenario,
            script_path=args.script,
        )
    )
    print(
        json.dumps(
            {
                "bundle": str(result.bundle),
                "manifest": str(result.manifest),
                "verified": result.verification.passed,
                "baseline_verified": (
                    result.baseline_verification.passed
                    if result.baseline_verification is not None
                    else None
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["RelayResult", "run_relay", "validate_bundle"]
