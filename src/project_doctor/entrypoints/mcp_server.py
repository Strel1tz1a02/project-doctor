"""Official SDK transport. Dependencies are injected; no fake adapter fallback."""

import asyncio
from collections.abc import Awaitable
from typing import Any, TypeVar

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from project_doctor.models.common import Limits
from project_doctor.models.environment import EnvironmentHandle, ProjectInput
from project_doctor.models.experiment import ExperimentResult, ExperimentSpec, ReconcileResult
from project_doctor.models.finding import Finding, ReportResult
from project_doctor.models.hypothesis import Hypothesis
from project_doctor.models.repair import (
    CodeRepairTargetView,
    RepairRecord,
    RepairTargetView,
    SourceFileView,
)
from project_doctor.models.scenario import Scenario
from project_doctor.models.task import CallContext, TaskRecord
from project_doctor.workflows.tools import ToolWorkflows

T = TypeVar("T")


def build_server(workflows: ToolWorkflows, timeouts: dict[str, float]) -> FastMCP:
    server = FastMCP(
        "Project Doctor", instructions="使用持久场景与实验 ID；缺证据保留线索，执行未知先核对。"
    )
    required = {
        "create_task",
        "prepare_environment",
        "discover_scenarios",
        "propose_hypotheses",
        "run_experiment",
        "evaluate_evidence",
        "reconcile_task",
        "finish_task",
    }
    if workflows.repair is not None:
        required.update({
            "get_repair_handoff", "inspect_fix_target", "read_fix_source", "submit_fix_patch",
            "verify_fix", "get_fix_status",
        })
    if not required.issubset(timeouts) or any(value <= 0 for value in timeouts.values()):
        raise ValueError("all business tools require positive timeouts")
    active_retests: dict[
        tuple[str, str], tuple[asyncio.Task[RepairRecord], asyncio.Future[RepairRecord]]
    ] = {}
    retest_launch_lock = asyncio.Lock()

    async def bounded(name: str, action: Awaitable[T]) -> T:
        try:
            return await asyncio.wait_for(action, timeout=timeouts[name])
        except TimeoutError as exc:
            raise ValueError(
                "tool timeout: execution outcome may be unknown; reconcile before replay"
            ) from exc

    annotations = ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False
    )

    @server.tool(annotations=annotations)
    async def create_task(project: ProjectInput, limits: Limits, operation_id: str) -> TaskRecord:
        """Create or resolve a business-keyed task. Same key with different input is a conflict."""
        return await bounded("create_task", workflows.create_task(project, limits, operation_id))

    @server.tool(annotations=annotations)
    async def prepare_environment(context: CallContext) -> EnvironmentHandle:
        """Prepare the isolated target. Runtime owns reservation and recovery."""
        return await bounded("prepare_environment", workflows.prepare_environment(context))

    @server.tool(annotations=annotations)
    async def discover_scenarios(context: CallContext) -> list[Scenario]:
        """Discover valid repository-manifest operations and preserve unknown coverage."""
        return await bounded("discover_scenarios", workflows.discover_scenarios(context))

    @server.tool(annotations=annotations)
    async def propose_hypotheses(context: CallContext, items: list[Hypothesis]) -> list[Hypothesis]:
        """Persist at most three proposed hypotheses; model-written status is not evidence."""
        return await bounded("propose_hypotheses", workflows.propose_hypotheses(context, items))

    @server.tool(annotations=annotations)
    async def run_experiment(
        context: CallContext,
        environment_id: str,
        scenario_id: str,
        scenario_version: int,
        spec: ExperimentSpec,
    ) -> ExperimentResult:
        """Execute a persisted scenario under a single-variable experiment, then restore."""
        return await bounded(
            "run_experiment",
            workflows.run_experiment(
                context,
                environment_id,
                scenario_id,
                scenario_version,
                spec,
            ),
        )

    @server.tool(annotations=annotations)
    async def evaluate_evidence(
        context: CallContext,
        hypothesis_ids: list[str],
        experiment_ids: list[str],
    ) -> list[Finding]:
        """Verify persisted results and artifacts; model-provided observations are not accepted."""
        return await bounded(
            "evaluate_evidence",
            workflows.evaluate_evidence(context, hypothesis_ids, experiment_ids),
        )

    @server.tool(annotations=annotations)
    async def reconcile_task(context: CallContext) -> ReconcileResult:
        """Reconcile persistence, target health and artifacts before replaying unknown work."""
        return await bounded("reconcile_task", workflows.reconcile_task(context))

    @server.tool(annotations=annotations)
    async def finish_task(context: CallContext) -> ReportResult:
        """Close the target, recheck evidence and publish a complete or partial JSON/HTML report."""
        return await bounded("finish_task", workflows.finish_task(context))

    if workflows.repair is not None:
        read_only = ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )

        @server.tool(annotations=read_only)
        async def get_repair_handoff(task_id: str) -> dict[str, Any]:
            """Read evidence-checked persisted diagnosis targets for a separate repair Agent."""
            return await bounded("get_repair_handoff", workflows.get_repair_handoff(task_id))

        @server.tool(annotations=read_only)
        async def inspect_fix_target(
            context: CallContext, finding_id: str
        ) -> RepairTargetView | CodeRepairTargetView:
            """Inspect persisted diagnostic source and permitted patch paths."""
            return await bounded(
                "inspect_fix_target", workflows.inspect_fix_target(context, finding_id)
            )

        @server.tool(annotations=read_only)
        async def read_fix_source(
            context: CallContext, finding_id: str, path: str,
            start_line: int, line_count: int,
        ) -> SourceFileView:
            """Read at most 120 lines of permitted, hash-checked application source."""
            return await bounded(
                "read_fix_source",
                workflows.read_fix_source(context, finding_id, path, start_line, line_count),
            )

        @server.tool(annotations=annotations)
        async def submit_fix_patch(
            context: CallContext, finding_id: str, diff: str
        ) -> RepairRecord:
            """Apply a bounded application-source diff in isolation and build its image."""
            return await bounded(
                "submit_fix_patch", workflows.submit_fix_patch(context, finding_id, diff)
            )

        @server.tool(annotations=annotations)
        async def verify_fix(context: CallContext, repair_id: str) -> RepairRecord:
            """Start diagnosis retest; poll get_fix_status for its durable verdict."""
            key = (context.task_id, repair_id)
            async with retest_launch_lock:
                running = active_retests.get(key)
                if running is None:
                    started: asyncio.Future[RepairRecord] = (
                        asyncio.get_running_loop().create_future()
                    )

                    def on_started(record: RepairRecord) -> None:
                        if not started.done():
                            started.set_result(record)

                    task = asyncio.create_task(
                        bounded("verify_fix", workflows.verify_fix(context, repair_id, on_started))
                    )
                    running = (task, started)
                    active_retests[key] = running

                    def on_done(done: asyncio.Task[RepairRecord]) -> None:
                        if active_retests.get(key) == running:
                            active_retests.pop(key, None)
                        try:
                            done.exception()
                        except asyncio.CancelledError:
                            pass

                    task.add_done_callback(on_done)
            task, started = running
            done, _ = await asyncio.wait(
                {task, started},
                timeout=min(30.0, timeouts["verify_fix"] / 2),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if started in done:
                return started.result()
            if task in done:
                return task.result()
            raise ValueError("retest launch is pending; query get_fix_status before retry")

        @server.tool(annotations=annotations)
        async def get_fix_status(context: CallContext, repair_id: str) -> RepairRecord:
            """Reconcile durable repair state and clean exited retest environments."""
            return await bounded("get_fix_status", workflows.get_fix_status(context, repair_id))

    return server
