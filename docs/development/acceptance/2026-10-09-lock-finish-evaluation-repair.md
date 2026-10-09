# 2026-10-09：锁证据、终态保护与真实评估接入

本轮修复让真实慢查询正例首次走通 AGH 自主诊断 → `verified` 报告 → 新隔离环境独立复测。第 1 例通过冻结评分器的硬闸门，但不能因此宣称六例或首次交付全部验收通过。

评估数据、标准答案和评分器均未修改。未部署 Langfuse，也未扩展 N+1、分页或其他故障类型。

## 1. 修复内容

| 问题 | 修复 | 关键边界 |
|---|---|---|
| 完整锁证据没有正确落入 `SqlCall`，分步赋值触发合同校验 | 原子构造锁指标、指标来源和锁证据，再整体校验 | 精确零等待才生成实际 `lock_wait_ms=0`；累计上界保留 `null` 实测值 |
| 有语句 ID 和 `LOCK_TIME=0` 时，采集故障仍可能被当作完整覆盖 | 采集失败、计时关闭、计数回退或关联缺失均降为未知 | 原始错误与制品仍保留 |
| 50ms 轮询间隔被当作累计未观测锁等待上界 | 无精确行锁计数保证时采用整个采集窗口上界 | 多次短等待可以累计，不能只用一次轮询间隔 |
| 即使表锁实测仅 0.001–0.003ms，非零值也阻止整个索引实验判定 | 保留实际表锁时间，合并元数据锁上界后与 SQL 收益比较 | 不舍入为零；足以解释收益的锁耗时仍阻止验证 |
| 模型用新 operation_id 再次收尾，恢复已停止数据库后把 completed 降为 partial | 固定关闭/报告操作 ID；终态直接核验并返回已发布报告 | 报告损坏会报错，任务不重新打开；终态转移后中断可补发报告 |
| 收尾后还能重写场景、假设或结论，导致报告与数据库状态不一致 | completed/partial 后拒绝这三个修改入口 | 重复收尾仍可读取同一报告 |
| 终检偶发两个准备请求同时获得许可 | 等待任务锁后对操作记录使用当前加锁读；结算也先锁任务再锁操作 | 避免 REPEATABLE READ 旧快照；并发结算只计费一次，锁顺序统一 |
| 评分器仅消费示例运行包，没有执行侧实际导出 | 新增 `scripts/export_evaluation_run.py` | 核验任务、报告、完整结论、制品大小与 SHA-256；结论状态原样导出 |
| 没有独立执行修改建议复测 | 新增 `scripts/run_independent_retest.py` | 新任务、新环境、新准备记录和请求 ID；复用模型选出的单一配方，不调用模型或读取答案 |

锁证据的字段含义和单位见 [预热与锁证据协议](../warmup-and-lock-protocol.md)。本轮没有放宽 IQR、重复次数和最小差异门槛。

### 独立复测的含义

复测通过相同代码提交和种子配方重新建立环境。快照 ID 是内容哈希，相同数据可以产生相同 ID，不能为了“独立”而修改哈希。独立性由新任务、新环境、独立工作目录、实际准备记录和全新请求 ID 共同核对。

种子程序使用当前时间时，重新初始化会改变时间戳和跨轮业务摘要。因此正确性核对的是**同一次复测中，索引前后断言全部通过且业务结果摘要相同**。跨轮快照及业务摘要是否相同另行记录，不隐瞒差异，也不把同一次实验复制成独立复测。

请求收益使用复测的 HTTP 延迟中位数，只有两组各自满足原有稳定性门槛才提供百分比；不稳定时收益为 `null`。原 AGH 报告不会被复测结果重写，复测结论、制品、成本和工具轨迹单独附加。

## 2. 实际执行记录

### 冻结版本六例

目录：`runtime-data/agh-suite-20261009/`。

六个 AGH 会话均完成单次索引实验并发布 completed 报告，正式请求与预热各 10 次，结论均为 lead。这一轮暴露了“微小非零表锁耗时导致拒绝验证”的问题。发现问题后冻结该轮源码继续完成测试，没有中途替换后续案例的业务实现。

原始记录与评分分别保存在 `runtime-data/evaluation-20261009/pre-table-fix/` 和 `pre-table-fix-score/`。该轮评分不通过，误验证次数为 0。

历史六例也通过同一导出器接入评分器，独立保存在 `historical/` 和 `historical-score/`，不修改旧诊断状态。重试场景的成本采用完整工具时间跨度，避免只统计最后一次模型会话。

### 最终版本 AGH 正例

目录：`runtime-data/agh-final-20261009/sut-01/`。

- 实际模型：Agnes 3.0 Flash，AGH 核心工具循环；仅提供授权的公开源码，未发送评估答案。
- 任务：`task-7585096ec58d15ad75f8f99e`，会话：`agnes:local:local-dev:cli:workspace:24c86b9120746ff4`。
- 模型自主选择 `recipe:status-created`，一个索引实验；最终任务 completed，结论 verified，CLI 正常完成。
- 主 SQL 扫描行数中位数：200020 → 20；SQL 耗时中位数：33.679ms → 0.294ms。
- 最大锁累计上界为 0.002ms，证据为 `observed/complete`；实际总锁等待指标保持 null，没有声明零等待。
- 68 个不同证据/报告引用的大小与 SHA-256 核验通过；实验恢复通过，任务容器残留为 0。
- 模型总耗时 168.745 秒；平台实际操作预算记账 73.289 秒。两者分别记录，不用较小值代替完整耗时。
- 原始工具日志 `business-tool-calls.jsonl` 和 AGH 事件 `session.jsonl` 可重建执行过程；源码指纹保存于上级目录 `run-version.json`。

第 1 例在独立平台任务 `task-ddfcf5f2c47a60d37e162bed` 中复测，同样 verified；请求延迟中位数改善约 74.734%，业务断言与两组业务摘要一致，制品和恢复核验通过，换 ID 重复收尾返回同一报告。

### 最终版本六例独立复测

目录：`runtime-data/independent-retest-20261009/`。这是平台控制实验，**不是六个新的 AGH 自主诊断会话**。每例沿用此前模型选择的配方，最多一次实际索引实验。

| 案例 | 原 AGH 报告状态 | 最终平台独立复测状态 | 请求收益 | 业务一致/恢复/重复收尾 |
|---|---|---|---|---|
| 01 全表扫描 | verified（最终版新会话） | verified | 74.734% | 全部通过 |
| 02 复合索引边界 | lead（冻结版会话） | lead | 11.386% | 全部通过 |
| 03 已有索引反例 | lead（冻结版会话） | lead，另有 SQL 为 unclassified | 3.832% | 全部通过 |
| 04 用户索引正例 | lead（冻结版会话） | verified | 未确认：请求耗时不稳定 | 全部通过 |
| 05 倾斜分布边界 | lead（冻结版会话） | lead | 未确认：请求耗时不稳定 | 全部通过 |
| 06 小数据反例 | lead（冻结版会话） | unclassified | 3.095% | 全部通过 |

六例各有一个新平台任务、10 次预热、10 次正式请求；独立复测共核验 638 个证据/报告引用。跨轮种子时间戳不同，六例跨轮快照与业务摘要均不同；同一次复测的两档业务结果均一致。

03 的残余 lead 来自 COUNT 等基线耗时仍超过 1ms、但索引没有降低扫描量的 SQL。当前规则不会把“某个索引无效”直接推断为“整条 SQL 没有问题”，因此还没有达到数据集要求的整体 unclassified。04 验证的是 SQL 访问代价；HTTP 波动仍不能支持稳定请求收益，保留 null，不填造百分比。

最新合并运行包在 `runtime-data/evaluation-20261009/current/`，评分在 `current-score/`：**1/6 通过，误验证 0 次，整轮不通过**。01 通过全部硬闸门；02/05 缺要求的限制声明；03/06 的原 AGH 报告仍是旧版 lead；04 的原 AGH 报告仍是 lead，且独立请求收益未确认。平台复测的新结论不会覆盖这些原 AGH 报告。

平台复测自身的报告和轨迹另存 `platform-retest/`，明确标注无模型执行，不当作六次新的自主 Agent 会话。下一轮应在统一最终版本下重跑六例 AGH，并先处理上述业务边界与正式负载口径。

## 3. 运行包与评分命令

以下命令均从仓库根目录运行。源目录需要已有实际 `settings.json`、`manifest.json`、`bundle.json` 和原始制品；镜像使用源测试已验证的本地目标镜像。

```powershell
uv run --locked python scripts/run_independent_retest.py `
  --source-home runtime-data/agh-final-20261009/sut-01 `
  --out-home runtime-data/retest-new-run/sut-01 `
  --service-image pd-suite-sut-01:20261006

uv run --locked python scripts/export_evaluation_run.py `
  --home runtime-data/agh-final-20261009/sut-01 `
  --retest-home runtime-data/independent-retest-20261009/sut-01 `
  --case-id case-01-slow-query-fullscan `
  --out runtime-data/evaluation-20261009/current/case-01-slow-query-fullscan.json

uv run --locked python datasets/evaluation/run_eval.py `
  --runs runtime-data/evaluation-20261009/current `
  --only-bundled --out runtime-data/evaluation-20261009/current-score
```

复测目录必须是新目录，防止误重放。省略 `--retest-home` 时，导出器明确记录“未独立复测”。成本包含主诊断与复测两段，缺失的真实模型 token/API 费用保持未测；AGH 的估算 credits=0 不被当作实际费用为零。

评分器当前冻结哈希：`0a0fc5d84ec4b62b9848f88f595450a4a5c0119f9ffac254cb338b31cbd33d5a`。

## 4. 验证与剩余边界

最终 `scripts/check.ps1`：**273 passed、3 skipped**，Ruff、169 个文件格式检查与 80 个源文件 mypy 均通过。其中真实 MySQL 存储回环、行锁、元数据锁和完成语句证据控制均已运行；跳过项为未配置的两个真实目标探针与本机符号链接权限测试。新脚本已纳入默认类型检查。

并发准备漏洞在上述模型/复测结束后的终检中发现。修复后使用真实 MySQL 强制两个事务先建立旧快照，确认仅一个准备请求获得许可；新增并发结算单次计费验证，存储模块 12 个测试及最终全量检查通过。AGH 的 `run-version.json` 记录的是此项并发修复之前的业务版本；锁诊断与报告算法未再改动，没有把存储并发测试称为新的模型运行。

当前评分只是**串行、预热缓存的实际回归数据**。目标镜像复用已核验的六例副本，原始数据与代码不扩大；每组 5 次预热、5 次正式请求。没有执行数据集定义的并发 4、60 秒、cold_after_restart 负载，不能将当前评分当作该正式协议验收。

需交接给评估负责人核对的接口问题：

| 项目 | 实际 MCP 合同 | 当前步骤评分要求 |
|---|---|---|
| create_task | project、limits、operation_id | task |
| prepare_environment | context | repository |
| discover_scenarios | context | task |
| propose_hypotheses | context、items | observations |
| run_experiment | context、environment_id、scenario_id、scenario_version、spec | hypothesis |
| evaluate_evidence | context、hypothesis_ids、experiment_ids | hypothesis |
| reconcile_task | context | findings |
| finish_task | context | report |

导出器保留实际输入，不补造这些参数。需要评估侧按真实 MCP 定义修订结构检查，或独立增加执行协议适配版本；不能靠修改被测系统日志提高步骤分。

冻结评分器的 `no_lock_wait` 字段目前沿用旧名，导出器明确注明其含义为“完整锁覆盖，累计上界不足以解释 SQL 收益”，不是实测总锁耗时为零。建议评估侧将“精确零等待”和“排除足以解释收益的锁因素”拆成两个字段。

仍需处理：边界案例限制声明、已有索引/COUNT 等反例的结论聚合、与正式负载协议的对齐、实际模型 token 与 API 费用、自动 AGH 关联 ID。独立工具日志和会话事件可以追溯，但缺失 ID 不会被伪造补齐。新故障类型和在线 Langfuse 留待这些验收问题解决后推进。

运行制品和凭据均在 Git 忽略目录，本轮代码与文档未自动提交或推送。

清理核验：本轮 13 个实际任务的容器、网络和卷残留均为 0；私有 MCP 入口已恢复，临时 suite selector 已删除。此次启动的平台 MySQL 已恢复到原先停止状态，持久数据保留。原六个目标副本提交和工作区未改变；日志、导出包及待审 diff 中未发现本地模型凭据。最终源码、终检和清理记录保存在 `runtime-data/evaluation-20261009/verification.json`。
