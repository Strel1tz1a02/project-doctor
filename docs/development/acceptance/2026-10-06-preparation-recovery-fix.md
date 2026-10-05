# 环境准备、取消恢复与真实 AGH 重测

结论：本次启动与收尾修复已通过回归及真实模型重测。Agnes 自主选取索引，实际调用八个业务工具完成实验到报告链路；任务 completed，诊断仍为 lead，不代表全部根因证明要求已满足。本次记录随修复代码一并提交。

## 修复内容

- AGH SDK 原有 60 秒请求时限与工具执行默认 120 秒时限分别处理。固定 AGH `2ef9b71`，使用仓库中的 `agh/apply_timeout_patch.py`：本次 SDK 等待 660 秒，三个长工具的 preset 上限 720 秒，平台预算 600 秒。只调整本次 `pd` 的长工具，不修改其他工具默认值。
- Docker 准备线程用 shield 等待；取消后在 AnyIO 屏蔽作用域内等待原线程结束，然后 teardown。清理成功持久化 failed；清理未知则保持 needs_reconcile。不会在旧线程可能继续启动容器时提前完成清理。
- 操作异常／取消结算实际墙钟时间，持久化原因并进入报告；ReportResult.limitations 与报告限制一致。
- MySQL 对任务加行锁，同一任务有 reserved/running/needs_reconcile 操作时，新 prepare ID 无法绕过互斥。真实并发预约回归确认两个不同 ID 只能接受一个。
- 工作副本排除 `.git/.hg/.svn`；保留提交与复制前业务文件哈希。旧副本只读文件清理受工作区路径检查约束。
- 即使没有 environment_id 或基线文件，finish_task 仍拆除确定归属该任务的 Compose 项目；缺基线不会被标为恢复验证通过。
- 增加数据库就绪、应用及种子就绪、快照三个阶段计时，留在隔离目录的 preparation-status.json。

## 启动慢的实际原因

未启用批量改写时，种子初始化批次中途已有约 12679 条已提交数据；应用启动本身约 4.8 秒，写入 20 万订单是主要等待点。

只在独立运行副本 JDBC URL 中增加 `rewriteBatchedStatements=true`。原始 datasets 内容未修改；8 个原始 Java/SQL 文件逐字节核对一致。数据量仍为 20 万，慢查询、索引配方和判定门槛未改。两个实验组共享此配置，优化用于实验前的种子写入，不作为索引干预变量。

运行副本新提交：55bd4d191d53ed4c3bcf4bc044f414c36a2548d1。
镜像：project-doctor-case01-probe:batch-20261006。

最终计时：数据库 16.492 秒；应用与全部种子就绪 11.444 秒；快照 0.847 秒；prepare_environment 总计 29.14 秒。

## 取消恢复验证

第一轮修复重测还遇到 AGH 的 120 秒执行限制，并暴露 AnyIO 重复取消，随后补上双层时限与屏蔽作用域。

第二轮未优化种子写入，经过超过 120 秒后由操作者通过 AGH 官方 session.cancel 结束。任务 task-004198334946e1d2a365124d 的 prepare-1 最终 failed，原因 `operation cancelled; preparation resources removed`，结算 337.233 秒，任务容器自动清除。操作者没有用 docker down 代替平台取消清理。

这证明取消结果已落库并完成资源清理，也说明取消等待不是立即停止 Docker：需等正在进行的后台操作结束。

## 最终真实诊断结果

任务：task-7a82a9e3a8d3cf5fc3657408。
AGH 会话：agnes:local:local-dev:cli:workspace:aabfc38176648289，159 条事件。

- 模型提出 2 个假设，自主选用 recipe:status-created。
- 1 次实际实验；两组各 5 次预热、5 次正式请求，合计 20 次请求。
- 两组准备校验、实验后恢复、最终收尾恢复通过；没有实验 failure。
- SQL 中位耗时：44.559 → 0.417 毫秒。
- 扫描行数中位数：200020 → 20。
- 任务 completed，1 个 finding 保持 lead。
- 锁证据仍为部分覆盖；耗时相对极差基线约 0.325、候选约 0.933，均超过原 0.25 门槛。没有为得到 verified 放宽规则。
- 68 个不同证据制品（含 JSON/HTML 报告）的文件大小及 SHA-256 核对通过。
- 平台 finish_task 自动清理，复核任务容器残留 0。

## 验证与制品

- 带 MySQL、Docker 的全量回归：238 passed，5 skipped。跳过项为 2 个未启用锁控制测试、2 个未配置固定目标的测试、1 个 Windows 符号链接权限测试；本次真实目标由上述独立模型重测覆盖。
- Ruff、格式检查、mypy、git diff --check 通过。
- AGH MCP register/connect 原有测试：62 passed。
- 本地忽略目录 runtime-data/agh-case01-20261005/ 保存 batch-bundle-final.json、batch-verified-summary.json、batch-session-final.raw.jsonl、repair2-prepare.json。
- 报告：artifacts/tasks/task-7a82a9e3a8d3cf5fc3657408/report.json 与 report.html。
- 旧探针 latest 文件已备份到 previous-probe；原始会话和旧任务报告仍保留。

AGH 适配代码、模型配置和运行副本仍为本地测试入口；本次不宣称已有面向用户的生产启动器，也不宣称已满足 verified 的首交付成功案例要求。
