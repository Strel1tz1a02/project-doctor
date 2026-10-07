# 步骤级评价与 Langfuse 接入方案（评审稿）

> 状态：**阶段一、阶段二（离线部分）已落地**。本文保留为设计稿；D1–D7 已确认并按建议执行，
> 其中 **D5 经用户调整为我方负责部署**。逐文件的改动明细、验证方式与交接要点见
> **《步骤级评价与Langfuse接入-交接说明.md》**。阶段三（在线只读接口）与阶段四（主观步骤模型评分）
> 为后续工作，尚未开始。
> 目标读者：队长 / 组员 / 执行侧（A、B 线）。

---

## 0. 一句话结论

把现有「**按用例打分**」升级为「**按用例 + 按步骤打分**」：把 Agent 的每一步行为（工具调用 / 诊断阶段）当作一个可独立打分的对象，用 **Langfuse 的 observation 级 score** 承载「这一步对不对 / 好不好 / 花了多少」；步骤数据支持「**记录离线**」与「**只读接口**」两条来源路径。

硬边界不变：**我们只做评测，只读数据，绝不调用诊断执行本身。**

---

## 1. 当前工作情况（我方）

### 1.1 定位与边界

- 我方负责 **Agent 评估方法 + 评估数据集**，已按「方案 B」并入 `project-doctor` 的 `datasets/` 子目录。
- 评测器是「**判卷机**」不是「考场」：只读取结构化**运行包（run bundle）**，不启动被测项目、不施打补丁、不跑实验。
- 与执行侧的接口边界 = **运行包**这唯一契约（`{baseline, report, trajectory, retest, artifacts, restore, cost}`）。

### 1.2 已建成的东西（清单）

| 产物 | 位置 | 说明 |
| --- | --- | --- |
| 评估方法 | `docs/Agent评估方法.md` | 指标定义、七步打分流程、三类样例判定标准 |
| 数据集结构规范 | `docs/数据集结构规范.md` | 目录契约、边界保证 |
| 契约视图 | `evaluation/contract.py` | 运行包字段的规范化视图 |
| 指标计算 | `evaluation/metrics.py` | 结论 / 证据 / 过程 / 成本四层 |
| 分数模型 | `evaluation/scores.py` | 17 个指标定义、3 组 reward profile、成本预算 |
| 编排与报告 | `evaluation/run_eval.py` | 装载 / 汇总 / 渲染 |
| 金标准运行包 | `evaluation/fixtures/run-bundle/` | 8 个用例，golden 回归 |
| 采集模块 | `evaluation/collect_run_bundle.py` | 输入原始/修改代码，可插拔后端，**不调用 SUT** |
| 隔离守卫 | `tools/isolation_guard.py`、`tools/guard_sut_separation.py` | 防泄漏 / 防 SUT 反向引用金标准 |

### 1.3 现有评估粒度（关键）

现有 **ScoreScope 只有两级**：`DATASET_ITEM`（用例级）与 `RUN`（整轮级）。

| 层（group） | 指标 | 作用域 |
| --- | --- | --- |
| 结论 conclusion | `root_cause_recall` / `root_cause_precision` / `code_location_hit` / `decision_match` / `false_verified` / `recommendation_effective` / `correctness_preserved` | 用例级 |
| 证据 evidence | `evidence_compliance` / `excluded_explanation_coverage` / `limitation_declared` / `artifact_integrity` | 用例级 |
| 过程 process | `trajectory_conformance` / `honesty` / `restore_verified` | 用例级 |
| 成本 cost | `wall_seconds` / `tool_calls` / `artifact_bytes` | 运行级 |

### 1.4 现有「步骤」能力的真相（**这是本次要补的核心缺口**）

《Agent 评估方法》里其实已经写了三层粒度设想（黑盒 / 玻璃盒 / 白盒），但**目前只落地到黑盒 + 粗颗粒玻璃盒**：

- `Trajectory` 契约只有 5 个字段：`required_steps_done`、`hypothesis_count`、`experiments_single_variable`、`records_retained`、`tool_calls`（后两者可选）。
- 过程层唯一的轨迹指标是：
  ```
  trajectory_conformance = steps_coverage × constraint_ratio
  steps_coverage        = 命中的 REQUIRED_STEPS 数 / 5
  constraint_ratio      = (假设数≤3, 实验单变量) 两个布尔的均值
  ```
- 也就是说，现状是**一个标量代表整条轨迹**，只能回答「该走的 5 步走了没」。

**结论：现在无法评价「某一步对不对 / 好不好」，无法定位错在哪个中间步骤。** 白盒层只在文档里，没有实现。

### 1.5 与 Langfuse 的对齐程度

| 维度 | 现状 |
| --- | --- |
| Score 字段模型（`name`/`value`/`data_type`/`source`） | ✅ 已对齐 |
| 数据类型（NUMERIC/BOOLEAN/CATEGORICAL/TEXT/CORRECTION） | ✅ 已对齐 |
| 来源（ANNOTATION/API/EVAL） | ✅ 已对齐 |
| 挂载粒度 | ⚠️ 只有用例级 / 运行级，**缺 observation（步骤）级** |
| Trace / Observation / Session 概念 | ❌ 未建模 |
| SDK / API 实际接入 | ❌ 未接入（仅"设计对齐"） |
| 人工审核队列 / 标注 | ❌ 未接入（`honesty` 预留了 ANNOTATION，但无流程） |

### 1.6 执行侧（数据提供方）现状

- 执行侧是一个由 **AGH + Agnes 模型**驱动的诊断 Agent，通过 **8 个 MCP 工具**完成闭环：
  `create_task → prepare_environment → discover_scenarios → propose_hypotheses → run_experiment → evaluate_evidence → reconcile_task → finish_task`。
- 中间过程**已经被持久化**：`TaskStore` 保存 task / scenarios / hypotheses / experiments / findings / operations；每个工具都有明确的输入输出契约（见 `docs/contracts/v0.1/*.json`：`ExperimentSpec/ExperimentResult/Observation/SqlCall/LockEvidence/EvidenceCheck/WarmupSpec/WarmupResult/...`）。
- **缺口**：`agh/tool-policy.json` 仍为 `declared_not_integrated`，真实 AGH 模型主循环尚未跑通；执行记录 / trace 尚未以标准格式对外导出；仓库内**没有任何 langfuse 集成**。

> 小结：数据"存在但零散"，缺少一个**步骤级、有序、可打分的统一轨迹格式**，也缺少 **Langfuse 这一承载层**。

---

## 2. 目标与范围

### 2.1 目标

1. 新增**步骤级评价**：对每一步（工具步 / 诊断阶段）判定「对不对（correctness）」「好不好（effectiveness）」「花多少（cost）」。
2. 采用 **Langfuse** 作为承载：步骤分挂到 observation，用例分挂到 trace，整轮挂到 session / dataset run。
3. 打通两条数据来源：
   - **路径甲（离线）**：把执行侧**记录的过程**当数据用。
   - **路径乙（在线）**：调用执行侧**只读接口**取回步骤记录。
4. **边界不变**：只读数据，不调用诊断执行，不接触金标准泄漏面。

### 2.2 三层粒度落地（把文档里的设想变成实现）

| 粒度 | 问题 | 现状 | 改造后 |
| --- | --- | --- | --- |
| 黑盒层（用例级） | 结论对不对 | ✅ 已实现 | 保持 |
| 玻璃盒层（轨迹级） | 路径对不对 | ⚠️ 仅标量 | 升级为**逐步轨迹** |
| 白盒层（步骤级） | 这一步对不对 | ❌ 未实现 | **本次新增** |

### 2.3 明确不做（边界）

- 不调用 8 个 MCP 诊断工具本身（那是执行 SUT）。
- 不替执行侧埋点、不改执行侧源码、不改 `docs/contracts/`。
- 步骤分**不新增硬闸门**（见 §6.1），避免污染「结论正确性」这一唯一硬闸门体系。

---

## 3. 数据来源：两条路径

### 3.1 路径甲：记录的过程作为数据（离线，**建议先做**）

- 执行侧把一次运行的**步骤轨迹**导出为一份 JSON（或沿用 `collect_run_bundle.py` 采集）。
- 我方离线读取 → 归一化为 `StepTrace` → 逐步打分 → 产出报告 / Langfuse 摄入文件。
- 优点：可复现、可冻结、可回归；不依赖网络与执行侧在线服务；与现有 fixtures 模式一致。

### 3.2 路径乙：调用对方只读接口（在线）

- 执行侧暴露**只读取回**接口，取回某次运行的步骤记录。可选形态：
  - 任务包导出接口（等价 `load_bundle(task_id)` 的只读导出）；
  - AGH 执行记录导出（会话 + 工具调用）；
  - **Langfuse Trace/Observation API**（若由执行侧写入 Trace，我方按 project/keys 拉取）。
- 我方拉取后同样归一化为 `StepTrace`，后续流程与路径甲一致。
- **红线**：接口必须是**读操作**；任何触发诊断/实验的写操作一律不走此通道。

### 3.3 统一中间表示：`StepTrace`

两条路径都收敛到同一归一化结构（这是解耦的关键）：

```
StepTrace = {
  case_id, run_id, source: "run-bundle" | "interface" | "langfuse",
  steps: [
    {
      index: 0,
      step_type: "propose_hypotheses",        # 工具名
      phase: "hypotheses",                     # 映射到的诊断阶段(可空)
      status: "ok" | "error" | "skipped",
      input: {...}, output: {...},             # 允许裁剪/摘要
      ts_start, ts_end, latency_ms,
      cost: {tokens, tool_calls, bytes},
      error: null | {...},
      evidence_refs: [...]
    }, ...
  ]
}
```

### 3.4 边界红线（无论哪条路径）

- 步骤数据里**不得包含** `case.json` 的 `expected/defects` 字段（金标准泄漏面）。
- 只读取回；不得把读取接口变成"跑一遍给我看"。

---

## 4. Langfuse 映射

| Langfuse 概念 | 我方对应 |
| --- | --- |
| Dataset / Dataset Item | 用例（`case.json` + `project/`） |
| Trace | 一次运行（一个用例的一次执行） |
| Session | 一轮评估（全部用例） |
| Observation（span / generation） | **一步行为**（一个工具调用 / 一个诊断阶段） |
| Score（挂 observation） | **步骤分**（本次新增） |
| Score（挂 trace） | 用例分（现有四层指标） |
| Dataset Run | 一次跨用例的实验（用于横向比较版本） |
| Evaluator（Code / LLM） | 步骤评估器（确定性）/ 主观步骤的模型评分 |

> 关键点：Langfuse 里 score 可以挂在 **trace 或 observation** 上——这正是"步骤级评价"的落点，无需自造体系。

---

## 5. 步骤模型（把"每一步"说清楚）

### 5.1 工具步（8 个 MCP 工具）

以 8 个工具的调用为单位，是最细、最客观、最易取数的粒度。

### 5.2 诊断阶段（5 个必需步骤）与工具步的映射

```
baseline               ← prepare_environment (+ create_task)
hypotheses             ← discover_scenarios, propose_hypotheses
discriminating_experiment ← run_experiment
localization           ← evaluate_evidence (evidence → code_location)
verification           ← evaluate_evidence / finish_task (retest, restore)
```

建议：**以工具步为打分单位**，再**上卷（roll-up）到 5 个诊断阶段**，最终并入现有 `trajectory_conformance`。

### 5.3 每步要评的四个维度

| 维度 | 问题 | 类型 | 判定者 |
| --- | --- | --- | --- |
| 合规 compliance | 参数/状态是否合法、是否越界 | BOOLEAN | 代码 |
| 正确 correctness | 这一步的判断对不对 | BOOLEAN / CATEGORICAL | 代码 |
| 有效 effectiveness | 这一步是否有推进（有没有价值） | NUMERIC | 代码 / 模型 |
| 成本 cost | 这一步花了多少（时延/token/调用数） | NUMERIC | 代码 |

### 5.4 步骤级指标草案（逐工具）

**通用（每个工具都算）**

| 指标 | 类型 | 含义 |
| --- | --- | --- |
| `step_status_ok` | BOOLEAN | 该步 `status == ok` |
| `step_tool_argument_valid` | BOOLEAN | 入参通过契约校验（无非法/缺参） |
| `step_retry_count` | NUMERIC | 该步重试次数 |
| `step_latency_ms` | NUMERIC | 该步耗时 |
| `step_tokens` | NUMERIC | 该步 token 消耗 |

**专用（举例，具体阈值待定）**

| 工具步 | 步骤指标 |
| --- | --- |
| `create_task` | `task_id_deterministic`、`limits_present`、`correlation_ids_present`（agh_session_id / tool_call_id） |
| `prepare_environment` | `isolation_bound`（compose 项目名唯一）、`fingerprint_recorded` |
| `discover_scenarios` | `scenario_valid`、`uncovered_declared` |
| `propose_hypotheses` | `hypothesis_count_le_3`、`hypothesis_falsifiable`(judge)、`hypothesis_targets_cost` |
| `run_experiment` | `single_variable`、`warmup_present`、`sample_count_ge_3`、`dispersion_within`、`budget_respected` |
| `evaluate_evidence` | **`downgrade_correctness`**（证据不足时是否正确降级为 lead，白盒核心）、`evidence_sufficiency_match` |
| `reconcile_task` | `no_blind_replay`、`idempotent` |
| `finish_task` | `restore_verified`、`report_completeness`(num)、`honesty`(cat) |

> `evaluate_evidence.downgrade_correctness` 是最典型的白盒步骤分：它精确回答"在证据不足时，这一步有没有把结论从 verified 正确降级为 lead"，直接对应现有 `false_verified` 的上游成因，让误验证**可定位到具体步骤**。

---

## 6. 判定与聚合（怎么用起来）

### 6.1 步骤分不进硬闸门（建议）

硬闸门体系保持现状（只有结论层/证据层那几条 + `false_verified` 全局零容忍）。
步骤分作为**评分项 + 归因维度**：不改判"用例是否通过"，但进入总分画像，并用于**定位失败发生在哪一步**。

### 6.2 聚合链

```
步骤分(observation) → 阶段分(roll-up) → 用例过程分 → 全局过程画像
```

- 现有 `trajectory_conformance`（单一标量）由"多维步骤分聚合"替代/补充，例如：
  `process_score = w1·阶段覆盖 + w2·步骤正确率 + w3·步骤有效性 − w4·步骤成本超支`。
- reward profile 的 `process` 组由 1 个指标扩为多指标（权重待定）。

### 6.3 与现有 `under / over / false_verified` 的联动

- `false_verified` 用例 → 报告可下钻到 `evaluate_evidence.downgrade_correctness=false`，把"错在哪一步"讲清楚。
- 新增方向性步骤指标（如 `premature_verification`），与全局口径呼应。

---

## 7. 需要改动 / 新增的模块（落点清单）

| # | 文件 | 改动 | 进 FROZEN？ |
| --- | --- | --- | --- |
| 1 | `evaluation/scores.py` | 新增 `ScoreScope.STEP`；新增步骤指标定义（group=`step`） | ✅ 是（评分口径） |
| 2 | `evaluation/contract.py` | 新增 `TraceStep` / `StepTrace` 值对象；`Trajectory` 增可选 `steps`（保持向后兼容） | ✅ 是 |
| 3 | `evaluation/steps.py`（新） | 步骤评估器注册表 + `evaluate_step(...)`，确定性规则 | ✅ 是 |
| 4 | `evaluation/trace_adapter.py`（新） | 两条来源归一化为 `StepTrace`（`FromRunBundle` / `FromLangfuse`） | ➖ 否 |
| 5 | `evaluation/collect_run_bundle.py` | 增 `trajectory` 步骤采集钩子（可插拔，仍不调用 SUT） | ➖ 否 |
| 6 | `evaluation/metrics.py` | 过程层消费 `steps`，产出步骤分与阶段上卷 | ✅ 是 |
| 7 | `evaluation/run_eval.py` | 报告结构纳入 `cases[].steps[]` 与步骤聚合 | ✅ 是（需重算哈希） |
| 8 | `evaluation/langfuse_export.py`（新） | 产出 Langfuse 可摄入的 traces/observations/scores JSON（离线优先） | ➖ 否 |
| 9 | `docs/Agent评估方法.md` | 增"步骤级评价"章节；三层粒度落实 | ➖ 否 |
| 10 | `evaluation/test_steps.py`、golden 扩展 | 步骤自检 + 回归 | ➖ 否 |

> 注：FROZEN 相关文件改动会改变评测器哈希，属预期——但**需要在一轮评估开始前统一冻结**，并同步更新 golden 期望值。

---

## 8. 分期实施（建议顺序，先易后难）

**阶段一 · 离线 MVP（不依赖执行侧、不依赖网络）**
1. 定义 `StepTrace` 契约 + `steps.py` 确定性评估器。
2. `trace_adapter` 支持"离线记录"来源；用现有 fixtures 造 1 个步骤轨迹样例跑通。
3. `metrics.py` / `run_eval.py` 纳入步骤分与阶段上卷。
4. 保持硬闸门不变，golden 更新。✅ 可独立验收。

**阶段二 · Langfuse 离线回写**
5. `langfuse_export.py`：把用例分（trace 级）+ 步骤分（observation 级）产出为 Langfuse 摄入 JSON；
   可选：用 Langfuse Python SDK 写入（需 project/keys）。
6. 建 Dataset（8 用例）与 Dataset Run，验证在 Langfuse UI 可见、可过滤。

**阶段三 · 在线只读接口（"调用对方函数接口"）**
7. 与执行侧约定只读导出接口（任务包 / AGH 执行记录 / Trace API）。
8. `FromLangfuse` / `FromInterface` 适配器接入，实现在线取回→打分闭环。

**阶段四 · 主观步骤的模型评分**
9. 对"假设质量 / 报告可读性"等主观步骤，接 Langfuse LLM-as-judge（`ScoreSource.EVAL` 或新 `LLM`）。

---

## 9. 协作边界与待确认决策点

| 编号 | 决策点 | 建议 |
| --- | --- | --- |
| D1 | "调用对方函数接口"是否越界？ | **只读数据取回 OK**；调用诊断工具本身**不行**。需队长确认 |
| D2 | 谁负责埋点 / 产出 trace？ | **执行侧**产出记录或写 Langfuse；**我方只消费 + 打分** |
| D3 | `case.json` 是否新增 `expected_steps`（步骤级金标准）？ | 先**不**加；步骤分用确定性规则，不依赖逐步骤正解。后续按需 |
| D4 | 步骤分是否进硬闸门？ | **不进**。只作评分项/归因维度 |
| D5 | Langfuse 部署与凭证归属？ | 需队长指定 project（自建 / 云）；我方只读 + 回写 score |
| D6 | 步骤口径以 8 工具还是 5 诊断步为准？ | **以 8 工具为准**，上卷到 5 诊断步 |
| D7 | 数据量/裁剪策略？ | 步骤 input/output 允许摘要化，制品只存引用 |

---

## 10. 风险与对策

| 风险 | 对策 |
| --- | --- |
| 步骤级金标准难定义 | 用"确定性合规规则"而非"唯一正解"；主观项才用模型评分 |
| 过度耦合执行侧 | 以 `StepTrace` 契约解耦，两条来源可互换 |
| 改动 FROZEN 文件致 golden 漂移 | 统一冻结 + 一次性重算期望值 |
| Trace 数据量大 | 摘要化 + 引用制品，不内联大对象 |
| 硬闸门被污染 | 步骤分明确不进闸门 |
| 边界失守（变成跑实验） | 只读红线 + 复用 `guard_sut_separation.py` 思路加静态断言 |

---

## 11. 与现有交付物的关系

- 现有 `collect_run_bundle.py`（采集模块）**保留**，作为"路径甲"的采集入口扩展。
- 现有 4 层指标**保留**（结论/证据/成本不变；过程层升级）。
- 现有 golden fixtures **保留**，新增"带步骤轨迹"的样例目录以隔离测试。

---

## 附：待评审通过后再动工

本文为设计稿。请先确认 **§9 的 D1–D7**，尤其是 **D1（边界）** 与 **D5（Langfuse 凭证）**；
确认后再按 **§8 阶段一** 开始实现。
