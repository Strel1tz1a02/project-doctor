# AGH 接入边界

P0 仅预留配置目录；不启动 AGH，也不提供第二个 Agent 循环。
后续 B0 接入时记录 AGH 固定版本／提交、模型配置引用、MCP 传输方式和真实调用证据。
模型凭据放外部配置／环境变量，仓库只保存引用。

2026-10-05 已完成一次数据集案例的真实 Agnes→AGH→MCP 接入探针。模型实际调用了部分业务工具，但环境准备遭遇 60 秒 MCP 超时，尚未完成实验到报告的成功链路。使用独立 AGH Home 与一次性适配器，未提供生产启动入口；接入问题、实际调用与清理证据见 [测试记录](../docs/development/acceptance/2026-10-05-agh-dataset-probe.md)。

2026-10-06 已完成 case-01 的真实模型诊断链路：环境准备、模型选索引、对照实验、证据判定、报告与自动清理；任务 completed，诊断 lead。启动约 29 秒，原始数据集和业务 Java/SQL 未修改。测量、失败恢复及限制见 [修复验收记录](../docs/development/acceptance/2026-10-06-preparation-recovery-fix.md)。

固定 AGH 提交 `2ef9b71` 的长工具适配补丁由 `apply_timeout_patch.py` 管理，运行 `uv run --locked python agh/apply_timeout_patch.py <AGH源码目录>` 后重建 `@agnes/cli`。补丁通过 `AGNES_MCP_CALL_TIMEOUT_MS` 设置 SDK 调用上限；本次独立 daemon 设置 660000 毫秒，平台工具预算 600 秒。还通过官方 base preset 的 `tools.timeouts` 将服务 ID `pd` 的准备、实验、收尾执行上限设为 720000 毫秒；其他工具仍沿用原默认值。服务 ID 改变时工具前缀也会改变，必须重新核对映射，不能直接沿用。

Windows 重建前停止使用该构建的 daemon，避免原生模块锁住旧输出。SDK 取消后，平台会屏蔽 AnyIO 重复取消、等待已有 Docker 工作线程结束，再清理和结算；这一等待受 Docker 准备时限约束，不能把已发出的 Docker 操作当作立即停止。
