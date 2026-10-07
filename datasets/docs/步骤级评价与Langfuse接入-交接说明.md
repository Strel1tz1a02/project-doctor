# 步骤级评价与 Langfuse 接入 — 交接说明

> 本文记录本轮「**步骤级评价 + Langfuse 接入**」的全部改动细节，供队内/交付交接使用。
>
> **工作边界（硬约束，务必保持）**：我方只负责 **Agent 评估方法 + 评估数据集**，是一个「**判卷机**」——
> 只读取结构化的**运行包（run bundle）**与**步骤记录**，**绝不调用、启动或干预被测系统（SUT）本身**。
> 本轮的步骤数据支持「离线记录」与「在线只读接口」两条来源路径，两条路径都**只读**。
>
> 配套设计稿：《步骤级评价与Langfuse接入方案.md》（本文为其落地实现的说明）。

---

## 0. 背景与决策确认（D1–D7）

本轮把原有「**按用例打分**」升级为「**按用例 + 按步骤打分**」。用户的 7 个决策点及落地结论：

| 编号 | 决策点 | 结论 | 落地位置 |
| --- | --- | --- | --- |
| D1 | 「调用对方函数接口」是否越界？ | **只读数据取回 OK**；调用诊断工具本身**不做** | `trace_adapter.py` 只做数据形状转换，零执行/零网络 |
| D2 | 谁负责埋点 / 产出 trace？ | **执行侧产出记录，我方只消费 + 打分** | `trace_adapter.py`（FromRunBundle / FromInterface / FromLangfuse） |
| D3 | 是否新增 `expected_steps`（步骤级金标准）？ | **先不加**；步骤分用**确定性规则**，不依赖逐步骤正解 | `steps.py` 的 `STEP_RULES`（7 条结构/一致性/预算规则） |
| D4 | 步骤分是否进硬闸门？ | **不进**；只作评分项 / 归因维度 | `scores.metric_score` 对 `group == "step"` 返回 `None`；`aggregate`/`render_markdown` 单列 |
| D5 | Langfuse 部署与凭证归属？ | **我方完成部署**（用户由原「队长指定 project」改为我方负责） | `langfuse_export.py` 产出摄入 JSON；`langfuse_deploy.py` 产出**有序部署请求计划 + 回放脚本**（追加轮次，见 §9/§11） |
| D6 | 步骤口径以 8 工具还是 5 诊断步为准？ | **以 8 工具为准**，上卷到 5 诊断阶段 | `steps.TOOL_PHASE` / `contract.DIAGNOSTIC_PHASES` |
| D7 | 数据量 / 裁剪策略？ | 步骤 `input`/`output` 允许摘要化，制品只存引用 | `StepTrace` 只承载可观测字段，不内联大对象 |

> 关键结论一句话：**步骤层是「加法」而非「改法」——它不改变任何通过判定与 golden 总分，只在报告里新增可下钻的归因维度。**

---

## 1. 改动总览（本轮新增 / 修改文件）

相对仓库基线（`git status`），本轮全部改动如下（工作根目录：`project-doctor/datasets/`）：

### 新增文件

| 文件 | 说明 |
| --- | --- |
| `evaluation/steps.py` | **白盒层确定性步骤评估器**：单步判定 + 7 项步骤指标 + 5 阶段上卷 |
| `evaluation/trace_adapter.py` | **步骤轨迹适配器**：三来源归一化为 `StepTrace`（纯标准库、零网络） |
| `evaluation/langfuse_export.py` | **Langfuse 摄入导出器**：报告/运行包 → Ingestion API 事件批次（离线） |
| `evaluation/test_steps.py` | 步骤层单测（43 项，覆盖上述三模块 + 契约 + 边界） |
| `evaluation/fixtures/steps/case-01-slow-query-fullscan.json` | 步骤轨迹样例：8 步全绿的「干净」轨迹 |
| `evaluation/fixtures/steps/case-02-slow-query-composite.json` | 步骤轨迹样例：含重试 / 跳过 / 超预算 / 证据不足降级的「复合」轨迹 |

### 追加轮次新增文件（P4.x，详见 §11）

| 文件 | 说明 |
| --- | --- |
| `evaluation/step_fixtures.py` | **步骤 fixture 装载 / 富化**：`merge_bundle` 把步骤轨迹注入运行包副本；`enrich_report` 在报告副本上补 `steps`/`phases`/`step_summary`，**不改 `passed`（D4 安全）** |
| `evaluation/interface_source.py` | **阶段三 · 在线只读接口**：生成只读请求计划（仅 `GET`/`HEAD` + `/api/read/` 前缀），越界方法/端点直接拒绝；本地导出归一化 → `StepTrace` fixture |
| `evaluation/langfuse_deploy.py` | **D5 部署就绪包**：报告 + 用例 → 有序部署请求计划（`dataset → ingestion → dataset-item → dataset-run-item`）+ 离线 dry-run / 回放脚本 |
| `evaluation/model_judge.py` | **阶段四 · 主观步骤模型评分脚手架**：离线构建 LLM-as-judge 评审请求体（维度 × 命中步骤）+ 响应解析 + `STEP` 分数映射 |
| `evaluation/test_followups.py` | 追加轮次回归测试（18 项）：扩容 / 步骤 fixture / 只读接口 / D5 部署 / 模型评审 / 冻结清单 |
| `evaluation/fixtures/steps/case-03…case-14-*.json` | 为 case-03~case-14 补齐步骤轨迹 fixture（12 个），使 **14 个用例全部进入步骤级评测** |
| `evaluation/fixtures/run-bundle/case-09…case-14-*.json` | 为 6 个新用例补齐金标准运行包 |
| `docs/步骤级评价与Langfuse接入-D5部署说明.md` | **D5 部署说明**：离线有序请求计划 + dry-run / 回放脚本用法（仅需环境变量，零 SUT 调用） |

### 修改文件

| 文件 | 改动摘要 |
| --- | --- |
| `evaluation/contract.py` | 新增 `STEP_STATUSES`、`DIAGNOSTIC_PHASES`、`StepCost` / `TraceStep` / `StepTrace`；`Trajectory` 增可选 `steps` |
| `evaluation/scores.py` | 新增 `ScoreScope.STEP` 与 7 项步骤指标定义；新增 `STEP_METRICS`；归一化排除步骤项 |
| `evaluation/metrics.py` | `CaseResult` 增 `steps` / `phases` / `step_summary`；`_metric_values`/`evaluate_case` 消费步骤轨迹 |
| `evaluation/run_eval.py` | `FROZEN_RELATIVE` 扩充；`aggregate` 增 `step` 块；`render_markdown` 增「步骤级归因」小节 |
| `evaluation/test_metrics.py` | 指标数由 17 → 24，适用数 22/23/15，新增步骤指标子集断言 |
| `docs/Agent评估方法.md` | 新增「步骤层」章节；三层粒度落地说明；分数模型补 STEP 作用域 |
| `docs/步骤级评价与Langfuse接入方案.md` | 顶部状态由「草案」更新为「阶段一/二已落地」，指向本文 |

> 说明：`evaluation/collect_run_bundle.py`、`docs/评测器能力边界说明.md`、`docs/运行包采集模块交接说明.md` 属**更早一轮**交付物，本轮未改动；其与本轮步骤层的关系见《方案》§11。

---

## 2. 步骤级评价是什么（三层粒度落地）

参照 Langfuse 对 Agent 评估的划分，本项目分三层：

| 粒度 | 回答的问题 | 状态 |
| --- | --- | --- |
| 黑盒层（用例级） | 结论对不对 | 已实现（原有） |
| 玻璃盒层（轨迹级） | 路径对不对 | 已实现（原有 `trajectory_conformance`） |
| **白盒层（步骤级）** | **这一步对不对 / 好不好 / 花多少** | **本轮新增** |

步骤层以 **8 个 MCP 工具**为单位打分，再 **上卷到 5 个诊断阶段**：

```
create_task, prepare_environment        → baseline
discover_scenarios, propose_hypotheses  → hypotheses
run_experiment                          → discriminating_experiment
evaluate_evidence                       → localization
reconcile_task, finish_task             → verification
```

单步判定用**确定性规则**（不设标准答案）：状态合法性、参数结构性、阶段覆盖、重试、单步延迟/token 预算、以及「证据不足时是否正确降级」。链路上卷为：
`步骤分(observation) → 阶段分(roll-up) → 用例过程分 → 全局过程画像`。

---

## 3. 逐文件改动明细

### 3.1 `evaluation/contract.py`（值对象 + 常量，进 FROZEN）

- 新增常量：
  - `STEP_STATUSES = ("ok", "error", "skipped")`；
  - `DIAGNOSTIC_PHASES = ("baseline", "hypotheses", "discriminating_experiment", "localization", "verification")`。
- 新增值对象：
  - `StepCost(tokens, tool_calls, bytes)`：单步资源消耗，缺省 `None` 表示「未记录」（与 0 区分）。
  - `TraceStep`：单步轨迹的规范化视图。字段含 `index / step_type / phase / status / tool / input / output /
    ts_start / ts_end / latency_ms / cost / error / evidence_refs`；提供 `ok`/`failed`/`skipped` 与
    `effective_latency_ms`（优先显式 `latency_ms`，否则由 `ts_start/ts_end` 秒差 ×1000 推导）。
    `from_obj` 宽容解析；`parse_many` 对旧式「步骤名列表」返回空元组（避免与旧字段冲突）。
  - `StepTrace(case_id, run_id, source, steps)`：一次运行的完整步骤轨迹；`by_phase()` / `phases_present()`。
- `Trajectory` 新增可选字段 `steps: tuple[TraceStep, ...] = ()`（向后兼容），并在 `from_obj` 中：
  - 仅当 `steps` 不是「轨迹对象数组」时才回退为旧式「已完成步骤名」解析；
  - 同步解析 `steps=TraceStep.parse_many(...)`。
- 新增宽容解析助手 `_opt_int` / `_opt_float`（`None`/空串 → `None`）。

### 3.2 `evaluation/scores.py`（分数模型，进 FROZEN）

- `ScoreScope` 增第三级 `STEP = "STEP"`（对应 Langfuse observation 级）。
- `METRIC_DEFINITIONS` 由 **17 → 24**，新增 7 项步骤指标（`group="step"`、`scope=STEP`、`applies_to=ALL_CASE_TYPES`）：

  | 指标 | 类型 | 含义 |
  | --- | --- | --- |
  | `step_status_ok` | BOOLEAN | 轨迹中不存在 `status=error` 的步骤 |
  | `step_tool_argument_valid` | BOOLEAN | 所有工具步骤的参数结构性合法 |
  | `step_phase_coverage` | NUMERIC | 由步骤推断出的 5 个诊断阶段覆盖度 |
  | `step_retry_count` | NUMERIC | 相邻重复步骤形成的重试次数 |
  | `step_latency_ms` | NUMERIC | 步骤延迟（相对单步预算归一化） |
  | `step_tokens` | NUMERIC | 步骤 token 消耗 |
  | `step_downgrade_correctness` | BOOLEAN | 证据不足时是否正确降级（白盒核心） |

- 新增 `STEP_METRICS`（`group == "step"` 的指标名元组），供 `steps.py` / `run_eval.py` 过滤。
- `metric_score`：由仅排除 `group == "cost"` 改为排除 `group in ("cost", "step")` → 步骤分**不进入** `group_scores` / `total_score`（D4）。
- `definitions_for` 的 `group_order` 增加 `"step": 4`。
- 自检更新：`len(METRIC_DEFINITIONS) == 24`、`len(STEP_METRICS) == 7`；适用数 normal/boundary/failure = 22/23/15；断言步骤指标 scope 为 STEP、且归一化返回 `None`。

### 3.3 `evaluation/steps.py`（**新**，进 FROZEN）

纯标准库，直接运行即自检（`python evaluation/steps.py`）。核心内容：

- `MCP_TOOLS`（8 工具，D6）、`TOOL_PHASE`（工具→阶段）、`phase_for(tool)`。
- `_ARG_ALIASES`：同义字段别名组（如 `task` 可写作 `task_id`/`prompt`/`goal` 等），`TOOL_REQUIRED_FIELDS`：每工具的结构性必填参数。
- `StepBudget(latency_ms=15_000.0, tokens=8_000.0)` + `DEFAULT_STEP_BUDGET`（缺省偏宽松，避免误判正常探索）。
- `evaluate_step(step, *, prev=None, budget=DEFAULT_STEP_BUDGET)`：返回单步明细
  `{index, phase, tool, status, latency_ms, tokens, tool_argument_valid, latency_score, tokens_score,
  retry, score, error, checks}`；`score = 状态因子(ok=1/skipped=0.5/error=0) × 参数合法性因子(非法=0)`；
  延迟/token 单独以 `latency_score`/`tokens_score` 报告（超预算按 `budget/raw` 衰减），不折进正确性分。
- 7 条确定性规则 → `STEP_RULES`（与 `STEP_METRICS` 一一对应）：`_rule_status_ok`、`_rule_tool_argument_valid`、
  `_rule_phase_coverage`、`_rule_retry_count`、`_rule_latency_ms`、`_rule_tokens`、`_rule_downgrade_correctness`。
  - `step_downgrade_correctness`（白盒核心）：当 `evaluate_evidence` 报「证据不足」时，若最终 `decision == verified`
    判 `False`（即误验证的步骤级成因）；证据充足 / 无可判定信号时返回 `None`（不参与统计）。
- `TraceEvalResult`（`case_id/run_id/source/steps/summary/phases`，`has_steps`）+ `evaluate_trace(...)`
  （宽容接收 `StepTrace` / 序列 / dict / `None`；缺 `phase` 时用工具名补齐）+ `_roll_up_phase(...)` 阶段上卷 +
  `step_scores(result)`（转成 `scope=STEP` 的 `Score` 列表，逐步带 `step_index`/`phase`/`tool`）。
- 自检覆盖：干净轨迹 8 步、延迟合计 **9520.0**、token **3500**、阶段覆盖 **1.0**、无重试；
  error=0 / skipped=0.5 / 非法参数=0；重试检测；降级正确性 True/False；超预算衰减；空轨迹宽容；STEP scope。

### 3.4 `evaluation/trace_adapter.py`（**新**，进 FROZEN）

把三来源归一化为 `contract.StepTrace`，**只做数据形状转换，零执行/零网络**：

- `FromRunBundle`：路径甲（离线）——运行包 / 步骤 JSON 中的 `trajectory.steps`。
- `FromInterface`：路径乙（在线只读）——任务包 / AGH 执行记录形态（`_STEP_KEYS` 命中）。
- `FromLangfuse`：路径乙——Langfuse Trace/Observation 导出 JSON（`usage`/`usageDetails`、毫秒 epoch、ISO `Z`）。
- `normalize(...)`：按形状自动判别来源；未知形态抛 `ValueError`。
- 辅助：`TOOL_ORDER`（规范闭环顺序，缺 `index` 时按出现序编号）、`_STATUS_ALIASES`（success/done→ok 等）、
  `_parse_ts`（>1e12 视为毫秒 epoch；兼容 ISO `Z`）、`_tokens_from_usage`。
- 自检：三来源归一化 + 自动判别 + 与 `steps.py` 打通。

### 3.5 `evaluation/metrics.py`（进 FROZEN）

- `CaseResult` 新增 `steps: list[dict]` / `phases: list[dict]` / `step_summary: dict`，并新增
  `step_scores()`（取 `metadata["group"] == "step"` 的取值快照），`to_dict()` 同步输出。
- `_metric_values`：调用 `steps.evaluate_trace(inp.trajectory.steps)`，当 `has_steps` 时把 7 项步骤指标并入
  `values`（随后由 `compute_scores` 归入 `cases[].scores`，但因 `metric_score` 对 step 返回 `None`，**不进总分**）。
- `evaluate_case`：把 `trace_eval.steps/phases/summary` 写入 `CaseResult`，并在 `notes` 追加一行步骤层摘要。
- 自检新增：轨迹带 steps 时产出逐步明细与阶段上卷，且**通过判定与总分不变**（`"step" not in group_scores`，
  `passed`/`total` 与无 steps 版本一致）；无 steps 时步骤字段为空（向后兼容）。

### 3.6 `evaluation/run_eval.py`（进 FROZEN，需重算哈希）

- `FROZEN_RELATIVE` 扩充：新增 `evaluation/steps.py`、`evaluation/trace_adapter.py`、`evaluation/langfuse_export.py`、
  `evaluation/test_steps.py`（`sha256_file` 对缺失文件返回 `None`、`freeze_manifest` 用 `"MISSING"` 占位，故先列后建有容错）。
- `aggregate(...)` 新增 `"step"` 聚合块：`cases_with_steps`、`step_count`、`error_step_count`、`retry_step_count`、
  `status_ok_rate`、`tool_argument_valid_rate`、`downgrade_correctness_rate`、`phase_coverage_mean`、
  `retry_count_mean`、`latency_ms_sum`、`tokens_sum`、`by_phase`（阶段上卷表）。
- `render_markdown` 新增「## 步骤级归因（白盒）」小节（仅在有步骤用例时渲染），并注明「不进 `group_scores`/`total_score`」。
- 新增 `_report_like(...)` 助手（把结果 + 聚合拼成可渲染的最小报告，仅自检用）。
- 自检新增：无步骤时步骤块为空且渲染不崩；注入带 steps 的轨迹后步骤块被填充、`status_ok_rate == 1.0`、
  且**不改通过判定/总分**；带步骤时 Markdown 出现「步骤级归因」。

### 3.7 `evaluation/langfuse_export.py`（**新**，进 FROZEN）

离线把「报告 dict」或「运行包 + 用例定义」转换为 **Langfuse Ingestion API** 事件批次（`{"batch": [...]}`）：

- 映射：一次运行/一个用例 → `trace-create`；一个步骤 → `span-create`（`span.id` = observationId）；
  用例分 → 挂 trace 的 `score-create`；步骤分（带 `step_index`）→ 挂 observation 的 `score-create`；
  用例集合 → Dataset/Dataset Item；一轮实验 → Dataset Run Item。
- 端点常量 `ENDPOINTS`：`/api/public/ingestion`、`/api/public/v2/datasets`、`/api/public/dataset-items`、
  `/api/public/dataset-run-items`（**只产出请求体，不发送请求**）。
- **确定性 id**：`uuid5` + 固定命名空间 → 同输入同 id，重复摄入幂等（`trace_id_for` / `observation_id_for`）。
- **布尔分数统一转 `1`/`0`**（Langfuse 要求）。
- 公共 API：`export_report` / `export_report_file` / `export_bundle` / `case_events` / `dataset_bodies` /
  `dataset_item_body` / `dataset_run_item_body` / `write_ingestion` / `ExportResult.counts()`。
- CLI：`python evaluation/langfuse_export.py --report <report.json> --out <ingestion.json> --run-name <name>`。
- 自检：报告/运行包 → Ingestion 事件（用例分挂 trace、步骤分挂 observation、布尔转 1/0、确定性 id、Dataset 请求体）。

### 3.8 测试与样例

- `evaluation/test_steps.py`（**新**，43 项）：`StepRegistryTest`、`EvaluateStepTest`、`StepRulesTest`、
  `EvaluateTraceTest`（含两个 fixture 的精确聚合断言）、`StepScoresTest`、`StepScoringBoundaryTest`（D4 边界）、
  `TraceAdapterIntegrationTest`、`BackwardCompatTest`。
- `evaluation/test_metrics.py`（改）：`test_registry_has_24_metrics`（24 + 7）；`test_applicability_invariants`
  适用数改 22/23/15，并新增 `STEP_METRICS ⊆ normal/boundary/failure` 断言。
- `evaluation/fixtures/steps/case-01-slow-query-fullscan.json`：8 步全绿的干净轨迹
  （延迟合计 9520.0、token 3500、阶段全覆盖、无重试、`evaluate_evidence` 证据充足、`finish_task` 结论 `verified`）。
- `evaluation/fixtures/steps/case-02-slow-query-composite.json`：8 步复合轨迹——含 1 次重试（相邻同工具同参）、
  1 个 `status=skipped`（`reconcile_task`，单步分 0.5）、1 个超预算步骤（`run_experiment` 40000ms → `latency_score=0.375`）、
  `evaluate_evidence` 证据不足但 `finish_task` 才给 `lead`（`step_downgrade_correctness=True`）。

---

## 4. 数据契约：`StepTrace`（统一中间表示）

两条来源都收敛到同一结构（解耦关键），示例：

```json
{
  "case_id": "case-01-slow-query-fullscan",
  "run_id": "run-case-01-0001",
  "source": "run-bundle",
  "steps": [
    {
      "index": 0,
      "step_type": "create_task",
      "phase": "baseline",
      "status": "ok",
      "tool": "create_task",
      "input": {"task": "排查慢查询"},
      "output": {},
      "ts_start": 1730000000.0,
      "ts_end": 1730000000.12,
      "latency_ms": 120.0,
      "cost": {"tokens": 300, "tool_calls": 1, "bytes": 0},
      "error": "",
      "evidence_refs": []
    }
  ]
}
```

- `source` ∈ `run-bundle` / `interface` / `langfuse`；
- `status` ∈ `ok` / `error` / `skipped`；`phase` ∈ 5 个诊断阶段（可空，缺省由工具名补齐）；
- 步骤 `input`/`output` 允许**摘要化**；制品只存引用（D7）。

**红线**：步骤数据里**不得包含** `case.json` 的 `expected` / `defects`（金标准泄漏面）。

---

## 5. Langfuse 映射与摄入

| Langfuse 概念 | 本项目对应 |
| --- | --- |
| Dataset / Dataset Item | 用例（`case.json` + `project/`） |
| Trace | 一次运行（一个用例的一次执行） |
| Session | 一轮评估（全部用例） |
| **Observation（span）** | **一步行为（一个工具调用 / 诊断阶段）** |
| Score（挂 observation） | **步骤分**（本轮新增，`scope=STEP`） |
| Score（挂 trace） | 用例分（现有四层指标） |
| Dataset Run | 一次跨用例的实验（版本横向比较） |
| Evaluator（Code / LLM） | 步骤评估器（确定性）/ 后续主观步骤模型评分 |

摄入要点：端点 `POST /api/public/ingestion`，请求体 `{"batch": [...]}`，返回 `207`；事件类型为 kebab-case
（`trace-create` / `span-create` / `score-create`）；**布尔分数写 `1`/`0`**；事件 id 由 `uuid5` 确定性派生，幂等。
本轮**默认离线产出 JSON**，是否真正推送到 Langfuse 由 D5（我方部署）另行执行。

---

## 6. 判定口径与红线（D3 / D4）

- **D3 确定性**：步骤层不引入「某一步的标准答案」，只做结构性 / 一致性 / 预算类判定。
- **D4 不进硬闸门与总分**：`scores.metric_score` 对 `group=="step"` 返回 `None`，故步骤分**不进入**
  `group_scores` / `total_score`；`aggregate` 的 `step` 块与 `render_markdown` 的「步骤级归因」**仅供下钻**。
  **golden 总分、全局误验证门槛、三类用例通过判定均保持不变。**
- **只读**：`trace_adapter.py` / `steps.py` / `langfuse_export.py` 均零网络、零 SUT 调用。
- **白盒核心联动**：`false_verified`（全局零容忍）出现时，可下钻到 `evaluate_evidence` 的
  `step_downgrade_correctness`，把「误验证发生在哪一步」讲清楚。

---

## 7. 如何验证（命令与结果）

在 `project-doctor/datasets/` 目录下执行：

```powershell
python evaluation/contract.py            # 契约自检
python evaluation/scores.py              # 分数模型自检（24 项指标 / 步骤层 7 项）
python evaluation/steps.py               # 步骤评估器自检
python evaluation/trace_adapter.py       # 轨迹适配器自检
python evaluation/metrics.py             # 指标自检（含步骤层归因）
python evaluation/run_eval.py            # 编排/报告自检（含步骤级归因聚合）
python evaluation/langfuse_export.py     # Langfuse 导出自检
python evaluation/langfuse_deploy.py     # D5 部署计划自检（端点白名单 / 金标准不泄漏）
python evaluation/step_fixtures.py       # 步骤 fixture 装载/富化自检
python evaluation/interface_source.py    # 阶段三 只读接口计划自检
python evaluation/model_judge.py         # 阶段四 评审请求计划自检

python -m unittest discover -s evaluation -p "test_*.py" -v
```

本轮验证结果：**全部自检 OK；单测 132 项全通过**（`test_steps` 43 + `test_metrics` 45 + `test_golden_bundle` 16 +
`test_run_eval` 10 + `test_followups` 18）。其中 `test_golden_bundle` 证明**引入步骤层后 golden 总分与全局门槛未变**；
`test_followups` 覆盖用例扩容（8→14）与追加模块的回归。

> 环境提示：仓库默认 `python` 为 3.10.x；本层纯标准库实现，无第三方依赖（`pytest` 未安装，用 `unittest` 即可）。

---

## 8. FROZEN 清单与哈希影响

`run_eval.py` 的 `FROZEN_RELATIVE` 现已包含本轮新增模块：

```
evaluation/contract.py
evaluation/scores.py
evaluation/metrics.py
evaluation/steps.py                # 首轮新增
evaluation/trace_adapter.py        # 首轮新增
evaluation/langfuse_export.py      # 首轮新增
evaluation/langfuse_deploy.py      # 追加轮次新增
evaluation/step_fixtures.py        # 追加轮次新增
evaluation/interface_source.py     # 追加轮次新增
evaluation/model_judge.py          # 追加轮次新增
evaluation/run_eval.py
evaluation/test_metrics.py
evaluation/test_steps.py           # 首轮新增
evaluation/test_run_eval.py
evaluation/test_golden_bundle.py
evaluation/test_followups.py       # 追加轮次新增
tools/validate_cases.py
_schema/case.schema.json
```

共 **18 项**（首轮 13 项 + 追加轮次 5 项）。

改动 FROZEN 文件会**改变评测器哈希**，属预期；须在**一轮评估开始前统一冻结**。本轮未改动 golden 期望值
（因为步骤层不进总分），故 golden 保持稳定。

---

## 9. 未完成 / 后续工作

- **D5 部署（就绪，待凭证执行）**：`langfuse_deploy.py` 已能离线产出**有序部署请求计划**
  （`dataset → ingestion → dataset-item → dataset-run-item`，含端点白名单与金标准不泄漏守卫），并生成 `replay.ps1` / `replay.sh`；
  `langfuse_export.py` 备好摄入 JSON。**建 Dataset（14 用例）+ Dataset Run** 只需配好环境变量
  （`LANGFUSE_HOST` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`）后执行回放脚本，详见《步骤级评价与Langfuse接入-D5部署说明.md》。
- **阶段三 · 在线只读接口（就绪）**：`interface_source.py` 已能生成只读请求计划（仅 `GET`/`HEAD` + `/api/read/` 前缀），
  越界方法/端点直接拒绝，并支持本地导出归一化为 `StepTrace` fixture；待执行侧确认接口形态后即可对接。
- **阶段四 · 主观步骤模型评分（脚手架就绪）**：`model_judge.py` 已能离线构建 LLM-as-judge 评审请求体
  （维度 × 命中步骤）、解析响应并映射为 `STEP` 分数；接入真实评审模型仅需填 endpoint / key。
- 上述均**不影响**当前黑盒 golden 与判定口径。

---

## 10. 交接要点（速览）

1. **边界不变**：我们只判卷，不调用执行；步骤数据只读。
2. **首轮加了三样东西**：步骤契约（`contract`）、步骤评估器（`steps.py`）、轨迹适配器（`trace_adapter.py`）+ Langfuse 导出（`langfuse_export.py`）。
3. **追加轮次又加了五样**：步骤 fixture 富化（`step_fixtures.py`）、只读接口取数（`interface_source.py`）、D5 部署计划（`langfuse_deploy.py`）、阶段四模型评审（`model_judge.py`）、回归测试（`test_followups.py`）；并将用例从 8 扩到 **14**。
4. **步骤分不改判定**：`metric_score(group="step") → None`；golden 总分与全局门槛不动。
5. **白盒核心**：`step_downgrade_correctness` 把 `false_verified` 定位到 `evaluate_evidence` 那一步。
6. **验收命令**：`python -m unittest discover -s evaluation -p "test_*.py"`（应 132 项通过）。
7. **待办**：D5 部署回放（待凭证）、阶段三在线接口对接（待接口形态）、阶段四接入真实评审模型（待 endpoint/key）。

---

## 11. 追加轮次（数据集扩容 8→14 + 阶段三/四 + D5 部署就绪）

在首轮基础上继续推进，本轮交付物与验收如下（工作根目录 `project-doctor/datasets/`）：

### 11.1 数据集扩容（8 → 14 用例）

新增 6 个用例，补齐此前缺失的 `problem_kind`（slug 以 `case.json` 为准）：

| 用例目录 | `problem_kind` | `case_type` | 要点 |
| --- | --- | --- | --- |
| `case-09-connection-pool-leak` | `connection_pool` | boundary | 连接池泄漏 |
| `case-10-large-response-unbounded` | `large_response` | boundary | 大响应体无界 |
| `case-11-connection-setup-per-request` | `connection_setup` | boundary | 每请求重复建连 |
| `case-12-excessive-logging-sync-debug` | `excessive_logging` | boundary | 同步 debug 日志过量 |
| `case-13-thread-pool-no-verifiable-defect` | `thread_pool` | failure | 无「可验证缺陷」的对照用例 |
| `case-14-config-regression-pool-size` | `config_regression` | boundary | 配置回归（池大小） |

每个用例均含 `case.json` + `README.md` + `project/`，全部通过 `tools/validate_cases.py` 的 schema 校验与隔离守卫。

### 11.2 步骤级 fixture 全覆盖（14/14）

- `evaluation/fixtures/steps/case-03…case-14-*.json`：补齐 12 个步骤轨迹 fixture。
- `evaluation/fixtures/run-bundle/case-09…case-14-*.json`：补齐 6 个金标准运行包。
- `evaluation/step_fixtures.py` 的 `merge_bundle` / `enrich_report` 只操作**深拷贝**，不会落笔到只读 fixture；富化后 `passed` 与 golden 总分不变（D4 安全）。

### 11.3 阶段三 · 在线只读接口（`interface_source.py`）

- `build_plan(...)` 生成任务包 / 执行记录 / Trace 三类**只读**取数请求（`GET`/`HEAD`，端点须落在 `/api/read/` 前缀）。
- `assert_read_only(...)` 对任何非只读方法或越界端点抛 `ValueError`，保证「只取数、不调用诊断工具」。
- `normalize_export(...)` / `to_fixture(...)` 把执行侧本地导出归一化为 `StepTrace` fixture，走离线打分闭环。

### 11.4 D5 · 部署就绪包（`langfuse_deploy.py`）

- 输入报告 + 用例 → 输出**有序**部署请求计划，`kinds_in_order = dataset → ingestion → dataset_item → dataset_run_item`。
- 端点白名单 `ENDPOINTS`（`/api/public/ingestion` 等）；`FORBIDDEN_GOLDEN_KEYS` 守卫拒绝任何携带金标准的请求体。
- 生成 `plan.json` + `requests/NN-<kind>.json` + `replay.ps1` / `replay.sh`；dry-run 只打印不发送。
- 执行细节见《步骤级评价与Langfuse接入-D5部署说明.md》。

### 11.5 阶段四 · 主观步骤模型评分脚手架（`model_judge.py`）

- 对主观维度（假设质量 / 证据支撑 / 报告可读性）按「维度 × 命中步骤」构建 LLM-as-judge 评审请求体；提示词**不含金标准**。
- 评审请求体文案全在 `messages[].content` 字符串里，故金标准守卫升级为**整词扫描字符串值**（同时覆盖键名），并避免误伤 `expected_latency_ms` 这类可观测字段。
- `parse_judge_response(...)` 做类型 / 范围校验；`judge_scores(...)` 映射为 `ScoreSource.EVAL` + `ScoreScope.STEP` 分数（仍 `group="step"`，D4 安全）。
- 主观维度 `SUBJECTIVE_CRITERIA` = `hypothesis_quality`（假设质量） / `evidence_grounding`（证据支撑） / `report_readability`（报告可读性）；请求体为 OpenAI 兼容 `chat/completions` + JSON Schema `response_format`。
- CLI（**离线产出**，零网络）：`python evaluation/model_judge.py --report evaluation/out/report.json --out evaluation/out/model_judge`；无参数时执行自检。
- 接入真实评审模型：设 `JUDGE_BASE_URL` / `JUDGE_API_KEY` 后运行生成的 `replay.ps1` / `replay.sh`；缺省模型 `DEFAULT_JUDGE_MODEL="gpt-4o-mini"`、端点 `DEFAULT_JUDGE_ENDPOINT="/v1/chat/completions"`。评审模型网关**独立于 SUT**，仍满足「零 SUT 调用」。

### 11.6 回归与冻结

- 新增 `evaluation/test_followups.py`（18 项）覆盖上述全部内容。
- `FROZEN_RELATIVE` 扩充至 **18 项**（新增 `langfuse_deploy.py` / `step_fixtures.py` / `interface_source.py` / `model_judge.py` / `test_followups.py`）。
- 全量单测 **132 项全通过**（详见 §7）。

> 边界重申：以上模块全部**零网络、零 SUT 调用**；回放脚本仅在**配好凭证后**由人手动执行，属「我方部署」动作，不是评测运行时行为。
