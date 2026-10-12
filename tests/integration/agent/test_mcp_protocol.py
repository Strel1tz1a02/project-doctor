"""Real SDK protocol, scripted business dependencies; not real AGH or MySQL evidence."""

import asyncio
import json
from pathlib import Path

from mcp.shared.memory import create_connected_server_and_client_session

from project_doctor.entrypoints.mcp_server import build_server
from project_doctor.models.task import TaskBundle
from project_doctor.workflows.repair import RepairWorkflow
from project_doctor.workflows.tools import ToolWorkflows
from tests.diagnosis.fakes import MemoryStore, ScriptedReader, ScriptedRuntime
from tests.diagnosis.test_n_plus_one import Reader
from tests.diagnosis.test_slow_query import add_spec
from tests.repair.test_diagnosis_retest import _repair
from tests.repair.test_gates import _handoff
from tests.repair.test_workflow import Diagnosis, Store, _settings


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
            assert {item.name for item in catalog.tools} == set(tools) - {
                "inspect_fix_target",
                "submit_fix_patch",
                "verify_fix",
                "get_fix_status",
            }
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


def test_repair_tools_expose_patch_input_but_no_model_measurement_input() -> None:
    root = Path(__file__).resolve().parents[3]
    policy = json.loads((root / "agh/tool-policy.json").read_text("utf-8"))["tools"]
    case = json.loads(
        (root / "tests/contracts/fixtures/verified_slow_query.json").read_text("utf-8")
    )
    bundle = add_spec(TaskBundle.model_validate(case["bundle"]))
    store = MemoryStore(bundle)
    workflows = ToolWorkflows(ScriptedRuntime(store), store, ScriptedReader(), {})
    workflows.repair = object()  # type: ignore[assignment]
    server = build_server(
        workflows, {name: item["timeout_seconds"] for name, item in policy.items()}
    )

    async def catalog() -> None:
        async with create_connected_server_and_client_session(server) as session:
            listed = {item.name: item for item in (await session.list_tools()).tools}
            assert set(listed) == set(policy)
            assert set(listed["submit_fix_patch"].inputSchema["properties"]) == {
                "context",
                "finding_id",
                "diff",
            }
            assert set(listed["verify_fix"].inputSchema["properties"]) == {"context", "repair_id"}

    asyncio.run(catalog())


def test_mcp_verify_fix_delegates_effect_verdict_to_diagnosis(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    policy = json.loads((root / "agh/tool-policy.json").read_text("utf-8"))["tools"]
    bundle, finding = _handoff()
    repair = _repair(bundle, finding).model_copy(update={"status": "built"})
    store = Store(bundle, repair)
    started = asyncio.Event()
    release = asyncio.Event()

    class WaitingDiagnosis(Diagnosis):
        async def run(self, bundle, finding, repair):
            started.set()
            await release.wait()
            return await super().run(bundle, finding, repair)

    diagnosis = WaitingDiagnosis(finding)
    workflows = ToolWorkflows(ScriptedRuntime(store), store, Reader(), {})
    workflows.repair = RepairWorkflow(_settings(tmp_path), store, Reader(), diagnosis)
    server = build_server(
        workflows, {name: item["timeout_seconds"] for name, item in policy.items()}
    )

    async def call() -> None:
        async with create_connected_server_and_client_session(server) as session:
            result = await asyncio.wait_for(
                session.call_tool(
                    "verify_fix",
                    {
                        "context": bundle.task.correlation.model_dump(mode="json"),
                        "repair_id": repair.id,
                    },
                ),
                timeout=1,
            )
            assert not result.isError
            assert result.structuredContent is not None
            payload = result.structuredContent.get("result", result.structuredContent)
            assert payload["status"] == "retesting"
            assert started.is_set()
            duplicate = await session.call_tool(
                "verify_fix",
                {
                    "context": bundle.task.correlation.model_dump(mode="json"),
                    "repair_id": repair.id,
                },
            )
            assert not duplicate.isError
            assert duplicate.structuredContent is not None
            duplicate_payload = duplicate.structuredContent.get(
                "result", duplicate.structuredContent
            )
            assert duplicate_payload["status"] == "retesting"
            assert diagnosis.calls == 0
        release.set()
        for _ in range(100):
            await asyncio.sleep(0.01)
            if store.repair.status == "retested":
                break
        assert diagnosis.calls == 1
        async with create_connected_server_and_client_session(server) as session:
            status = await session.call_tool(
                "get_fix_status",
                {
                    "context": bundle.task.correlation.model_dump(mode="json"),
                    "repair_id": repair.id,
                },
            )
            assert not status.isError
            assert status.structuredContent is not None
            payload = status.structuredContent.get("result", status.structuredContent)
            assert payload["status"] == "retested"

    asyncio.run(call())
