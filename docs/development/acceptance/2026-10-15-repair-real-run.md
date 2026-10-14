# 真实诊断→修复交接链审计与阻断（2026-10-15）

阶段 2 Task 1（[repair 计划](../superpowers/plans/2026-10-15-evaluation-closure-repair.md)）。
本任务只做审计、样本锁定与预检；**没有发起任何真实修复会话**。

## 1. 现有交接链接口（复用，未改动）

- `src/project_doctor/workflows/repair_handoff.py`：`export_repair_handoff(store, reader, task_id)` 要求任务
  已 `completed`/`partial`，只导出 `kind ∈ {slow_query, n_plus_one, deep_pagination}` 且
  `status ∈ {lead, verified}` 的持久化 Finding，并对每个候选跑 `validate_repair_handoff` 与
  证据校验；不导出任何 `case.json`、期望结论或补丁。
- `src/project_doctor/features/repair/gates.py`：`validate_repair_handoff` 校验 finding 已在任务内持久化、
  有代码位置/证据/实验引用、`recommendation.validation_status == expected_mechanism`、场景与 SQL
  调用可回溯、每个代码位置 commit 与任务一致且带证据关联；N+1 另需 `validate_handoff` 的
  `BatchQuerySpec`（`strategy=batch_in`、`child_code_location` 与 finding 一致）。
- `src/project_doctor/workflows/repair_facts.py`：`build_repair_facts(...)` 是唯一把持久修复状态转成
  `handoff.json` / `repair.json` 的地方；缺少独立修复会话、补丁制品损坏、finding 未持久化、
  commit 不一致等情况一律拒绝或记为缺失，不补造成功布尔值。
- 导出路径：`scripts/export_repair_handoff.py` → 独立会话 → `bundle.repairs` →
  `scripts/register_repair_facts.py --home …` → `scripts/export_evaluation_run.py --home … --case-id … --out …`。

## 2. 现有合同测试（合成探针，仅证明接口）

```text
uv run --locked pytest -q tests/repair/test_handoff_export.py \
  tests/repair/test_repair_facts.py tests/runtime/test_repair_handoff_evaluation.py
→ 23 passed
```

这些是契约/合成测试，**不等于**真实修复链通过。

## 3. 真实样本与判定（评测侧信息，禁止交给 Agent）

| 用例 | 类型 | 期望结论 | `expected.repair` | `expected.handoff` | 目标缺陷 | 角色 |
| --- | --- | --- | --- | --- | --- | --- |
| case-44-n-plus-one-article-author | boundary | verified | `expected_to_change=true`，目标 d1 | 声明（空对象） | d1 `ArticleService.java:32`（N+1，primary） | 应修 |
| case-07-n-plus-one-order-user | boundary | verified | `expected_to_change=true`，目标 d1 | 未声明 | d1 `OrderService.java:33`（N+1，primary） | 应修 |
| case-16-n-plus-one-stop-times-hotpath | boundary | lead | `expected_to_change=false` | 声明（空对象） | d1/d2 `BlockTripService.java:35/51` | 证据不足 |
| case-42-slow-query-unattributable-gain | boundary | lead | `expected_to_change=false` | 未声明 | d1 `OrderReportMapper.java:19`（收益不可归因） | 收益不可归因 |
| case-46-n-plus-one-out-of-bounds-stop | boundary | lead | `expected_to_change=false` | 声明（空对象） | d1 `ArticleService.java:32` | 越界停 |

补充：case-44/46 的 `expected.handoff` 为 `{}`（声明即评估 `handoff_valid`）；case-07/42 未声明
`expected.handoff`，其交接链不进入硬闸门，但仍是阶段 2「应修/克制」路径的样本。

## 4. 手工可审计交接 dry run 的预检（未执行）

| 前提 | 实测 | 结论 |
| --- | --- | --- |
| Docker Linux engine | `docker` CLI 缺失 | **阻断 1**：无法准备隔离目标与 MySQL |
| 平台 MySQL DSN | `PROJECT_DOCTOR_PLATFORM_DSN` 未设置 | **阻断 2**：任务/证据持久化不可用 |
| 目标构建 | `mvn` 缺失；本机 `java` 为 14，用例要求 JDK 17 | **阻断 3**：用户服务无法构建/启动 |
| AGH 可执行与 profile | `agnes` 不在 PATH；`E:\projects\agnes-harness` 与 `C:\Users\jvxi\.agh`（含 profiles）存在 | 需先重建 CLI 并核对 MCP selector，当前不可用 |

因此 `export_repair_handoff` → 独立修复会话 → `register_repair_facts.py` → `export_evaluation_run.py`
这条真实链路**未执行**。按计划要求，此处停止真实运行步骤，**未编造任何持久化 Finding、补丁或复测记录**。

## 5. 是否产生 RED 测试

没有可复现的真实失败可供归因（handoff / Agent 决策 / 补丁 / 复测 / 登记 / 导出六层均无真实轨迹），
按计划「没有失败就不改产品代码」，本任务未改动产品代码，也未新增测试。

阶段 2 的后续任务（Task 2 运行时接通 query_shape、Task 3 独立修复会话、Task 4 复测与登记）见
[阶段 2 任务 2 记录](2026-10-15-n-plus-one-runtime.md)（Task 2 已实现）与后续阶段；Task 3/4 保持
「未运行」，等待上述三项前提补齐。
