import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from project_doctor.features.reports.build import build_report
from project_doctor.integrations.artifacts.publish import publish_artifact
from project_doctor.models.common import EvidenceRef
from project_doctor.models.experiment import ExperimentSpec
from project_doctor.models.finding import ReportResult
from project_doctor.models.repair import RepairRecord
from project_doctor.models.task import TaskBundle
from project_doctor.workflows.repair_facts import build_repair_facts
from scripts.export_evaluation_run import export_run

ROOT = Path(__file__).parents[2]
TARGET = "src/main/java/com/example/slowquery/service/ArticleService.java"
AIMED_PATCH = (
    f"diff --git a/{TARGET} b/{TARGET}\n"
    f"--- a/{TARGET}\n"
    f"+++ b/{TARGET}\n"
    "@@ -29,2 +29,3 @@ public class ArticleService {\n"
    "         List<Article> articles = articleMapper.findRecent(size);\n"
    "+        List<Author> authors = authorMapper.findByIds(authorIds);\n"
    "         return articles;\n"
)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_bundle(status: str) -> TaskBundle:
    case = json.loads(
        (ROOT / "tests/contracts/fixtures/verified_slow_query.json").read_text(encoding="utf-8")
    )
    bundle = TaskBundle.model_validate(case["bundle"])
    bundle.experiments[0].spec = ExperimentSpec.model_validate(case["spec"])
    bundle.task.status = "completed"
    for finding in bundle.findings:
        finding.status = status
    return bundle


def make_home(path: Path, bundle: TaskBundle) -> Path:
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
    (path / "business-tool-calls.jsonl").write_text(
        json.dumps(
            {
                "name": "finish_task",
                "args": [{"task_id": bundle.task.id}],
                "result": result.model_dump(mode="json"),
                "started_at": 100,
                "ended_at": 101,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (path / "session.jsonl").write_text('{"seq":1,"type":"tool"}\n', encoding="utf-8")
    return path


def evidence(root: Path, name: str, content: str) -> EvidenceRef:
    (root / name).write_bytes(content.encode("utf-8"))
    return EvidenceRef(
        artifact_id=name.rsplit(".", 1)[0],
        relative_path=name,
        media_type="text/plain",
        format_version="patch.v1",
        sha256=sha(content),
        size_bytes=len(content.encode()),
    )


def image(tag: int) -> str:
    return "sha256:" + str(tag) * 64


def aimed_record(bundle: TaskBundle, root: Path) -> RepairRecord:
    return RepairRecord(
        id="repair-1",
        task_id=bundle.task.id,
        finding_id=bundle.findings[0].id,
        operation_id="op-1",
        attempt_id="attempt-1",
        status="built",
        source_commit=bundle.task.project.commit,
        patch_sha256=sha(AIMED_PATCH),
        source_sha256=sha("src"),
        baseline_source_sha256=sha("base"),
        workspace_name="ws",
        baseline_image_digest=image(1),
        patched_image_digest=image(2),
        patch_ref=evidence(root, "fix.patch", AIMED_PATCH),
        build_ref=evidence(root, "build.log", "BUILD OK"),
    )


def register(home: Path, bundle: TaskBundle, **kwargs) -> None:
    facts = build_repair_facts(
        bundle, artifacts_root=home / "artifacts", repair_session_id="repair-session", **kwargs
    )
    if facts.handoff is not None:
        (home / "handoff.json").write_text(json.dumps(facts.handoff), encoding="utf-8")
    if facts.repair is not None:
        (home / "repair.json").write_text(json.dumps(facts.repair), encoding="utf-8")


def case44_payload(tmp_path: Path) -> dict:
    bundle = load_bundle("verified")
    home = make_home(tmp_path / "home44", bundle)
    bundle.repairs = [aimed_record(bundle, home / "artifacts")]
    (home / "bundle.json").write_text(bundle.model_dump_json(), encoding="utf-8")
    register(home, bundle)
    return export_run(home, "case-44-n-plus-one-article-author")


def case46_payload(tmp_path: Path) -> dict:
    bundle = load_bundle("lead")
    home = make_home(tmp_path / "home46", bundle)
    transcript = tmp_path / "repair-session.jsonl"
    transcript.write_text('{"seq":1,"type":"tool"}\n', encoding="utf-8")
    register(
        home,
        bundle,
        repair_session_transcript=transcript,
        repair_decision_id="decision-1",
        finding_id=bundle.findings[0].id,
    )
    return export_run(home, "case-46-n-plus-one-out-of-bounds-stop")


def evaluate(runs: Path, out: Path) -> dict:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "datasets/evaluation/run_eval.py"),
            "--runs",
            str(runs),
            "--out",
            str(out),
            "--cases-root",
            str(ROOT / "datasets"),
            "--only-bundled",
        ],
        check=False,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode in (0, 1), completed.stdout + completed.stderr
    return json.loads((out / "report.json").read_text(encoding="utf-8"))


def scores(report: dict, case_id: str) -> dict:
    row = next(c for c in report["cases"] if c["case_id"] == case_id)
    return {
        "gates_failed": row["failed_gates"],
        **{s["name"]: s["value"] for s in row["scores"]},
    }


@pytest.fixture(scope="module")
def report(tmp_path_factory) -> dict:
    tmp_path = tmp_path_factory.mktemp("handoff-eval")
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "case-44-n-plus-one-article-author.json").write_text(
        json.dumps(case44_payload(tmp_path), ensure_ascii=False), encoding="utf-8"
    )
    (runs / "case-46-n-plus-one-out-of-bounds-stop.json").write_text(
        json.dumps(case46_payload(tmp_path), ensure_ascii=False), encoding="utf-8"
    )
    return evaluate(runs, tmp_path / "out")


def test_case44_handoff_and_repair_wiring(report):
    scores44 = scores(report, "case-44-n-plus-one-article-author")
    assert scores44["handoff_valid"] is True
    assert "handoff_valid" not in scores44["gates_failed"]
    assert scores44["repair_warranted"] is True
    assert scores44["repair_target_hit"] is True
    # 合成包未跑独立复测层：无实测收益 → 不归因、不计修复成功（诚实输出，非本计划缺口）。
    assert scores44["gain_attributable"] is False
    assert "repair_restraint" in scores44["gates_failed"]


def test_case46_restraint_with_valid_handoff(report):
    scores46 = scores(report, "case-46-n-plus-one-out-of-bounds-stop")
    assert scores46["handoff_valid"] is True
    assert "handoff_valid" not in scores46["gates_failed"]
    assert scores46["repair_warranted"] is True
    assert scores46["repair_target_hit"] is True
    assert scores46["repair_restraint"] is True
    assert scores46["gain_attributable"] is True


def test_synthetic_run_has_no_false_verified(report):
    # The zero must come from evaluating both cases, not from evaluating none.
    assert report["global"]["cases_evaluated"] == 2
    assert report["global"]["false_verified_count"] == 0


def test_tampered_handoff_fails_the_gate(tmp_path: Path):
    payload = case46_payload(tmp_path)
    payload["handoff"]["finding_from_this_run"] = False
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "case-46-n-plus-one-out-of-bounds-stop.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    row = scores(evaluate(runs, tmp_path / "out"), "case-46-n-plus-one-out-of-bounds-stop")
    assert row["handoff_valid"] is False
    assert "handoff_valid" in row["gates_failed"]
