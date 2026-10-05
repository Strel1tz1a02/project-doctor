"""Pre-flight validation of an experiment spec against the task, scenario and budget."""

from __future__ import annotations

from project_doctor.models.errors import Failure, FailureCode
from project_doctor.models.experiment import ExperimentSpec
from project_doctor.models.scenario import Scenario
from project_doctor.models.task import TaskRecord


def validate_experiment(
    spec: ExperimentSpec, scenario: Scenario, task: TaskRecord
) -> list[Failure]:
    """Return every reason the spec must not run; an empty list means it may start.

    The runtime owns side effects, so this only inspects persisted inputs and never
    trusts the caller's earlier checks.
    """
    failures: list[Failure] = []

    def add(code: FailureCode, message: str) -> None:
        failures.append(Failure(code=code, message=message, retry_policy="never"))

    if spec.task_id != task.id:
        add("scenario_invalid", "experiment belongs to another task")
    if spec.scenario_id != scenario.id or spec.scenario_version != scenario.version:
        add("scenario_invalid", "experiment scenario or version does not match")
    if spec.snapshot_id != scenario.dataset.snapshot_id:
        add("scenario_invalid", "experiment dataset snapshot does not match the scenario")
    if not set(spec.hypothesis_ids).issubset(task.hypothesis_ids):
        add("scenario_invalid", "experiment references unknown hypotheses")
    if spec.repetitions < 3:
        add("scenario_invalid", "experiment requires at least three repetitions")
    if spec.warmup is not None:
        if scenario.cache.state != "warm":
            add("scenario_invalid", "workload warmup requires cache state warm")
        if len(scenario.steps) != 1 or scenario.steps[0].method != "GET":
            add("scenario_invalid", "warmup protocol supports one read-only GET request")
        if scenario.cache.preparation_recipe_ref != spec.warmup.preparation_recipe_ref:
            add("scenario_invalid", "cache preparation recipe does not match warmup protocol")
        if scenario.load.mode != "serial":
            add("scenario_invalid", "warmup protocol requires serial measurement")
    if task.usage.experiments >= task.limits.max_experiments:
        add("budget_exhausted", "experiment budget is exhausted")
    return failures
