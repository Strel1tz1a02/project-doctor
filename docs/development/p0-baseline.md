# P0 公共基线与交接

首交范围：慢查询诊断到 JSON／HTML 报告；首个机制为缺少适用索引导致有代价扫描。
N+1、深分页及正式评估数据不在本次开发范围。

## 1. 当前交付与验证边界

| 内容 | 状态 | 证据／入口 |
| --- | --- | --- |
| 包骨架、职责目录 | 已实现 | `src/project_doctor/` 与 tests 各线目录 |
| v0.1 数据模型 | 已验证 | `tests/contracts/` 的 41 项合同测试 |
| Runtime、TaskStore、EvidenceReader | 已定义，未接真实实现 | 三个 ports 文件；静态类型检查通过 |
| 六组开发合同样例 | 已验证 | `tests/contracts/fixtures/`；序列化／反序列化一致 |
| JSON Schema | 已生成并校验 | `docs/contracts/v0.1/` 共 39 份；由代码生成，禁止手改 |
| 配置及检查命令 | 已实现 | `config/settings.example.json`、`scripts/check.ps1` |
| AGH／MCP／MySQL／Docker／真实目标实验 | 未验证 | A0、B0 接入探针仍需实际执行 |
| 慢查询判据、报告渲染、生产持久化 | 未实现 | A1～A4、B1～B5 后续实现 |
| 远端 CI | 未验证 | 本地检查已通过，工作流尚未在远端执行 |

这里完成的是用户指定的 P0 公共基线；原总计划中的整个 P0 还包含真实接入探针。
公共合同可以支持双方独立编码，但不能据此宣布真实目标已可测或 AGH 已集成。
未自行提交 Git；保留可审阅的本地修改，由负责人合入基线后双方从同一提交建分支。

## 2. 安装与检查

在仓库根目录执行：

```powershell
uv sync --locked --python 3.13
./scripts/check.ps1
```

等价命令：

```powershell
uv run --locked pytest tests/contracts
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
```

本地验证版本：CPython 3.13.15、Pydantic 2.13.5、pytest 9.1.1、Ruff 0.16.10、mypy 1.20.2；
确切 Python 依赖记录在 uv.lock。本版本组合只验证公共合同，AGH／MCP／数据库相关依赖尚未安装或锁定。
新增依赖仅由 B 更新 pyproject.toml 与 uv.lock，A 提交实际接入验证结果。

## 3. 公共合同的具体决定

- schema_version 固定为 0.1，未知字段拒绝；耗时用 ms，预算时间用秒，行号从 1 开始。
- 缺少观测值用 null；指标来源必须明确，计划估算不能填入实际行数／耗时。
- ExperimentSpec 本轮只有 index 变量，baseline/candidate_index 两组，每组至少三次。
- `intervention_recipe_ref` 指向 A 校验过的索引配方，模型不能直接提交任意 SQL。
- Scenario 保存 `preparation_recipe_ref`，参数与 parameter_sources 一一对应；状态码之外必须有业务断言。
- `restore_reserve_seconds` 明确恢复预算。模型只校验结构，实际计量／强制停止由 A 实现。
- CodeLocation 含提交、仓库相对路径、行号及关联证据 ID；路径统一为 POSIX 相对格式。
- EnvironmentHandle、ExperimentResult、RestoreResult、ReportResult 带 result_type，OperationResult 使用可区分联合。
- 缺失 AGH 标识为 null，同时在 missing_correlation 记录缺失项，禁止伪造调用 ID。
- TaskStatus、ExperimentPhase、EnvironmentHealth 是三套独立状态，不能复用一个字段。
- ReconcileResult.operation_results 使用 ReconciledOperation；避免任务与实验模型互相导入。
- ReportData.task 使用 ReportTask 摘要，完整 TaskRecord 在 TaskBundle；报告不会引入模型循环依赖。
- 模型的 verified 只表示必需结构齐全，不证明因果关系、制品可用或恢复真实发生。B 的诊断门槛和 A 的真实校验必须在后续实现。

## 4. A／B 对接与文件归属

| 负责人 | 公共接口／目录 | 后续责任 |
| --- | --- | --- |
| A | `features/experiments/ports.py` 的 Runtime | 执行、预算、独占、观测、持久结果、恢复、发布报告制品 |
| A | integrations、environments、experiments、execute_experiment、reconcile | 真实实现；禁止改 B 的判据与报告 |
| B | `workflows/task_ports.py` 的 TaskStore 合同 | 定义消费接口；A 实现 MySQL |
| B | `features/diagnosis/ports.py` 的 EvidenceReader 合同 | 调用证据校验；A 实现实际文件读取 |
| B | models、scenarios、diagnosis、reports、entrypoints、agh、根配置 | 场景、判定、报告、MCP 与实例组装 |
| 第三人 | `evaluation/data/` | 正式评估数据；本基线未创建或修改该目录 |

A 的 prepare/run/close 自己预留及结算业务操作，B 不重复扣预算或保存实验。
reserve 同 ID 同输入核对已有结果，同 ID 不同输入冲突，执行结果未知先 reconcile；P0 未实现数据库幂等逻辑。
A 发布 B 已渲染的报告内容及索引，不重新判定或渲染。
三个实现工厂待 A 创建，B 仅在 bootstrap 注入，不导入 A 内部表或容器代码。

## 5. 六组样例的使用

每份文件包含 synthetic、purpose、bundle、spec、evidence_check、expected_status。
verified_slow_query 是结构示例，其他五组分别提供缺位置、缺文件、不可比、恢复失败、未知结果。
其中 hash、SQL 耗时和来源均为人工合成占位；不对应实际制品或真实测量。
expected_status 用来解释开发测试意图，不是运行时输入，也不是正式评估答案。
双方可读取 bundle/spec 来编写测试假实现，生产入口不能读取 fixture 作为诊断结果。

重新生成：

```powershell
uv run --locked python scripts/generate_contract_fixtures.py
uv run --locked python scripts/export_contracts.py
./scripts/check.ps1
```

合同改动先确认跨线影响，再由唯一负责人修改代码／样例／Schema／总计划。
不兼容改动升级版本；同一版本不允许擅自修改字段语义或单位。

## 6. 配置方式

复制 config/settings.example.json 为 config/settings.local.json，调整三个互不包含的绝对目录及隔离网络。
Settings.model_validate_json 校验结构与目录边界；P0 不自动加载配置、不解析凭据、不创建外部目录。
platform_dsn_ref 为平台数据库连接引用，目标数据库配置由项目配方另管，二者不可混用。
允许网络只描述未来执行约束，P0 配置校验不等于已经实现网络隔离；A 必须验证实际请求目标与重定向。
agh/tool-policy.json 是未接入的声明，超时必须由 A 的实际执行器强制实施。

## 7. 下一步

A0：落实首个目标栈、启动／恢复配方及 SQL／计划／代码关联采集，验证平台 MySQL。
B0：接通真实 AGH→MCP→Python→MySQL→AGH，保存可获取的真实会话与调用记录。
两项接入探针未完成之前，A/B 可按合同开发和单测，但不能进入真实链路验收。
