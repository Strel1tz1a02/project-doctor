# Project Doctor 双人并行开发计划

> 执行方式：交给两名开发者，分别执行 [A 任务书](2026-10-02-developer-a-runtime.md) 与 [B 任务书](2026-10-02-developer-b-diagnosis.md)。本计划不授权启动子 Agent；如需使用，先获得用户确认。

**Goal:** 首个交付只完成慢查询的诊断到报告：有效场景 → SQL 与代码关联 → 实际测量与计划 → 可逆对照 → 恢复 → 证据判定 → JSON／HTML 报告。

**Architecture:** 单个 Python 项目。A 提供可恢复的实验执行能力及存储实现，B 通过固定合同组织场景、诊断决策与报告；AGH 是唯一模型主循环。MCP 只做接入与组装。

**Tech Stack:** Python、Pydantic、官方 Python MCP SDK、AGH、MySQL、Docker Compose、httpx、pytest、Ruff、类型检查。负载控制确有需求时才接入 k6。

**Spec:** [开发指南](../../../agent.md)、[产品设计](../specs/2026-09-30-backend-performance-diagnosis-agent-design.md)、[架构设计](../specs/2026-10-02-platform-architecture-design.md)。

## 1. 决策与事实

2026-10-02 已检查：仓库只有文档，没有 pyproject.toml、src、tests 或可运行 demo；工作区无已有未提交修改。设计文档提到的外部 AGH 示例与测试记录未在本仓库中找到，不能当成集成已通过。

用户最新确定首个交付仅为慢查询诊断与报告。本轮优先落地“缺少适用索引导致有代价扫描”的慢查询机制，使用隔离环境中临时索引的可逆对照验证；这不表示覆盖所有慢查询原因。锁等待、外部服务延迟、其他扫描或排序机制无法区分时保留线索，不强行归因。首个待测项目尚未确定，A0 必须落实目标语言、ORM、数据库与采集方式。若项目不能提供这些证据，先解决接入，不用伪造观测补齐链路。

本轮不实现 N+1、深分页的专门判据、实验变量或报告验收；两者属于后续交付，尚未排期。产品整体设计仍保留三类长期范围，本计划只收敛首次交付。

不能承诺两个人从第一分钟完全独立：需要一个短暂的合同冻结阶段。冻结后可以同步开发，业务对接只有三个能力入口，文件归属互不重叠。

## 2. 全局约束

- 评估用数据由第三人负责；A、B 不承担评估集设计、样本采集／生成、答案标注、人工审查、数据版本发布和评估指标制定。
- A、B 仍负责代码测试、合同 fixture、最小联调种子和真实运行证据。这些仅用于开发验证，不作为正式评估集交付；产品本身的数据准备与适用性检查功能仍在开发范围内。
- 本次交付仅慢查询／有代价的全表扫描；其他症状单列线索或未分类异常，不要求诊断 N+1、深分页。
- 平台创建隔离副本；实验请求不能回落到用户原地址；平台 MySQL 与目标数据库分离。
- 不自动修改目标代码作为产品功能，不做生产压测，不叠加第二个 Agent 循环。
- 程序控制预算、独占、权限、恢复和证据校验；模型提出至多三个竞争假设及实验预测。
- 一环境串行实验，独占覆盖执行与恢复；恢复失败隔离环境，不能再开始下一实验。
- 业务模块不导入具体 MCP、AGH、MySQL、Docker 实现；models 只定义数据。
- 正式结论要求有效业务请求、可比实验、具体 SQL、提交及代码行、完整原始证据、竞争解释处理。
- 运行数据放在配置的外部运行目录；凭据只存引用；采集阶段脱敏。
- 所有建议未经实施复测均标为预计作用机制；不编造改善百分比或线上优先级。

## 3. 文件归属：一个文件只有一个负责人

| 唯一负责人 | 可创建／修改的路径 | 责任 |
| --- | --- | --- |
| A | `features/environments/`、`features/experiments/` | 环境安全、恢复、实验校验与执行 |
| A | `integrations/` 全部 | MySQL、Docker、HTTP、观测、制品实现 |
| A | `workflows/execute_experiment.py`、`workflows/reconcile.py` | 实验生命周期与中断核对 |
| A | `demo/`、`tests/runtime/`、`tests/integration/runtime/` | 演示项目及真实执行验证 |
| B | `models/` | 共享数据合同，冻结后按变更流程更新 |
| B | `features/scenarios/`、`features/diagnosis/`、`features/reports/` | 场景、证据判定、影响报告 |
| B | `workflows/task_ports.py`、`workflows/tasks.py`、`workflows/diagnose.py` | 任务持久能力接口与诊断业务流程 |
| B | `entrypoints/`、`agh/` | MCP、实例组装、AGH 指令与配置 |
| B | `tests/contracts/`、`tests/diagnosis/`、`tests/integration/agent/`、`tests/e2e/` | 合同、规则、AGH 和整体验收 |
| B | 根级配置、锁文件、README.md、agent.md、CI | 项目初始化、依赖及交付说明 |
| 各自 | `docs/development/a/` 或 `docs/development/b/` | 本线验证记录 |

评估数据另由第三人维护在 `evaluation/data/`，A、B 不修改该目录。该路径仅约定职责，不要求二人在本次开发中创建目录或实现评估平台。

上表源码路径均相对 `src/project_doctor/`，demo、tests、agh、docs 和根级文件相对仓库根目录。命名空间包或空初始化文件统一由 B 在冻结阶段创建；A 不改祖先 `__init__.py`，各模块不从初始化文件统一导出。

依赖由 B 统一添加；A 提交依赖需求与实际验证结果。只锁定验证通过的 Python、AGH、MCP、MySQL 驱动组合。本计划不把尚未验证的库版本写成事实；MySQL 推荐候选是 SQLAlchemy + PyMySQL + Alembic，由 A 做连接、迁移、事务探针后交 B 锁定。

## 4. 开工门槛与并行节奏

| 阶段 | A 同时做什么 | B 同时做什么 | 通过条件 |
| --- | --- | --- | --- |
| P0 合同冻结 | A0：检查目标仓库、恢复配方、观测可行性及 MySQL 探针 | B0：骨架、合同、样例、AGH→MCP 最小探针 | 两人签认合同；目标接入方案可执行；实际工具调用可追踪 |
| P1 独立实现 | A1～A3：环境、制品、真实实验执行 | B1～B3：场景、诊断规则、报告及 MCP，使用假实现 | 各自合同测试通过；首个真实实验包和报告样例可读取 |
| P2 慢查询联调 | A4：接入实际 Runtime、Store、EvidenceReader，验证中断与恢复 | B4：组装并运行真实 AGH 慢查询诊断到报告链路 | 真实请求、SQL、计划、代码、制品、恢复及工具记录齐全 |
| P3 首交收尾 | A：修复本线联调缺陷，整理运行证据 | B5：慢查询报告及首交验收收尾 | 慢查询真实支持案例、反例及故障边界通过；不增加其他诊断类型 |

P0 公共基线已落地并完成本地合同检查，尚未提交 Git；真实接入探针仍未验证。仓库基线、合同版本和依赖锁文件由负责人合入一次；双方从该提交分别建 `codex/runtime`、`codex/diagnosis` 分支，用各自 checkout。禁止共用同一可写工作目录开发。双方可以按当前公共合同开发，真实链路验收仍须先完成 A0／B0 探针。

## 5. 共享合同 v0.1：B 编码，双方签认

以下合同已落实到 P0 模型、三个 ports 和 JSON Schema，具体类型及补充字段见 [P0 交接记录](../../development/p0-baseline.md)。真实实现与接入探针仍待 A0／B0 完成。禁止额外字段；时间采用 UTC，耗时单位 ms，行号为一基正整数。可选观测值为 null，不能用 0 冒充缺失。

2026-10-02 用户批准兼容新增 `ExperimentResult.spec: ExperimentSpec | None = None`。A 持久化实际执行配置，B 判定必须读取该配置；旧结果仍可读取，但缺配置不能形成正式结论。对应 Schema 已更新，详见 [B → A 交接](../../development/b/handoff-to-a.md)。

| 文件／模型 | 必需语义与字段 |
| --- | --- |
| `models/common.py` | `schema_version="0.1"`；`CodeLocation(commit, path, line, association_evidence_ids)`；`EvidenceRef(artifact_id, relative_path, media_type, format_version, sha256, size_bytes)`；ID 均为非空字符串 |
| `models/scenario.py` | `Scenario(id, version, source, purpose, steps, dataset, load, cache, credential_refs, uncovered_paths)`；source 区分真实样本、仓库推导、自行推断。`RequestStep(method, relative_path, params, parameter_sources, assertions)`；断言含状态及业务结果，不只判断 HTTP 200 |
| `models/dataset.py` | `DatasetProfile(id, snapshot_id, source, row_counts, relationship_cardinalities, distribution_notes, target_scale, applicability_unknowns)`；source 区分授权样本、种子、合成；target_scale 可缺失 |
| `models/environment.py` | `ProjectInput(repo_path, commit, supplied_url, recipe_ref, credential_refs)`；`EnvironmentHandle(id, isolated_base_url, fingerprint, baseline_snapshot_id, health)`；`RestoreResult(verified, fingerprint, snapshot_id, evidence_refs, reason)`；health 为 available/restoring/quarantined |
| `models/experiment.py` | `ExperimentSpec(id, task_id, scenario_id, scenario_version, hypothesis_ids, variable, levels, repetitions, limits, baseline_fingerprint, snapshot_id, observation_config_id)`；本轮 variable 只允许 index，levels 为 baseline/candidate_index；repetitions 每组至少三次，预算不足返回 evidence_insufficient；每组从基线恢复后再应用唯一变化；索引必须来自 A 校验的配方 |
| `models/observation.py` | `Observation(id, experiment_id, level, repetition, request_id, business_valid, latency_ms, result_digest, sql_calls, fingerprint, snapshot_id, observation_config_id, evidence_refs)`；`SqlCall(id, normalized_sql, duration_ms, rows_examined, rows_returned, lock_wait_ms, metric_sources, parameter_provenance, code_location, plan_evidence_ids, span_id)`；每项统计标明来源，实际行数不能填计划估算；锁相关指标缺失为 null；result_digest 针对脱敏、规范化业务结果，用于两组语义一致性核对 |
| `models/experiment.py` | `ExperimentResult(experiment_id, operation_id, phase, observations, restore_result, evidence_refs, failure)`；phase 为 prepared/running/restoring/finished/needs_reconcile；失败结果仍保存已有观测；只有明确完成且恢复成功的实验可作正式判定依据 |
| `models/hypothesis.py` | `Hypothesis(id, kind, explanation, predictions, falsifiers, status, evidence_ids)`；本轮 kind 只支持 slow_query/unclassified；status 区分 proposed/supported/refuted/unresolved |
| `models/finding.py` | `Finding(id, task_id, kind, status, scenario_id, experiment_ids, sql_call_ids, code_locations, evidence_refs, excluded_explanations, impact, recommendation, limitations)`；status 为 verified/lead/refuted/unclassified；impact 记录测量方法、共享请求／SQL 标识和不确定性 |
| `models/task.py` | `TaskRecord(id, project, status, limits, usage, environment_id, scenario_ids, experiment_ids, hypothesis_ids, finding_ids, correlation, coverage)`；status 为 created/running/blocked/completed/partial；`CallContext(task_id, operation_id, agh_session_id, tool_call_id)`，后两项允许 null 并注明缺失 |
| `models/errors.py` | `Failure(code, message, evidence_refs, retry_policy)`；code 为 environment_blocked/scenario_invalid/evidence_insufficient/tool_failure/environment_contaminated/budget_exhausted/operation_conflict；retry_policy 为 never/reconcile_first/safe_same_input |

`Limits` 在 common.py 定义 max_wall_seconds、max_requests、max_experiments、max_artifact_bytes；`Usage` 对应实际消耗。每个实验提交前预留预算、执行中计量，恢复预留独立时间；预算耗尽也必须进入恢复或隔离路径。阈值可配置并随运行记录保存，不把示例数字作为通用诊断标准。

### 5.1 只有三个跨开发者能力入口

**实验入口：A 定义并实现**，放在 `features/experiments/ports.py`：

```python
class Runtime(Protocol):
    async def prepare(self, project: ProjectInput, context: CallContext) -> EnvironmentHandle: ...
    async def run(
        self, environment_id: str, scenario: Scenario, spec: ExperimentSpec, context: CallContext
    ) -> ExperimentResult: ...
    async def reconcile(self, task_id: str) -> ReconcileResult: ...
    async def close(self, environment_id: str, context: CallContext) -> RestoreResult: ...
    async def publish_report(self, data: ReportData, context: CallContext) -> ReportResult: ...
```

`ReconcileResult(task_id, environment_health, operation_results, unresolved_operations, evidence_refs)` 在 models/experiment.py 定义。run 持有环境独占，执行 level、采集、发布制品、恢复并核对，然后返回；B 不另行执行 SQL、改索引或重置容器。网络采集／恢复方法不是暴露给模型的任意命令执行工具。

**任务入口：B 定义，A 提供 MySQL 实现**，放在 `workflows/task_ports.py`：

```python
class TaskStore(Protocol):
    async def create(self, task: TaskRecord) -> None: ...
    async def get(self, task_id: str) -> TaskRecord: ...
    async def save_scenario(self, task_id: str, scenario: Scenario) -> None: ...
    async def save_hypotheses(self, task_id: str, items: list[Hypothesis]) -> None: ...
    async def save_findings(self, task_id: str, items: list[Finding]) -> None: ...
    async def transition(self, task_id: str, expected: TaskStatus, target: TaskStatus) -> bool: ...
    async def reserve(
        self, task_id: str, operation_id: str, input_digest: str, request_allowance: int
    ) -> Reservation: ...
    async def finish_operation(
        self, task_id: str, operation_id: str, result: OperationResult, consumed: Usage
    ) -> None: ...
    async def load_operation(self, task_id: str, operation_id: str) -> OperationResult | None: ...
    async def load_bundle(self, task_id: str) -> TaskBundle: ...
```

models/task.py 定义 `Reservation(accepted, reason, replay_result)`、`OperationResult(operation_id, state, input_digest, payload, failure)`、`TaskBundle(task, scenarios, hypotheses, experiments, findings, evidence_refs)`；payload 为 EnvironmentHandle/ExperimentResult/RestoreResult/ReportResult 的 result_type 可区分联合，TaskStatus 定义在 models/common.py。reserve 原子检查预算、同操作标识及输入摘要，不能重复扣预算；同 ID 不同输入返回 operation_conflict。不确定结果返回需核对，不能自动重放。实验阶段、环境健康、证据索引的内部存储方法归 A，不增加 B 对内部表的依赖。

**证据入口：B 定义，A 实现**，放在 `features/diagnosis/ports.py`：

```python
class EvidenceReader(Protocol):
    async def verify(self, refs: list[EvidenceRef]) -> EvidenceCheck: ...
```

models/common.py 定义 `EvidenceCheck(valid, missing_ids, corrupted_ids, reasons)`。verify 必须实际读取、校验 hash 与大小，并阻止路径逃逸；不能只核对索引存在。

### 5.2 所有权与幂等边界

- B 的任务流程创建任务、保存场景／假设／结论，组织模型可观察的各工具。
- A 的 Runtime.prepare/run/close 自己调用 TaskStore.reserve/finish_operation，并在结束前持久化实际结果。B 不再次预留／结算这三类操作，也不重复存实验。
- A 将预留绑定到环境独占和持久操作记录；进程崩溃后锁释放不代表环境健康，必须 reconcile 才能再执行。
- `discover_scenarios` 的场景版本及 `evaluate_evidence` 的结论按确定性键 upsert，由 B 保证重复调用一致；报告生成无环境副作用。新 task_id 必须重新测量。
- 工具调用 operation_id 是业务幂等键，不能拿一次性的 AGH tool_call_id 代替。

### 5.3 冻结的 MCP 工具表：B 独占

| 工具 | 结构化输入 → 输出 | 副作用／重放 |
| --- | --- | --- |
| `create_task` | ProjectInput + Limits + operation_id → TaskRecord | 持久建任务；同业务键复用 |
| `prepare_environment` | CallContext → EnvironmentHandle | 创建隔离副本；由 Runtime 核对 |
| `discover_scenarios` | CallContext → list[Scenario] | 保存场景；同版本复用 |
| `propose_hypotheses` | CallContext + list[Hypothesis] → list[Hypothesis] | 至多三个；程序校验后保存 |
| `run_experiment` | CallContext + environment_id + scenario_id/version + ExperimentSpec → ExperimentResult | 有副作用；由 Runtime 核对 |
| `evaluate_evidence` | CallContext + hypothesis_ids + experiment_ids → list[Finding] | 程序取持久证据，模型不得提交伪造观测 |
| `reconcile_task` | CallContext → ReconcileResult | 核对并可能恢复；不盲目重放 |
| `finish_task` | CallContext → ReportResult | 恢复／隔离、保存部分或完整报告；核对后重放 |

ReportResult 在 models/finding.py 定义 task_id、task_status、json_ref、html_ref、limitations。各工具的默认超时、预算上限、只读／有副作用与重放策略写入 agh/tool-policy.json；B 配置，A 验证真实执行约束。平台不接受模型指定任意外部 URL、文件路径或任意 SQL 干预；请求和 index 干预只使用 A 已校验的项目配方。

ReportData 同文件定义 task、applicability、coverage、verified_findings、leads、unclassified、blocked_paths、limitations，以及 B 渲染的 json_content、html_content；两个内容必须来自同一份结构数据。Runtime.publish_report 只负责经制品机制发布和保存索引，不做判定或渲染。finish_task 由 B 先调用 close、更新任务状态、渲染，再调用 publish_report；该方法不新增第四个跨线入口。

### 5.4 合同样例与变更

B0 生成 `tests/contracts/fixtures/` 中 verified_slow_query、missing_location、missing_artifact、incomparable、restore_failed、unknown_outcome 六组 JSON，明确标记 synthetic，仅用于合同测试。A 的真实产出必须通过同一 Schema。

这六组是开发用最小测试输入，不承担评估样本数量、分布、标签质量或正式评估集建设任务。

接口变更先提交原因、字段／单位变化和样例差异，双方确认后由唯一负责人修改；同一版本内只允许兼容性新增可选字段。删改字段或语义必须升版本、迁移样例并同时更新两线调用者。不能让一方临时接受任意 dict 绕过合同。

## 6. 五项重点审查及归属

| 风险输入 | 应有行为 | 验证负责人 |
| --- | --- | --- |
| supplied_url 指向外部或生产，重定向逃出隔离网 | 执行前或重定向处拒绝，零外部实验请求 | A2 |
| 200 但业务失败／断言缺失 | 标 scenario_invalid，不计为性能问题 | A3、B1 |
| 相同 operation_id 不同参数，或执行后回包前崩溃 | 冲突拒绝／先核对；不重复副作用或预算 | A1、A4 |
| 制品路径穿越、文件损坏、索引孤儿 | 不读根目录外文件，证据不可用，不出正式结论 | A1、B2 |
| 两组请求结果不同、锁等待未排除、合成数据无分布依据 | 无效对照／竞争解释未区分降级；条件性结论 | A3、B2、B3 |

## 7. 联调和交付规则

- A 与 B 分别运行自己的测试；B 用假 Runtime/TaskStore/EvidenceReader，A 用冻结 Scenario/ExperimentSpec，不等待对方实现。
- A 提供 `build_runtime(settings, store)`、`build_store(settings)`、`build_evidence_reader(settings)` 三个工厂，分别在 `integrations/runtime_factory.py`、`integrations/mysql/factory.py`、`integrations/artifacts/factory.py`；B 的 `entrypoints/bootstrap.py` 只调用这些工厂和业务流程。
- 工厂只在入口引用；features 不导入这些文件。Settings 由 B 定义在 `entrypoints/settings.py`，A 使用传入值，不自己读取全局配置。
- A 每个阶段提交真实合同产物及操作方式；B 在 `tests/e2e/` 编写最终场景测试。报告模板、数据库迁移、依赖锁各只有一方修改。
- 合并顺序：合同基线 → A 存储／执行能力 → B 消费者／入口 → 联调修复。双方功能开发同期进行，合并顺序不等于开发顺序。
- 联调缺陷按归属修复：采集／恢复／持久化找 A，场景／判定／MCP／报告找 B；不跨线直接改代码。

## 8. 完成标准

- A、B 的开发交付不以第三人的正式评估集完成为前提；工程验收使用最小联调案例，正式评估结果另行记录。
- P2 才算慢查询产品链路完成：真实 AGH 调用多个业务工具，MySQL 可恢复状态，真实 HTTP/SQL 关联到固定提交代码行，有执行计划与实际统计，临时索引对照只改变一个因素且业务结果一致，原始文件可读且校验通过，实际恢复有证据，JSON 与 HTML 可核对。
- P3 完成首次交付：有代价扫描的慢查询机制有真实支持案例与不会误判的反例，缺证据／不可比／恢复失败不能形成正式结论；明确首个目标栈及当前支持的慢查询原因。不以 N+1、深分页完成作为验收条件。
- 规则测试用模拟数据通过仅表示规则已验证；真实模型、真实环境、真实故障分别列状态，不能互相替代。
- 交付记录逐项标 `已验证／未验证／存在问题`，附命令、环境版本、证据位置；不以文档长度或模型文案作为验收。
- 本计划不规定未经测算的工期。P0 后两人按实际接入结果给任务估时，只完成慢查询诊断到报告，不提前开发后续诊断类型。

自检：产品场景发现与复用对应 B1；慢查询测量、计划与索引对照对应 A3；执行与恢复对应 A1～A4；慢查询判据对应 B2；报告与影响对应 B3；AGH 真实记录对应 B0/B4；MySQL、制品、中断分别对应 A1/A4；首交收尾对应 B5。跨线共享类型集中于本合同，未引入第二个循环或通用插件框架。

## 9. 第三人的评估数据交接边界

- B 在 P0 提供已冻结的 JSON Schema、字段／单位说明和当前支持边界；A 提供实际启动、重置与采集能力说明。二人提供接口资料，不负责制作评估样本。
- 第三人独立交付数据版本、来源、目标仓库提交／运行配方引用、输入场景、预期机制及标注依据；正式评估数据不混入 `tests/contracts/fixtures/`。
- 参考答案／标签与产品输入分开保存，诊断运行不能读取参考答案。需要评价程序读取的标签字段由第三人另定，不扩充产品模型来承载答案。
- 数据适配失败按边界处理：违反冻结 Schema 的样本由第三人修正；合法输入触发产品缺陷，由对应开发者修复。评估集新增能力需求先确认范围，不能直接插入 A、B 任务。
