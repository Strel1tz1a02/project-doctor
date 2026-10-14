# 45 例真实运行与失败矩阵（2026-10-15，未运行）

阶段 3（[full-suite 计划](../superpowers/plans/2026-10-15-evaluation-closure-full-suite.md)）。
本文件是评测侧台账：**不得**交给被测 Agent。真实运行因环境缺失**全部未执行**（见 §4）。

## 1. Task 1：深分页 pagination 干预接通状态

与阶段 2 的 `query_shape` 同一结论、同一实现：`parse_intervention_recipe(variable, recipe)` 按
`spec.variable` 分派，`pagination` 先解析配方校验（策略 `keyset`/`max_page_limit`、基线值≠候选值），
随后显式拒绝为「受控运行时开关尚未接通」，`runtime.run()` 返回 `scenario_invalid` 且不产生任何观测。

- 单测：`tests/runtime/test_experiment.py::test_unwired_variables_are_rejected_instead_of_faking_a_candidate[pagination]`
  与 `::test_malformed_recipes_still_report_the_recipe_error[pagination]`。
- 集成：`tests/integration/runtime/test_slow_query.py::test_unwired_variables_are_rejected_before_any_measurement[pagination]`
  （真实 `RuntimeService.run` 路径，未执行任何 SQL）。
- 未做：受控 offset/keyset 切换、同页数据对比、扫描量/耗时证据、异常恢复——目标没有可逆开关，
  网关也没有「切换运行时 flag 并重启服务」的能力（详见
  [阶段 2 运行时记录](2026-10-15-n-plus-one-runtime.md) §1/§4）。
- 因此 `check_deep_pagination` 现有判定规则只在合成/契约测试中被覆盖（`tests/diagnosis/test_deep_pagination.py`），
  没有被真实 `candidate_pagination` 实验驱动过；对应用例只能 `lead`/`unclassified`。

## 2. 45 例台账（Task 2 Step 1）

`datasets/_template/case.json`（case_id `case-99-slow-query-template`）是模板，被
`validate_cases.is_reserved_name` 排除，因此真实用例为 **45** 个（与 `tools/validate_cases.py` 输出的
「合计 45 个用例」一致）。

| 用例 | 类型 | problem_kind | 期望结论 | limitations_required | expected.repair | expected.handoff |
| --- | --- | --- | --- | --- | --- | --- |
| case-01-slow-query-fullscan | normal | slow_query | verified | 0 | 是 | — |
| case-02-slow-query-composite | boundary | slow_query | lead | 2 | — | — |
| case-03-slow-query-unreproducible | failure | slow_query | unclassified | 3 | — | — |
| case-04-slow-query-user-index | normal | slow_query | verified | 0 | 是 | — |
| case-05-slow-query-skewed-status | boundary | slow_query | lead | 3 | — | — |
| case-06-slow-query-undersized | failure | slow_query | unclassified | 3 | — | — |
| case-07-n-plus-one-order-user | boundary | n_plus_one | verified | 2 | 是 | — |
| case-08-deep-pagination-large-offset | boundary | deep_pagination | lead | 3 | — | — |
| case-09-connection-pool-leak | boundary | connection_pool | lead | 3 | — | — |
| case-10-large-response-unbounded | boundary | large_response | lead | 3 | — | — |
| case-11-connection-setup-per-request | boundary | connection_setup | lead | 3 | — | — |
| case-12-excessive-logging-sync-debug | boundary | excessive_logging | lead | 3 | — | — |
| case-13-thread-pool-no-verifiable-defect | failure | thread_pool | unclassified | 3 | — | — |
| case-14-config-regression-pool-size | boundary | config_regression | lead | 3 | — | — |
| case-15-slow-query-threads-fullscan | normal | slow_query | verified | 0 | — | — |
| case-16-n-plus-one-stop-times-hotpath | boundary | n_plus_one | lead | 3 | 是 | 是 |
| case-17-connection-pool-background-hold | boundary | connection_pool | lead | 3 | — | — |
| case-18-deep-pagination-large-offset | boundary | deep_pagination | lead | 3 | — | — |
| case-19-large-response-unbounded-json | boundary | large_response | lead | 3 | — | — |
| case-20-connection-setup-client-per-request | boundary | connection_setup | lead | 3 | — | — |
| case-21-excessive-logging-sync-global-lock | boundary | excessive_logging | lead | 3 | — | — |
| case-22-thread-pool-input-starvation | boundary | thread_pool | lead | 3 | — | — |
| case-23-config-regression-summary-limit | boundary | config_regression | lead | 3 | — | — |
| case-24-slow-query-audit-log-scan-sort | normal | slow_query | verified | 0 | — | — |
| case-25-slow-query-leading-wildcard | boundary | slow_query | lead | 3 | — | — |
| case-26-n-plus-one-category-count-loop | boundary | n_plus_one | lead | 3 | — | — |
| case-27-n-plus-one-runner-step-log | boundary | n_plus_one | lead | 3 | — | — |
| case-28-connection-pool-nested-acquire | boundary | connection_pool | lead | 3 | — | — |
| case-29-connection-pool-growth-task-discard | boundary | connection_pool | lead | 3 | — | — |
| case-30-slow-query-date-function-column | boundary | slow_query | lead | 3 | — | — |
| case-31-n-plus-one-feed-author-like | boundary | n_plus_one | lead | 3 | — | — |
| case-32-connection-pool-long-tx-remote-call | boundary | connection_pool | lead | 3 | — | — |
| case-33-slow-query-or-cross-column | boundary | slow_query | lead | 3 | — | — |
| case-34-slow-query-implicit-type-conversion | boundary | slow_query | lead | 3 | — | — |
| case-35-slow-query-charset-mismatch-join | boundary | slow_query | lead | 3 | — | — |
| case-36-n-plus-one-product-category-brand | boundary | n_plus_one | lead | 3 | — | — |
| case-37-n-plus-one-section-course-resource | boundary | n_plus_one | lead | 3 | — | — |
| case-38-n-plus-one-repository-nested-commits | boundary | n_plus_one | lead | 3 | — | — |
| case-39-connection-pool-cursor-stream-hold | boundary | connection_pool | lead | 3 | — | — |
| case-40-connection-pool-hot-row-lock-hold | boundary | connection_pool | lead | 3 | — | — |
| case-41-connection-pool-response-stream-hold | boundary | connection_pool | lead | 3 | — | — |
| case-42-slow-query-unattributable-gain | boundary | slow_query | lead | 3 | 是 | — |
| case-43-connection-pool-config-not-root-cause | boundary | connection_pool | lead | 3 | 是 | — |
| case-44-n-plus-one-article-author | boundary | n_plus_one | verified | 2 | 是 | 是 |
| case-46-n-plus-one-out-of-bounds-stop | boundary | n_plus_one | lead | 3 | 是 | 是 |

按类型：normal 5 / boundary 37 / failure 3。按期望结论：verified 7 / lead 34 / unclassified 3。
只有 5 例声明 `expected.repair` + `expected.handoff`（case-44、16、46 与 case-01/04），其中 3 例要求
「不该改」（case-16/42/43/46 中的克制样本见阶段 2 记录）。

## 3. Task 2 Step 2：预检与冻结

| 项目 | 实测 |
| --- | --- |
| HEAD | `ac7eb18`（阶段 2 提交后），工作区干净 |
| SUT 源码指纹 | 见各阶段验收记录（每次改动后重新采集） |
| 数据集哈希 | `7d1c1bbe4792a8a677adbd31992dec9a3863ecb02d8d1bba7fee272e16f37bcd` |
| 评测器哈希 | `c56d8a06f33daacb8afaca98e73c0a2a650bac1baf7999c92eb48fabfd0b8adc` |
| 旧评分器（历史口径） | `score_diagnosis.py`，其 `scorer_sha256` 见旧报告 manifest（与新口径不可比） |
| 新评估 ID | `5b3ad8bf575f298331f98ae37af98a752c3671d31b8768728c5372bd74c09bbe`（六例子集，`fixture_only`） |
| `docker info` | **不可用**（`docker` CLI 缺失） |
| `PROJECT_DOCTOR_PLATFORM_DSN` | **未设置** |
| AGH 可执行 / profile | `agnes` 不在 PATH；`agnes-harness` 源码与 `C:\Users\jvxi\.agh\profiles` 存在，需重建 CLI 并核对 MCP selector |
| 目标镜像 / 构建 | 无法构建（无 docker；`mvn` 缺失；本机 JDK 14 ≠ 用例要求 17） |

## 4. Task 2 Step 3：运行入口核查（真实缺口，未擅自修复）

- `agh/` 下只有 `README.md`、`diagnosis-instructions.md`、`repair-instructions.md`、`tool-policy.json`、
  `apply_timeout_patch.py`；`scripts/` 下没有案例运行器（只有契约/导出/交接相关脚本）。
- 2026-10-10 的「恢复上轮串行版本」把 **AGH 单案例启动器 `scripts/run_agh_case.py` 及其测试
  `tests/runtime/test_agh_runner.py`** 连同持续负载/冷重启/源码绑定等一并归档，理由见
  [2026-10-10 恢复记录](2026-10-10-serial-version-restoration.md) 与
  `runtime-data/serial-rollback-20261010/manifest.json`（`saved_files` 含这两个路径的 SHA-256）。
- 因此「每例全新 cwd/session/task 的运行入口」当前**不存在于产品侧**；历史运行靠
  `runtime-data/` 下的一次性脚本（例如 `serial-evaluation-20261013-retry3/run_models.py`），
  按计划不得把它当作产品入口。
- 复活该启动器等于撤销 2026-10-10 的归档决定，且必须在真实 Docker+AGH 下验证；在本环境（无
  Docker/DSN/JDK 17）中无法完成验证，故**未新增**运行器，登记为需用户决策 + 真实环境验证的缺口。

## 5. Task 2 Step 4 / Task 3 / Task 4：未运行

- 小批次（正常/边界/失败各一例）与 45 例逐例运行、逐例导出、全量评分均**未执行**：无 Docker、
  无平台 DSN、无 AGH CLI、无 JDK 17。
- 现有可用证据仅限工程门槛与合成/契约测试：`tools/validate_cases.py` 45/45、
  `tools/isolation_guard.py` 45/45、`tools/guard_sut_separation.py` 通过、
  `python -m unittest discover -s evaluation` 156 项、六例历史包重评（子集口径，见阶段 1）。
- **没有** 45 个真实运行包，因此无法给出 `cases_evaluated=45`/`cases_missing_bundle=[]`/
  `false_verified_count=0`/`overall_passed=true` 的任何结论；不得用 fixture 或 `--only-bundled`
  分数代替。

## 6. 下一步（解除阻断所需）

1. 提供可用的 Linux Docker engine 与镜像构建能力（JDK 17 工具链）。
2. 设置 `PROJECT_DOCTOR_PLATFORM_DSN`。
3. 决定是否恢复产品侧 AGH 单案例启动器（或提供等效入口），并重建 AGH CLI/profile 后核对 MCP selector。
4. 完成后按 `scripts/export_evaluation_run.py` 逐例导出运行包，再用
   `datasets/evaluation/run_eval.py --runs <45-runs> --out <score> --cases-root datasets`
   （**不带** `--only-bundled`）评分。
