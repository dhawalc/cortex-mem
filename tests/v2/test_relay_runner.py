from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from demo.relay.adapters import (
    AdapterRequest,
    AdapterUnavailable,
    ClaudeAdapter,
    CodexAdapter,
    OpenClawAdapter,
    launch_fresh_process,
)
from demo.relay.artifacts import validate_bundle
from demo.relay.runner import run_relay


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
        bundle / "receipts-export" / "receipts.jsonl"
    ).read_text().splitlines()
    assert len(receipt_lines) >= 3
    assert (bundle / "stage-2" / "recall.json").is_file()
    assert (bundle / "stage-3" / "recall.json").is_file()
    assert (bundle / "verifier" / "report.json").is_file()


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


def test_bundle_manifest_detects_tampering(
    scripted_bundle, tmp_path: Path
) -> None:
    tampered = tmp_path / "tampered"
    shutil.copytree(scripted_bundle.bundle, tampered)
    service = tampered / "workspace" / "relay_service" / "service.py"
    service.write_text(service.read_text() + "\n# modified after sealing\n")

    validation = validate_bundle(tampered)

    assert not validation.valid
    assert any("hash mismatch for workspace/relay_service/service.py" in failure for failure in validation.failures)


def test_real_adapter_commands_match_discovered_headless_flags(tmp_path: Path) -> None:
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
    request = AdapterRequest(
        stage="implementer",
        prompt="minimal prompt\n",
        prompt_path=tmp_path / "prompt.txt",
        workdir=tmp_path,
        stdout_path=tmp_path / "stdout",
        stderr_path=tmp_path / "stderr",
        result_path=tmp_path / "result",
        mcp_config_path=config,
    )
    claude = ClaudeAdapter().build_command(request, "fresh-id")
    assert claude[:3] == ["claude", "-p", "minimal prompt\n"]
    assert "--bare" in claude
    assert "--strict-mcp-config" in claude
    assert "--no-session-persistence" in claude
    assert claude[claude.index("--session-id") + 1] == "fresh-id"

    codex = CodexAdapter().build_command(request, "unused")
    assert codex[:3] == ["codex", "exec", "--json"]
    assert "--ephemeral" in codex
    assert "--ignore-user-config" in codex
    assert "--ignore-rules" in codex
    assert any("mcp_servers.aoms.command=" in item for item in codex)

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

    openclaw_config = json.loads(
        (tmp_path / "openclaw-config.json").read_text()
    )
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
    assert process.adapter_evidence["fresh_context"][
        "guaranteed_by_adapter"
    ] is True
    assert process.adapter_evidence["mcp"]["per_run_injected"] is True

    with pytest.raises(AdapterUnavailable, match="private state path already exists"):
        adapter.build_command(request, "another-id")
