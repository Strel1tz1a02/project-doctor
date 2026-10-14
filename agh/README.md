# AGH 接入边界

P0 仅预留配置目录；不启动 AGH，也不提供第二个 Agent 循环。
后续 B0 接入时记录 AGH 固定版本／提交、模型配置引用、MCP 传输方式和真实调用证据。
模型凭据放外部配置／环境变量，仓库只保存引用。

2026-10-05 已完成一次数据集案例的真实 Agnes→AGH→MCP 接入探针。模型实际调用了部分业务工具，但环境准备遭遇 60 秒 MCP 超时，尚未完成实验到报告的成功链路。使用独立 AGH Home 与一次性适配器，未提供生产启动入口；接入问题、实际调用与清理证据见 [测试记录](../docs/development/acceptance/2026-10-05-agh-dataset-probe.md)。

2026-10-06 已完成 case-01 的真实模型诊断链路：环境准备、模型选索引、对照实验、证据判定、报告与自动清理；任务 completed，诊断 lead。启动约 29 秒，原始数据集和业务 Java/SQL 未修改。测量、失败恢复及限制见 [修复验收记录](../docs/development/acceptance/2026-10-06-preparation-recovery-fix.md)。

固定 AGH 提交 `2ef9b71` 的长工具适配补丁由 `apply_timeout_patch.py` 管理，运行 `uv run --locked python agh/apply_timeout_patch.py <AGH源码目录>` 后重建 `@agnes/cli`。补丁通过 `AGNES_MCP_CALL_TIMEOUT_MS` 设置 SDK 调用上限；本次独立 daemon 设置 660000 毫秒，平台工具预算 600 秒。还通过官方 base preset 的 `tools.timeouts` 将服务 ID `pd` 的准备、实验、收尾执行上限设为 720000 毫秒；其他工具仍沿用原默认值。服务 ID 改变时工具前缀也会改变，必须重新核对映射，不能直接沿用。

Windows 重建前停止使用该构建的 daemon，避免原生模块锁住旧输出。SDK 取消后，平台会屏蔽 AnyIO 重复取消、等待已有 Docker 工作线程结束，再清理和结算；这一等待受 Docker 准备时限约束，不能把已发出的 Docker 操作当作立即停止。

## 独立修复会话

诊断 Agent 调用 `finish_task` 后，把返回的 `task_id` 交给另一个 AGH 会话。修复会话使用 [repair-instructions.md](repair-instructions.md)，先调用只读 `get_repair_handoff(task_id)`，由平台从持久任务及制品核验中返回候选 Finding；随后由修复 Agent 判断是否改、读源码和提交补丁。补丁后的成功判定仍由诊断层复测工具负责。两个会话不共享聊天上下文，也不需要把数据集答案或手工编造的 Finding 交给修复会话。

Windows 上启动独立会话的示例（`$aghCli`、`$aghHome` 和 `$taskId` 由操作者指定；密钥留在 AGH 配置中）：

```powershell
$env:AGH_HOME = $aghHome
$repairCwd = Join-Path $env:TEMP "project-doctor-repair-agent"
New-Item -ItemType Directory -Force -Path $repairCwd | Out-Null
$prompt = (Get-Content "agh/repair-instructions.md" -Raw -Encoding utf8) + "`n本次持久诊断 task_id：$taskId"
node $aghCli -p $prompt --mode json --profile local-dev --cwd $repairCwd
```

修复会话的工作目录应与被测源码仓库分开；源码读取和补丁提交都走 Project Doctor MCP 工具。需要先确认该 AGH profile 已连接当前 Project Doctor MCP 服务。

当前真实 `run_experiment` 仅执行索引对照。N+1 与深分页已有诊断判定规则和修复交接结构，但对应的查询形状／分页运行时干预尚未接通；不要把它们描述成已能由现有 AGH 诊断主流程实测产出。
