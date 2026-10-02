# project-doctor

后端项目性能诊断 Agent。用户提供项目仓库与本地或测试地址，Agent 在隔离环境中结合代码与运行证据定位性能问题，输出具体 SQL、触发代码位置、证据和修改建议。

首版聚焦慢查询 / 全表扫描、N+1 查询和深分页。AGH 承担核心诊断执行链路。

当前已实现 P0 公共基线及 B 侧：显式场景 manifest、保守慢查询判据、证据核对流程、JSON／HTML 报告和八个 MCP 工具。官方 SDK 协议与 scripted 流程已验证；真实 A 执行／MySQL／Docker／AGH 链路尚未验证。

首次交付只完成慢查询诊断到 JSON／HTML 报告；N+1、深分页后续安排。正式评估数据由第三人负责。

```powershell
uv sync --locked --python 3.13
./scripts/check.ps1
```

[P0 公共基线与 A/B 交接](docs/development/p0-baseline.md) · [双人开发计划](docs/superpowers/plans/2026-10-02-two-developer-plan.md)

[B → A 联调交接](docs/development/b/handoff-to-a.md) · [B 接入验证记录](docs/development/b/compatibility.md)

九份候选问题专题文档位于 [`docs/diagnosis/`](docs/diagnosis/)，[早期讨论草案](docs/项目性能诊断Agent-设计草案.md)仅作历史参考。
