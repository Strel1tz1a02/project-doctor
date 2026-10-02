# B 接入验证记录

日期：2026-10-02。

最终本地检查：77 项测试通过，Ruff／格式／mypy 全部通过；改动未提交 Git，未修改 A 的 integrations、环境执行实现或第三人的评估目录。

| 检查 | 结果 |
| --- | --- |
| Python 3.13 + Pydantic 公共模型 | 已验证 |
| 官方 MCP Python SDK 1.30.0 八个工具注册、目录、结构化输出、错误输入 | 已验证：tests/integration/agent/test_mcp_protocol.py |
| 使用 scripted A 能力的场景→实验→证据→报告流程 | 已验证：tests/e2e/test_b_scripted_chain.py |
| MySQL 读写与重启恢复 | 未验证：A 的 store 工厂尚未实现 |
| 真目标 HTTP／SQL／计划及环境恢复 | 未验证：A 的 Runtime 尚未实现 |
| 真实 AGH 模型经 MCP 执行业务工具 | 未验证：缺少真实 A 实现及本任务的模型配置／凭据引用 |

本地 AGH 源码只读核对：`E:/projects/agnes-harness`，提交 `2ef9b71f36f6af70af405f20f82369c13d91d82e`。
其 `docs/guide/mcp.zh-CN.md` 明确需要审核定义、信任／启用、检查目录，再在目标会话中实际调用。
本次没有注册到用户已有 AGH，也没有改动该仓库或运行模型调用，因此不标记真实 AGH 接通。

MCP 使用 v1 维护线，依赖限制 `<2`，具体版本在 uv.lock；依据[官方 v1 文档](https://py.sdk.modelcontextprotocol.io/v1/)。
未来升级 SDK 或 AGH 需要重新跑协议与真实会话检查，不能只依据管理面连接状态。

## 配置并联调

先由 A 完成真实工厂，再配置本地 settings 与 manifest。注册时使用独立可执行文件及参数：

```text
executable: E:/projects/project-doctor/.venv/Scripts/python.exe
args:
  -m
  project_doctor.entrypoints.cli
  --settings
  E:/projects/project-doctor/config/settings.local.json
  --manifest
  E:/projects/project-doctor/config/manifest.local.json
```

AGH 的 stdio 登记入口支持 `--stdio EXECUTABLE` 和重复 `--arg VALUE`；不要拼成 shell 命令。
凭据通过 SecretRef／本地引用配置，不能粘贴到工具参数。按 AGH 最新 get revision 做审核和启用。
将 agh/diagnosis-instructions.md 用作诊断指令，核对真实八步工具输入输出以及可获取的会话／调用 ID。
联调记录须包含真实目标提交、环境指纹、MySQL 业务记录、原始制品、恢复证据及 JSON／HTML，而非 scripted 测试样例。
