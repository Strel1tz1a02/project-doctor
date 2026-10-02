# 开发者 A：实验执行与恢复 Implementation Plan

> 执行方式：单名开发者执行；共享合同及文件归属见 [总计划](2026-10-02-two-developer-plan.md)。使用子 Agent 前须用户确认。

**Goal:** 首次交付慢查询的真实测量、执行计划、SQL→代码证据和可逆索引对照，输出可恢复的 ExperimentResult 供 B 判定与报告。

**Architecture:** Runtime 编排环境独占、预算、采集、制品发布和恢复；外部实现通过就近接口注入，实际状态写入平台 MySQL。

**Tech Stack:** Python、Pydantic、MySQL、Docker Compose、httpx、pytest；数据库驱动与迁移库经探针后由 B 锁定。

**Spec:** 总计划及其链接的 agent.md、两份设计文档；所有全局约束与审查风险均适用。

**范围排除：** 评估用数据交给第三人。A 不制作正式评估集、采集评估样本或编写参考答案；保留实现和验证实验能力所需的最小种子、故障测试及真实运行证据，均不作为评估集交付。`evaluation/data/` 不由 A 修改。

**首交边界：** 仅慢查询／有代价扫描，先验证缺少适用索引的机制；N+1 和深分页采集／实验专门能力后续安排，本轮不实现。

## A0：目标接入探针，可与 B0 同期

**Files:** `docs/development/a/target-handoff.md`、`demo/reference/`、`tests/integration/runtime/test_target_probe.py`。

**Interfaces:** 消费项目交接信息；产出 ProjectInput 所需 recipe_ref、目标栈版本与可核对的观测样例，交 B 冻结合同。

- [ ] 核对首个目标固定提交、启动、迁移、种子、有效业务请求和凭据引用；说明 SQL→请求→代码行的采集办法。
- [ ] 优先复用现有演示仓库；未交接时构建明确标为合成的最小联调项目，包含缺少适用索引的只读筛选查询和必需种子，可临时加索引对照，记录此支持边界；不为正式评估批量制造案例、分布或标签。
- [ ] 实际启动隔离服务，执行一个有效请求，采集参数来源、SQL 和代码位置，验证数据库数据恢复；不把打印日志当成恢复证明。
- [ ] 实际验证平台 MySQL 连接、迁移、事务回滚；把依赖版本结果交 B。无法完成的接入列阻断，不静默替换 SQLite。
- [ ] 运行 `pytest tests/integration/runtime/test_target_probe.py -v`；通过须有真实 HTTP、SQL、恢复证据；提交 A 独占路径。

## A1：持久化、制品与操作记录

**Files:** `integrations/mysql/{factory,task_store,operation_store,evidence_index}.py`、`integrations/mysql/migrations/`、`integrations/artifacts/{factory,publish,verify}.py`、`tests/runtime/test_artifacts.py`、`tests/integration/runtime/test_store.py`。

**Interfaces:** 实现总计划 TaskStore、EvidenceReader；工厂签名采用总计划；内部实验阶段与环境健康操作仅供 A 使用。

- [ ] 先写测试：reserve 同 ID 同摘要只预留一次；不同摘要冲突；事务失败不留下半条业务记录；transition 的 expected 不匹配返回 false。
- [ ] 写制品测试：临时写入失败没有可用索引；发布后未写索引形成可核对孤儿；缺失／hash 损坏判 invalid；`../`、绝对路径和符号链接逃逸拒绝。
- [ ] 运行上述测试确认失败，再实现最小表结构和事务：任务、版本场景、假设、实验、观测摘要、结论、操作、证据索引、环境健康。原始记录写文件，摘要可用有版本 JSON 列；避免未产生需求的查询层。
- [ ] 实现先临时文件→校验→原子发布→索引事务；保留可核对状态，故障不把索引标成可用。采集时脱敏后才发布，校验值针对保存内容；实现 Runtime.publish_report 发布 B 已渲染的 JSON／HTML，不在 A 复制报告规则。
- [ ] 运行 `pytest tests/runtime/test_artifacts.py tests/integration/runtime/test_store.py -v`，MySQL 测试必须实际连接；只提交 A 文件。

## A2：隔离环境与经验证的恢复

**Files:** `features/environments/{ports,prepare,restore}.py`、`integrations/docker/{compose,snapshots}.py`、`tests/runtime/test_environment.py`、`tests/integration/runtime/test_restore.py`。

**Interfaces:** 产出 EnvironmentHandle、RestoreResult；被 Runtime 使用，不由 B 直接调用 Docker。

- [ ] 先写测试：原地址不能成为实验地址；专用 Compose project 名称避免串环境；恢复不得触碰平台 MySQL；锁覆盖测量与恢复。
- [ ] 写真实恢复测试：改变目标数据／临时索引后恢复，核对数据摘要、schema 与配置指纹；仅重启容器不能通过；失败设置 quarantined。
- [ ] 运行测试确认失败，再实现仓库隔离副本、配方、网络限制、健康检查与目标数据库专用快照恢复；缺凭据返回 environment_blocked。
- [ ] HTTP 地址和重定向验证落在隔离目标白名单；观测配置和缓存条件纳入指纹。多个 level 的唯一变量差异另记录，不能把允许变化本身误判为不可比。
- [ ] 运行 `pytest tests/runtime/test_environment.py tests/integration/runtime/test_restore.py -v`；附真实恢复原始证据，提交 A 文件。

## A3：慢查询测量、计划与可逆索引对照

**Files:** `features/experiments/{ports,validate,compare,interventions}.py`、`workflows/execute_experiment.py`、`integrations/{runtime_factory.py,http/requests.py,observation/reference.py,observation/plans.py,observation/execution_stats.py}`、`tests/runtime/test_experiment.py`、`tests/integration/runtime/test_slow_query.py`。

**Interfaces:** 实现 Runtime.prepare/run/close；消费 Scenario、ExperimentSpec；返回并持久化 ExperimentResult。compare 仅计算实验差异，不判慢查询根因是否已验证。

- [ ] 先写测试：HTTP 200 业务断言失败为 scenario_invalid；预算不够不开始下一测量；请求超时仍恢复；采集失败保存部分观测。
- [ ] 写真实实验断言：baseline 与 candidate_index 两组各至少三次；固定数据、请求参数、观测、缓存策略和负载，仅改变已允许的临时索引；两组业务结果摘要一致；SQL 具有请求 ID、代码行、实际耗时、计划与原始证据引用，每组从同一快照恢复。
- [ ] 实现首个目标数据库的计划和实际统计转换，统计字段逐项标来源；估算与实际行数分开，缺锁等待／执行统计保留 null 和原因，不用估算补齐。索引配方校验列／表及权限，拒绝模型提交任意 DDL。
- [ ] 记录可能影响结果的锁、连接等待和外部依赖证据；能观测到什么就输出什么，归因与证据不足由 B 判定。验证临时索引移除及数据／结构恢复成功。
- [ ] 运行测试确认失败，实现受限请求、断言、观测转换和制品保存；数据源不能提供的字段用 null 和原因，不猜调用位置。
- [ ] run 预留预算并持环境独占直到恢复核对完成；最终结果不明确使用 needs_reconcile。返回耗时样本及条件，稳定性和根因判据由 B 决定。
- [ ] 运行 `pytest tests/runtime/test_experiment.py tests/integration/runtime/test_slow_query.py -v`；导出真实 JSON 并通过 B 的合同 Schema，提交 A 文件。

## A4：中断核对与第一轮联调

**Files:** `workflows/reconcile.py`、`tests/integration/runtime/test_reconcile.py`、`docs/development/a/p2-evidence.md`。

**Interfaces:** 实现 Runtime.reconcile；返回 ReconcileResult；B 的 bootstrap 接工厂，不改 B 文件。

- [ ] 先写故障测试：HTTP 执行后回包前中断、发布制品后索引前中断、恢复中中断；重启后同 operation_id 不重复发副作用请求，不重复扣预算。
- [ ] 写恢复失败测试：持久环境健康为 quarantined，第二实验被拒绝；中断后先核对持久状态、实际环境与文件。
- [ ] 运行失败测试，再实现核对策略：明确未执行可安全执行；明确完成返回已存结果；未知先恢复／隔离并保留未知记录，不能用聊天记录证明成功。
- [ ] 运行 `pytest tests/integration/runtime/test_reconcile.py -v`；与 B4 做真实端到端，仅修 A 所有文件；提交证据及限制。

## 首次交付收尾

- [ ] 在 P3 修复 A 所有路径中的联调缺陷，提交慢查询真实实验包、计划／实际统计、索引变更与恢复证据，以及当前观测缺项说明。
- [ ] 不增加 A5 扩展任务；N+1、深分页的专门观测与实验留待后续计划。

每个任务结束运行相应测试；整线交付再运行 `ruff check src/project_doctor tests/runtime tests/integration/runtime` 与项目统一类型检查。真实依赖缺失导致 skip 必须记为未验证。
