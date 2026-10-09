import asyncio
import json
from pathlib import Path

import pytest

from project_doctor.features.reports.build import build_report
from project_doctor.integrations.artifacts.publish import publish_artifact
from project_doctor.models.experiment import ExperimentSpec
from project_doctor.models.finding import ReportResult
from project_doctor.models.task import TaskBundle
from scripts.export_evaluation_run import attach_retest, export_run
from scripts.run_independent_retest import run


def test_retest_rejects_missing_docker_before_creating_task(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.run_independent_retest.shutil.which", lambda name: None)
    with pytest.raises(ValueError, match="Docker CLI unavailable"):
        asyncio.run(run(tmp_path / "source", tmp_path / "out", "test-image"))
    assert not (tmp_path / "out").exists()


@pytest.fixture
def bundle():
    path = Path(__file__).parents[1] / "contracts/fixtures/verified_slow_query.json"
    case = json.loads(path.read_text(encoding="utf-8"))
    result = TaskBundle.model_validate(case["bundle"])
    result.experiments[0].spec = ExperimentSpec.model_validate(case["spec"])
    return result


def make_home(path, bundle):
    path.mkdir()
    root = path / "artifacts"
    report = build_report(bundle)

    async def publish():
        refs = []
        for name, content, media in (
            ("report.json", report.json_content, "application/json"),
            ("report.html", report.html_content, "text/html"),
        ):
            refs.append(await publish_artifact(root, name, content.encode(), media, "report.v1"))
        return refs

    refs = asyncio.run(publish())
    result = ReportResult(
        task_id=bundle.task.id, task_status=bundle.task.status, json_ref=refs[0], html_ref=refs[1]
    )
    (path / "bundle.json").write_text(bundle.model_dump_json(), encoding="utf-8")
    (path / "finish_task-latest.json").write_text(result.model_dump_json(), encoding="utf-8")
    calls = [
        {"name": "finish_task", "args": [{"task_id": "another-task"}], "result": {}},
        {
            "name": "finish_task",
            "args": [{"task_id": bundle.task.id, "api_key": "must-not-export"}],
            "result": result.model_dump(mode="json"),
            "started_at": 100,
            "ended_at": 101,
        },
    ]
    (path / "business-tool-calls.jsonl").write_text(
        "\n".join(json.dumps(x) for x in calls), encoding="utf-8"
    )
    (path / "session.jsonl").write_text('{"seq":1,"type":"tool"}\n', encoding="utf-8")
    return path


def test_export_keeps_status_unknown_costs_and_actual_arguments(tmp_path, bundle):
    home = make_home(tmp_path / "home", bundle)
    result = export_run(home, "anonymous-case")
    assert result["report"]["findings"][0]["status"] == bundle.findings[0].status
    assert result["retest"]["performed"] is False
    assert "api_cost" in result["collection"]["missing_measurements"]
    assert len(result["trajectory"]["steps"]) == 1
    step = result["trajectory"]["steps"][0]
    assert step["input"]["context"]["task_id"] == bundle.task.id
    assert step["ts_end"] - step["ts_start"] == 1
    assert step["cost"]["tokens"] is None
    assert "must-not-export" not in json.dumps(result)
    # Missing fixture evidence never becomes all-true flags merely from verified status.
    assert not any(result["report"]["findings"][0]["evidence_flags"].values())


@pytest.mark.parametrize("status", ["verified", "lead", "unclassified"])
def test_completed_execution_does_not_imply_a_verified_diagnosis(tmp_path, bundle, status):
    bundle.task.status = "completed"
    for finding in bundle.findings:
        finding.status = status
        finding.limitations = ["本次不足以认定性能根因，结论受测量条件限制。"]
    result = export_run(make_home(tmp_path / "home", bundle), "anonymous-case")
    assert result["report"]["insufficient_evidence"] == (status != "verified")
    assert all(f["status"] == status for f in result["report"]["findings"])
    if status != "verified":
        assert "不足以认定性能根因" in result["report"]["reason"]


def test_corrupted_saved_report_cannot_be_exported(tmp_path, bundle):
    home = make_home(tmp_path / "home", bundle)
    (home / "artifacts/report.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="missing or corrupted"):
        export_run(home, "anonymous-case")


def test_retest_cannot_reuse_the_original_task(tmp_path, bundle):
    source = make_home(tmp_path / "source", bundle)
    (source / "retest-link.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="new task"):
        attach_retest(export_run(source, "case"), source, source, "case")


def test_retest_binding_rejects_changed_recipe_and_missing_artifacts(tmp_path, bundle):
    source = make_home(tmp_path / "source", bundle)
    repeated = bundle.model_copy(deep=True)
    repeated.task = repeated.task.model_copy(
        update={
            "id": "independent-task",
            "environment_id": "independent-environment",
            "correlation": repeated.task.correlation.model_copy(
                update={"task_id": "independent-task"}
            ),
        }
    )
    actual = repeated.experiments[0]
    assert actual.spec is not None
    actual.spec.task_id = repeated.task.id
    actual.spec.snapshot_id = "independent-snapshot"
    for observation in actual.observations + actual.warmup_results:
        observation.request_id += "-independent"
    for finding in repeated.findings:
        finding.task_id = repeated.task.id
    retest = make_home(tmp_path / "retest", repeated)
    original = bundle.experiments[0]
    assert original.spec is not None
    link = {
        "source_task_id": bundle.task.id,
        "source_experiment_id": original.experiment_id,
        "retest_task_id": repeated.task.id,
        "source_commit": bundle.task.project.commit,
        "recipe_ref": original.spec.intervention_recipe_ref,
        "source": "independent_platform_run_no_model",
    }
    (retest / "retest-link.json").write_text(json.dumps(link), encoding="utf-8")
    for path in (source, retest):
        (path / "settings.json").write_text(
            json.dumps({"workspace_root": str(path / "isolated")}), encoding="utf-8"
        )
        (path / "manifest.json").write_text('{"scenarios":[]}', encoding="utf-8")
    payload = export_run(source, "case")
    attach_retest(payload, source, retest, "case")
    assert payload["retest"]["performed"] is False
    assert payload["retest"]["improvement_percent"] is None
    assert payload["report"]["findings"][0]["status"] == bundle.findings[0].status
    actual.spec.intervention_recipe_ref = "changed-recipe"
    (retest / "bundle.json").write_text(repeated.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="changed the recorded experiment protocol"):
        attach_retest(export_run(source, "case"), source, retest, "case")


def test_end_to_end_wall_time_does_not_use_only_platform_usage(tmp_path, bundle):
    home = make_home(tmp_path / "home", bundle)
    elapsed = bundle.task.usage.wall_seconds + 100
    (home / "summary.json").write_text(
        json.dumps({"task": bundle.task.id, "model_elapsed_seconds": elapsed}), encoding="utf-8"
    )
    assert export_run(home, "case")["cost"]["wall_seconds"] == elapsed


def test_keyword_context_calls_are_not_dropped(tmp_path, bundle):
    home = make_home(tmp_path / "home", bundle)
    with (home / "business-tool-calls.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(
            "\n"
            + json.dumps(
                {
                    "name": "evaluate_evidence",
                    "args": [],
                    "kwargs": {
                        "context": {"task_id": bundle.task.id},
                        "hypothesis_ids": ["hypothesis-1"],
                        "experiment_ids": ["experiment-1"],
                    },
                    "result": [],
                    "started_at": 102,
                    "ended_at": 103,
                }
            )
        )
    steps = export_run(home, "case")["trajectory"]["steps"]
    assert len(steps) == 2
    assert steps[1]["input"]["context"]["task_id"] == bundle.task.id
