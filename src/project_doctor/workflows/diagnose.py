from project_doctor.features.diagnosis.compare import MeasurementPolicy
from project_doctor.features.diagnosis.gates import evidence_refs
from project_doctor.features.diagnosis.n_plus_one import check_n_plus_one
from project_doctor.features.diagnosis.ports import EvidenceReader, VerifiedJsonReader
from project_doctor.features.diagnosis.slow_query import check_slow_query
from project_doctor.models.finding import Finding
from project_doctor.models.task import TaskBundle


async def evaluate(
    bundle: TaskBundle,
    reader: EvidenceReader,
    policy: MeasurementPolicy | None = None,
) -> list[Finding]:
    policy = policy or MeasurementPolicy()
    results: list[Finding] = []
    for experiment in bundle.experiments:
        spec = experiment.spec
        if spec is not None and spec.task_id != bundle.task.id:
            raise ValueError("experiment belongs to another task")
        scenario = next(
            (
                item
                for item in bundle.scenarios
                if spec is not None
                and item.id == spec.scenario_id
                and item.version == spec.scenario_version
            ),
            None,
        )
        # Historical results without spec are only associated if the task has exactly one scenario.
        if scenario is None and len(bundle.scenarios) == 1:
            scenario = bundle.scenarios[0]
        if scenario is None:
            raise ValueError("experiment has no unambiguous persisted scenario")
        plans = {}
        if isinstance(reader, VerifiedJsonReader):
            plan_ids = {
                key
                for observation in experiment.observations
                for call in observation.sql_calls
                for key in call.plan_evidence_ids
            }
            for ref in evidence_refs(experiment):
                if ref.artifact_id in plan_ids and ref.format_version == "explain.v1":
                    try:
                        plans[ref.artifact_id] = await reader.read_verified_json(ref)
                    except (OSError, ValueError):
                        # Missing/invalid plans cannot support a negative diagnosis.
                        pass
        if spec is not None and spec.variable == "query_shape":
            findings = check_n_plus_one(
                experiment, scenario, bundle.task.id, bundle.task.project.commit, policy
            )
        else:
            findings = check_slow_query(
                experiment,
                scenario,
                bundle.task.id,
                bundle.task.project.commit,
                policy,
                verified_plans=plans,
            )
        try:
            check = await reader.verify(evidence_refs(experiment))
            reasons = (
                check.reasons
                + [f"缺失制品：{key}" for key in check.missing_ids]
                + [f"损坏制品：{key}" for key in check.corrupted_ids]
            )
            if not check.valid:
                findings = [
                    item.model_copy(
                        update={
                            "status": "lead",
                            "excluded_explanations": [],
                            "limitations": item.limitations + reasons,
                        }
                    )
                    for item in findings
                ]
        except (OSError, ValueError) as exc:
            findings = [
                item.model_copy(
                    update={
                        "status": "lead",
                        "excluded_explanations": [],
                        "limitations": item.limitations + [f"证据校验失败：{type(exc).__name__}"],
                    }
                )
                for item in findings
            ]
        results.extend(findings)
    return results
