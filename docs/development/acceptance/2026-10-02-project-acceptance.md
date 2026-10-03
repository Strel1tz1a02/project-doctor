# 首个交付验收：未通过

验收基准：`258f866`，2026-10-02。范围为慢查询诊断到 JSON/HTML 报告，不包含正式评估数据。此次未修改业务代码。

## 检查结果

| 检查 | 结果 |
| --- | --- |
| `uv sync --locked` | 通过 |
| `scripts/check.ps1` | 失败：pytest 172 passed、1 failed、3 skipped，后续检查被中止 |
| 单独 `ruff check .` | 通过 |
| 单独 `ruff format --check .` | 失败：design/performance-agent-deepdive-02-n-plus-one.md 的 Python 代码块格式 |
| 单独 `mypy` | 通过，75 个源文件 |
| 真实 MySQL 往返 | 本次未验证：PROJECT_DOCTOR_PLATFORM_DSN 未设置 |
| 真实容器、HTTP、SQL、恢复、报告闭环 | 本次未验证：Docker 不可用，交接文档中的目标源码目录不存在 |
| AGH 模型驱动诊断 | 未验证；现有 MCP 协议测试不能替代真实 AGH 链路 |

失败测试是 B 所有的 test_bootstrap.py：仍以 A 工厂缺失为前提。应使用 monkeypatch 明确模拟模块缺失，另测缺失 DSN，不能直接删除启动失败保护。

## 阻断发现

### 1. 中断操作被判成完成（A，P1，已复现）

位置：src/project_doctor/workflows/reconcile.py:47、integrations/mysql/operation_store.py:load_operation。
真实 store 对 reserved/running 记录也返回 OperationResult，即使没有 result_json。reconcile 将对象存在等同于已有最终结果。

复现：SQLite 使用正式 schema 插入 running 操作，以正式 load_operation 连接 reconcile；结果为 environment_health=available、operation state=completed、result=null、unresolved_operations=[]。

修复要求：按终态及持久化结果分类；running 无最终结果必须进入 unresolved 并持久化隔离，reserved 必须走未执行分支。回归测试须连接正式 store 语义，当前 FakeStore 返回 None 掩盖了问题。

### 2. SQL 无法归属到本次请求（A，P1，代码确认）

位置：integrations/observation/sql_probe.py:65、234。
查询是全局 history_long 最近 64 条标记 SQL，没有请求标识、线程关联或请求前后水位；探针丢弃 step/response。串行 HTTP 不会清除之前请求的 SQL，重复采样可能混入历史 SQL。代码位置标记不能证明请求关联。

修复要求：目标侧集成请求关联标记；采集必须隔离本次请求及重复次数，加入历史残留和并发背景 SQL 的验收用例。交接文档承认目标拦截器尚未接入，当前真实闭环仍缺组件。

### 3. 相同内容的制品跨路径导致 A/B 冲突（A/B，P1，已复现）

位置：integrations/artifacts/publish.py:47、features/diagnosis/gates.py:14。
A 用内容哈希作为 artifact_id，同样内容写入 baseline 与 candidate_index 不同路径时返回相同 ID、不同元数据；B 明确拒绝此情况。

复现：调用正式 publish_artifact 两次，在两个目录发布相同 `{}` 内容，将两个引用放入合同样例 ExperimentResult；正式 evidence_refs 抛出 `conflicting evidence metadata for the same artifact`。相同 EXPLAIN 计划属于正常情况。

修复要求：统一选择内容寻址的唯一规范路径，或为每个制品生成包含身份信息的 ID、保留独立 sha256；A/B 共同冻结规则并加入真实 publisher 到 gate 的回归用例。

### 4. 锁等待证据不完整却标为实际零（A/B，P1，代码确认）

位置：integrations/observation/sql_probe.py:98、perf_schema_row_to_sql_call。
模块自身说明 LOCK_TIME 不覆盖 InnoDB 行锁等待，却将其作为 lock_wait_ms 的 actual 来源；另将小于 0.05ms 的非零值舍入为零。B 的零等待门槛由此无法排除行锁干扰。

修复要求：采集足够的锁等待证据，或用 null/明确的指标覆盖范围使 B 降级为线索；不得通过舍入满足证据门槛。增加行锁与微小非零等待回归用例。

## 其他待修事项

- A：runtime_factory.py:458 将 spec.baseline_fingerprint 直接填入观测，没有对观测时的环境状态核验；candidate_index 也填相同值。需明确指纹范围并由实际状态生成，避免配置变化仍通过门槛。
- A：runtime_factory.py:426 的 artifact_bytes 只统计恢复引用，漏掉观测原始统计和计划制品，预算结算不完整。
- A：sql_probe.py:192 将所有 `?` 替换成 0，生成的是替代参数计划；必须标明限制，不能宣称是实际请求参数的执行计划。
- A：runtime_factory.py:508 接受直接 CREATE 文本，recipe 名称未做路径包含校验；应落实受控 recipe 引用规则。
- B：修复 bootstrap 过期测试；公共检查：修复 Markdown 格式问题。

## 复验门槛

先修复四项阻断并通过对应跨模块回归，再使公共检查全绿。准备可复现的目标源码与镜像、Docker 和平台 MySQL；在真实隔离环境完成请求→关联 SQL→实际统计→索引实验→恢复核验→JSON/HTML 报告，核对原始制品，并验证中断后的持久化隔离。AGH 发起并消费工具结果的链路也须实际运行。

正式评估集仍交由第三人处理；以上回归仅验证工程正确性。
