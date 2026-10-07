#!/usr/bin/env python3
"""本轮追加交付物的回归测试：用例扩充（8→14）+ 阶段三/四 + D5 部署就绪。

覆盖范围（对应《步骤级评价与Langfuse接入-交接说明》§11「追加轮次」）：

- **数据集扩容**：``case-09`` ~ ``case-14`` 六个新用例目录齐备，且全部通过 schema 校验；
- **步骤 fixture 覆盖**：14 个用例均具备运行包 + 步骤轨迹；用步骤 fixture 富化报告
  只新增步骤层字段，**不改动** ``passed``（D4）；
- **阶段三 只读接口**（``interface_source``）：取数计划只读、越界方法被拒、本地导出归一化；
- **D5 部署就绪**（``langfuse_deploy``）：有序部署请求计划（dataset→ingestion→item→run_item）、
  端点白名单、金标准不泄漏；
- **阶段四 模型评分**（``model_judge``）：评审请求计划 / 响应解析 / 步骤分数映射，
  且**字符串内容**里的金标准也会被拦截（键级之外的第二道网）；
- **FROZEN 清单**：本轮新增模块已纳入冻结。

仅读取离线 fixture，**零网络、零 SUT 调用**。运行：

    python evaluation/test_followups.py
    python -m unittest discover -s evaluation -p "test_*.py"
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_TOOLS = _HERE.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import langfuse_deploy as D  # noqa: E402
import model_judge as J  # noqa: E402
import interface_source as I  # noqa: E402
import step_fixtures as F  # noqa: E402
import run_eval as R  # noqa: E402
import validate_cases as V  # noqa: E402
from scores import ScoreScope, ScoreSource  # noqa: E402

_ROOT = _HERE.parent  # 数据集根 project-doctor/datasets/
_STEPS_DIR = _HERE / "fixtures" / "steps"
_RUN_BUNDLE_DIR = _HERE / "fixtures" / "run-bundle"

EXPECTED_CASE_COUNT = 14
NEW_CASE_IDS = (
    "case-09-connection-pool-leak",
    "case-10-large-response-unbounded",
    "case-11-connection-setup-per-request",
    "case-12-excessive-logging-sync-debug",
    "case-13-thread-pool-no-verifiable-defect",
    "case-14-config-regression-pool-size",
)


def _case_dirs() -> list[Path]:
    return sorted(
        path.parent
        for path in _ROOT.glob("*/case.json")
        if not V.is_reserved_name(path.parent.name)
    )


class DatasetExpansionTest(unittest.TestCase):
    """数据集由 8 例扩充到 14 例：目录齐备 + schema 全绿。"""

    def test_fourteen_cases_on_disk(self):
        dirs = _case_dirs()
        self.assertEqual(len(dirs), EXPECTED_CASE_COUNT, [d.name for d in dirs])

    def test_six_new_cases_present(self):
        names = {d.name for d in _case_dirs()}
        for case_id in NEW_CASE_IDS:
            self.assertIn(case_id, names)
            # 数据单元约定：case.json + README.md + project/
            unit = _ROOT / case_id
            self.assertTrue((unit / "case.json").is_file(), case_id)
            self.assertTrue((unit / "README.md").is_file(), case_id)
            self.assertTrue((unit / "project").is_dir(), case_id)

    def test_all_cases_pass_schema(self):
        schema = V.load_schema(V.DEFAULT_SCHEMA_PATH)
        targets = V.discover_cases()
        self.assertEqual(len(targets), EXPECTED_CASE_COUNT)
        for case_path in targets:
            errors = V.validate_file(case_path, schema)
            self.assertEqual(errors, [], f"{case_path}: {errors}")


class StepFixtureCoverageTest(unittest.TestCase):
    """步骤 fixture 覆盖全部用例，且富化报告不改动通过判定（D4）。"""

    def test_both_fixture_sets_cover_all_cases(self):
        self.assertEqual(len(F.load_step_fixtures(str(_STEPS_DIR))), EXPECTED_CASE_COUNT)
        bundles = sorted(_RUN_BUNDLE_DIR.glob("*.json"))
        self.assertEqual(len(bundles), EXPECTED_CASE_COUNT)

    def test_enrich_report_adds_steps_without_changing_verdict(self):
        ids = sorted(F.load_step_fixtures(str(_STEPS_DIR)))
        report = {
            "manifest": {"generated_at": "2026-10-02T08:00:00Z"},
            "cases": [
                {"case_id": cid, "passed": True, "total_score": 1.0, "scores": []}
                for cid in ids
            ],
        }
        enriched = F.enrich_report(report, steps_root=str(_STEPS_DIR))
        for case in enriched["cases"]:
            self.assertTrue(case["steps"], case["case_id"])
            self.assertIn("step_summary", case)
            self.assertTrue(case["passed"])  # D4：判定不变
            step_scores = [
                s for s in case["scores"]
                if (s.get("metadata") or {}).get("group") == "step"
            ]
            self.assertTrue(step_scores, case["case_id"])
        # 入参报告未被就地修改（深拷贝语义）。
        self.assertNotIn("steps", report["cases"][0])

    def test_merge_bundle_does_not_mutate_input(self):
        fixture = F.load_step_fixture("case-01-slow-query-fullscan", _STEPS_DIR)
        bundle = {"trajectory": {"required_steps_done": True}}
        merged = F.merge_bundle(bundle, fixture)
        self.assertNotIn("steps", bundle["trajectory"])  # 原包未被改动
        self.assertTrue(merged["trajectory"]["steps"])
        self.assertTrue(merged["trajectory"]["required_steps_done"])  # 既有字段保留


class ReadOnlyInterfaceTest(unittest.TestCase):
    """阶段三：在线只读接口的计划与本地归一化。"""

    def test_plan_is_read_only_and_sequential(self):
        plan = I.build_plan(["case-01-slow-query-fullscan", "case-02-slow-query-composite"])
        self.assertTrue(all(r.method == "GET" for r in plan.requests))
        self.assertTrue(all(r.endpoint.startswith(I.READONLY_PREFIXES)
                            for r in plan.requests))
        self.assertEqual([r.seq for r in plan.requests], [1, 2, 3, 4, 5, 6])
        self.assertEqual(plan.counts()["total"], 6)

    def test_write_method_is_rejected(self):
        leaked = I.InterfacePlan(requests=[I.ReadOnlyRequest(
            seq=1, kind="task", endpoint="/api/read/tasks/x", method="POST")])
        with self.assertRaises(ValueError):
            I.assert_read_only(leaked)

    def test_normalize_export_roundtrips_to_fixture(self):
        doc = json.loads((_STEPS_DIR / "case-01-slow-query-fullscan.json").read_text(encoding="utf-8"))
        trace = I.normalize_export(doc, case_id="case-01-slow-query-fullscan")
        self.assertTrue(trace.steps)
        fixture = I.to_fixture(trace)
        self.assertIn("steps", fixture)
        self.assertEqual(len(fixture["steps"]), len(trace.steps))
        # 归一化结果可与步骤评估器打通。
        result = I.A.normalize(doc, case_id="case-01-slow-query-fullscan")
        self.assertEqual(len(result.steps), len(trace.steps))


class LangfuseDeployPlanTest(unittest.TestCase):
    """D5 部署就绪：有序、白名单、不泄漏金标准。"""

    def test_kind_order_and_counts_for_real_cases(self):
        cases = D.load_cases(_ROOT)
        self.assertEqual(len(cases), EXPECTED_CASE_COUNT)
        plan = D.build_plan(D._sample_report(), cases, run_name="run-check",
                            generated_at="2026-10-02T08:00:00Z")
        order = plan.kinds_in_order()
        self.assertEqual(order[0], "dataset")
        self.assertEqual(order[1], "ingestion")
        counts = plan.counts()
        self.assertEqual(counts["total"], 2 + 2 * EXPECTED_CASE_COUNT)
        self.assertEqual(counts["dataset_item"], EXPECTED_CASE_COUNT)
        self.assertEqual(counts["dataset_run_item"], EXPECTED_CASE_COUNT)

    def test_endpoints_stay_in_whitelist(self):
        plan = D.build_plan(D._sample_report(), D.load_cases(_ROOT), run_name="run-check",
                            generated_at="2026-10-02T08:00:00Z")
        allowed = set(D.ENDPOINTS.values())
        self.assertTrue(all(r.endpoint in allowed for r in plan.requests))

    def test_dataset_item_inputs_carry_no_golden(self):
        plan = D.build_plan(D._sample_report(), D.load_cases(_ROOT), run_name="run-check",
                            generated_at="2026-10-02T08:00:00Z")
        blob = json.dumps([r.body for r in plan.requests], ensure_ascii=False)
        for key in D.FORBIDDEN_GOLDEN_KEYS:
            self.assertNotIn(f'"{key}"', blob)


class ModelJudgeTest(unittest.TestCase):
    """阶段四：主观步骤模型评分的计划 / 解析 / 映射与金标准红线。"""

    def test_request_counts_and_targets(self):
        report = J._sample_report()
        plan = J.build_judge_plan(report, run_name="run-check", enrich_steps=False,
                                  generated_at="2026-10-02T08:00:00Z")
        counts = plan.counts()
        self.assertEqual(counts["total"], 5)
        self.assertEqual(counts["by_criterion"],
                         {"hypothesis_quality": 2, "evidence_grounding": 2,
                          "report_readability": 1})
        self.assertTrue(all(r.method == "POST" for r in plan.requests))

    def test_response_parsing_clamp_and_bool(self):
        crit_num = J.SUBJECTIVE_CRITERIA[0]
        crit_bool = J.SUBJECTIVE_CRITERIA[1]
        self.assertEqual(J.parse_judge_response(crit_num, {"score": 0.7}), 0.7)
        self.assertEqual(J.parse_judge_response(crit_num, {"score": 2.0}), 1.0)
        self.assertEqual(J.parse_judge_response(crit_num, {"score": -1.0}), 0.0)
        self.assertIs(J.parse_judge_response(crit_bool, {"score": "true"}), True)
        with self.assertRaises(ValueError):
            J.parse_judge_response(crit_num, {"score": "abc"})

    def test_scores_map_to_step_scope_eval(self):
        plan = J.build_judge_plan(J._sample_report(), run_name="run-check",
                                  enrich_steps=False, generated_at="2026-10-02T08:00:00Z")
        responses = {r.request_id: {"score": 0.5, "rationale": "ok"} for r in plan.requests}
        scores = J.judge_scores(plan, responses)
        self.assertEqual(len(scores), 5)
        self.assertTrue(all(s.scope is ScoreScope.STEP for s in scores))
        self.assertTrue(all(s.source is ScoreSource.EVAL for s in scores))
        self.assertTrue(all(s.metadata["group"] == "step" for s in scores))

    def test_golden_leak_in_message_content_is_rejected(self):
        forbidden = frozenset(D.FORBIDDEN_GOLDEN_KEYS)
        # 1) 字符串值内的金标准整词会被拦截（键级之外的第二道网）。
        self.assertTrue(J._find_forbidden_tokens(
            {"content": "the ground_truth says verified"}, forbidden))
        leaked = J.JudgePlan(run_name="r", session_id="r", model="m",
                             endpoint=J.DEFAULT_JUDGE_ENDPOINT,
                             requests=[J.JudgeRequest(
                                 seq=1, request_id="x", criterion="hypothesis_quality",
                                 case_id="c", run_id="r", step_index=0, scope="STEP",
                                 target={}, endpoint=J.DEFAULT_JUDGE_ENDPOINT,
                                 body={"messages": [{"role": "user",
                                                     "content": "expected: verified"}]})])
        with self.assertRaises(ValueError):
            J._assert_no_golden_leak(leaked)
        # 2) 可观测字段里的 expected_latency_ms 不应误伤（整词边界）。
        self.assertEqual(J._find_forbidden_tokens({"x": "expected_latency_ms"}, forbidden), [])


class FrozenManifestTest(unittest.TestCase):
    """本轮新增模块已纳入冻结清单，且清单文件在盘上存在。"""

    def test_new_modules_are_frozen(self):
        frozen = set(R.FROZEN_RELATIVE)
        for rel in ("evaluation/langfuse_deploy.py",
                    "evaluation/step_fixtures.py",
                    "evaluation/langfuse_export.py",
                    "evaluation/interface_source.py",
                    "evaluation/model_judge.py",
                    "evaluation/test_followups.py"):
            self.assertIn(rel, frozen)

    def test_frozen_files_exist(self):
        for rel in R.FROZEN_RELATIVE:
            self.assertTrue((_ROOT / rel).is_file(), rel)


if __name__ == "__main__":
    unittest.main(verbosity=2)
