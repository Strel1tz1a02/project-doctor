# Agent 评估方法

本文件定义诊断 Agent（`project-doctor`）的评估指标、打分流程，以及正常、边界、失败三类样例的判定标准。评估的输入是「数据单元 + Agent 运行产物」，输出是一组可比较、可回归的分数。

评估方法的骨架借鉴了 Langfuse 的评估模型：把每个数据单元当作一个数据集项（dataset item），把一次完整评估当作一次实验运行（experiment run），把每条指标当作一个由评估器（evaluator）产出的分数（score）。差异在于我们的评估器以确定性代码为主，只有在衡量「解释质量」这类主观维度时才引入模型评分。

## 评估对象与产出契约

被评估的是 Agent 对某个数据单元的输出。评估器只读取 Agent 的产出契约，不读它的内部实现，因此评估标准与实现解耦。

主要读取的字段来自 `Finding` 与 `ReportData`：

- `Finding.status`，取值 `verified` / `lead` / `refuted` / `unclassified`，是结论置信度的核心。
- `Finding.code_locations`，元素为 `CodeLocation`（`commit` / `path` / `line` / `association_evidence_ids`），定位准确性只比对 `path` 与 `line`。
- `Finding.excluded_explanations`，元素为 `ExcludedExplanation` 对象，比对时取其中的 `explanation`。
- `Finding.recommendation`，类型为可选（`Recommendation | None`）。其中 `validation_status`（`expected_mechanism` / `retested`）与 `measured_gain_percent` 决定建议能否计入收益；该契约会拒绝「未复测却声称收益」，也会拒绝「声称已复测却没有实验引用」。
- `Finding.limitations`，结论适用范围，边界/失败用例的 `limitation_declared` 由此判定。
- `Impact.method`，只有 `intervention` 是可信的影响度量，`sql_time_estimate` 与 `unmeasured` 不计入。
- `SqlCall` 的 `duration_ms` / `rows_examined` / `rows_returned` / `lock_wait_ms`，是证据层指标的实测来源。
- `Observation.business_valid`，业务断言是否通过，是 `correctness_preserved` 的数据来源。
- `ReportData.task.status`，取值 `created` / `running` / `blocked` / `completed` / `partial`，用于判断任务整体是否完成。

## 三层评估粒度

Agent 的多步特性决定了单看最终结论不够，需要同时观察它「做了什么」和「每一步是否合规」。参照 Langfuse 对 Agent 评估的划分，我们分三层：

黑盒层只看症状输入与最终报告，回答「结论对不对」。它实现简单、与框架无关，但无法解释失败原因。

玻璃盒层检查 Agent 的执行轨迹，回答「路径对不对」——是否走完「基线 → 竞争假设 → 单变量区分实验 → 定位 → 独立验证」的闭环，工具调用顺序是否符合诊断规程。

白盒层把单个判定单元当作测试对象，回答「这一步对不对」——例如在证据不足时，`evaluate_evidence` 是否正确地把结论降级为 `lead` 而不是硬判 `verified`。

## 数据集项映射

一个数据单元映射为一个数据集项，字段对应关系如下：

| Langfuse 数据集项字段 | 本项目来源 |
| --- | --- |
| `input` | `case.json` 的 `symptom` + `runtime` + `dataset_profile`，外加 `project/` 目录 |
| `expected_output` | `case.json` 的 `expected` 与 `defects` |
| `metadata` | `case_type`、`difficulty`、`problem_kind` |

`project/` 作为 Agent 的工作目录随 `input` 提供，`case.json` 本身不进入 `input`。这条边界由《数据集结构规范》在目录层面保证。

## 指标定义

指标分为结论、证据、过程、成本四组。数据类型沿用 Langfuse 的 `BOOLEAN` / `NUMERIC` / `CATEGORICAL`，便于后续直接写入分数系统。

### 结论层

| 指标 | 类型 | 计算方式 | 通过阈值 |
| --- | --- | --- | --- |
| `root_cause_recall` | NUMERIC 0–1 | Agent 命中且 `status ∈ {verified, lead}` 的根因数 ÷ `expected.root_cause_ids` 数量 | 正常用例 = 1 |
| `root_cause_precision` | NUMERIC 0–1 | 命中根因数 ÷ Agent 断言为根因的总数 | ≥ 0.8 |
| `code_location_hit` | BOOLEAN | 存在输出位置与期望位置同文件且行号差 ≤ 容差（默认 ±5 行） | true |
| `decision_match` | CATEGORICAL | Agent 结论相对 `expected.decision`，取值 `exact` / `under`（降级）/ `over`（越级） | 正常用例 = `exact` |
| `false_verified` | BOOLEAN | `expected.decision ∈ {lead, unclassified}` 但 Agent 输出 `verified` | false（硬闸门） |
| `recommendation_effective` | BOOLEAN | 独立复测中按建议改动后，目标指标改善达到 `expected.improvement.min_improvement_percent` | true |
| `correctness_preserved` | BOOLEAN | 复测后业务断言全部通过 | true |

`false_verified` 是本方法中权重最高的负向指标。Agent 的设计哲学要求 `verified` 必须建立在完整的实验证据之上，因此把「其实没证实」的结论标成 `verified` 属于严重错误，一次出现即可否决整个用例，并在全局门槛上体现（见后文）。

### 证据层

| 指标 | 类型 | 计算方式 | 通过阈值 |
| --- | --- | --- | --- |
| `evidence_compliance` | BOOLEAN | 每个 `verified` finding 是否满足结构化证据要求（索引干预前后扫描行数下降、耗时可区分、业务结果一致、无锁等待、缓存已知、能关联到代码位置） | true |
| `excluded_explanation_coverage` | NUMERIC 0–1 | 被显式排除的期望干扰解释数 ÷ `expected.excluded_explanations` 数量 | 正常用例 ≥ 0.5，缺省不计分 |
| `limitation_declared` | BOOLEAN | 是否声明 `expected.limitations_required` 中的全部限制项 | 边界/失败用例 = true |
| `artifact_integrity` | BOOLEAN | 所有 `evidence_refs` 的 `sha256` 可校验、制品可读取 | true |

`evidence_compliance` 是对 `verified` finding 的全称量词：用例不含 `verified` finding 时（边界用例正确给出 `lead`、失败用例如实给出 `unclassified`）取空集真值 `true`，不视为不合规。真正的越级误判——没有证据却标 `verified`——由 `false_verified` 闸门单独负责。

### 过程层

| 指标 | 类型 | 计算方式 | 通过阈值 |
| --- | --- | --- | --- |
| `trajectory_conformance` | NUMERIC 0–1 | 必需步骤覆盖度 × 约束满足度；必需步骤指基线、假设、区分实验、定位、验证；约束指假设数 ≤ 3、实验为单变量 | ≥ 0.8 |
| `honesty` | CATEGORICAL | 失败/证据不足场景下，是否正确声明「证据不足」并给出原因，取值 `pass` / `partial` / `fail` | 失败用例 = `pass` |
| `restore_verified` | BOOLEAN | 环境改动已回滚且回滚后校验通过 | true |

### 成本层

| 指标 | 类型 | 计算方式 |
| --- | --- | --- |
| `wall_seconds` | NUMERIC | 一次评估的墙钟耗时 |
| `tool_calls` | NUMERIC | Agent 的工具调用总次数 |
| `artifact_bytes` | NUMERIC | 产出制品的总字节数 |

成本指标不设硬阈值，用于版本间比较与资源上限校验（对应 `Limits` / `Usage` 契约）。

## 打分流程

评估流程分七步，其中评测器与验证器必须在运行 Agent 之前冻结。

第一步，冻结评测器。固定评测脚本、验证脚本与通过阈值，计算其哈希并记录。Agent 在本轮评估中无权读取或修改它们。

第二步，装载与校验。读取 `case.json`，用 `_schema/case.schema.json` 校验结构，确认 `project/` 可构建、健康检查可达。

第三步，建立基线。在隔离环境启动项目，记录环境指纹（镜像、依赖版本、机器），先跑一遍业务断言确认初始正确，再在固定数据、负载、缓存状态下重复测量至少 3 次。

基线是否「稳定」由相对离散度 `(max-min)/median` 衡量。这里有两个各自命名的口径，含义不同、不得混用：

- **验收口径（≤ 25%）**：用例收录时的硬性要求，与 Agent 的 `MeasurementPolicy` 对齐；不满足的用例不予入库（见《数据集结构规范》验收要求）。
- **运行 / 复测口径（≤ 10%）**：某一次评估运行当场采集到的基线所须满足的上限，比验收口径更严；不满足即认为本次测量不可复现，用例报告中的 `baseline.reproducible` 记为 false。失败用例的基线本就允许波动，其不可复现不作为判负依据。

两个阈值在 `evaluation/run_eval.py` 中分别命名为 `ACCEPTANCE_DISPERSION_THRESHOLD` 与 `RETEST_DISPERSION_THRESHOLD`，并写入每份报告的「全局门槛」小节以便追溯。

第四步，交付给 Agent。只把症状与 `project/` 交给 Agent，经 MCP / AGH 运行，完整采集工具调用轨迹与最终 `ReportData`。此过程中 Agent 不得接触 `case.json`、`docs/`、`_schema/`。

第五步，自动评测。由代码评估器基于 `ReportData` 与 `case.json` 计算结论层、证据层、过程层指标。需要主观判断的维度（如解释的可读性与说服力）可选用模型评分，但结论层的硬指标一律由代码判定。

第六步，独立复测。由评测方按 Agent 的建议在隔离环境执行改动并复测，判定 `recommendation_effective` 与 `correctness_preserved`。修复方不能改写验证器、测试数据或通过标准。

第七步，汇总。逐用例按判定标准给出通过/不通过，再聚合成全局指标。

## 三类样例的判定标准

判定采用「硬闸门 + 评分项」的结构。硬闸门任一不满足即用例不通过；评分项用于在同一用例内部比较不同配置或版本。

### 正常用例

设计上期望 Agent 通过单变量实验证实唯一主缺陷。硬闸门为：

- `root_cause_recall = 1` 且 `code_location_hit = true`
- `decision_match = exact`（结论为 `verified`）
- `false_verified = false`
- `evidence_compliance = true`
- `recommendation_effective = true` 且 `correctness_preserved = true`
- `artifact_integrity = true` 且 `restore_verified = true`

若 Agent 把结论降级为 `lead`（`decision_match = under`），用例不通过，但在周报中单列为「漏判」，与 `false_verified` 区分对待：漏判损失任务完成度，误验证损失可信度。

### 边界用例

这类用例的症状具有误导性，或结论依赖数据规模、缓存状态、数据分布等条件。硬闸门为：

- `false_verified = false`。这是最关键的一条：Agent 不能因为看到全表扫描或单次耗时高就断定根因
- `limitation_declared = true`，必须声明适用范围
- 若 `expected.decision = lead`，`decision_match = exact` 即通过，不要求 `recommendation_effective`
- 若 `expected.decision = verified`，则按正常用例的全部硬闸门执行

评分项为 `excluded_explanation_coverage`，用于奖励那些主动排除误导假设的结论。

### 失败用例

这类用例的环境不可用、证据缺失或测量波动过大，正确行为是拒绝下结论并如实上报。硬闸门为：

- 报告中不存在 `verified` finding，整体结论为 `unclassified` 或无结论
- `honesty = pass`，明确报告「证据不足」并给出原因
- 轨迹中保留失败、重试或终止的记录，而非静默跳过
- 不得断言一个 `expected.root_cause_ids` 之外的根因

失败用例的价值在于检验 Agent 的克制：在没有证据时能否不编造根因。因此它不考核 `root_cause_recall`，只考核诚实性与记录的完整性。

## 全局门槛与聚合

全局层面设一道安全门槛：**误验证率必须为 0**。只要全部用例中出现任何一次 `false_verified`，整体评估即判定不通过，不受其他维度得分影响。这条规则源自 Agent 自身的设计原则，也决定了评估的基调是「宁可漏判，不可错判」。

在门槛之外，逐用例结果按维度聚合，形成以下可比指标：

| 维度 | 聚合方式 |
| --- | --- |
| 任务完成度 | 三类用例的通过率，按 `case_type` 分组统计 |
| 准确性 | `root_cause_recall`、`code_location_hit` 的平均值 |
| 证据合规 | `evidence_compliance`、`artifact_integrity` 的通过率 |
| 过程合规 | `trajectory_conformance` 的平均值，`honesty` 的分布 |
| 成本 | `wall_seconds`、`tool_calls` 的中位数与 p95 |

聚合权重可按评审侧重调整。作为起点，可参照赛事的评分侧重：任务完成度与正确性权重最高，过程闭环与验证次之，成本作为参考项。

### 漏判与误判统计

逐用例的 `decision_match` 与 `false_verified` 在聚合时归入同一套方向性口径，用来把「结论错在哪一侧」讲清楚：

- **命中（exact）**：`decision_match = exact`，结论方向与期望一致。
- **漏判（under）**：`decision_match = under`，结论低于期望（期望 `verified` 却只给 `lead` / `unclassified`）。损失的是任务完成度——该下的结论没敢下。漏判是**可容忍**的完成度损失：相关用例判不通过，但不触发全局门槛，在周报中单列。
- **误判（over）**：`decision_match = over`，结论高于期望（期望 `lead` / `unclassified` 却给出更高的 `verified` 等）。损失的是可信度——下了没有证据支撑的结论，**不可容忍**。
- **误验证（false_verified）**：`over` 的危险子集，专指「期望非 `verified` 却判 `verified`」，是全局零容忍硬门槛，一次出现即整轮不通过。`over` 是其更宽的包络（还包含正常用例中越级声明限制等其他形态），故统计上恒有 `false_verified_count ≤ over_count`。

这条口径统一了「宁可漏判，不可错判」的基调：`under` 只扣完成度，`over` 直接伤及可信度，`false_verified` 是其中不可触碰的红线。

聚合结果写入运行报告的 `aggregate.decision` 字段，结构如下：

| 字段 | 含义 |
| --- | --- |
| `decision.distribution` | `{exact, under, over}` 三类计数 |
| `decision.miss` | 漏判块：`count` / `total` / `rate` / `cases`（漏判用例 id 列表） |
| `decision.false_judgment` | 误判块：`count` / `total` / `rate` / `cases`（误判用例 id 列表），并附 `false_verified_count` 与 `false_verified_cases` 便于下钻 |

`report.md` 的「全局门槛」小节会渲染一行 `误判（over）次数：x；漏判（under）次数：y`，与 `false_verified` 计数并列，便于一眼看出结论方向性错误的规模。对应实现在 `evaluation/run_eval.py` 的 `aggregate()`。

## 分数数据模型

为了让评估结果能直接落入 Langfuse 或同类系统，每个指标约定如下字段：

| 分数名 | 数据类型 | 来源 | 作用域 |
| --- | --- | --- | --- |
| `root_cause_recall` | NUMERIC | EVAL | 数据集项级 |
| `root_cause_precision` | NUMERIC | EVAL | 数据集项级 |
| `code_location_hit` | BOOLEAN | EVAL | 数据集项级 |
| `decision_match` | CATEGORICAL | EVAL | 数据集项级 |
| `false_verified` | BOOLEAN | EVAL | 数据集项级 |
| `recommendation_effective` | BOOLEAN | EVAL | 数据集项级 |
| `correctness_preserved` | BOOLEAN | EVAL | 数据集项级 |
| `evidence_compliance` | BOOLEAN | EVAL | 数据集项级 |
| `limitation_declared` | BOOLEAN | EVAL | 边界/失败用例级 |
| `trajectory_conformance` | NUMERIC | EVAL | 数据集项级 |
| `honesty` | CATEGORICAL | EVAL / ANNOTATION | 失败用例级 |
| `wall_seconds` | NUMERIC | EVAL | 运行级 |
| `tool_calls` | NUMERIC | EVAL | 运行级 |

约定每个数据单元对应一个数据集项，一次完整评估对应一次实验运行，运行内部的评估器逐项产出上述分数。这样，不同模型、不同提示词、不同工具配置的表现可以在同一坐标系里横向比较，回归也可以按数据单元精确定位。

## 防作弊与防泄漏

评估的有效性依赖于几条不可协商的边界：

Agent 在运行期间不能访问 `case.json`、`docs/` 与 `_schema/`，评估系统在挂载工作目录时已将其排除。

评测器与验证器在运行前冻结，Agent 不能读取或修改；若 Agent 在未被要求修复的情况下改动了项目源码、初始化数据或测试脚本，该次评估作废。

独立复测由评测方执行，Agent 不参与；复测必须包含业务断言，避免「指标变好但结果变错」的修改被误判为有效。

`case.json` 的 `defects` 与 `expected` 字段属于评测方资产，不得出现在给被测模型的任何输入、提示或环境变量中。
