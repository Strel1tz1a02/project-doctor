# 开发者 B：场景、诊断与 AGH Implementation Plan

> 执行方式：单名开发者执行；共享合同及文件归属见 [总计划](2026-10-02-two-developer-plan.md)。使用子 Agent 前须用户确认。

**Goal:** 首次交付 AGH 驱动的慢查询诊断到报告，验证有代价扫描的根因与证据，生成 JSON／HTML 报告。

**Architecture:** MCP 调用普通业务流程，流程通过三个能力入口消费 A 实现。诊断规则和报告可独立用合成合同样例验证，不依赖真实模型。

**Tech Stack:** Python、Pydantic、官方 Python MCP SDK、AGH、pytest、Ruff、类型检查；版本以 P0 探针结果锁定。

**Spec:** 总计划及其链接的 agent.md、两份设计文档；所有全局约束与审查风险均适用。

**范围排除：** 评估用数据交给第三人。B 不设计正式评估集、制作样本、标注答案或制定评估指标；保留代码正确性需要的合同 fixture、规则测试和端到端测试。六组 synthetic fixture 仅为开发用最小样例，不能称为正式评估数据。`evaluation/data/` 不由 B 修改。

**首交边界：** 本轮只实现慢查询／有代价扫描，优先缺少适用索引的机制；N+1、深分页不开发专门判据，无法归因的慢链路保留线索。

## B0：骨架、共享合同和 AGH 探针

公共骨架、模型、三个接口、六组合同样例、Schema、配置与检查入口已由 P0 基线完成，见 [交接记录](../../development/p0-baseline.md)。B 从现有代码继续，不能重新设计或重复生成另一套合同；测试假实现按 B1～B3 所需补充。真实 AGH／MCP／MySQL 探针尚未完成，仍属于 B0。

**Files:** `pyproject.toml`、依赖锁文件、`.gitignore`、`src/project_doctor/**/__init__.py`、`models/`、`workflows/task_ports.py`、`features/diagnosis/ports.py`、`entrypoints/settings.py`、`tests/contracts/`、`agh/`、`docs/development/b/compatibility.md`。

**Interfaces:** 完整落实总计划 v0.1，含 TaskStore、EvidenceReader；与 A 签认 Runtime，后者由 A 创建。Settings 明确 platform_dsn_ref、artifact_root、workspace_root、allowed_target_network、tool_timeouts、model_config_ref；不保存明文密钥。

- [ ] 写模型测试：未知字段拒绝、ms 单位非负、行号正整数、证据摘要格式有效、至多三假设、唯一变量、缺值为 null；六组 fixture 可以 round-trip。
- [ ] 运行 `pytest tests/contracts -v` 确认失败，再创建对应模型、JSON Schema、就近 ports、包骨架及假实现；通过后交 A 冻结提交。
- [ ] 探针通过真实 AGH 模型调用一个 MCP 工具，工具写入并读回平台 MySQL，返回结构化结果；A 尚未实现 store 时只在 `tests/integration/agent/probe/` 写临时探针，最终删除，不建第二套产品存储。
- [ ] 保存真实工具输入输出、会话 ID 和可获取的调用 ID；不可获取的记 null。记录 AGH 提交／版本、Python、MCP、驱动和迁移库版本，探针通过后锁定依赖。
- [ ] 确定统一类型检查器及命令写入 pyproject.toml／CI；提交共享基线。探针失败时报告兼容问题，规则开发仍可继续，但不能称 AGH 已接通。

## B1：候选场景、数据适用性与复用

**Files:** `features/scenarios/{discover,validate,deduplicate,applicability}.py`、`workflows/tasks.py`、`tests/diagnosis/test_scenarios.py`。

**Interfaces:** `discover(project: ProjectInput, repository_manifest: dict) -> list[Scenario]`；`validate(scenario: Scenario) -> list[Failure]`；`dedup_key(scenario: Scenario) -> str`。manifest 只包含本次目标已支持的路由／OpenAPI／现有测试来源，不开发全语言解析器。

- [ ] 写测试：凭据只有引用；请求有参数来源及业务断言；推断操作标 source；缺必需参数列未覆盖路径；HTTP 200 不替代业务断言。
- [ ] 写去重测试：同 URL 不同准备／参数类别／数据规模／负载不能合并；用户纠正另存版本；新任务不得重用历史测量。
- [ ] 运行 `pytest tests/diagnosis/test_scenarios.py -v` 确认失败，再实现首个目标场景生成、适用性摘要和场景保存；缺分布标合成／未知，不能自动认为现实代表性成立。
- [ ] 运行同命令通过后提交 B 文件；用假 store 验证，不等 A 数据库实现。

## B2：慢查询根因与证据的程序判据

**Files:** `features/diagnosis/{gates,slow_query,compare}.py`、`workflows/diagnose.py`、`tests/diagnosis/test_slow_query.py`。

**Interfaces:** `async evaluate(bundle: TaskBundle, reader: EvidenceReader) -> list[Finding]`；`check_slow_query(observations: list[Observation], hypotheses: list[Hypothesis]) -> Finding`。evaluate 先取持久实验并校验证据，纯规则函数不接模型客户端。

- [ ] 先写反例：仅 type=ALL、扫描比值大、没有索引或超过示例耗时均不能证明根因；实际代价未成立、锁等待未排除、估算冒充实际统计、缺代码位置、业务无效、制品损坏、恢复失败或实验不可比，均不能 verified。
- [ ] 写支持案例：有效请求关联到具体 SQL 和固定提交代码位置，有实际耗时／工作量与计划；临时索引前后仅一个因素变化、业务结果一致、访问路径及实际代价变化符合预测，锁等待／缓存变化等竞争解释有可核对的排除依据；恢复成功，报告本次条件与现实影响未知项。
- [ ] 定义可配置测量稳定策略：重复样本、组内离散度、组间差异及最小可检测差异随运行保存；样本不足／差异落在噪声内输出 evidence_insufficient，不以单次耗时降低证明索引收益。
- [ ] 运行 `pytest tests/diagnosis/test_slow_query.py -v` 确认失败，实现证据门槛与假设 supported/refuted/unresolved 更新；模型文字不能提升状态。无用户性能目标时仅说明测试条件下的退化机制，不自造业务 SLA；其他慢查询原因尚不支持时保留线索。
- [ ] 运行同命令通过，提交 B 文件；案例使用 synthetic fixture，不称真实链路验证。

## B3：报告和受控工具入口

**Files:** `features/reports/{rank,render_json,render_html}.py`、`workflows/diagnose.py`、`entrypoints/{mcp_server,bootstrap}.py`、`agh/{diagnosis-instructions.md,tool-policy.json}`、`tests/diagnosis/{test_report,test_tools}.py`。

**Interfaces:** `build_report(bundle: TaskBundle) -> ReportData`；ReportData 放 models/finding.py；JSON／HTML 只消费同一 ReportData。MCP 工具输入输出严格按总计划表。

- [ ] 写报告测试：每张 verified 卡具备接口、条件、SQL、提交／路径／行、原始证据、实验、竞争解释、影响、建议／代价；线索与未分类异常分列。
- [ ] 写排序测试：同请求／SQL 两机制不双计全部耗时；无干预仅展示估计；无代表性流量不写线上优先级；未复测建议不写提升百分比。
- [ ] 写工具测试：用户／模型伪造观测不被接受；四个以上假设拒绝；run 调 A Runtime 一次且不重复扣预算；finish 恢复失败仍输出部分报告及隔离状态。
- [ ] 运行 `pytest tests/diagnosis/test_report.py tests/diagnosis/test_tools.py -v` 确认失败，再实现薄 MCP、流程组装及报告；HTML 转义不可信 SQL／路径／模型文字，制品引用只解析可信根目录。
- [ ] AGH 指令按“适用性→至多三假设→预测→单变量实验→证据更新→下一动作／收尾”；预算耗尽输出部分报告。初始化可用假实现，生产入口不可静默回退假实现。
- [ ] 运行同命令通过并提交 B 文件；报告输出经 A 制品发布能力保存，不直接写入目标仓库。

## B4：接 A 的真实实现并验收慢查询到报告

**Files:** `entrypoints/bootstrap.py`、`tests/e2e/test_slow_query.py`、`tests/integration/agent/test_real_tool_chain.py`、`docs/development/b/p2-evidence.md`。

**Interfaces:** 调总计划三工厂并注入；不导入 A 内部表或调用 Docker。报告通过 `Runtime.publish_report(data: ReportData, context: CallContext) -> ReportResult` 保存；B0 冻结、A 制品实现，不新增跨线接口或模型可调用工具。

- [ ] 编写端到端断言：真实慢查询有基线／临时索引对照、业务结果一致、实际统计与执行计划，全部证据能读回且 hash 正确，SQL 到代码可定位，临时索引撤销及目标恢复验证成功，报告 verified 条目可逐项复核。
- [ ] 增加反例链：缺位置／无效业务／恢复失败不能变 verified；重复 run 不重复请求；重启后 reconcile 返回真实核对结果。
- [ ] 实际 AGH 运行并导出多步调用记录；核对模型确实经 MCP 调了场景、假设、实验、证据及收尾工具，不以离线脚本替代这项验收。
- [ ] 运行 `pytest tests/e2e/test_slow_query.py tests/integration/agent/test_real_tool_chain.py -v`；实际 AGH 测试需配置模型凭据，缺配置记未验证。
- [ ] 保存 JSON／HTML 和真实记录索引；只修 B 文件，A 缺陷交 A；提交 B 文件。

## B5：慢查询首次交付收尾

**Files:** `tests/diagnosis/test_slow_query.py`、`tests/e2e/test_slow_query.py`、`README.md`、`agent.md`、CI。

**Interfaces:** 沿用 evaluate、Finding 与合同；仅收尾 A3／A4 与 B2～B4 的慢查询链路，不新增诊断类型。

- [ ] 核对真实慢查询支持案例、不会误判的反例以及证据缺失／不可比／恢复失败的完整链路结果，修复 B 所有路径中的缺陷。
- [ ] 核对报告具备 SQL、提交／代码行、计划、实际测量、对照结果、恢复记录、竞争解释、修改建议与适用限制；未实施的建议不宣称优化收益。
- [ ] 运行 `pytest tests/diagnosis/test_slow_query.py tests/e2e/test_slow_query.py -v`；最终 `pytest`、`ruff check .` 和统一类型检查通过，外部测试 skip 逐项说明。
- [ ] 更新 README 与 agent.md 的已实现／已验证边界，交付启动方法、慢查询 JSON／HTML 报告、恢复及中断证据；说明当前仅验证的慢查询原因和目标栈，N+1／深分页后续安排。
