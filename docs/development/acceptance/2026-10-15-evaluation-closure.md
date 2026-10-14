# 评估闭环最终验收（2026-10-15）：未通过／未运行

阶段 4（[acceptance 计划](../superpowers/plans/2026-10-15-evaluation-closure-acceptance.md)）。
路线图的最终判据是「同一冻结版本的 45 个真实运行包，不带 `--only-bundled`，达到
`global.overall_passed=true`、无缺包、`false_verified_count=0`」。**该判据未达成**，原因是执行环境缺失，
不是评分口径问题。本报告先写「什么能用、什么仍不可信、下一步」，再列逐项证据。

## 1. 什么能用（工程门槛与已修复缺陷）

| 项目 | 状态 | 证据 |
| --- | --- | --- |
| 仓库工程门槛 | 通过 | `./scripts/check.ps1`：414 passed / 17 skipped；ruff、format、mypy 全绿 |
| 数据集结构/隔离守卫 | 通过 | `tools/validate_cases.py` 45/45；`tools/isolation_guard.py` 45/45；`tools/guard_sut_separation.py` 通过 |
| 评测器单测与金标准回归 | 通过 | `python -m unittest discover -s evaluation` 158 项；14 例 fixture 逐用例总分未变 |
| 诊断侧误验证修复 | 已修复并回归 | 低选择性结论守卫（[阶段 1 记录](2026-10-15-diagnosis-quality-first-pass.md)）：六例历史包回放后 case-05 由 `verified` 变 `lead`，case-01/04 不受影响 |
| 评测器误判修复 | 已修复并回归 | 限制项逐机制覆盖（case-02、case-05 类别）+ case-02 多行 SQL 首行位置；[迁移说明](../../../datasets/docs/2026-10-15-evaluator-migration.md) |
| 未接通变量的伪对照防护 | 已修复并回归 | 按变量分派 + 显式拒绝（`scenario_invalid`，消息含「未接通」），避免「只测基线却声称候选级」 |

## 2. 什么仍不可信（未通过）

- **没有任何真实 Agent 运行包**：45 例逐例运行、六例新诊断运行、独立修复会话、独立复测全部未执行。
- 因此以下判据**未验证**（不得用 fixture、合成探针或 `--only-bundled` 分数代替）：
  `cases_evaluated=45`、`cases_missing_bundle=[]`、`false_verified_count=0`、`all_cases_passed=true`、
  `version_bound=true`、`overall_passed=true`。
- 37 个 boundary 用例的 `limitations_required` 从未被真实声明文本驱动过；本轮的机制判定只被
  case-02／case-05 两份真实文本验证过。
- N+1 与深分页的运行时干预未接通，也没有目标侧可逆开关；这两类问题在真实运行中只能得到
  `lead`/`unclassified`，其诊断规则只被合成/契约测试覆盖。
- 修复能力（`repair_*`）与交接链（`handoff_valid`）只在合成测试中跑通；真实修复会话、补丁与复测
  收益均无证据。
- 六例历史包在正式评测器口径下为 **3/6**（case-02/03/06 通过），与旧 `score_diagnosis.py` 的 4/6
  不是同一口径，不可直接比较；case-05 仍为误验证（旧包，不回溯改写）。

## 3. 阻断原因（实测）

| 前提 | 实测结果 |
| --- | --- |
| Docker Linux engine | 缺失（`docker` CLI 不存在）→ 无法创建隔离 MySQL/目标容器 |
| `PROJECT_DOCTOR_PLATFORM_DSN` | 未设置 → 平台任务/证据存储不可用 |
| `mvn` / JDK | `mvn` 缺失；本机 `java` 为 14，用例要求 JDK 17 → 目标服务无法构建启动 |
| AGH CLI / profile | `agnes` 不在 PATH；`E:\projects\agnes-harness` 与 `C:\Users\jvxi\.agh\profiles` 存在，需重建并核对 MCP selector |
| 产品侧案例运行器 | 不存在：`scripts/run_agh_case.py` 与 `tests/runtime/test_agh_runner.py` 于 2026-10-10 按用户要求归档（见 [恢复记录](2026-10-10-serial-version-restoration.md) 与 `runtime-data/serial-rollback-20261010/manifest.json`） |

## 4. 本阶段（Task 1）做了什么

阶段 4 的修复队列来自阶段 3 的失败矩阵；该矩阵因无真实运行而为空。因此本阶段只处理**已有真实证据**的
失败簇：

| 失败簇 | 原始证据 | 归因 | 最小修复 | 复评结果 |
| --- | --- | --- | --- | --- |
| 限制项整句匹配（case-02） | `runtime-data/serial-evaluation-20261013-retry3/sut-02/bundle.json` + `diagnosis-runs/case-02-*.json` | 评测器（要求整句 vs 分句联合） | `limitation_coverage` 逐机制覆盖 + 剥离脚手架/缺陷编号 | 该包 `passed` False → True |
| 多行 SQL 定位（case-02） | 同上 + `datasets/case-02-*/project/.../OrderMapper.java:14-23` | 评测器（expected 只登记第 21 行） | 增加 SQL 首行 15 为 accepted 位置（默认容差不变） | `code_location_hit` False → True |
| 取值/分布范围要求（case-05） | `sut-05/bundle.json` + `diagnosis-runs/case-05-*.json` | 评测器（同根因，要求在机制词汇外） | 机制词汇增加 `distribution_scope` | `limitation_declared` False → True；该包仍因误验证不通过（被测系统侧，已由阶段 1 守卫阻断，不回溯改写历史包） |
| 单值索引过度结论（case-05） | `sut-05/bundle.json` 实测行数（COUNT 模板 200000→159807） | 被测系统 | `slow_query` 低选择性守卫（阶段 1） | 六例回放后 case-05 变 `lead`（新运行才有效） |

未做无证据的放宽：没有下调金标准阈值、没有删除困难用例、没有改变 `MeasurementPolicy`、没有把
`--only-bundled` 或合成探针结果写入任何「通过」结论。

## 5. 版本与评估 ID（冻结记录）

| 项目 | 值 |
| --- | --- |
| 起始 HEAD | `0c9dae474404b5bd8f18dec9de8eb2ae36778c6a` |
| 本轮提交 | `1e71b84`（诊断守卫）、`23d477e`（评测器修正）、`ac7eb18`（按变量分派）、`665b453`（pagination 测试+矩阵）、`2d251de`（范围类要求 + 本报告） |
| 数据集哈希 | `7d1c1bbe4792a8a677adbd31992dec9a3863ecb02d8d1bba7fee272e16f37bcd` |
| 评测器哈希（当前） | `6f51e39396cd0a6d6dbf2e1acc4b8eb56afbae501fdb80e06bc793e8c4c14ca2` |
| 六例子集评估 ID（当前） | `7557aeff4c0cdc452fc00e29a0ab3d2b302b5bdfd04d5b33b226085a3dfd0001`（`fixture_only`） |
| 历史六例运行包 | `runtime-data/serial-evaluation-20261013-retry3/{diagnosis-runs,sut-0*}` |
| 评分报告 | 旧：`.../diagnosis-score/`（4/6，旧口径）；新：`.../diagnosis-score-20261015/`、`.../diagnosis-score-20261015b/` |

## 6. 下一步（解除阻断后才能宣称通过）

1. 提供 Linux Docker engine 与 JDK 17 构建能力；设置 `PROJECT_DOCTOR_PLATFORM_DSN`。
2. 决定是否恢复产品侧 AGH 单案例启动器（或提供等效入口），重建 CLI/profile 并核对 MCP selector。
3. 冻结版本后从零执行 45 例（含必要的独立修复与复测），逐例用
   `scripts/export_evaluation_run.py` 导出运行包。
4. 用 `python datasets/evaluation/run_eval.py --runs <45-runs-dir> --out <score-dir> --cases-root datasets`
   （**不带** `--only-bundled`）评分，逐项核对 §2 的六个判据；未通过则按失败簇回到 Task 1 继续修复。

在当前环境下，本路线图的最终判据**未达成**，如实记录为「未通过／未运行」。
