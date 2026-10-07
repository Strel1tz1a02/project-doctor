#!/usr/bin/env python3
"""白盒层「步骤级」评估器单元测试（纯标准库 unittest）。

覆盖 ``steps.py``（确定性单步 / 轨迹评估）、与 ``trace_adapter.py`` 三来源归一化的
端到端打通，以及 ``fixtures/steps/*.json`` 步骤样例的确定性断言。

设计红线（D1–D6）在此被固化为测试：
- **D1/D2**：只消费执行侧产出的步骤记录，做归一化 + 打分，不调用任何工具 / SUT；
- **D3**：只用确定性规则，不依赖逐步骤正解；
- **D4**：步骤分只作评分项 / 归因，不进入用例级 ``group_scores`` / ``total_score`` 与硬闸门；
- **D6**：以 8 个 MCP 工具为准，由工具名推导 5 个诊断阶段。

运行：

    python evaluation/test_steps.py
    python -m unittest discover -s evaluation -p "test_*.py"
"""

from __future__ import annotations

import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract as C  # noqa: E402
import scores as S  # noqa: E402
import steps as ST  # noqa: E402
import trace_adapter as TA  # noqa: E402
from contract import DIAGNOSTIC_PHASES, StepTrace, TraceStep  # noqa: E402

FIXTURES = os.path.join(_HERE, "fixtures", "steps")
RUN_BUNDLES = os.path.join(_HERE, "fixtures", "run-bundle")


# --------------------------------------------------------------------------- #
# 夹具
# --------------------------------------------------------------------------- #

def load_steps_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_run_bundle(name: str) -> dict:
    with open(os.path.join(RUN_BUNDLES, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


def step(
    index: int = 0,
    *,
    tool: str = "",
    phase: str = "",
    status: str = "ok",
    input=None,
    output=None,
    latency_ms=None,
    tokens=None,
    ts_start=None,
    ts_end=None,
    step_type: str = "",
) -> TraceStep:
    """构造一个 ``TraceStep`` 的便捷工厂。"""
    return TraceStep(
        index=index, step_type=step_type, phase=phase, status=status, tool=tool,
        input=input, output=output, ts_start=ts_start, ts_end=ts_end,
        latency_ms=latency_ms, cost=C.StepCost(tokens=tokens),
    )


# --------------------------------------------------------------------------- #
# 注册表一致性
# --------------------------------------------------------------------------- #

class StepRegistryTest(unittest.TestCase):
    def test_eight_mcp_tools_fully_mapped(self):
        """D6：8 工具与 5 阶段一一可推导。"""
        self.assertEqual(len(ST.MCP_TOOLS), 8)
        self.assertEqual(set(ST.TOOL_PHASE), set(ST.MCP_TOOLS))
        self.assertTrue(all(p in DIAGNOSTIC_PHASES for p in ST.TOOL_PHASE.values()))

    def test_step_rules_match_registry(self):
        self.assertEqual(len(ST.STEP_RULES), 7)
        self.assertEqual(set(ST.STEP_RULES), set(S.STEP_METRICS))
        self.assertTrue(
            all(S.METRIC_DEFINITIONS[n].group == "step" for n in ST.STEP_RULES))

    def test_phase_for_unknown_tool_is_empty(self):
        self.assertEqual(ST.phase_for("not_a_tool"), "")
        self.assertEqual(ST.phase_for("run_experiment"), "discriminating_experiment")


# --------------------------------------------------------------------------- #
# 单步评估 evaluate_step
# --------------------------------------------------------------------------- #

class EvaluateStepTest(unittest.TestCase):
    def test_ok_step_scores_one(self):
        row = ST.evaluate_step(step(0, tool="create_task", input={"task": "x"}))
        self.assertEqual(row["score"], 1.0)
        self.assertTrue(row["tool_argument_valid"])
        self.assertFalse(row["retry"])
        self.assertEqual(row["phase"], "baseline")
        self.assertEqual(row["checks"], [])

    def test_error_step_scores_zero_and_flagged(self):
        row = ST.evaluate_step(
            step(0, tool="run_experiment", status="error", input={"hypothesis": "h"}))
        self.assertEqual(row["score"], 0.0)
        self.assertTrue(row["checks"])

    def test_skipped_step_scores_half(self):
        row = ST.evaluate_step(step(0, status="skipped"))
        self.assertEqual(row["score"], 0.5)

    def test_missing_required_argument_zeros_score(self):
        row = ST.evaluate_step(step(0, tool="run_experiment", input={}))
        self.assertIs(row["tool_argument_valid"], False)
        self.assertEqual(row["score"], 0.0)
        self.assertTrue(any("参数" in c for c in row["checks"]))

    def test_argument_alias_accepted(self):
        # hypothesis / cause / root_cause 视为同一语义字段。
        for key in ("hypothesis", "cause", "root_cause"):
            row = ST.evaluate_step(step(0, tool="run_experiment", input={key: "h"}))
            self.assertIs(row["tool_argument_valid"], True, key)

    def test_empty_string_argument_counts_missing(self):
        row = ST.evaluate_step(step(0, tool="create_task", input={"task": ""}))
        self.assertIs(row["tool_argument_valid"], False)

    def test_unknown_tool_argument_not_judged(self):
        row = ST.evaluate_step(step(0, tool="custom_model", input={}))
        self.assertIsNone(row["tool_argument_valid"])
        self.assertEqual(row["score"], 1.0)

    def test_latency_over_budget_decays(self):
        row = ST.evaluate_step(
            step(0, tool="create_task", input={"task": "x"}, latency_ms=30_000.0))
        self.assertEqual(row["latency_score"], 0.5)

    def test_tokens_over_budget_decays(self):
        row = ST.evaluate_step(
            step(0, tool="create_task", input={"task": "x"}, tokens=16_000))
        self.assertEqual(row["tokens_score"], 0.5)

    def test_latency_derived_from_timestamps(self):
        row = ST.evaluate_step(
            step(0, tool="create_task", input={"task": "x"},
                 ts_start=1000.0, ts_end=1003.0))
        self.assertEqual(row["latency_ms"], 3000.0)

    def test_retry_detected_on_identical_adjacent_step(self):
        prev = step(0, tool="discover_scenarios", input={"task": "x"})
        cur = step(1, tool="discover_scenarios", input={"task": "x"})
        self.assertTrue(ST.evaluate_step(cur, prev=prev)["retry"])

    def test_not_retry_when_input_or_tool_differs(self):
        prev = step(0, tool="discover_scenarios", input={"task": "x"})
        self.assertFalse(ST.evaluate_step(
            step(1, tool="discover_scenarios", input={"task": "y"}), prev=prev)["retry"])
        self.assertFalse(ST.evaluate_step(
            step(1, tool="propose_hypotheses", input={"task": "x"}), prev=prev)["retry"])


# --------------------------------------------------------------------------- #
# 7 项确定性规则
# --------------------------------------------------------------------------- #

class StepRulesTest(unittest.TestCase):
    B = ST.DEFAULT_STEP_BUDGET

    def test_status_ok_rule(self):
        self.assertTrue(ST.STEP_RULES["step_status_ok"]([step()], self.B))
        self.assertFalse(ST.STEP_RULES["step_status_ok"]([step(status="error")], self.B))

    def test_tool_argument_rule(self):
        self.assertTrue(ST.STEP_RULES["step_tool_argument_valid"](
            [step(tool="create_task", input={"task": "x"})], self.B))
        self.assertFalse(ST.STEP_RULES["step_tool_argument_valid"](
            [step(tool="create_task", input={})], self.B))

    def test_phase_coverage_rule(self):
        steps = [step(0, phase="baseline"), step(1, phase="hypotheses"),
                 step(2, phase="localization")]
        self.assertEqual(
            ST.STEP_RULES["step_phase_coverage"](steps, self.B), 0.6)

    def test_retry_count_rule(self):
        steps = [step(0, tool="run_experiment", input={"hypothesis": "h"}),
                 step(1, tool="run_experiment", input={"hypothesis": "h"}),
                 step(2, tool="run_experiment", input={"hypothesis": "h"})]
        self.assertEqual(ST.STEP_RULES["step_retry_count"](steps, self.B), 2)

    def test_latency_and_tokens_rules(self):
        steps = [step(0, latency_ms=10.0, tokens=5),
                 step(1, latency_ms=20.5, tokens=7)]
        self.assertEqual(ST.STEP_RULES["step_latency_ms"](steps, self.B), 30.5)
        self.assertEqual(ST.STEP_RULES["step_tokens"](steps, self.B), 12)

    def test_downgrade_correctness_true(self):
        steps = [
            step(0, tool="evaluate_evidence", input={"hypothesis": "h"},
                 output={"insufficient_evidence": True}),
            step(1, tool="finish_task", input={"report": {}}, output={"decision": "lead"}),
        ]
        self.assertIs(
            ST.STEP_RULES["step_downgrade_correctness"](steps, self.B), True)

    def test_downgrade_correctness_false_when_verified(self):
        steps = [
            step(0, tool="evaluate_evidence", input={"hypothesis": "h"},
                 output={"insufficient_evidence": True}),
            step(1, tool="finish_task", input={"report": {}},
                 output={"decision": "verified"}),
        ]
        self.assertIs(
            ST.STEP_RULES["step_downgrade_correctness"](steps, self.B), False)

    def test_downgrade_correctness_none_paths(self):
        rule = ST.STEP_RULES["step_downgrade_correctness"]
        # 无 evaluate_evidence 步骤 → 不可判定
        self.assertIsNone(rule([step(0, tool="create_task", input={"task": "x"})], self.B))
        # 证据充足 → 本项不判定
        self.assertIsNone(rule([step(
            0, tool="evaluate_evidence", input={"hypothesis": "h"},
            output={"evidence_sufficient": True})], self.B))
        # 证据不足但没有最终结论 → 不可判定
        self.assertIsNone(rule([step(
            0, tool="evaluate_evidence", input={"hypothesis": "h"},
            output={"insufficient_evidence": True})], self.B))


# --------------------------------------------------------------------------- #
# 轨迹级评估 evaluate_trace
# --------------------------------------------------------------------------- #

class EvaluateTraceTest(unittest.TestCase):
    def test_clean_fixture_exact_aggregates(self):
        trace = StepTrace.from_obj(
            load_steps_fixture("case-01-slow-query-fullscan.json"))
        result = ST.evaluate_trace(trace)
        self.assertTrue(result.has_steps)
        self.assertEqual(result.case_id, "case-01-slow-query-fullscan")
        self.assertEqual(len(result.steps), 8)

        s = result.summary
        self.assertIs(s["step_status_ok"], True)
        self.assertIs(s["step_tool_argument_valid"], True)
        self.assertEqual(s["step_phase_coverage"], 1.0)
        self.assertEqual(s["step_retry_count"], 0)
        self.assertEqual(s["step_latency_ms"], 9520.0)
        self.assertEqual(s["step_tokens"], 3500)
        # 证据充足 → 降级正确性不判定
        self.assertNotIn("step_downgrade_correctness", s)
        self.assertEqual([p["phase"] for p in result.phases], list(DIAGNOSTIC_PHASES))
        self.assertTrue(all(p["status_ok"] for p in result.phases))

    def test_composite_fixture_aggregates(self):
        trace = StepTrace.from_obj(
            load_steps_fixture("case-02-slow-query-composite.json"))
        result = ST.evaluate_trace(trace)
        self.assertEqual(len(result.steps), 8)

        s = result.summary
        self.assertIs(s["step_status_ok"], True)      # skipped 不算 error
        self.assertEqual(s["step_retry_count"], 1)
        self.assertEqual(s["step_latency_ms"], 44015.0)
        self.assertEqual(s["step_tokens"], 8270)
        self.assertIs(s["step_downgrade_correctness"], True)
        # 超预算单步（40000ms > 15000ms）→ 延迟按预算衰减
        self.assertEqual(result.steps[4]["latency_score"], 0.375)
        # skipped 步 → 0.5；重试步被标记
        self.assertEqual(result.steps[6]["score"], 0.5)
        self.assertTrue(result.steps[3]["retry"])

    def test_phase_normalised_from_tool_names(self):
        steps = [step(0, tool="create_task", input={"task": "x"}),
                 step(1, tool="run_experiment", input={"hypothesis": "h"}),
                 step(2, tool="finish_task", input={"report": {}})]
        result = ST.evaluate_trace(steps)
        self.assertEqual(result.steps[0]["phase"], "baseline")
        self.assertEqual(result.steps[1]["phase"], "discriminating_experiment")
        self.assertEqual(result.steps[2]["phase"], "verification")
        self.assertEqual(result.summary["step_phase_coverage"], 0.6)  # 3 / 5

    def test_accepts_mapping_sequence_and_steptrace(self):
        payload = {"case_id": "c1",
                   "steps": [{"tool": "create_task", "input": {"task": "x"},
                              "status": "ok"}]}
        self.assertEqual(ST.evaluate_trace(payload).case_id, "c1")
        self.assertTrue(ST.evaluate_trace(
            [step(tool="create_task", input={"task": "x"})]).has_steps)
        self.assertTrue(ST.evaluate_trace(StepTrace(steps=(step(),))).has_steps)

    def test_empty_and_none_are_tolerated(self):
        for empty in (None, [], StepTrace()):
            self.assertFalse(ST.evaluate_trace(empty).has_steps)

    def test_bad_input_raises_type_error(self):
        for bad in ("steps", 42, object()):
            with self.assertRaises(TypeError):
                ST.evaluate_trace(bad)


# --------------------------------------------------------------------------- #
# Score 产出（scope=STEP）
# --------------------------------------------------------------------------- #

class StepScoresTest(unittest.TestCase):
    def _result(self):
        return ST.evaluate_trace(StepTrace.from_obj(
            load_steps_fixture("case-01-slow-query-fullscan.json")))

    def test_scores_are_step_scoped(self):
        scores = ST.step_scores(self._result())
        self.assertTrue(scores)
        self.assertTrue(all(sc.scope is S.ScoreScope.STEP for sc in scores))

    def test_per_step_scores_carry_index_and_metadata(self):
        per_step = [sc for sc in ST.step_scores(self._result())
                    if sc.name == "step_score"]
        self.assertEqual(len(per_step), 8)
        for sc in per_step:
            self.assertIn("step_index", sc.metadata)
            self.assertIn("phase", sc.metadata)
            self.assertIn("tool", sc.metadata)
            self.assertEqual(sc.metadata["scope_id"], "case-01-slow-query-fullscan")

    def test_summary_metrics_emitted(self):
        names = {sc.name for sc in ST.step_scores(self._result())}
        self.assertIn("step_phase_coverage", names)
        self.assertIn("step_score", names)

    def test_latency_and_tokens_only_when_recorded(self):
        scores = ST.step_scores(self._result())
        latency = [sc for sc in scores if sc.name == "step_latency_ms"]
        tokens = [sc for sc in scores if sc.name == "step_tokens"]
        # 轨迹级各 1 条 + 每步各 1 条（未记录 latency/token 的步不产出）
        self.assertEqual(len(latency), 1 + 8)
        self.assertEqual(len(tokens), 1 + 3)

    def test_score_serialises_with_langfuse_keys(self):
        sc = [s for s in ST.step_scores(self._result())
              if s.name == "step_score"][0]
        payload = sc.to_dict()
        self.assertEqual(payload["scope"], "STEP")
        self.assertEqual(payload["dataType"], "NUMERIC")
        self.assertEqual(S.Score.from_dict(payload), sc)

    def test_empty_result_yields_no_scores(self):
        self.assertEqual(ST.step_scores(ST.evaluate_trace(None)), [])


# --------------------------------------------------------------------------- #
# D4：步骤级指标只作归因，不进入用例级聚合
# --------------------------------------------------------------------------- #

class StepScoringBoundaryTest(unittest.TestCase):
    def test_step_metrics_are_not_normalised(self):
        for name in S.STEP_METRICS:
            definition = S.METRIC_DEFINITIONS[name]
            sample = (True if definition.data_type is S.DataType.BOOLEAN else 1.0)
            self.assertIsNone(S.metric_score(name, sample), name)

    def test_step_group_absent_from_group_scores(self):
        groups = S.group_scores({
            "step_status_ok": True, "step_phase_coverage": 1.0,
            "root_cause_recall": 1.0, "decision_match": "exact",
        })
        self.assertNotIn("step", groups)
        self.assertIn("conclusion", groups)


# --------------------------------------------------------------------------- #
# trace_adapter 三来源归一化 → steps 端到端打通
# --------------------------------------------------------------------------- #

class TraceAdapterIntegrationTest(unittest.TestCase):
    def test_run_bundle_nested_trajectory(self):
        bundle = {
            "trajectory": {"steps": [
                {"tool": "create_task", "input": {"task": "t"}, "status": "ok"},
                {"tool": "evaluate_evidence", "input": {"hypothesis": "h"},
                 "status": "ok", "output": {"insufficient_evidence": True}},
                {"tool": "finish_task", "input": {"report": {}}, "status": "ok",
                 "output": {"decision": "lead"}},
            ]},
            "collection": {"case_id": "case-xx"},
        }
        trace = TA.FromRunBundle.normalize(bundle)
        self.assertEqual(trace.source, "run-bundle")
        self.assertEqual(trace.case_id, "case-xx")
        result = ST.evaluate_trace(trace)
        self.assertEqual(len(result.steps), 3)
        self.assertIs(result.summary["step_downgrade_correctness"], True)

    def test_interface_operations_normalised(self):
        record = {
            "task_id": "t-1",
            "operations": [
                {"tool_name": "discover_scenarios", "arguments": {"task": "t"},
                 "result": {"scenarios": [1]}, "status": "success"},
                {"name": "propose_hypotheses", "args": {"observations": []},
                 "status": "failed"},
            ],
        }
        trace = TA.FromInterface.normalize(record)
        self.assertEqual(trace.source, "interface")
        self.assertEqual(trace.steps[0].status, "ok")     # success → ok
        self.assertEqual(trace.steps[0].phase, "hypotheses")
        self.assertEqual(trace.steps[1].status, "error")  # failed → error
        self.assertIs(ST.evaluate_trace(trace).summary["step_status_ok"], False)

    def test_langfuse_observations_normalised(self):
        langfuse = {
            "id": "trace-1", "name": "case-01",
            "observations": [
                {"id": "o1", "name": "run_experiment", "type": "SPAN",
                 "startTime": "2026-10-06T12:00:00Z",
                 "endTime": "2026-10-06T12:00:05Z",
                 "input": {"hypothesis": "h"}, "usage": {"input": 100, "output": 200}},
                {"id": "o2", "name": "evaluate_evidence", "type": "SPAN",
                 "startTime": "2026-10-06T12:00:05Z",
                 "endTime": "2026-10-06T12:00:06Z",
                 "metadata": {"phase": "localization"}, "level": "ERROR",
                 "statusMessage": "boom"},
            ],
        }
        trace = TA.FromLangfuse.normalize(langfuse)
        self.assertEqual(trace.source, "langfuse")
        self.assertEqual(trace.run_id, "trace-1")
        self.assertEqual(trace.steps[0].latency_ms, 5000.0)
        self.assertEqual(trace.steps[0].cost.tokens, 300)
        self.assertEqual(trace.steps[1].status, "error")
        self.assertEqual(trace.steps[1].phase, "localization")

    def test_auto_discrimination(self):
        self.assertEqual(TA.normalize({"observations": []}).source, "langfuse")
        self.assertEqual(TA.normalize({"operations": []}).source, "interface")
        self.assertEqual(TA.normalize({"steps": []}).source, "run-bundle")
        with self.assertRaises(ValueError):
            TA.normalize({}, source="nope")

    def test_fixture_via_adapter_matches_direct_eval(self):
        payload = load_steps_fixture("case-01-slow-query-fullscan.json")
        bundle = {"trajectory": payload, "collection": {"case_id": payload["case_id"]}}
        via_adapter = ST.evaluate_trace(TA.FromRunBundle.normalize(bundle))
        direct = ST.evaluate_trace(StepTrace.from_obj(payload))
        self.assertEqual(via_adapter.summary, direct.summary)


# --------------------------------------------------------------------------- #
# 向后兼容：既有运行包（无 steps）不受影响
# --------------------------------------------------------------------------- #

class BackwardCompatTest(unittest.TestCase):
    def test_legacy_run_bundle_without_steps_has_no_step_layer(self):
        bundle = load_run_bundle("case-01-slow-query-fullscan.json")
        trace = TA.FromRunBundle.normalize(bundle)
        self.assertEqual(trace.steps, ())
        self.assertFalse(ST.evaluate_trace(trace).has_steps)


if __name__ == "__main__":
    unittest.main(verbosity=2)
