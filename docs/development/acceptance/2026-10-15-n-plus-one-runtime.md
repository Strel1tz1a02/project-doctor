# N+1／深分页运行时干预：接通状态与阻断（2026-10-15）

阶段 2 Task 2（[repair 计划](../superpowers/plans/2026-10-15-evaluation-closure-repair.md)）。
计划要求把 `variable=query_shape`（以及阶段 3 的 `pagination`）接到真实运行时干预。本记录的结论是
**不具备接通前提**，因此只做了「显式拒绝 + 能力边界声明」的最小改动，没有伪造候选级测量。

## 1. 现状核查

- `features/experiments/interventions.py` 已有 `parse_index_recipe` / `parse_query_shape_recipe` /
  `parse_pagination_recipe` 三个受控配方解析器（严格校验字段、策略、基线值必须与候选值不同）。
- `integrations/runtime_factory.py` 的 `run()` 此前**只按索引配方解析**：任何 `query_shape` /
  `pagination` 规格都会被 `parse_index_recipe` 以「only CREATE [UNIQUE] INDEX …」拒绝，报错语义错误
  （看起来像配方写错，而不是「该变量的运行时干预没接通」，容易被误读为可修复的输入问题）。
- 干预施加与恢复只走数据库：`recipe.create_sql` 经 `gateway.execute_sql` 应用，恢复走
  `_restore_after_run` 的数据库快照回滚。`query_shape` / `pagination` 是**应用运行时开关**（flag），
  数据库快照无法回滚它——现有网关没有「设置/还原运行时 flag 并重启服务」的能力。
- 数据集侧静态核对：`datasets/*/project/`（45 个目标）没有任何 `keyset` / `batch_in` /
  feature-toggle / `System.getProperty` 形式的可逆开关（仅少量与用例缺陷本身相关的 `@Value` 配置）。

## 2. 本轮改动（最小、可测）

- `interventions.py` 新增 `parse_intervention_recipe(variable, recipe)`：按 `spec.variable` 分派；
  `index` 返回 `IndexRecipe`；`query_shape` / `pagination` **先解析配方**（畸形配方仍报配方自身错误），
  随后显式抛出「受控运行时开关尚未接通：目标未声明可逆开关，不伪造候选级测量」；未知变量直接拒绝。
- `runtime_factory.run()` 改用该分派器 → 未接通变量以 `scenario_invalid` 明确失败，不产生任何观测。
- `agh/diagnosis-instructions.md`：明确 `query_shape` / `pagination` 会被拒绝，禁止凭静态命中宣称
  N+1/深分页已证实，只能 `lead`/`unclassified` 并写明限制。
- `agh/README.md`：记录上述能力边界与依据（静态核对 + 适配层单测，非真实会话复跑）。

## 3. 测试

| 测试 | 断言 |
| --- | --- |
| `tests/runtime/test_experiment.py::test_index_variable_returns_the_index_recipe` | `index` 仍返回索引配方 |
| `::test_unwired_variables_are_rejected_instead_of_faking_a_candidate[query_shape/pagination]` | 显式拒绝，消息含变量名与「未接通」 |
| `::test_malformed_recipes_still_report_the_recipe_error[4 组]` | 畸形配方仍报配方错误，不被「未接通」掩盖 |
| `tests/integration/runtime/test_slow_query.py::test_unwired_query_shape_variable_is_rejected_before_any_measurement` | 真实 `RuntimeService.run` 路径：`scenario_invalid`、无观测、未执行任何 SQL |

RED 证据：新增用例首次运行报 `ImportError: cannot import name 'parse_intervention_recipe'`（分派器尚不存在）；
实现后 `tests/runtime/test_experiment.py` 25 项、`tests/integration/runtime/test_slow_query.py` 10 项通过；
`./scripts/check.ps1` 413 passed / 17 skipped，ruff、format、mypy 全绿。

## 4. 未完成（阻断）

计划要求的「受控 flag → 基线/候选两级真实 SQL 调用、业务一致性、统计、恢复证据 → 持久化
`ExperimentResult` → `check_n_plus_one`」**未实现也未被验证**，原因：

1. 目标项目没有任何可逆运行时开关；实现 flag 切换需要先改造用例目标（新增受控开关并在
   `README`/配方中声明），这属于数据集与目标改造，不能在无 Docker 的情况下验证。
2. 网关缺少「设置/还原运行时 flag」的能力；新增该能力需要能在真实容器内重启服务并验证恢复，
   当前无 Docker、无平台 DSN、`mvn` 缺失、本机 JDK 14（用例要求 17）。

因此阶段 2 的 `query_shape` 实测、Task 3（独立修复会话）与 Task 4（复测/登记/评分）均保持「未运行」。
