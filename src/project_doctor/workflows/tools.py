"""Model-visible orchestration. Runtime owns side effects; this layer never runs SQL or Docker."""

from dataclasses import dataclass, field

from project_doctor.features.diagnosis.compare import MeasurementPolicy
from project_doctor.features.diagnosis.ports import EvidenceReader
from project_doctor.features.experiments.ports import Runtime
from project_doctor.features.reports.build import build_report
from project_doctor.features.scenarios.discover import discover
from project_doctor.features.scenarios.validate import validate
from project_doctor.models.common import Limits, TaskStatus
from project_doctor.models.environment import EnvironmentHandle, ProjectInput
from project_doctor.models.experiment import ExperimentResult, ExperimentSpec, ReconcileResult
from project_doctor.models.finding import Finding, ReportResult
from project_doctor.models.hypothesis import Hypothesis, HypothesisBatch
from project_doctor.models.scenario import Scenario
from project_doctor.models.task import CallContext, TaskRecord
from project_doctor.workflows.diagnose import evaluate
from project_doctor.workflows.task_ports import TaskStore
from project_doctor.workflows.tasks import create_task


@dataclass
class ToolWorkflows:
    runtime: Runtime
    store: TaskStore
    reader: EvidenceReader
    repository_manifest: dict[str, object]
    policy: MeasurementPolicy = field(default_factory=MeasurementPolicy)

    async def create_task(
        self, project: ProjectInput, limits: Limits, operation_id: str
    ) -> TaskRecord:
        return await create_task(project, limits, operation_id, self.store)

    async def prepare_environment(self, context: CallContext) -> EnvironmentHandle:
        task = await self.store.get(context.task_id)
        if task.status not in {"created", "running"}:
            raise ValueError("task state does not allow environment preparation")
        return await self.runtime.prepare(task.project, context)

    async def discover_scenarios(self, context: CallContext) -> list[Scenario]:
        task = await self.store.get(context.task_id)
        if task.status in {"completed", "partial"}:
            raise ValueError("terminal task cannot change scenarios")
        scenarios = discover(task.project, self.repository_manifest)
        for scenario in scenarios:
            await self.store.save_scenario(task.id, scenario)
        return scenarios

    async def propose_hypotheses(
        self, context: CallContext, items: list[Hypothesis]
    ) -> list[Hypothesis]:
        task = await self.store.get(context.task_id)
        if task.status in {"completed", "partial"}:
            raise ValueError("terminal task cannot change hypotheses")
        batch = HypothesisBatch.model_validate({"items": [item.model_dump() for item in items]})
        proposed = [
            item.model_copy(update={"status": "proposed", "evidence_ids": []})
            for item in batch.items
        ]
        await self.store.save_hypotheses(context.task_id, proposed)
        return proposed

    async def run_experiment(
        self,
        context: CallContext,
        environment_id: str,
        scenario_id: str,
        scenario_version: int,
        spec: ExperimentSpec,
    ) -> ExperimentResult:
        bundle = await self.store.load_bundle(context.task_id)
        if bundle.task.status not in {"created", "running"}:
            raise ValueError("task state does not allow experiments")
        if environment_id != bundle.task.environment_id:
            raise ValueError("environment does not belong to task")
        if (
            spec.task_id != context.task_id
            or spec.scenario_id != scenario_id
            or spec.scenario_version != scenario_version
        ):
            raise ValueError("experiment task/scenario/version mismatch")
        if not set(spec.hypothesis_ids).issubset({item.id for item in bundle.hypotheses}):
            raise ValueError("unknown hypothesis IDs")
        scenario = next(
            (
                item
                for item in bundle.scenarios
                if item.id == scenario_id and item.version == scenario_version
            ),
            None,
        )
        if scenario is None:
            raise ValueError("unknown scenario version")
        failures = validate(scenario)
        if failures:
            raise ValueError(failures[0].message)
        # A reserves budget, validates network/recipe, persists actual result and restores once.
        return await self.runtime.run(environment_id, scenario, spec, context)

    async def evaluate_evidence(
        self,
        context: CallContext,
        hypothesis_ids: list[str],
        experiment_ids: list[str],
    ) -> list[Finding]:
        bundle = await self.store.load_bundle(context.task_id)
        if bundle.task.status in {"completed", "partial"}:
            raise ValueError("terminal task cannot change findings")
        if not experiment_ids or not hypothesis_ids:
            raise ValueError("explicit persisted experiment and hypothesis IDs are required")
        if not set(experiment_ids).issubset({item.experiment_id for item in bundle.experiments}):
            raise ValueError("unknown experiment IDs")
        if not set(hypothesis_ids).issubset({item.id for item in bundle.hypotheses}):
            raise ValueError("unknown hypothesis IDs")
        selected = bundle.model_copy(
            update={
                "experiments": [
                    item for item in bundle.experiments if item.experiment_id in experiment_ids
                ],
                "hypotheses": [item for item in bundle.hypotheses if item.id in hypothesis_ids],
            }
        )
        if any(
            item.spec and not set(item.spec.hypothesis_ids).issubset(set(hypothesis_ids))
            for item in selected.experiments
        ):
            raise ValueError("hypotheses do not match selected experiments")
        findings = await evaluate(selected, self.reader, self.policy)
        previous = [
            item.model_copy(
                update={
                    "status": "lead",
                    "excluded_explanations": [],
                    "limitations": item.limitations
                    + ["已被本轮证据核对替代，不能沿用旧结论状态。"],
                }
            )
            for item in bundle.findings
            if set(item.experiment_ids).intersection(experiment_ids)
            and item.id not in {finding.id for finding in findings}
        ]
        await self.store.save_findings(context.task_id, previous + findings)
        updated_hypotheses = []
        for hypothesis in selected.hypotheses:
            supported = (
                hypothesis.kind == "slow_query"
                and hypothesis.explanation == "index_access_cost"
                and bool(findings)
                and all(finding.status == "verified" for finding in findings)
            )
            updated_hypotheses.append(
                hypothesis.model_copy(
                    update={
                        "status": "supported" if supported else "unresolved",
                        "evidence_ids": list(
                            dict.fromkeys(
                                ref.artifact_id
                                for finding in findings
                                for ref in finding.evidence_refs
                            )
                        ),
                    }
                )
            )
        await self.store.save_hypotheses(context.task_id, updated_hypotheses)
        return findings

    async def reconcile_task(self, context: CallContext) -> ReconcileResult:
        await self.store.get(context.task_id)
        return await self.runtime.reconcile(context.task_id)

    async def finish_task(self, context: CallContext) -> ReportResult:
        from project_doctor.features.environments.prepare import compose_project_name

        bundle = await self.store.load_bundle(context.task_id)
        if bundle.task.status in {"completed", "partial"}:
            published = await self.store.load_report(context.task_id)
            if published is not None:
                check = await self.reader.verify([published.json_ref, published.html_ref])
                if not check.valid:
                    raise ValueError(
                        "published report unavailable; terminal task will not be reopened"
                    )
                return published
            # A crash between the state transition and publishing is resumable,
            # but must never restore an environment already closed.
            return await self.runtime.publish_report(
                build_report(bundle),
                context.model_copy(update={"operation_id": "finish:report"}),
            )
        close_context = context.model_copy(update={"operation_id": "finish:close"})
        result = await self.runtime.close(
            bundle.task.environment_id or compose_project_name(context.task_id), close_context
        )
        restored = result.verified
        bundle = await self.store.load_bundle(context.task_id)
        refreshed = await evaluate(bundle, self.reader, self.policy) if bundle.experiments else []
        if not restored:
            refreshed = [
                item.model_copy(
                    update={
                        "status": "lead",
                        "excluded_explanations": [],
                        "limitations": item.limitations + ["收尾恢复未验证。"],
                    }
                )
                for item in refreshed
            ]
        previous = [
            item.model_copy(
                update={
                    "status": "lead",
                    "excluded_explanations": [],
                    "limitations": item.limitations + ["收尾重新核对后，旧结论状态不再沿用。"],
                }
            )
            for item in bundle.findings
            if item.id not in {finding.id for finding in refreshed}
        ]
        await self.store.save_findings(context.task_id, previous + refreshed)
        healthy = (
            restored
            and bool(bundle.experiments)
            and all(
                item.phase == "finished"
                and item.failure is None
                and item.restore_result
                and item.restore_result.verified
                for item in bundle.experiments
            )
        )
        target: TaskStatus = "completed" if healthy else "partial"
        if not await self.store.transition(context.task_id, bundle.task.status, target):
            raise ValueError("task state changed while finishing; reconcile before continuing")
        current = await self.store.load_bundle(context.task_id)
        report = build_report(current)
        if not restored:
            report.limitations.append(result.reason or "收尾恢复未验证，环境需核对或已隔离。")
            # Build once more with the warning as persisted finding/coverage context is unchanged.
            import json

            from project_doctor.features.reports.render_html import render_html

            payload = json.loads(report.json_content)
            payload["limitations"] = report.limitations
            report.json_content = json.dumps(payload, ensure_ascii=False, indent=2)
            report.html_content = render_html(report.json_content)
        publish_context = context.model_copy(update={"operation_id": "finish:report"})
        return await self.runtime.publish_report(report, publish_context)
