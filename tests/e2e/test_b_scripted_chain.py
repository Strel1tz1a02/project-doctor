"""B workflow chain with scripted A dependencies. This is not the real-target acceptance test."""

import asyncio
import json
from pathlib import Path

from project_doctor.models.task import TaskBundle
from project_doctor.workflows.tools import ToolWorkflows
from tests.diagnosis.fakes import MemoryStore, ScriptedReader, ScriptedRuntime
from tests.diagnosis.test_slow_query import add_spec


def test_b_scenario_experiment_evidence_to_report() -> None:
    root = Path(__file__).resolve().parents[2]
    case = json.loads(
        (root / "tests/contracts/fixtures/verified_slow_query.json").read_text("utf-8")
    )
    bundle = add_spec(TaskBundle.model_validate(case["bundle"]))
    bundle.task.status = "created"
    bundle.hypotheses[0].explanation = "index_access_cost"
    store = MemoryStore(bundle)
    runtime = ScriptedRuntime(store)
    workflows = ToolWorkflows(
        runtime, store, ScriptedReader(), {"scenarios": [bundle.scenarios[0].model_dump()]}
    )

    async def run() -> None:
        context = bundle.task.correlation
        environment = await workflows.prepare_environment(context)
        scenarios = await workflows.discover_scenarios(context)
        hypotheses = await workflows.propose_hypotheses(context, bundle.hypotheses)
        assert hypotheses[0].status == "proposed"
        spec = bundle.experiments[0].spec
        assert spec is not None
        await workflows.run_experiment(
            context, environment.id, scenarios[0].id, scenarios[0].version, spec
        )
        findings = await workflows.evaluate_evidence(context, [hypotheses[0].id], [spec.id])
        assert findings[0].status == "verified"
        assert store.bundle.hypotheses[0].status == "supported"
        report = await workflows.finish_task(context)
        assert report.task_status == "completed"
        assert runtime.report is not None
        assert runtime.report.verified_findings
        assert "SELECT" in runtime.report.html_content

    asyncio.run(run())
