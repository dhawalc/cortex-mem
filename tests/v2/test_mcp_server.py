from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

import aoms.adapters.mcp_server as mcp_adapter
import aoms.application as application_module
from aoms.adapters.mcp_server import create_server
from aoms.application import AOMSApplication
from aoms.contracts import (
    MemoryKind,
    MemoryRecord,
    Provenance,
    RecallRequest,
    RecallResult,
    RememberRequest,
    RememberResult,
    Scope,
    ScopeContext,
    SearchRequest,
    SearchResult,
)
from aoms.embeddings import NullProvider
from aoms.recall import RecallEngine
from aoms.repositories import SQLiteMemoryRepository
from cortex_mem.__version__ import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = Path(__file__).with_name("fixtures") / "mcp_tool_schemas.snapshot.json"
FIXED_TIME = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
FIXED_RECEIPT_ID = UUID("11111111-2222-4333-8444-555555555555")
PARITY_CONTEXT = ScopeContext(
    agent_id="parity-agent",
    workspace_id="parity-workspace",
)

CONTRACTS = {
    "recall": (RecallRequest, RecallResult),
    "remember": (RememberRequest, RememberResult),
    "search": (SearchRequest, SearchResult),
}


def _fastmcp_input_schema(name: str, request_model: type) -> dict:
    """Expected FastMCP wrapper schema, generated only from the contract model."""

    schema = copy.deepcopy(request_model.model_json_schema())
    schema.pop("additionalProperties")
    schema["title"] = f"{name}Arguments"
    return schema


def _tool_text(result) -> str:
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    return result.content[0].text


@pytest.mark.asyncio
async def test_stdio_handshake_contract_snapshot_and_tools_end_to_end(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "first-run-data"
    environment = dict(os.environ)
    environment.update(
        {
            "AOMS_DATA_DIR": str(data_dir),
            "AOMS_EMBEDDING_PROVIDER": "none",
            "AOMS_AGENT_ID": "fixture-agent",
            "AOMS_WORKSPACE": "fixture-workspace",
            "PYTHONPATH": os.pathsep.join(
                filter(
                    None,
                    [str(PROJECT_ROOT), environment.get("PYTHONPATH")],
                )
            ),
        }
    )
    repository = SQLiteMemoryRepository(data_dir / "aoms.sqlite3")
    await repository.store(
        MemoryRecord(
            id="foreign-mcp-canary",
            kind=MemoryKind.FACT,
            content="FOREIGN_MCP_CANARY omega-zanzibar",
            scope=Scope.AGENT_PRIVATE,
            scope_agent_id="foreign-agent",
            created_by_agent_id="foreign-agent",
            provenance=Provenance(source="mcp-scope-fixture"),
            created_at=FIXED_TIME,
            updated_at=FIXED_TIME,
        )
    )
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "aoms.adapters.mcp_server"],
        env=environment,
        cwd=PROJECT_ROOT,
    )

    stderr_path = tmp_path / "mcp.stderr"
    with stderr_path.open("w+") as stderr:
        async with stdio_client(parameters, errlog=stderr) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                listed = await session.list_tools()

                assert initialized.serverInfo.name == "AOMS"
                assert initialized.serverInfo.version == __version__
                assert initialized.instructions == mcp_adapter.SERVER_INSTRUCTIONS
                assert [tool.name for tool in listed.tools] == [
                    "recall",
                    "remember",
                    "search",
                ]

                schema_snapshot = {}
                for tool in listed.tools:
                    request_model, result_model = CONTRACTS[tool.name]
                    assert tool.inputSchema == _fastmcp_input_schema(
                        tool.name, request_model
                    )
                    assert tool.outputSchema == result_model.model_json_schema()
                    assert "agent_id" not in tool.inputSchema["properties"]
                    assert "workspace" not in tool.inputSchema["properties"]
                    schema_payload = {
                        "inputSchema": tool.inputSchema,
                        "outputSchema": tool.outputSchema,
                    }
                    encoded_schema = json.dumps(
                        schema_payload,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                    schema_snapshot[tool.name] = hashlib.sha256(
                        encoded_schema
                    ).hexdigest()
                expected_snapshot = json.loads(SNAPSHOT_PATH.read_text())
                assert schema_snapshot == expected_snapshot

                remembered = await session.call_tool(
                    "remember",
                    {
                        "id": "mcp-fixture-fact",
                        "kind": "fact",
                        "content": "Project Zephyr deploys with the amber switch.",
                        "tags": ["zephyr", "deployment"],
                        "scope": "workspace",
                        "provenance": {
                            "source": "mcp-integration-fixture",
                            "details": {"case": "stdio"},
                        },
                    },
                )
                remembered_model = RememberResult.model_validate(
                    remembered.structuredContent
                )
                assert remembered_model.created is True
                assert remembered_model.record.scope_workspace_id == (
                    "fixture-workspace"
                )
                assert remembered_model.record.created_by_agent_id == "fixture-agent"
                assert "Created memory mcp-fixture-fact" in _tool_text(remembered)

                searched = await session.call_tool(
                    "search", {"query": "Zephyr amber", "limit": 5}
                )
                searched_model = SearchResult.model_validate(
                    searched.structuredContent
                )
                assert searched_model.total == 1
                assert searched_model.items[0].record.id == "mcp-fixture-fact"
                assert "mcp-fixture-fact" in _tool_text(searched)

                recalled = await session.call_tool(
                    "recall",
                    {"task": "How does Project Zephyr deploy?", "token_budget": 400},
                )
                recalled_model = RecallResult.model_validate(
                    recalled.structuredContent
                )
                assert recalled_model.token_count <= 400
                assert [source.memory_id for source in recalled_model.sources] == [
                    "mcp-fixture-fact"
                ]
                assert recalled_model.context in _tool_text(recalled)

                canary_search = await session.call_tool(
                    "search",
                    {
                        "query": "omega zanzibar",
                        "scopes": ["agent-private"],
                    },
                )
                canary_search_model = SearchResult.model_validate(
                    canary_search.structuredContent
                )
                assert canary_search_model.items == []
                assert canary_search_model.diagnostics["scope_filtered_count"] == 1
                assert "FOREIGN_MCP_CANARY" not in json.dumps(
                    canary_search.structuredContent
                )

                canary_recall = await session.call_tool(
                    "recall",
                    {
                        "task": "omega zanzibar",
                        "token_budget": 400,
                        "scopes": ["agent-private"],
                    },
                )
                canary_recall_model = RecallResult.model_validate(
                    canary_recall.structuredContent
                )
                assert canary_recall_model.sources == []
                assert canary_recall_model.diagnostics["scope_filtered_count"] == 1
                assert "FOREIGN_MCP_CANARY" not in json.dumps(
                    canary_recall.structuredContent
                )

    assert (data_dir / "aoms.sqlite3").is_file()
    stderr_output = stderr_path.read_text()
    assert "AOMS MCP ready" in stderr_output
    assert "fixture-agent" in stderr_output
    assert "fixture-workspace" in stderr_output


async def _fixture_application(db_path: Path) -> AOMSApplication:
    repository = SQLiteMemoryRepository(db_path)
    engine = RecallEngine(
        repository,
        embedding_provider=NullProvider(),
        scope_context=PARITY_CONTEXT,
        clock=lambda: FIXED_TIME,
        timer=lambda: 10.0,
    )
    application = AOMSApplication(
        repository,
        scope_context=PARITY_CONTEXT,
        recall_engine=engine,
        embedding_provider=NullProvider(),
        background_embeddings=False,
    )
    await repository.store_many(
        [
            MemoryRecord(
                id="fixture-decision",
                kind=MemoryKind.DECISION,
                content="Zephyr releases require an amber canary before rollout.",
                tags=["zephyr", "release"],
                scope=Scope.WORKSPACE,
                scope_workspace_id=PARITY_CONTEXT.workspace_id,
                created_by_agent_id=PARITY_CONTEXT.agent_id,
                provenance=Provenance(source="parity-fixture"),
                created_at=FIXED_TIME,
                updated_at=FIXED_TIME,
            ),
            MemoryRecord(
                id="fixture-failure",
                kind=MemoryKind.FAILURE,
                content="Skipping the amber canary caused a Zephyr rollback.",
                tags=["zephyr", "failure"],
                scope=Scope.WORKSPACE,
                scope_workspace_id=PARITY_CONTEXT.workspace_id,
                created_by_agent_id=PARITY_CONTEXT.agent_id,
                provenance=Provenance(source="parity-fixture"),
                created_at=FIXED_TIME,
                updated_at=FIXED_TIME,
            ),
        ]
    )
    return application


@pytest.mark.asyncio
async def test_direct_application_and_mcp_tool_results_have_exact_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return FIXED_TIME if tz is not None else FIXED_TIME.replace(tzinfo=None)

    monkeypatch.setattr(application_module, "datetime", FrozenDateTime)
    monkeypatch.setattr("aoms.recall.uuid4", lambda: FIXED_RECEIPT_ID)

    direct = await _fixture_application(tmp_path / "direct.sqlite3")
    transported = await _fixture_application(tmp_path / "mcp.sqlite3")
    server = create_server(
        application=transported,
        environ={
            "AOMS_AGENT_ID": "parity-agent",
            "AOMS_WORKSPACE": "parity-workspace",
        },
    )

    remember_request = RememberRequest(
        id="fixture-procedure",
        kind=MemoryKind.PROCEDURE,
        content="Run the Zephyr amber canary and inspect it before rollout.",
        tags=["zephyr", "release"],
        scope=Scope.WORKSPACE,
        provenance=Provenance(source="parity-input"),
    )
    search_request = SearchRequest(query="Zephyr amber", limit=10, offset=0)
    recall_request = RecallRequest(
        task="Prepare the Zephyr rollout with its canary safeguards",
        token_budget=800,
    )

    async with create_connected_server_and_client_session(server) as session:
        direct_remember = await direct.remember(remember_request)
        mcp_remember = await session.call_tool(
            "remember", remember_request.model_dump(mode="json")
        )
        assert mcp_remember.structuredContent == direct_remember.model_dump(
            mode="json"
        )

        direct_search = await direct.search(search_request)
        mcp_search = await session.call_tool(
            "search", search_request.model_dump(mode="json")
        )
        assert mcp_search.structuredContent == direct_search.model_dump(mode="json")

        direct_recall = await direct.recall(recall_request)
        mcp_recall = await session.call_tool(
            "recall", recall_request.model_dump(mode="json")
        )
        assert mcp_recall.structuredContent == direct_recall.model_dump(mode="json")


def test_transport_flag_selects_streamable_http(monkeypatch) -> None:
    transports = []

    class FakeServer:
        def run(self, *, transport):
            transports.append(transport)

    monkeypatch.setattr(mcp_adapter, "create_server", lambda **_: FakeServer())

    assert mcp_adapter.main([], environ={"AOMS_LOG_LEVEL": "ERROR"}) == 0
    assert (
        mcp_adapter.main(
            ["--streamable-http", "--host", "127.0.0.1", "--port", "9123"],
            environ={"AOMS_LOG_LEVEL": "ERROR"},
        )
        == 0
    )
    assert transports == ["stdio", "streamable-http"]


def test_process_scope_defaults_are_single_user_and_non_null() -> None:
    assert mcp_adapter._scope_context_from_environ({}) == ScopeContext(
        agent_id="default",
        workspace_id="default",
    )
