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


@pytest.mark.parametrize("restore_ok", [True, False])
def test_finish_with_new_id_replays_report_without_restoring_again(
    bundle: TaskBundle, restore_ok: bool
) -> None:
    workflows, runtime, store = setup(bundle, restore_ok=restore_ok)

    async def run():
        first = await workflows.finish_task(bundle.task.correlation)
        runtime.restore_ok = False
        second = await workflows.finish_task(
            bundle.task.correlation.model_copy(update={"operation_id": "another-finish"})
        )
        assert second == first
        assert store.bundle.task.status == first.task_status

    asyncio.run(run())
    assert runtime.close_calls == 1


def test_resume_report_publication_after_terminal_transition(bundle: TaskBundle) -> None:
    workflows, runtime, _ = setup(bundle)
    workflows.store.bundle.task.status = "completed"
    result = asyncio.run(workflows.finish_task(bundle.task.correlation))
    assert result.task_status == "completed"
    assert runtime.close_calls == 0


def test_corrupt_terminal_report_does_not_reopen_task(bundle: TaskBundle) -> None:
    workflows, runtime, store = setup(bundle)
    asyncio.run(workflows.finish_task(bundle.task.correlation))
    workflows.reader = ScriptedReader(valid=False)
    with pytest.raises(ValueError):
        asyncio.run(
            workflows.finish_task(
                bundle.task.correlation.model_copy(update={"operation_id": "retry-corrupt"})
            )
        )
    assert store.bundle.task.status == "completed"
    assert runtime.close_calls == 1


@pytest.mark.parametrize("restore_ok", [True, False])
@pytest.mark.parametrize("tool", ["discover_scenarios", "propose_hypotheses", "evaluate_evidence"])
def test_terminal_task_cannot_mutate_published_report_inputs(
    bundle: TaskBundle, restore_ok: bool, tool: str
) -> None:
    workflows, runtime, store = setup(bundle, restore_ok=restore_ok)
    asyncio.run(workflows.finish_task(bundle.task.correlation))
    before = store.bundle.model_copy(deep=True)
    args = {
        "discover_scenarios": (),
        "propose_hypotheses": (bundle.hypotheses,),
        "evaluate_evidence": (["hypothesis-1"], ["experiment-1"]),
    }
    with pytest.raises(ValueError, match="terminal task"):
        asyncio.run(getattr(workflows, tool)(bundle.task.correlation, *args[tool]))
    assert store.bundle == before
    assert runtime.close_calls == 1
