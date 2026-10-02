import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from project_doctor.entrypoints.settings import Settings
from project_doctor.models.common import CodeLocation, EvidenceRef, Limits
from project_doctor.models.experiment import ExperimentSpec, ReconcileResult
from project_doctor.models.finding import Finding, Recommendation
from project_doctor.models.hypothesis import HypothesisBatch
from project_doctor.models.observation import SqlCall
from project_doctor.models.scenario import RequestStep
from project_doctor.models.task import CallContext, OperationResult, TaskBundle

FIXTURES = Path(__file__).parent / "fixtures"
CASE_NAMES = (
    "verified_slow_query",
    "missing_location",
    "missing_artifact",
    "incomparable",
    "restore_failed",
    "unknown_outcome",
)


def load_case(name: str = "verified_slow_query") -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.mark.parametrize("name", CASE_NAMES)
def test_fixture_round_trip(name: str) -> None:
    case = load_case(name)
    assert case["synthetic"] is True
    bundle = TaskBundle.model_validate(case["bundle"])
    assert TaskBundle.model_validate_json(bundle.model_dump_json()) == bundle
    spec = ExperimentSpec.model_validate(case["spec"])
    assert spec.scenario_id == bundle.scenarios[0].id
    assert bundle.findings[0].status == case["expected_status"]


def test_fixture_failures_are_distinct() -> None:
    missing_location = TaskBundle.model_validate(load_case("missing_location")["bundle"])
    assert missing_location.experiments[0].observations[0].sql_calls[0].code_location is None
    missing_artifact = load_case("missing_artifact")
    assert missing_artifact["evidence_check"]["missing_ids"]
    incomparable = TaskBundle.model_validate(load_case("incomparable")["bundle"])
    assert len({item.snapshot_id for item in incomparable.experiments[0].observations}) == 2
    failed = TaskBundle.model_validate(load_case("restore_failed")["bundle"])
    assert failed.experiments[0].restore_result is not None
    assert failed.experiments[0].restore_result.verified is False
    unknown = TaskBundle.model_validate(load_case("unknown_outcome")["bundle"])
    assert unknown.experiments[0].phase == "needs_reconcile"


def test_unknown_fields_and_versions_rejected() -> None:
    data = load_case()["bundle"]
    for key, value in (("extra_field", True), ("schema_version", "9.9")):
        invalid = copy.deepcopy(data)
        invalid[key] = value
        with pytest.raises(ValidationError):
            TaskBundle.model_validate(invalid)


@pytest.mark.parametrize("path", ["../secret", "/tmp/file", "C:/secret", r"a\b", ".", "a/../b"])
def test_wire_paths_cannot_escape(path: str) -> None:
    data = load_case()["bundle"]["evidence_refs"][0]
    data["relative_path"] = path
    with pytest.raises(ValidationError):
        EvidenceRef.model_validate(data)


@pytest.mark.parametrize("line", [0, -1, True, 1.5])
def test_code_lines_are_positive_integers(line: object) -> None:
    data = load_case()["bundle"]["findings"][0]["code_locations"][0]
    data["line"] = line
    with pytest.raises(ValidationError):
        CodeLocation.model_validate(data)


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_duration_cannot_be_negative_or_nonfinite(value: float) -> None:
    data = load_case()["bundle"]["experiments"][0]["observations"][0]["sql_calls"][0]
    data["duration_ms"] = value
    with pytest.raises(ValidationError):
        SqlCall.model_validate(data)


def test_missing_metrics_are_null_not_zero() -> None:
    call = SqlCall(id="sql", normalized_sql="SELECT 1")
    assert call.duration_ms is None and call.rows_examined is None
    data = call.model_dump()
    data["rows_examined"] = 0
    with pytest.raises(ValidationError, match="actual metric source"):
        SqlCall.model_validate(data)


def test_estimated_rows_cannot_be_actual_rows() -> None:
    data = load_case()["bundle"]["experiments"][0]["observations"][0]["sql_calls"][0]
    data["metric_sources"]["rows_examined"]["measurement"] = "estimated"
    with pytest.raises(ValidationError, match="actual metric source"):
        SqlCall.model_validate(data)


def test_only_index_experiments_with_repetitions_supported() -> None:
    for field, value in (("variable", "offset"), ("repetitions", 1), ("levels", ["baseline"])):
        data = copy.deepcopy(load_case()["spec"])
        data[field] = value
        with pytest.raises(ValidationError):
            ExperimentSpec.model_validate(data)


def test_hypothesis_batch_at_most_three() -> None:
    item = load_case()["bundle"]["hypotheses"][0]
    with pytest.raises(ValidationError):
        HypothesisBatch.model_validate({"items": [item] * 4})


def test_status_200_requires_business_assertions_and_parameter_sources() -> None:
    data = load_case()["bundle"]["scenarios"][0]["steps"][0]
    invalid = copy.deepcopy(data)
    invalid["assertions"]["business"] = []
    with pytest.raises(ValidationError):
        RequestStep.model_validate(invalid)
    invalid = copy.deepcopy(data)
    invalid["parameter_sources"] = {}
    with pytest.raises(ValidationError):
        RequestStep.model_validate(invalid)


@pytest.mark.parametrize("path", ["https://example.com/", "//example.com/", "/a?secret=1", "/../a"])
def test_scenario_cannot_supply_external_request_url(path: str) -> None:
    data = load_case()["bundle"]["scenarios"][0]["steps"][0]
    data["relative_path"] = path
    with pytest.raises(ValidationError):
        RequestStep.model_validate(data)


def test_verified_finding_requires_location_and_references() -> None:
    data = load_case()["bundle"]["findings"][0]
    for field in ("code_locations", "sql_call_ids", "evidence_refs", "excluded_explanations"):
        invalid = copy.deepcopy(data)
        invalid[field] = []
        with pytest.raises(ValidationError):
            Finding.model_validate(invalid)


def test_recommendation_cannot_claim_unmeasured_gain() -> None:
    data = load_case()["bundle"]["findings"][0]["recommendation"]
    data["measured_gain_percent"] = 80
    with pytest.raises(ValidationError):
        Recommendation.model_validate(data)


def test_missing_agh_ids_must_be_explicit() -> None:
    with pytest.raises(ValidationError):
        CallContext(task_id="task", operation_id="op")
    context = CallContext(
        task_id="task",
        operation_id="op",
        missing_correlation=["agh_session_id", "tool_call_id"],
    )
    assert context.agh_session_id is None


def test_operation_union_has_discriminator() -> None:
    result = OperationResult.model_validate(
        {
            "operation_id": "op",
            "state": "completed",
            "input_digest": "a" * 64,
            "payload": load_case()["bundle"]["experiments"][0],
        }
    )
    assert result.payload is not None
    assert result.payload.result_type == "experiment"
    invalid = result.model_dump()
    invalid["payload"]["result_type"] = "guessed"
    with pytest.raises(ValidationError):
        OperationResult.model_validate(invalid)


def test_unresolved_operation_blocks_environment() -> None:
    with pytest.raises(ValidationError):
        ReconcileResult(
            task_id="task",
            environment_health="available",
            unresolved_operations=["op"],
        )


def test_restore_reserve_is_within_budget() -> None:
    data = load_case()["spec"]["limits"]
    data["restore_reserve_seconds"] = data["max_wall_seconds"]
    with pytest.raises(ValidationError):
        Limits.model_validate(data)


def test_settings_roots_and_network_are_explicit(tmp_path: Path) -> None:
    data = {
        "platform_dsn_ref": "env:PROJECT_DOCTOR_PLATFORM_DSN",
        "model_config_ref": "file:agh/config.local.json",
        "artifact_root": tmp_path / "artifacts",
        "workspace_root": tmp_path / "isolated",
        "target_repo_root": tmp_path / "target",
        "allowed_target_network": "172.28.0.0/24",
        "tool_timeouts": {"run_experiment": 120},
    }
    assert Settings.model_validate(data).artifact_root == tmp_path / "artifacts"
    for field, value in (
        ("workspace_root", tmp_path / "target" / "runtime"),
        ("allowed_target_network", "0.0.0.0/0"),
        ("tool_timeouts", {"run_experiment": float("inf")}),
    ):
        invalid = data | {field: value}
        with pytest.raises(ValidationError):
            Settings.model_validate(invalid)


def test_example_settings_and_tool_policy_agree() -> None:
    root = Path(__file__).resolve().parents[2]
    settings = Settings.model_validate_json(
        (root / "config/settings.example.json").read_text(encoding="utf-8")
    )
    policy = json.loads((root / "agh/tool-policy.json").read_text(encoding="utf-8"))
    assert policy["status"] == "declared_not_integrated"
    assert settings.tool_timeouts == {
        name: tool["timeout_seconds"] for name, tool in policy["tools"].items()
    }
