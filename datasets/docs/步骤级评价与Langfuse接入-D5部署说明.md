# 步骤级评价与 Langfuse 接入 — D5 部署说明

> 对应决策 **D5「我方完成部署」**：评测侧（判卷机）负责把「一次评估运行」在 Langfuse 上
> **需要落地的全部写请求**编排成一份**有序请求计划**，并在 Langfuse 实例就绪后由持有凭证的
> 操作者执行回放。
>
> **工作边界（红线）**：本模块**只组装请求、绝不发起任何网络请求、也不接触被测系统（SUT）**。
> 因此「部署」在此处的含义是：产出可审计、可回放、幂等的部署计划 + 回放脚本，而
> **不是**在本文档的构建过程中真的联网。真正联网的一次，是操作者在配好凭证后运行回放脚本。

---

## 1. 前置条件

### 1.1 Langfuse 实例与凭证
向 Langfuse 实例申请一对 API Key（Project Public Key / Secret Key），并确定实例地址。
回放前需设置三个环境变量：

| 环境变量 | 含义 | 示例 |
| --- | --- | --- |
| `LANGFUSE_HOST` | Langfuse 实例基址（不含尾斜杠） | `https://cloud.langfuse.com` |
| `LANGFUSE_PUBLIC_KEY` | Project Public Key（`pk-...`） | `pk-lf-xxxxxxxx` |
| `LANGFUSE_SECRET_KEY` | Project Secret Key（`sk-...`） | `sk-lf-xxxxxxxx` |

> 回放脚本用 Basic Auth（`public:secret`）访问，仅在脚本执行时读取上述变量；**本仓库不保存任何凭证**。

### 1.2 运行环境
- Python **3.10+**（本仓库默认 3.10.11，纯标准库，无需第三方依赖）。
- 回放：Windows 用 PowerShell（`replay.ps1`）；类 Unix 用 bash + `curl`（`replay.sh`）。

### 1.3 输入：一份评估报告
部署计划的输入是 `run_eval.py` 产出的 **`report.json`**（通常在 `evaluation/out/report.json`）。
若只有运行包、没有报告，可用 `evaluation/step_fixtures.py` 的 `evaluate_fixture` 离线生成/富化
报告（见《步骤级评价与Langfuse接入-交接说明.md》）。

---

## 2. 生成部署计划（离线、零网络）

在 **`datasets/` 根目录**执行：

```powershell
python evaluation/langfuse_deploy.py `
    --report evaluation/out/report.json `
    --dataset-name project-doctor-eval `
    --out evaluation/out/langfuse_deploy
```

常用参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--report` | 必填（缺省则执行自检） | `run_eval.py` 产出的 `report.json` |
| `--cases-root` | `datasets/` | 数据集根目录（读取 `case.json` 作为 Dataset Item 的 input） |
| `--dataset-name` | `project-doctor-eval` | Langfuse 数据集名 |
| `--dataset-description` | 空 | 数据集描述 |
| `--run-name` | 报告 `generated_at` | Dataset Run 名 |
| `--session-id` | 同 `--run-name` | 会话 id |
| `--steps-root` | `evaluation/fixtures/steps` | 步骤 fixture 目录 |
| `--no-enrich-steps` | 关 | **不建议**：关掉富化会让真实运行包产出 **0 span** |
| `--out` | `evaluation/out/langfuse_deploy` | 输出目录 |
| `--no-replay` | 关 | 不生成回放脚本 |

自检（无需任何参数，纯离线）：

```powershell
python evaluation/langfuse_deploy.py
# 期望输出：[ OK ] langfuse_deploy.py 自检通过：有序部署请求计划（dataset→ingestion→item→run_item）、
#           端点白名单、金标准不泄漏、确定性、回放脚本与落盘往返均符合预期
```

---

## 3. 产物结构

`--out` 目录下会生成：

```
evaluation/out/langfuse_deploy/
├── plan.json              # 有序请求清单（依赖顺序 / 端点白名单 / 计数 / 全部请求体）
├── requests/
│   ├── 01-dataset.json    # 每条请求的 {seq, kind, method, endpoint, note, body}
│   ├── 02-ingestion.json
│   ├── 03-dataset_item.json
│   ├── 04-dataset_item.json
│   ├── 05-dataset_run_item.json
│   └── 06-dataset_run_item.json ...
├── replay.ps1             # Windows 回放脚本（生成但**不自动执行**）
└── replay.sh              # 类 Unix 回放脚本（生成但**不自动执行**）
```

`plan.json` 关键字段：

| 字段 | 说明 |
| --- | --- |
| `dependency_order` | 固定为 `["dataset","ingestion","dataset_item","dataset_run_item"]` |
| `endpoints` | 端点白名单（与 `langfuse_export.ENDPOINTS` 同源） |
| `counts` | 各 `kind` 的请求条数与 `total` |
| `requests[]` | 有序请求列表，每项含 `seq` / `kind` / `method` / `endpoint` / `note` / `body` |

---

## 4. 依赖顺序与端点白名单

Langfuse 端点的先后约束（**必须按此顺序**，因为 item / run item 会引用 `traceId`）：

```
1) dataset           POST /api/public/v2/datasets        建 Dataset（按 name 幂等）
2) ingestion         POST /api/public/ingestion          摄入 trace/span/score（先建出 trace）
3) dataset_item      POST /api/public/dataset-items      建 Dataset Item（可引用 sourceTraceId）
4) dataset_run_item  POST /api/public/dataset-run-items  建 Dataset Run Item（引用 traceId）
```

- 先建 **trace**（步骤 2 的 `ingestion`），再建 **item / run item**，否则引用不到 `traceId`。
- 所有请求端点必须落在 `langfuse_export.ENDPOINTS` **白名单**内；越界端点会被 `_assert_endpoints` 拒绝。
- `ingestion` 的 body 为 `{"batch": [...]}`，事件类型用 **kebab-case**（`trace-create` / `span-create` /
  `score-create`），布尔一律写成 `1`/`0`；事件 id 由 `uuid5` 生成，**重复回放幂等**（不会重复建 trace）。

### 三层评价在 Langfuse 中的落点

| 评价层 | Langfuse 对象 |
| --- | --- |
| 用例（case） | Dataset / Dataset Item |
| 单用例的一次运行 | Trace（= Session 下的一次运行） |
| 一个诊断步骤 | Observation（span） |
| 步骤分 | Observation 上的 Score（`metadata.group == "step"`） |
| 用例总分 | Trace 上的 Score |
| 跨用例实验 | Dataset Run |

---

## 5. 防泄漏红线

`FORBIDDEN_GOLDEN_KEYS = ("expected", "defects", "root_cause_ids", "ground_truth", "expected_steps")`。

- 任何部署请求体都**不得携带**上述金标准字段，`_assert_no_golden_leak` 会递归扫描 body 的**键与字符串值**并拒绝。
- 整词边界匹配（`(?<![0-9A-Za-z_])…(?![0-9A-Za-z_])`，整条候选词用非捕获组包裹），因此可观测字段
  如 `expected_latency_ms` **不会**被误伤。
- 因此：**Langfuse 上只有「模型实际看到的输入」与「评分结果」**，评测方私有的标准答案始终留在本地。

---

## 6. 执行回放（联网的唯一步骤）

> 回放脚本**只生成、不自动执行**。请先核对 `plan.json` 与 `requests/` 内容无误，再执行。

### 6.1 Windows / PowerShell

```powershell
# 1) 设置凭证（当前会话内有效；请勿写入仓库）
$env:LANGFUSE_HOST       = "https://cloud.langfuse.com"
$env:LANGFUSE_PUBLIC_KEY = "pk-lf-..."
$env:LANGFUSE_SECRET_KEY = "sk-lf-..."

# 2) 按依赖顺序回放
powershell -ExecutionPolicy Bypass -File evaluation/out/langfuse_deploy/replay.ps1
```

`replay.ps1` 会：校验三个环境变量非空 → 用 Basic Auth 组头 → 按 `requests/*.json` 的 `seq`
顺序逐条 `Invoke-RestMethod -Method POST`，并打印 `[seq] POST <url>`；缺凭证时直接 `throw`。

### 6.2 类 Unix / bash

```bash
export LANGFUSE_HOST="https://cloud.langfuse.com"
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_SECRET_KEY="sk-lf-..."
bash evaluation/out/langfuse_deploy/replay.sh
```

`replay.sh` 用 `set -euo pipefail`，缺任一变量即中止，逐条 `curl -u "$public:$secret"` POST。

---

## 7. 回放后核验清单

- [ ] `plan.json` 的 `counts` 与 `requests/` 文件数一致（`total` 等于文件数）。
- [ ] Langfuse 上出现预期 Dataset（`--dataset-name`）、Dataset Item、Trace 及 Observation span。
- [ ] 每个用例 Trace 上的 Score 数、以及带 `group=step` 的 Observation score 数符合预期。
- [ ] 抽查任一 Dataset Run Item 的 `traceId` 与 ingestion 中 `trace-create` 的 `id` 对齐。
- [ ] 重复执行一次回放脚本：trace / score **不重复增长**（幂等）。若重复，检查 `uuid5` 命名空间是否被改动。
- [ ] 全站搜索：**不存在**携带 `expected` / `defects` / `root_cause_ids` / `ground_truth` / `expected_steps` 的字段。

---

## 8. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 产出 **0 个 span** | 真实运行包不含 `steps`，且用了 `--no-enrich-steps` | 去掉该参数（默认用步骤 fixture 富化） |
| 回放报 `401/403` | 凭证错误或未设环境变量 | 核对 `LANGFUSE_*` 三变量 |
| 回放报 404 | `LANGFUSE_HOST` 带尾斜杠或路径不对 | 基址不含尾斜杠，端点由脚本拼 `requests` 里的 `endpoint` |
| 请求被 `_assert_no_golden_leak` 拒绝 | 报告里混入了金标准字段 | 从报告/用例中移除该字段后重新生成计划 |
| 越界端点被拒 | 手工改了 `requests/*.json` 的 `endpoint` | 只用白名单端点，勿手改 |

---

## 9. 与整体流程的关系

```
执行侧产出运行包（7 层） ─┐
                          ├─► run_eval.py ─► report.json
步骤 fixture（14 用例） ──┘                     │
                                               ├─► langfuse_deploy.py ─► plan.json + requests/ + replay.*
                                               │                          （离线、零网络、无 SUT）
                                               └─► 【操作者】设凭证 → 运行 replay.* → Langfuse 落地

model_judge.py（阶段四，主观步骤 LLM 判分）──► 步骤分（source=EVAL, scope=STEP, group=step）
```

- 全流程**只读搬运 + 打分**，从不调用 SUT；步骤分**不进**硬门禁/总分（D4），仅作评分项与归因。
- 详细设计见《步骤级评价与Langfuse接入方案.md》，落地细节与模块清单见《步骤级评价与Langfuse接入-交接说明.md》。
