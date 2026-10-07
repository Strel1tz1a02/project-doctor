# tools/ —— 数据集工具链

纯 **标准库** 实现（无第三方依赖），可在任意 CPython ≥ 3.10 上运行。

> 为什么不用 `jsonschema` / `pydantic`：本仓库约定的运行环境只保证标准库；
> 且 `project-doctor` 自身要求 Python ≥ 3.13，数据集工具不应被其依赖绑定。

## validate_cases.py

依据 `_schema/case.schema.json` 校验各数据单元的 `case.json`。

```bash
# 校验所有 <Datasets>/*/case.json
python tools/validate_cases.py

# 校验指定文件
python tools/validate_cases.py slow-query-demo/case.json

# 机器可读输出（供流水线消费）
python tools/validate_cases.py --json
```

退出码：`0` 全部通过 / `1` 存在失败 / `2` 用法或 schema 自身错误。

**保留目录过滤**：自动发现时会跳过保留目录——任何以 `_` 开头的目录
（如 `_template/`、`_schema/`）以及 `docs` / `tools` / `evaluation` / `.github`。
判定规则由 `is_reserved_name()` 提供，与 `isolation_guard.py` 保持一致。
因此模板目录 `_template/` 里即便放了 `case.json`，也不会被当作真实数据单元参与校验。

支持的 JSON Schema 关键字（draft 2020-12 子集）：
`$ref`、`$defs`、`type`、`enum`、`const`、`required`、`properties`、
`additionalProperties`、`minProperties`、`items`、`minItems`、
`minLength`、`maxLength`、`pattern`、`minimum`、`maximum`。

## test_validate_cases.py

```bash
python -m unittest discover -s tools -p "test_*.py" -v
# 或
python tools/test_validate_cases.py -v
```

测试覆盖：正常用例通过、必填缺失、枚举越界、`case_id` 正则、
`additionalProperties` 拒绝、`$ref` 解析、边界值（`minimum` / `minItems` / `minProperties`）、
`bool` 不被当作 `integer`、错误路径定位，以及仓库内全部真实 `case.json` 的端到端校验。

## isolation_guard.py

**答案隔离守卫**：把《数据集结构规范》里「运行时只暴露 `project/`」的约定变成可执行断言。
扫描每个数据单元的 `project/`，发现下列任一情况即判为泄漏：

| 判定 | 含义 |
| --- | --- |
| `missing_project` | 缺少 `project/` 目录，无法隔离 |
| `symlink_project` | `project/` 本身是符号链接 |
| `sensitive_file` | `project/` 内出现 `case.json` / `case.schema.json` |
| `symlink_escape` | `project/` 内存在指向其外的符号链接 |
| `vcs_dir` | `project/` 内混入 `.git` 等版本库目录 |
| `answer_reference` | 文本文件引用了 `case.json` / `_schema` / `Datasets/docs` / `ground truth` / `root_cause_ids` 等答案资产 |

```bash
python tools/isolation_guard.py            # 扫描所有数据单元
python tools/isolation_guard.py --json     # 机器可读输出
```

退出码：`0` 全部通过 / `1` 存在泄漏 / `2` 用法或 IO 错误。

## guard_sut_separation.py

**SUT 隔离守卫**：数据集以「方案 B」并入 `project-doctor` 仓库后，金标准与被测系统
（`src/project_doctor`）同处一仓。`isolation_guard.py` 只保证「用例 `project/` 不泄漏答案」，
无法覆盖「SUT 源码反过来读取金标准」这一新增风险，本脚本补上这道防线。

扫描 SUT 源码（缺省 `<repo>/src`），命中下列标记即判为泄漏（词边界匹配，
不会误伤 `DatasetProfile` / `dataset.py` 等合法标识）：

| 命中标记 | 含义 |
| --- | --- |
| `datasets` | 引用了数据集目录 |
| `case.json` / `case.schema.json` | 引用了问题卡 / schema |
| `ground truth` / `ground_truth` | 引用了金标准 |
| `root_cause_ids` | 引用了根因标识 |

```bash
python tools/guard_sut_separation.py            # 扫描 <repo>/src
python tools/guard_sut_separation.py --sut DIR  # 指定 SUT 源码目录
python tools/guard_sut_separation.py --json     # 机器可读输出
```

退出码：`0` 通过（或未找到 SUT 目录：独立数据集模式，自动跳过）/ `1` 发现泄漏 / `2` 用法或 IO 错误。

## test_guard_sut_separation.py

```bash
python tools/test_guard_sut_separation.py -v
```

测试覆盖：金标准标记扫描（含词边界正确性，`DatasetProfile` 不误报）、二进制跳过、
`scan_sut` 对「引用金标准 / 干净 / 目录缺失」的识别，以及对真实 SUT 目录的端到端断言。

## test_isolation_guard.py

```bash
python tools/test_isolation_guard.py -v
```

覆盖：保留名判定、越界符号链接判定、文本标记扫描、二进制跳过，以及 `scan_case`
对敏感文件 / 答案引用 / 缺失 `project/` / 版本库目录的识别；并对仓库内**真实数据单元**
做一次端到端隔离断言（`RealRepoTest`）。符号链接用例在无创建权限的平台上自动跳过。

## fixtures/

- `valid_case.json`：一个完全合规的 `normal` 用例样本，同时作为 schema 的活文档。
  测试基于它 `deepcopy` 后注入错误来构造各类非法样本，避免维护大量 fixture。

## .gitignore

数据集根的 `.gitignore` 只忽略**本地产物**（`__pycache__/`、`evaluation/runs|reports/`、
编辑器文件等），绝不忽略任何用例资产：`case.json`、`README.md`、`project/`、
`_schema/`、`docs/`、`tools/`、`evaluation/` 的源码都必须入库，否则评估不可复现。

## CI

本数据集并入 `project-doctor` 仓库后，其 CI 位于**宿主仓库根**的
`.github/workflows/datasets-validate.yml`（GitHub Actions 只识别仓库根的 workflows），
在 `datasets/**` 变更时触发，通过 `defaults.run.working-directory: datasets` 下钻到本目录执行，
分两个 job：

**`validate`** —— 结构与单测（快）：

1. `tools/test_validate_cases.py -v` —— schema 校验器单测；
2. `tools/validate_cases.py` —— 全部用例的 schema 校验；
3. `tools/test_isolation_guard.py -v` —— 隔离守卫单测；
4. `tools/isolation_guard.py` —— **答案隔离断言**（任一泄漏即失败）；
5. `tools/test_guard_sut_separation.py -v` —— SUT 隔离守卫单测；
6. `tools/guard_sut_separation.py` —— **SUT 隔离断言**（SUT 引用金标准即失败）；
7. `python -m unittest discover -s evaluation -p "test_*.py" -v` —— 评估器全部单测
   （指标模型与契约 `test_metrics.py`、双口径基线阈值 `test_run_eval.py`、
   金标准运行包回归 `test_golden_bundle.py`）；
8. `evaluation/run_eval.py` —— 打分流程干跑自检。

**`golden-regression`** —— 金标准运行包回归（独立信号）：

9. `evaluation/run_eval.py --runs evaluation/fixtures/run-bundle --out evaluation/out`
   —— 用 `fixtures/` 里冻结的十四份运行包（覆盖全部 14 个用例）跑完整七步流程；退出码 `0` 表示整轮结论通过。
   数值与结构断言（每例总分、双口径阈值、误验证为 0、失败用例基线允许波动等）
   由 `evaluation/test_golden_bundle.py` 承载——任何对指标 / 聚合 / 报告渲染的
   无意改动都会在此暴露，保证**评估结论可复现、可回溯**。

> 单独成 job 是为了在 CI 面板上把「评测器单元正确」与「整轮结论可复现」两个信号
> 分开显示，便于定位回归发生在指标层还是编排层。

> 并入前，该 workflow 位于 `Datasets/.github/workflows/validate-cases.yml`（独立仓库根直接生效）。
> 若日后迁出为独立仓库，需把它移回 `<Datasets>/.github/workflows/` 并去掉 `working-directory`。
