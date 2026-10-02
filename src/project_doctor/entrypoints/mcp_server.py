"""Official SDK transport. Dependencies are injected; no fake adapter fallback."""

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from project_doctor.models.common import Limits
from project_doctor.models.environment import EnvironmentHandle, ProjectInput
from project_doctor.models.experiment import ExperimentResult, ExperimentSpec, ReconcileResult
from project_doctor.models.finding import Finding, ReportResult
from project_doctor.models.hypothesis import Hypothesis
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
    if not required.issubset(timeouts) or any(value <= 0 for value in timeouts.values()):
        raise ValueError("all business tools require positive timeouts")

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
        """Execute a persisted scenario under a single-variable index experiment, then restore."""
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

    return server
