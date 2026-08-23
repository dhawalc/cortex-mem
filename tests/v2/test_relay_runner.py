from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from demo.relay.adapters import (
    AdapterRequest,
    AdapterUnavailable,
    ClaudeAdapter,
    CodexAdapter,
    OpenClawAdapter,
    launch_fresh_process,
)
from demo.relay.artifacts import validate_bundle
from demo.relay import runner as relay_runner
from demo.relay.runner import run_relay
from demo.relay_fixture.verify import verify_run


@pytest.fixture(scope="module")
def scripted_bundle(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("relay-runner")
    return asyncio.run(
        run_relay(
            root / "bundle",
            agent_names=("scripted", "scripted", "scripted"),
            seed=7319,
            with_baseline=True,
        )
    )


def test_scripted_relay_end_to_end_and_manifest(scripted_bundle) -> None:
    bundle = scripted_bundle.bundle
    assert scripted_bundle.verification.passed
    assert scripted_bundle.verification.grade == "PROOF"
    validation = validate_bundle(bundle)
    assert validation.valid, validation.failures
    assert validation.checked_files > 30

    prompt_hashes: list[str] = []
    process_ids: list[int] = []
    for number, stage in enumerate(("planner", "implementer", "reviewer"), 1):
        stage_root = bundle / "stages" / f"stage-{number}-{stage}"
        prompt = stage_root / "initial-prompt.txt"
        prompt_record = json.loads((stage_root / "prompt.json").read_text())
        expected_hash = hashlib.sha256(prompt.read_bytes()).hexdigest()
        assert prompt_record["sha256"] == expected_hash
        prompt_hashes.append(expected_hash)

        record = json.loads((stage_root / "record.json").read_text())
        assert record["process"]["returncode"] == 0
        assert record["process"]["fresh_session_id"]
        assert record["git"]["commits"]
        assert (stage_root / "changes.patch").read_text()
        process_ids.append(record["process"]["pid"])

        traffic = [
            json.loads(line)
            for line in (stage_root / "mcp-traffic.jsonl").read_text().splitlines()
        ]
        assert {item["direction"] for item in traffic} == {
            "client_to_server",
            "server_to_client",
        }
        assert any(
            item["message"].get("method") == "tools/call"
            for item in traffic
            if isinstance(item["message"], dict)
        )

    assert len(set(process_ids)) == 3
    assert len(set(prompt_hashes)) == 3
    receipt_lines = (
        (bundle / "receipts-export" / "receipts.jsonl").read_text().splitlines()
    )
    assert len(receipt_lines) >= 3
    assert (bundle / "stage-2" / "recall.json").is_file()
    assert (bundle / "stage-3" / "recall.json").is_file()
    assert (bundle / "verifier" / "report.json").is_file()
    verifier_record = json.loads((bundle / "verifier" / "report.json").read_text())
    assert verifier_record["grade"] == "PROOF"


def test_scripted_relay_pins_model_requested_recall_budget(tmp_path: Path) -> None:
    script = yaml.safe_load(relay_runner.DEFAULT_SCRIPT.read_text(encoding="utf-8"))
    implementer_calls = script["stages"]["implementer"]["calls"]
    recall = next(call for call in implementer_calls if call.get("name") == "recall")
    recall["arguments"]["token_budget"] = 5000
    script_path = tmp_path / "over-budget-scripted.yaml"
    script_path.write_text(yaml.safe_dump(script, sort_keys=False), encoding="utf-8")

    result = asyncio.run(
        run_relay(
            tmp_path / "pinned-budget-bundle",
            agent_names=("scripted", "scripted", "scripted"),
            seed=7319,
            script_path=script_path,
        )
    )

    assert result.verification.passed, result.verification.failures
    artifact = json.loads((result.bundle / "stage-2" / "recall.json").read_text())
    assert artifact["receipt"]["token_budget"] == 1000
    assert artifact["receipt"]["total_tokens"] <= 1000
    traffic = [
        json.loads(line)
        for line in (
            result.bundle / "stages" / "stage-2-implementer" / "mcp-traffic.jsonl"
        )
        .read_text()
        .splitlines()
    ]
    pinned_call = next(item for item in traffic if "enforcement" in item)
    assert pinned_call["message"]["params"]["arguments"]["token_budget"] == 1000
    assert pinned_call["enforcement"]["recall_token_budget"] == {
        "requested": 5000,
        "pinned": 1000,
    }


def test_scripted_relay_fails_stage_without_required_recall(tmp_path: Path) -> None:
    script = yaml.safe_load(relay_runner.DEFAULT_SCRIPT.read_text(encoding="utf-8"))
    reviewer_calls = script["stages"]["reviewer"]["calls"]
    script["stages"]["reviewer"]["calls"] = [
        call for call in reviewer_calls if call.get("name") != "recall"
    ]
    script_path = tmp_path / "missing-recall-scripted.yaml"
    script_path.write_text(yaml.safe_dump(script, sort_keys=False), encoding="utf-8")
    output = tmp_path / "missing-recall-bundle"
    failed_output = Path(f"{output.resolve()}-FAILED")

    with pytest.raises(
        RuntimeError, match="completed without the required AOMS recall"
    ):
        asyncio.run(
            run_relay(
                output,
                agent_names=("scripted", "scripted", "scripted"),
                seed=7319,
                script_path=script_path,
            )
        )

    validation = validate_bundle(failed_output)
    assert validation.valid, validation.failures
    failure = json.loads((failed_output / "failure.json").read_text())
    assert failure["stage"] == "reviewer"
    assert not (failed_output / "stage-3" / "recall.json").exists()


def test_memory_disabled_baseline_is_comparable(scripted_bundle) -> None:
    bundle = scripted_bundle.bundle
    assert scripted_bundle.baseline_verification is not None
    assert not scripted_bundle.baseline_verification.passed
    comparison = json.loads((bundle / "comparison.json").read_text())
    assert comparison["only_variable"] == "MCP memory availability"
    assert comparison["prompts_identical"] is True
    assert comparison["memory_enabled"]["verifier"]["passed"] is True
    assert comparison["memory_disabled"]["verifier"]["passed"] is False
    assert comparison["passed_delta"] == 1

    for number, stage in enumerate(("planner", "implementer", "reviewer"), 1):
        primary = bundle / "stages" / f"stage-{number}-{stage}"
        baseline = bundle / "baseline" / "stages" / f"stage-{number}-{stage}"
        assert not (baseline / "mcp-config.json").exists()
        assert (baseline / "mcp-traffic.jsonl").read_text() == ""
        assert (primary / "initial-prompt.txt").read_bytes() == (
            baseline / "initial-prompt.txt"
        ).read_bytes()


def test_bundle_manifest_detects_tampering(scripted_bundle, tmp_path: Path) -> None:
    tampered = tmp_path / "tampered"
    shutil.copytree(scripted_bundle.bundle, tampered)
    service = tampered / "workspace" / "relay_service" / "service.py"
    service.write_text(service.read_text() + "\n# modified after sealing\n")

    validation = validate_bundle(tampered)

    assert not validation.valid
    assert any(
        "hash mismatch for workspace/relay_service/service.py" in failure
        for failure in validation.failures
    )


def _real_adapter_request(tmp_path: Path) -> AdapterRequest:
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "aoms": {
                        "command": "/python",
                        "args": ["-m", "proxy"],
                        "env": {"AOMS_DATA_DIR": "/fixture"},
                    }
                }
            }
        )
    )
    return AdapterRequest(
        stage="implementer",
        prompt="minimal prompt\n",
        prompt_path=tmp_path / "prompt.txt",
        workdir=tmp_path,
        stdout_path=tmp_path / "stdout",
        stderr_path=tmp_path / "stderr",
        result_path=tmp_path / "result",
        mcp_config_path=config,
    )


def test_real_adapter_commands_match_discovered_headless_flags(tmp_path: Path) -> None:
    request = _real_adapter_request(tmp_path)
    claude = ClaudeAdapter().build_command(request, "fresh-id")
    assert claude[:3] == ["claude", "-p", "minimal prompt\n"]
    assert "--bare" in claude
    assert "--strict-mcp-config" in claude
    assert "--no-session-persistence" in claude
    assert claude[claude.index("--allowedTools") + 1] == (
        "mcp__aoms__recall,mcp__aoms__search,mcp__aoms__remember"
    )
    assert claude[claude.index("--session-id") + 1] == "fresh-id"

    codex = CodexAdapter().build_command(request, "unused")
    assert codex == [
        "codex",
        "-a",
        "never",
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "-C",
        str(tmp_path),
        "-s",
        "workspace-write",
        "-c",
        'mcp_servers.aoms.command="/python"',
        "-c",
        'mcp_servers.aoms.args=["-m","proxy"]',
        "-c",
        'mcp_servers.aoms.env={AOMS_DATA_DIR="/fixture"}',
        "minimal prompt\n",
    ]

    openclaw_adapter = OpenClawAdapter()
    openclaw = openclaw_adapter.build_command(request, "fresh-id")
    assert openclaw[:6] == [
        "openclaw",
        "agent",
        "--local",
        "--agent",
        "main",
        "--session-id",
    ]
    assert openclaw[6] == "fresh-id"
    assert openclaw[-3:] == ["--message", "minimal prompt\n", "--json"]
    assert "--deliver" not in openclaw

    openclaw_config = json.loads((tmp_path / "openclaw-config.json").read_text())
    assert openclaw_config["agents"]["defaults"]["workspace"] == str(tmp_path)
    assert openclaw_config["agents"]["defaults"]["skipBootstrap"] is True
    assert openclaw_config["mcp"]["servers"]["aoms"] == {
        "command": "/python",
        "args": ["-m", "proxy"],
        "env": {"AOMS_DATA_DIR": "/fixture"},
    }
    assert openclaw_adapter.environment(request) == {
        "OPENCLAW_CONFIG_PATH": str(tmp_path / "openclaw-config.json"),
        "OPENCLAW_STATE_DIR": str(tmp_path / "openclaw-state"),
    }


def test_codex_adapter_argv_parses_with_installed_cli(tmp_path: Path) -> None:
    executable = shutil.which("codex")
    if executable is None:
        pytest.skip("codex CLI is not installed")
    command = CodexAdapter().build_command(_real_adapter_request(tmp_path), "unused")
    command[0] = executable
    # Codex has no validate-only command; help parses every option without a run.
    command[-1] = "--help"

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Usage: codex exec [OPTIONS]" in completed.stdout


@pytest.mark.parametrize(
    ("mode", "expects_bare", "expected_grade"),
    (("bare", True, "PROOF"), ("oauth", False, "REHEARSAL")),
)
def test_claude_auth_mode_controls_argv_and_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expects_bare: bool,
    expected_grade: str,
) -> None:
    monkeypatch.setenv("AOMS_RELAY_CLAUDE_AUTH", mode)
    request = AdapterRequest(
        stage="planner",
        prompt="prompt\n",
        prompt_path=tmp_path / "prompt.txt",
        workdir=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        result_path=tmp_path / "result.json",
        mcp_config_path=None,
    )
    adapter = ClaudeAdapter()

    command = adapter.build_command(request, "fresh-id")
    evidence = adapter.evidence(request, "fresh-id")

    assert ("--bare" in command) is expects_bare
    assert evidence["auth"]["mode"] == mode
    assert evidence["evidence_grade"] == expected_grade
    if mode == "oauth":
        assert evidence["auth"]["user_level_config_excluded"] is False
        assert "did NOT exclude user-level config" in evidence["auth"]["note"]


def test_verifier_marks_oauth_claude_bundle_as_rehearsal(
    scripted_bundle, tmp_path: Path
) -> None:
    rehearsal = tmp_path / "oauth-rehearsal"
    shutil.copytree(scripted_bundle.bundle, rehearsal)
    record_path = rehearsal / "stages" / "stage-1-planner" / "record.json"
    record = json.loads(record_path.read_text())
    record["adapter"] = "claude"
    record["process"]["adapter"] = "claude"
    record["process"]["adapter_evidence"] = {
        "auth": {
            "mode": "oauth",
            "user_level_config_excluded": False,
            "note": "OAuth mode did NOT exclude user-level config.",
        },
        "evidence_grade": "REHEARSAL",
    }
    record_path.write_text(json.dumps(record), encoding="utf-8")

    report = verify_run(rehearsal, scenario_path=rehearsal / "scenario.yaml")

    assert report.passed
    assert report.grade == "REHEARSAL"


def test_failed_stage_publishes_sealed_bundle_and_surfaces_stdout_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class StubFailingAdapter:
        name = "stub-failure"

        def build_command(self, request: AdapterRequest, session_id: str) -> list[str]:
            del request, session_id
            return [
                sys.executable,
                "-c",
                (
                    "import json, sys; "
                    "print(json.dumps({'type': 'result', 'is_error': True, "
                    "'api_error_status': 400, "
                    "'result': 'Credit balance is too low'})); "
                    "print('stub stderr', file=sys.stderr); sys.exit(1)"
                ),
            ]

        def version(self) -> str:
            return "stub-failure/1"

    monkeypatch.setitem(
        relay_runner.ADAPTERS, StubFailingAdapter.name, StubFailingAdapter()
    )
    output = tmp_path / "failed-relay"
    failed_output = Path(f"{output.resolve()}-FAILED")

    with pytest.raises(RuntimeError) as caught:
        asyncio.run(
            run_relay(
                output,
                agent_names=("scripted", "stub-failure", "scripted"),
                seed=7319,
            )
        )

    message = str(caught.value)
    assert "api_error_status=400" in message
    assert "Credit balance is too low" in message
    assert str(failed_output) in message
    assert not output.exists()
    assert failed_output.is_dir()

    validation = validate_bundle(failed_output)
    assert validation.valid, validation.failures
    failure = json.loads((failed_output / "failure.json").read_text())
    assert failure["status"] == "failed"
    assert failure["variant"] == "memory-enabled"
    assert failure["stage"] == "implementer"
    assert failure["adapter"] == "stub-failure"
    assert failure["returncode"] == 1
    stage_root = failed_output / "stages" / "stage-2-implementer"
    assert (
        json.loads((stage_root / "record.json").read_text())["process"]["returncode"]
        == 1
    )
    assert "Credit balance is too low" in (stage_root / "stdout.log").read_text()
    assert (stage_root / "stderr.log").read_text() == "stub stderr\n"
    assert (failed_output / "stages" / "stage-1-planner" / "record.json").is_file()
    assert not (failed_output / "stages" / "stage-3-reviewer").exists()
    manifest = json.loads((failed_output / "manifest.json").read_text())
    assert manifest["metadata"]["status"] == "failed"
    assert manifest["metadata"]["failure"]["stage"] == "implementer"


def test_openclaw_adapter_launches_stub_with_private_state_and_captures_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "openclaw"
    stub.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys

config_path = os.environ["OPENCLAW_CONFIG_PATH"]
state_path = os.environ["OPENCLAW_STATE_DIR"]
os.makedirs(state_path)
with open(config_path, encoding="utf-8") as handle:
    config = json.load(handle)
print(json.dumps({
    "argv": sys.argv[1:],
    "config": config,
    "cwd": os.getcwd(),
    "state_path": state_path,
}))
print("stub diagnostic", file=sys.stderr)
""",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", os.pathsep.join((str(bin_dir), os.environ["PATH"])))

    mcp_config = tmp_path / "mcp.json"
    mcp_config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "aoms": {
                        "type": "stdio",
                        "command": "/python",
                        "args": ["proxy.py"],
                        "env": {"AOMS_DATA_DIR": "/fixture"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("stub prompt\n", encoding="utf-8")
    request = AdapterRequest(
        stage="planner",
        prompt="stub prompt\n",
        prompt_path=prompt_path,
        workdir=workdir,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        result_path=tmp_path / "adapter-result.json",
        mcp_config_path=mcp_config,
    )
    adapter = OpenClawAdapter()

    process = asyncio.run(
        launch_fresh_process(
            adapter,
            request,
            project_root=Path(__file__).resolve().parents[2],
        )
    )

    assert process.returncode == 0
    output = json.loads(request.stdout_path.read_text())
    assert output == json.loads(request.result_path.read_text())
    assert output["cwd"] == str(workdir)
    assert output["argv"][:5] == [
        "agent",
        "--local",
        "--agent",
        "main",
        "--session-id",
    ]
    assert output["argv"][5] == process.fresh_session_id
    assert output["argv"][-3:] == ["--message", "stub prompt\n", "--json"]
    assert output["config"]["mcp"]["servers"]["aoms"]["command"] == "/python"
    assert output["state_path"] == str(tmp_path / "openclaw-state")
    assert request.stderr_path.read_text() == "stub diagnostic\n"
    assert process.adapter_evidence["fresh_context"]["guaranteed_by_adapter"] is True
    assert process.adapter_evidence["mcp"]["per_run_injected"] is True

    with pytest.raises(AdapterUnavailable, match="private state path already exists"):
        adapter.build_command(request, "another-id")
