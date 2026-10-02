import asyncio

import pytest

from project_doctor.models.experiment import ExperimentSpec
from project_doctor.models.task import TaskBundle
from project_doctor.workflows.tools import ToolWorkflows
from tests.diagnosis.fakes import MemoryStore, ScriptedReader, ScriptedRuntime
from tests.diagnosis.test_slow_query import add_spec


def setup(
    bundle: TaskBundle, restore_ok: bool = True
) -> tuple[ToolWorkflows, ScriptedRuntime, MemoryStore]:
    add_spec(bundle)
    bundle.task.status = "running"
    store = MemoryStore(bundle)
    runtime = ScriptedRuntime(store, restore_ok)
    workflows = ToolWorkflows(
        runtime, store, ScriptedReader(), {"scenarios": [bundle.scenarios[0].model_dump()]}
    )
    return workflows, runtime, store


def test_runtime_owns_replay_and_budget(bundle: TaskBundle) -> None:
    workflows, runtime, store = setup(bundle)
    context = bundle.task.correlation
    spec = bundle.experiments[0].spec
    assert isinstance(spec, ExperimentSpec)

    async def run() -> None:
        await workflows.run_experiment(context, "environment-1", "scenario-1", 1, spec)
        await workflows.run_experiment(context, "environment-1", "scenario-1", 1, spec)

    asyncio.run(run())
    assert runtime.run_calls == 1
    assert store.reservation_calls == 0


def test_model_cannot_mark_hypothesis_supported(bundle: TaskBundle) -> None:
    workflows, _, _ = setup(bundle)
    result = asyncio.run(workflows.propose_hypotheses(bundle.task.correlation, bundle.hypotheses))
    assert result[0].status == "proposed"
    assert result[0].evidence_ids == []


def test_unknown_experiment_is_rejected(bundle: TaskBundle) -> None:
    workflows, _, _ = setup(bundle)
    with pytest.raises(ValueError, match="unknown experiment"):
        asyncio.run(
            workflows.evaluate_evidence(bundle.task.correlation, ["hypothesis-1"], ["fake"])
        )


def test_finish_reverifies_stale_findings_and_publishes_partial(bundle: TaskBundle) -> None:
    workflows, runtime, store = setup(bundle, restore_ok=False)
    workflows.reader = ScriptedReader(valid=False)
    result = asyncio.run(workflows.finish_task(bundle.task.correlation))
    assert result.task_status == "partial"
    assert runtime.report is not None
    assert not runtime.report.verified_findings
    assert "收尾恢复未验证" in runtime.report.html_content
    assert store.bundle.task.status == "partial"


def test_foreign_environment_is_rejected_before_runtime(bundle: TaskBundle) -> None:
    workflows, runtime, _ = setup(bundle)
    spec = bundle.experiments[0].spec
    assert spec is not None
    with pytest.raises(ValueError, match="environment does not belong"):
        asyncio.run(
            workflows.run_experiment(bundle.task.correlation, "foreign", "scenario-1", 1, spec)
        )
    assert runtime.run_calls == 0


def test_arbitrary_model_explanation_does_not_become_supported(bundle: TaskBundle) -> None:
    workflows, _, store = setup(bundle)
    result = asyncio.run(
        workflows.evaluate_evidence(bundle.task.correlation, ["hypothesis-1"], ["experiment-1"])
    )
    assert result[0].status == "verified"
    assert store.bundle.hypotheses[0].status == "unresolved"
