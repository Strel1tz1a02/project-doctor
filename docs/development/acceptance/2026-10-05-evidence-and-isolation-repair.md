# 2026-10-05 慢查询修复验收

结论：锁空快照误判、网络隔离退化、SQL 位置断言错误已修复；预热分离已完成真实链路验证。当前索引配方没有证明扫描工作量下降，诊断保留 lead。

## 修复范围

- 锁采集在正式请求前启动，通过 request ID、THREAD_ID、语句 EVENT_ID 关联。记录采集能力、原始事件和覆盖范围。仅输出 observed/unknown、partial，完整总锁等待保持 null。
- 应用和数据库只连接内部网络；独立入口仅绑定 127.0.0.1。实际容器网络与端口配置已核对。
- SQL 位置测试分别检查文件路径与 line==14；真实测试结束时清理环境，避免后续端口冲突。
- 两组分别恢复相同基线、准备和预热，组内正式请求之间不读取全库指纹。预热和正式请求分开记录，失败请求计预算。
- 请求预算同时受实验与任务剩余额度约束；任务制品剩余额度约束更大的实验预算。时间为恢复保留额度。
- 准备、预热、锁证据进入 JSON/HTML 报告；旧记录可读取但缺证据只输出 lead。
- MySQL JSON 使用 JSON 模式序列化，支持带时区锁窗口。存储测试使用唯一任务 ID，可重复执行。

配置与限制见 [预热与锁证据协议](../warmup-and-lock-protocol.md)。

## 验证结果

| 验证 | 实际结果 |
| --- | --- |
| scripts/check.ps1 | 227 passed、7 skipped；Ruff、格式、mypy 通过 |
| 真实目标容器测试 | 8 passed（包含 2 个受环境门控的真实测试） |
| 真实 MySQL 存储测试 | 9 passed（包含存储回环与锁窗口 JSON 回环） |
| 真实行锁／元数据锁阳性对照 | 2 passed |
| Git diff --check | 通过 |

上述验证分批执行。234 个测试中，233 个已通过；唯一未执行项是 Windows 符号链接权限测试。
锁阳性测试使用独立临时 MySQL，结束后已删除。目标测试环境已清理。评估数据集没有修改。

## 完整业务链路

- 测试根目录：`runtime-data/live-20261005/`，不提交 Git。
- 目标：本仓库 `demo/slow-query-demo` 的独立副本；构建时未改业务查询。
- 目标提交：`218108e7ca1c99348b6f8b8fd37dedf500307cb9`；平台包含本次未提交修复。
- 使用官方 MCP SDK 内存传输调用真实业务工具；工具选择由联调脚本指定，未进行 AGH 模型自主诊断评估。
- 请求：GET `/api/orders/search?email=user1&status=PAID&page=1&size=20`。
- 种子：50000 用户、200000 订单。
- 任务：`task-155cb0efc6065e3b8a9cc1a9`，状态 completed，实验 finished，最终恢复验证成功。
- 10 次预热、20 条正式样本，30 个独立请求 ID；业务断言及所有业务结果摘要一致。
- 440 条 SQL 调用、536 份实验证据制品；大小和 SHA-256 全部验证通过，锁采集错误为 0。
- 两组准备验证通过；实际锁状态 observed/unknown，覆盖 partial，未填造零等待。
- JSON/HTML 报告已生成，22 项 SQL 线索均保留 lead。N+1 等未覆盖路径由场景说明保留，不扩展为本次已支持诊断。

| 主列表 SQL（OrderMapper.java:14） | baseline | candidate_index |
| --- | --- | --- |
| 正式样本数 | 10 | 10 |
| SQL 耗时中位数 ms | 108.132 | 95.9305 |
| 扫描行数中位数 | 94732 | 94732 |

COUNT SQL（第 29 行）的耗时中位数为 94.802 / 95.1775ms，扫描行数均为 94712。
当前索引配方未降低扫描工作量，耗时差异也未满足稳定性门槛；完整锁覆盖缺失。这些观察不构成已验证性能收益。

本地制品：`verified-summary.json`、`isolation-verified.json`、`bundle.json`、MCP 调用结果和任务目录中的 `report.json` / `report.html`。
报告路径：`runtime-data/live-20261005/artifacts/tasks/task-155cb0efc6065e3b8a9cc1a9/report.html`。

Docker Desktop 起初因残留 socket 启动失败；仅备份并重建 socket 运行目录，没有重置镜像、容器或数据库数据。
目标容器已清理；本次专用平台 MySQL 停止并保留，便于复核。其他项目容器保持原状态。
