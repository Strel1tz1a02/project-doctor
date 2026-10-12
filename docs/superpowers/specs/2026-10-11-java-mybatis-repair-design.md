# Java/MyBatis N+1 修复层设计

日期：2026-10-11。状态：已确认实施。

## 目标与范围

消费已持久化的 `Finding + Recommendation + BatchQuerySpec`，在隔离源码副本中完成 Java/MyBatis N+1 的 `batch_in` 永久改写，重建目标镜像，验证业务结果和性能，再记录可追溯的修复结果。其他策略返回明确的不支持结果，不猜测源码。原始目标仓库、诊断判据、评估数据和原始 Finding 证据不可改。

首版源码适配器处理 MyBatis `@Select` 注解，要求唯一 Java 调用点，并能从 `getXxx()` 参数确定父结果键。XML mapper 与其他调用形态返回不支持；后续可增设适配器，不扩张当前确定性校验的承诺。

## 修复流程

1. 平台按 `task_id + finding_id` 读取持久结论。要求 `kind=n_plus_one`、`status=lead|verified`、`fix_spec.strategy=batch_in`、`Recommendation.validation_status=expected_mechanism`；核对场景、父子 SQL、证据引用、mapper 位置和目标提交。
2. 平台在隔离目录复制目标源码，定位 `child_code_location` 的 MyBatis mapper 方法，并回溯唯一调用点。把必要的、有行号及文件哈希的源码片段交给模型。位置缺失、提交或哈希不符、调用点歧义时停止。
3. 模型提交统一 diff。首版平台只允许被定位的 Java mapper 和调用文件变更，校验路径、补丁上下文、原文件哈希、目标方法及批量查询形状；拒绝改测试、数据集、诊断规则、Dockerfile、构建脚本或仓库外文件。补丁仅应用到隔离副本，保存补丁与前后文件哈希。
   如果目标通过 mapper 方法名给 SQL 加请求标记，批量改写应保留该方法名，并将它的唯一调用移到原循环之前；新增无标记方法无法形成可归属的复测证据，诊断层必须拒绝收益声明。
4. 从已打补丁的隔离源码构建唯一镜像标签，记录镜像摘要；不得复用 `project-doctor-target:latest` 作为修复后镜像。编译失败即停止，保留日志。
5. 修复层把原提交镜像与补丁镜像交给诊断复测服务。诊断层在两个全新、独立的隔离环境中使用同一场景版本、数据快照内容、缓存/预热与负载协议；核对业务结果摘要、父结果关联键、SQL 次数、扫描量、锁证据与稳定重复样本。环境恢复与制品校验必须成功，诊断层返回比较结论及证据。
6. 修复结果单独持久化：原任务/结论/场景/实验、补丁摘要、源码与镜像身份、两个复测任务、正确性及性能证据。只有全部硬门槛通过，才将原 Recommendation 的 `validation_status`、`measured_gain_percent`、`retest_experiment_ids` 回填为复测值；其余 Finding 字段逐字保留。失败保留 `expected_mechanism`，收益为 null。

## 组件边界

- `models/repair.py`：修复请求、源码定位、补丁、构建和复测结果合同。
- `features/repair/`：交接校验和只回填三字段。
- `features/diagnosis/retest.py` 与 `workflows/diagnose_retest.py`：诊断层的复测比较和证据判定。
- `workflows/repair.py`：按状态串联目标检查、补丁应用、构建，并委托诊断层复测；使用稳定 operation ID 处理重试。
- `integrations/repair/`：源码副本、Git 补丁和 Docker 构建。
- `integrations/diagnosis/retest.py`：两个隔离镜像的运行时复测与证据发布。
- `TaskStore`：修复记录持久化；MCP 暴露只读定位、提交补丁、诊断复测和状态核对，AGH 负责模型提出补丁，平台负责执行和判定。

MCP `verify_fix` 在持久化状态变为 `retesting` 后立即返回该记录。诊断层继续在服务进程中运行；模型轮询 `get_fix_status`，只在持久状态为 `retested` 时报告收益。MySQL 修复记录是事实来源；进程持有的现有修复锁用于判断是否仍在执行。状态核对遇到无活锁的 `preparing` 或 `retesting`，以条件更新归为 `needs_reconcile`，不得自动重放。诊断层使用确定的两个隔离环境标识逐一关闭容器；异常退出和正常失败都先持久化清理待办，清理失败保留在修复记录中，下次查询可重试。重复 `verify_fix` 不启动第二个复测。修复工作流的直接 Python 调用仍可等待最终结果，MCP 入口只负责异步交付和进程内任务保活。

## 失败与验收

不具备结构化交接、源提交不符、找不到唯一调用点、补丁越界、构建失败、业务结果变化、SQL 次数未收敛、环境/证据未恢复或收益不可测时，修复不能标记 `retested`。同一操作重试返回同一结果；执行状态未知先核对，不重放副作用。验收包括合同/规则测试、补丁隔离与越界反例、真实 Java 编译、Docker/MySQL 原始与补丁镜像复测、AGH→MCP 工具调用与报告追溯。

本设计继承 [诊断到修复交接契约](../../development/b/handoff-to-fix-layer.md)；它的 `QueryShapeRecipe` 仍只用于诊断干预，不代表永久代码修复。

当前 `RuntimeService.run` 只执行索引配方，现有独立复测脚本也只允许同提交、同镜像的索引实验。因此修复复测需要共享其请求/SQL/锁采集原语，但单独定义两次 baseline-only 的源码版本对照；不得把索引复测脚本改名后当作修复验证。
