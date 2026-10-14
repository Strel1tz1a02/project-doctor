# 诊断质量第一轮：误验证与评分误判修复（2026-10-15）

阶段 1（[first-pass 计划](../superpowers/plans/2026-10-15-evaluation-closure-first-pass.md)）。本轮响应
[失败复核](../../../runtime-data/serial-evaluation-20261013-retry3/diagnosis-score/failure-review.md)：
case-05 真实误验证、case-02 评分误判。

## 1. 身份冻结（本轮开始时）

| 项目 | 值 |
| --- | --- |
| 起始 HEAD | `0c9dae474404b5bd8f18dec9de8eb2ae36778c6a`（工作区仅 5 份未跟踪的计划文档） |
| 本轮提交 | `1e71b84`（诊断侧低选择性结论守卫）、`23d477e`（评测器限制项/定位修正） |
| 冻结时 HEAD | `23d477e3dec1d407d6f8f54d3b0ba1a985aad263` |
| SUT 源码指纹 | `7ab99a700010f9623abd88202369a288db23fa04566f4a4dc6e4cfc968f00e62`（`git dirty=false`） |
| 历史运行 Agent 版本 | `ba1782367c1e10da1520bf168067025c180a20cf`，指纹 `644d4c68379971e93698f412a33b43bc4189…`，`dirty=true` |
| 旧评测器哈希 | `0416f9f843fb444622ebd769197ddf177d87416ba47147468afb5a4bf875486b` |
| 新评测器哈希 | `c56d8a06f33daacb8afaca98e73c0a2a650bac1baf7999c92eb48fabfd0b8adc` |
| 新数据集哈希 | `7d1c1bbe4792a8a677adbd31992dec9a3863ecb02d8d1bba7fee272e16f37bcd` |
| 新评估 ID（子集口径） | `5b3ad8bf575f298331f98ae37af98a752c3671d31b8768728c5372bd74c09bbe` |
| 原始六例运行包 | `runtime-data/serial-evaluation-20261013-retry3/diagnosis-runs/{case-01…case-06}.json` |
| 原始会话/制品 | `runtime-data/serial-evaluation-20261013-retry3/sut-0{1..6}/` |
| 旧评分（原样保留） | `runtime-data/serial-evaluation-20261013-retry3/diagnosis-score/report.json`（4/6，误验证 1） |
| 新评分（本次） | `runtime-data/serial-evaluation-20261013-retry3/diagnosis-score-20261015/report.json` |

模型配置引用：本轮未发起新模型调用，沿用历史运行的 `model_id`（见旧报告 manifest），不在此重复记录密钥。

## 2. 改动

### 2.1 诊断侧：约束单值索引结论（`1e71b84`）

- 新增 `src/project_doctor/features/diagnosis/plan_scope.py`：`all_filtered(plan)` 从 v1（`query_block`/
  `ordering_operation`/`nested_loop`）与 v2（`query_plan`/`inputs`）计划的**全部**表节点取 `filtered`
  估计；非法/缺失/越界值一律忽略，畸形计划不会让诊断崩溃。`filtered` 只是提示，不参与判定。
- `slow_query.py` 在「扫描行下降且耗时可区分」（原 `verified` 分支）前增加证据范围检查：若实测中候选
  访问仍保留基线扫描的 **≥50%**（被查询取值不具选择性），且场景未记录分布证据，则降级为 `lead`，
  并在 `limitations` 记录已证参数、快照与未覆盖区间。不改变 `Impact` / `MeasurementPolicy`，不硬编码
  用例编号或 `filtered` 阈值。
- 历史六包回放（用记录在案的实测样本重跑 `check_slow_query`，非新运行）：
  `sut-01→verified`、`sut-02→lead/unclassified`、`sut-03→unclassified/lead`、`sut-04→verified`、
  `sut-05→lead/lead`、`sut-06→unclassified`。即 **case-05 的误验证在诊断侧消失，case-01/04 不受影响**。

### 2.2 评测侧：限制项逐机制覆盖与多行 SQL 位置（`23d477e`）

详见 [评测器迁移说明](../../../datasets/docs/2026-10-15-evaluator-migration.md)：`limitation_coverage`
逐机制在全部声明中查证并要求实质陈述（拒绝关键词堆砌）、剥离评测脚手架与缺陷编号；case-02 的
`expected.code_locations` 增加 SQL 首行 15（默认行容差 5 不变）。

## 3. 测试

| 命令 | 结果 |
| --- | --- |
| `./scripts/check.ps1`（pytest + ruff + format + mypy） | 405 passed / 17 skipped；ruff、format、mypy 全绿 |
| `tests/diagnosis/test_plan_scope.py`（新增 5 项） | 通过 |
| `tests/diagnosis/test_slow_query.py`（新增 5 项） | 通过 |
| `python -m unittest discover -s evaluation` | 156 项通过（含 14 例金标准回归，`GOLDEN_TOTALS` 未变） |
| `python -m unittest discover -s tools` | 53 项通过（1 skipped） |
| `tools/validate_cases.py` | 45/45 通过 |
| `tools/isolation_guard.py` | 45/45 合规，无泄漏 |
| `tools/guard_sut_separation.py` | SUT 源码未引用金标准 |

RED→GREEN 证据：`plan_scope` 缺失时 `tests/diagnosis/test_plan_scope.py` 报 `ModuleNotFoundError`；
新增慢查询守卫用例在实现前 2 项失败（`test_single_value_scan_retention_is_not_broadly_verified`、
`test_plan_filtered_estimate_never_decides_and_malformed_plans_do_not_crash`），实现后全绿。

## 4. 评分（同一批原始包，仅换评测器口径）

```text
python datasets/evaluation/run_eval.py \
  --runs runtime-data/serial-evaluation-20261013-retry3/diagnosis-runs \
  --out  runtime-data/serial-evaluation-20261013-retry3/diagnosis-score-20261015 \
  --cases-root datasets --only-bundled
```

- 该命令是**六例子集**评分（`mode=fixture_only`），**不是**全量真实验收；`--only-bundled` 只用于子集
  复核，39 个无包用例被跳过。
- case-02：`passed` False → **True**（`limitation_declared`、`code_location_hit` 由 False 变 True）。
- case-01 / case-04：旧口径通过 → 新口径不通过，失败闸门为 4 项修复能力闸门。二者在 `case.json` 里声明
  `expected.repair`，而本批是**纯诊断运行**（`retest.performed=false`、无补丁），按仓库正式评测器不应
  通过。旧 `diagnosis-score/report.json` 由 `score_diagnosis.py`（诊断专项口径）产出，**两个口径不可
  直接比较**；旧报告原样保留。
- case-03 / case-06 通过；**case-05 仍不通过**（`false_verified` 误验证、`decision_match=over`、
  `limitation_declared=false`）。该包是 2026-10-13 的旧 Agent 输出，本次诊断侧修复不回溯改写历史包。
- 全局（子集口径）：`false_verified_count=1`、`overall_passed=false`。

## 5. 环境预检与阻断

| 前提 | 实测 | 结论 |
| --- | --- | --- |
| `docker` CLI | 缺失（`Get-Command docker` 无结果） | **阻断**：无法创建隔离 MySQL/目标环境 |
| `PROJECT_DOCTOR_PLATFORM_DSN` | 未设置 | **阻断**：平台 MySQL 存储不可用 |
| `mvn` | 缺失；本机 `java` 为 14（用例要求 JDK 17） | **阻断**：目标用户服务无法本地启动 |
| AGH | `agnes` 不在 PATH；存在 `E:\projects\agnes-harness` 与 `C:\Users\jvxi\.agh`（含 profiles） | 未验证可执行，需重建 CLI 并确认 profile |
| 目标镜像 | 无法构建（无 docker） | **阻断** |

因此第一阶段第 3 项（六例新 AGH 诊断运行）**未执行**：本阶段交付的是代码、测试与六例历史包的重评，
**没有任何新的真实 Agent 运行包**，也不声称真实验收通过。

## 6. 未完成项（进入后续阶段）

1. 六例新的真实诊断运行包（依赖 Docker + 平台 DSN + AGH CLI + JDK 17）。
2. case-05 的 `limitation_declared` 已在本轮追加修正中通过（新增 `distribution_scope` 机制，见
   [评测器迁移说明](../../../datasets/docs/2026-10-15-evaluator-migration.md) 第二轮）；该历史包仍因
   **误验证**（`false_verified`/`decision_exact`）不通过，需由新运行包验证诊断侧修复。
3. 其余 37 个 boundary 用例的 `limitations_required` 尚无真实包复核。
4. 阶段 2 的修复链（独立修复会话、复测、登记）与阶段 3/4 的全量 45 例运行、冻结验收均未开始。
