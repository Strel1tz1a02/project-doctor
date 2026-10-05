# 慢查询证据与隔离修复计划

**目标：**完成用户已确认的锁证据修复、网络隔离、测试断言修复和预热能力。

**执行方式：**单人顺序完成，不使用子 Agent，不自动提交或推送。

**设计依据：**本次审查与用户确认的修复方案；保持原有重复次数、25% 相对极差和 1ms 差异门槛。

## 文件与职责

- `models/experiment.py`、`models/lock.py`：可兼容读取旧记录的准备、预热与锁证据合同。
- `features/experiments/preparation.py`、`features/diagnosis/gates.py`：协议摘要与纯业务证据核查。
- `integrations/runtime_factory.py`、`integrations/observation/lock_probe.py`：分别准备两组、预热、正式请求、锁采集、预算和恢复。
- `integrations/docker/compose.py`、`demo/ingress/`：内部应用/数据库网络与仅回环发布的独立转发入口。
- `features/reports/`：展示准备、预热和锁证据缺口。
- `tests/`：覆盖失败请求计费、预算不足、恢复失败、锁阳性对照和真实链路。

## 约束与审查重点

- 有限采样只能证明观测到等待，不能证明完整零等待；未知不得转换为零。
- 两组分别恢复相同快照；正式请求间不执行全库指纹读取，避免污染缓存。
- 请求失败也计预算；总预算同时约束预热、正式请求、时间、制品与恢复保留时间。
- 准备结束校验指纹；预热与正式请求的业务结果和 ID 必须可核查。
- 所有证据时间持久化使用 JSON 序列化；旧合同可读但缺证据只能输出 lead。

## 执行检查表

- [x] 先复现错误断言和请求后空快照误判，补缺失合同与保守锁证据采集。
- [x] 恢复内部网络和回环入口，修正真实测试的路径/行号断言。
- [x] 实现预热分离、预算、指纹与恢复核查，更新报告和合同样例。
- [x] 运行 pytest、Ruff、格式和 mypy，运行 MySQL 与 Docker 锁阳性测试。
- [x] 重跑真实诊断到报告链路，记录原始证据、判定缺口和清理结果。

实际验收见 `docs/development/acceptance/2026-10-05-evidence-and-isolation-repair.md`。
