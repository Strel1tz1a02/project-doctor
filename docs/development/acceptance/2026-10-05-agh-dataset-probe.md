# 2026-10-05 数据集案例 AGH 真实接入测试

结论：Agnes 模型已通过真实 AGH 会话调用 Project Doctor MCP 业务工具；数据集首个正常案例未通过，环境准备在 MCP 60 秒超时处中断，未进入索引对照。不能将模型静态分析或部分报告称为已完成根因诊断。

## 环境与隔离

- 平台提交：365b4ed；未修改产品代码、证据门槛或评估数据。
- AGH 本地提交：2ef9b71f36f6af70af405f20f82369c13d91d82e；Node 24.18.0。
- 模型：Agnes 3.0 Flash，通过官方中国网关。用户明确授权本次调用；凭据仅在本地忽略目录，通过环境 secret 引用加载，未进入源码、提示词和最终会话导出。
- AGH 使用独立 Home、独立 daemon；禁用 code 包、Computer Use 和 subagent，模型只使用 MCP 业务工具及工具描述。
- 测试案例：datasets/case-01-slow-query-fullscan。模型只获得 project/ 的源码说明、SQL、服务代码和受控配方库存；case.json、案例维护者 README、评测代码和标准答案未提供给模型。
- 数据集原目录只读；运行副本位于 runtime-data/agh-case01-20261005/target。原始业务 Java 与 SQL 哈希未变，仅原配置文件增加 DB 环境变量支持，另加 SQL 标记、就绪监听器、Dockerfile 与候选配方。
- 副本冻结提交：d782e85545a823fad302daee0b19adeeb4bfe2dc。SQL 标记指向实际 SQL 首行 OrderMapper.java:14；不依据标准答案指定行号。
- 镜像：project-doctor-case01-probe:20261005。计划请求 GET /api/orders/recent?status=PAID&size=20，20 万订单；预算最多 1 个实验、24 个请求，预定每组 5 次预热和 5 次正式请求。

## 接入探针与实际执行

前置连通和目录检查已经通过，但不是诊断成功的证据。

1. 首次目录接入使用较长服务名 project-doctor-probe，AGH 生成的工具 prefix 超过 extension-manifest Schema 的 33 字符限制，挂载失败。使用短名 pd 后正常。
2. 第一轮模型将引用 Schema 中的对象参数编码成字符串，工具校验拒绝，未创建业务任务。已取消并保留记录。
3. 临时适配器将 $defs/$ref 展开成自包含 Schema，语义校验仍由原业务模型执行。随后模型能够传对象。第二轮又暴露临时审计器未处理元组内 Pydantic 对象的问题；已修复并验证。这是测试设施缺陷，不算产品诊断失败。
4. 最终会话真正调用 create_task、prepare_environment、discover_scenarios、propose_hypotheses、reconcile_task、finish_task。完整事件可核查，不能以 scripted 联调替代。

最终 AGH 会话：agnes:local:local-dev:cli:workspace:31e2b362c6ffd660。

任务：task-3856b8d080d86a6de480f6a0。

| 实际结果 | 值 |
| --- | --- |
| AGH 事件数 | 482 |
| 工具调用 | 30：22 次业务工具、8 次工具描述 |
| 工具错误 | 9 |
| 持久假设 | 3，保持 proposed |
| 索引实验 | 0；run_experiment 未执行 |
| 正式测量请求 | 0 |
| Finding | 0 |
| 任务状态 | partial |
| 报告 | JSON 与 HTML，文件大小和 SHA-256 均通过核对 |

模型依据源码倾向选择 recipe:status-created，但没有执行，不构成运行验证，也不能支持 verified。

## 暴露的阻断和缺陷

1. **MCP 长操作超时未对齐。** 平台工具允许 600 秒，但 AGH 当前 conn.callTool 仅传 signal，底层 MCP JS SDK 在约 60 秒超时。应用尚处初始化时 prepare_environment 被取消。需要端到端统一调用超时，或改成长操作启动／查询协议；本次没有私改 AGH 源码或协议。
2. **首次准备取消后状态不可恢复。** prepare-1 保留 running/reserved，reconcile 返回 unresolved，后续相同业务键拒绝执行。容器仍运行，但任务没有 environment_id 和基线快照。不能因为容器健康就认定原操作完成。
3. **模型重复尝试未知操作。** 获得 unresolved/quarantined 后仍重试相同键，并尝试 prepare-2/3/4。需要程序拒绝在未解决的准备操作上新建并行准备，指令也应明确此时只收尾，不能用换 ID 绕过未知状态。
4. **Windows 源码复制边界。** 当前 gateway 复制 .git，重试时 shutil.rmtree 遇到只读 .git/objects 文件触发 WinError 5。工作副本应明确排除版本库元数据，保存独立的提交／源码指纹证据，避免连同 .git 清理。
5. **收尾不能覆盖首次准备的孤儿资源。** 无 environment_id 时 finish_task 生成部分报告，没有拆除已启动容器。最终由测试操作者按任务 Compose 项目标签清理；不能称为模型或平台自动清理成功。
6. **失败路径预算未完整结算。** 实际准备已等待约 60 秒，持久 Usage.wall_seconds 仅约 0.0102，失败／取消操作未完整结算。请求为 0 正确，但墙钟预算不能据此视为准确。
7. **报告缺少具体阻断说明。** JSON 中有通用适用性、恢复与标识缺失限制，但没有记录本次 MCP 超时、未解决的准备操作和复制失败；ReportResult.limitations 为空。模型文本说明不能替代结构化失败记录。

本次还未进入锁证据或索引收益判定阶段，因此不能用这次结果说明数据集案例本身无法诊断。

## 本地制品与清理

全部执行制品在忽略目录 runtime-data/agh-case01-20261005/：

- session-final.raw.jsonl：真实最终 AGH 事件；已检查不含本次 API Key。包含路径、源码和业务信息，仅用于本地复核。
- session-parameter-failure.jsonl：首轮参数失败记录。
- session-progress-2.jsonl：第二轮测试设施错误记录。
- business-tool-calls.jsonl：最终业务调用输入输出；原始日志对 CancelledError 没有单独标识，首次取消以 AGH timeout 事件及缺失结果交叉核对。
- bundle-final.json、verified-summary.json：持久业务事实和复核结果。
- artifacts/tasks/task-3856b8d080d86a6de480f6a0/report.json、report.html：平台部分报告。
- prepare_agh_probe.py 位于 runtime-data/ 根；server.py、run_diagnosis.py 等为一次性测试适配器，尚未变成产品入口。

本次隔离目标容器和卷已清理，残留容器数为 0；独立 AGH daemon 已停止；专用平台 MySQL 已停止并保留；其他项目容器未操作。正式评估答案和数据集均未修改。

下一次先解决长操作超时、准备恢复及资源收尾，再重跑同一个案例；此后才能判断索引与锁证据门槛对正常案例的实际影响。
