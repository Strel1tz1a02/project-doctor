# 评测器迁移说明：限制项逐机制覆盖与多行 SQL 位置（2026-10-15）

## 起因（来自真实运行复核）

`runtime-data/serial-evaluation-20261013-retry3/diagnosis-score/failure-review.md` 复核六例真实慢查询
诊断包后确认两处评测器缺陷，均属评测侧，不涉及被测系统：

1. **case-02（组合缺陷）限制项误判**：Agent 把「前导通配符 / N+1 / COUNT / 深分页 未能在单变量索引实验下
   证实」拆成多条真实分句分别陈述。旧规则把每条 `limitations_required` 当作一整段文本、用中文连续词串
   去匹配**单条**声明，导致分句联合覆盖被误判为「未声明」。
2. **case-02 多行 SQL 定位误判**：`findSlowOrders` 的 `@Select` 注解跨源码 14–23 行（SQL 文本自第 15 行
   起），旧 `expected.code_locations` 只登记第 21 行（`ORDER BY`），默认 ±5 行容差把「指向 SQL 首行」
   的真实回答判为未命中。

## 变更内容

### 1. 限制项判定：逐机制覆盖（评测侧）

- `evaluation/contract.py` 新增 `limitation_coverage(declared, required)`：
  - 先剥离评测侧脚手架（`必须声明…`）与数据集缺陷编号（`d2`、`d5/d4`）——两者都不是 Agent 能知道的
    内容（`_REQUIREMENT_SCAFFOLD` / `_DEFECT_ID`）。
  - 要求点名了已知机制时（本轮词汇：`前导通配符/LIKE`、`N+1`、`COUNT`、`深分页/offset`、`数据规模`），
    逐个机制在**全部声明**中查找，每个机制只要有一条实质陈述覆盖即可（可分散在多条真分句里）。
  - 「实质性」= 命中机制关键词的那条声明，去掉全部机制关键词后仍需留下 ≥6 个字符；把机制名堆成
    一串关键词（`"前导通配符 N+1 COUNT(*) 深分页"`）不算声明。
  - 要求没有点名已知机制时，退回原有 `text_covers` 容忍匹配。
- `text_covers` 本身也剥离同样的脚手架与缺陷编号，其余判定不变（公开签名不变）。
- `evaluation/metrics.py` 的 `limitation_declared` 改用 `limitation_coverage`（对全部声明联合判定）。

### 2. case-02 多行 SQL 首次行位置（评测侧）

- `case-02-slow-query-composite/case.json` 的 `expected.code_locations` 增加
  `OrderMapper.java:15`（`findSlowOrders` 的 SQL 首行），保留原有第 21 行。
- **默认行容差 `DEFAULT_LINE_TOLERANCE = 5` 未调整**；同文件其他方法（如第 30 行的 `countSlowOrders`）
  与其他文件仍然判为未命中。

## 影响面

- 只有点名上述 5 类机制的要求走机制路径；其余 `limitations_required` 一律走原容忍匹配，行为不变。
- 14 例金标准运行包 fixture 的逐用例总分、分组得分与通过判定**未变化**（`test_golden_bundle.py` 的
  `GOLDEN_TOTALS` 无需改写）；`python -m unittest discover -s evaluation` 156 项通过。
- 新增评测器单测：`test_metrics.LimitationCoverageTest`（分句联合覆盖、删任一分句即失败、关键词堆砌
  不算声明、无机制时容忍匹配）与 `ContractTest` 的脚手架/编号剥离用例、case-02 多行位置用例。

## 版本与哈希

| 项目 | 旧（20261013 口径） | 新（本迁移） |
| --- | --- | --- |
| evaluator_hash | `0416f9f843fb444622ebd769197ddf177d87416ba47147468afb5a4bf875486b` | `c56d8a06f33daacb8afaca98e73c0a2a650bac1baf7999c92eb48fabfd0b8adc` |
| `evaluation/contract.py` | `967345f85d98eb16749a0fe1717ce4250a788012bf4d82ac5512a31c8c46330e` | `3732a0e348426409834077fb54cb26479990e7dcc351038068fc21d1112d1434` |
| `evaluation/metrics.py` | `eb27881e2bd4f91d80d27680327e28609be32306efe58185fb5f5e49a070e158` | `ab4d5659d5521fcb65455c03d411b771a760c4e9c3448ba2019d413883791447` |
| dataset_hash | （旧报告未记录） | `7d1c1bbe4792a8a677adbd31992dec9a3863ecb02d8d1bba7fee272e16f37bcd` |

## 历史包重评（仅换评测器口径，不是新的 Agent 结果）

同一批原始包 `runtime-data/serial-evaluation-20261013-retry3/diagnosis-runs/`，命令：

```text
python datasets/evaluation/run_eval.py \
  --runs runtime-data/serial-evaluation-20261013-retry3/diagnosis-runs \
  --out  runtime-data/serial-evaluation-20261013-retry3/diagnosis-score-20261015 \
  --cases-root datasets --only-bundled
```

- 新评估 ID `5b3ad8bf575f298331f98ae37af98a752c3671d31b8768728c5372bd74c09bbe`（模式 `fixture_only`）。
- **case-02：`passed` False → True**（`limitation_declared` False → True，`code_location_hit` False → True）。
- case-01 / case-04：旧口径通过 → 新口径不通过，失败闸门为 4 项修复能力闸门。这两例在 `case.json` 里
  声明了 `expected.repair`，而这批包是**纯诊断运行**（`retest.performed=false`、无补丁），按仓库正式
  评测器不应通过。旧 `diagnosis-score/report.json` 由 `score_diagnosis.py`（诊断专项口径）产出，
  与新口径不可直接比较；旧报告原样保留，未覆盖。
- case-03 / case-06 通过，case-05 仍不通过（`false_verified` 误验证，属被测系统侧，见阶段 1 第一项改动）。

## 已知未修正（留给后续阶段）

- 其余 37 个 boundary 用例的 `limitations_required` 尚无真实运行包可复核；本轮不做无证据的放宽。

## 第二轮（同日追加）：取值／分布范围类要求

第一轮之后重评六例，case-05 的 `limitation_declared` 仍为 False。复核该包真实声明后确认：其三条要求
属「结论依赖取值／分布」类，同样存在「要求整句 vs 分句联合」的口径问题（要求里还带 `必须声明` 与
缺陷编号），属与 case-02 同根因的评测侧缺陷。据此在机制词汇中增加 `distribution_scope`
（`取值`／`分布`／`选择性`／`倾斜`／`高占比`），判定规则不变：必须有**一条实质声明**陈述该范围依赖。

- 新单测：`test_metrics.Case05LimitationCoverageTest`（三条要求被真实分句联合覆盖；删掉全部取值／分布
  声明或 COUNT 声明即失败）。
- case-05 重评：`limitation_declared` False → True；失败闸门只剩 `false_verified_false` 与
  `decision_exact`，即该历史包**仍然误验证**（属被测系统侧，已由阶段 1 的诊断侧守卫阻断，但不回溯改写
  历史包）。
- 版本：evaluator_hash `c56d8a06…` → `6f51e39396cd0a6d6dbf2e1acc4b8eb56afbae501fdb80e06bc793e8c4c14ca2`；
  `evaluation/contract.py` → `f910c83a4fe18888af4d23b686c3528b25816493cce65d6ba7be6d6f730218a4`
  （`metrics.py` 与 `dataset_hash` 不变）；新评估 ID
  `7557aeff4c0cdc452fc00e29a0ab3d2b302b5bdfd04d5b33b226085a3dfd0001`（六例子集，`fixture_only`）。
- 14 例金标准运行包 fixture 逐用例总分与通过判定仍**未变化**（158 项评测器单测通过）。
