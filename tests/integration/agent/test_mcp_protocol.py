"""Real SDK protocol, scripted business dependencies; not real AGH or MySQL evidence."""

import asyncio
import json
from pathlib import Path

from mcp.shared.memory import create_connected_server_and_client_session

from project_doctor.entrypoints.mcp_server import build_server
from project_doctor.models.task import TaskBundle
from project_doctor.workflows.tools import ToolWorkflows
from tests.diagnosis.fakes import MemoryStore, ScriptedReader, ScriptedRuntime
from tests.diagnosis.test_slow_query import add_spec


def test_mcp_catalog_structured_call_and_invalid_input() -> None:
    root = Path(__file__).resolve().parents[3]
    case = json.loads(
        (root / "tests/contracts/fixtures/verified_slow_query.json").read_text("utf-8")
    )
    bundle = add_spec(TaskBundle.model_validate(case["bundle"]))
    bundle.task.status = "running"
    store = MemoryStore(bundle)
    workflows = ToolWorkflows(
        ScriptedRuntime(store),
        store,
        ScriptedReader(),
        {"scenarios": [bundle.scenarios[0].model_dump()]},
    )
    tools = json.loads((root / "agh/tool-policy.json").read_text("utf-8"))["tools"]
    server = build_server(
        workflows, {name: policy["timeout_seconds"] for name, policy in tools.items()}
    )

    async def call() -> None:
        async with create_connected_server_and_client_session(server) as session:
            catalog = await session.list_tools()
            assert {item.name for item in catalog.tools} == set(tools)
            evaluate_tool = next(item for item in catalog.tools if item.name == "evaluate_evidence")
            assert "observations" not in evaluate_tool.inputSchema["properties"]
            result = await session.call_tool(
                "evaluate_evidence",
                {
                    "context": bundle.task.correlation.model_dump(mode="json"),
                    "hypothesis_ids": ["hypothesis-1"],
                    "experiment_ids": ["experiment-1"],
                },
            )
            assert not result.isError
            assert result.structuredContent is not None
            assert result.structuredContent["result"][0]["status"] == "verified"
            bad = await session.call_tool(
                "evaluate_evidence",
                {
                    "context": bundle.task.correlation.model_dump(mode="json"),
                    "hypothesis_ids": ["hypothesis-1"],
                    "experiment_ids": ["fabricated"],
                },
            )
            assert bad.isError

    asyncio.run(call())
