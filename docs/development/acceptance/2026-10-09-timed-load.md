# 持续并发负载实现与验收

## 本轮实现

ExperimentSpec 兼容新增 timed_load，ExperimentResult 新增 load_results，旧格式仍可读取。
协议 restart-concurrent-readonly.v1 支持指定并发、预热秒数、正式秒数、请求超时与每组请求上限。
默认并发 4、预热 10 秒、测量 60 秒；计次 warmup 与 timed_load 不能混用。

执行复用既有 run_experiment 的预算预留、任务独占、幂等、持久化、最终恢复及报告路径。
两组分别恢复快照，候选组应用索引；重启数据库及应用，核对前后 StartedAt 和缓冲池自动加载配置后再预热。
数据库启动关闭缓冲池自动加载与退出转储。此定义只证明进程重启及准备动作：宿主机文件缓存没有清除，应用就绪检查也可能读取数据。

固定数量工作者共用 HTTP 连接池，持续发请求至窗口结束；窗口结束后不再接纳请求，等待已发请求结束。
每个请求有唯一标记、相对时间、业务断言、摘要和失败原因。
预热完全结束后才启动正式窗口；P95 采用成功正式样本的 nearest-rank，并同时显示失败数。
请求预算提前耗尽时窗口不完整，不能缩短窗口后标成功。预算还包含预热。

原始样本保存为带 hash 的 timed-load.v1 制品。MCP 返回和报告保留计数、P95、窗口及重启摘要，避免把数万条原始请求塞入模型上下文。
失败／超时保留已尝试记录并恢复基线；取消会等待工作者退出和恢复，并把操作置为 needs_reconcile，不能直接重放。

## 实测证据

受控本机 HTTP 服务上的真实负载探针通过：

| 指标 | 实测 |
| --- | --- |
| HTTP 最大同时执行数 | 4 |
| 预热接纳窗口 | 10 秒 |
| 正式接纳窗口 | 60 秒 |
| 预热请求 | 612 |
| 正式请求 | 3655 |
| 失败请求 | 0 |

证据：runtime-data/timed-load-20261009/http-window.json 与 http-summary.json。
原始窗口 SHA256：cf240ae84d7f9fe3a319aecebe215ac421e8672f194bdffcc37e0f2af7478592。
这是受控 HTTP 探针，不是数据集案例诊断，也没有调用模型。

针对性测试覆盖并发重叠、预算耗尽、失败样本、请求标记、取消、恢复、跨任务重启拒绝、Docker 回执格式和报告计数。
最终 scripts/check.ps1：319 passed、11 skipped；Ruff 和格式检查通过，mypy 85 个源文件通过。
本轮未启用真实存储与锁控制测试，共跳过八项；另有两项未配置目标目录的应用探针和一项 Windows 符号链接权限测试。
真实 Docker 重启和数据库两组对照没有通过记录，不能用前一轮的真实测试替代本轮验收。

## 当前阻塞与边界

Docker Desktop 无法启动引擎。实际日志报错：Secrets Engine 无法访问残留 engine.sock。
官方启动命令及主程序启动未恢复引擎；Windows 原地改名备份 socket 的尝试失败，未修改密钥、配置、镜像或容器。
因此本轮没有完成真实目标重启、数据库恢复及索引两组 4/10/60 对照，也没有新六案例模型评分。

持续并发目前没有完整逐 SQL／锁关联，诊断始终保留线索，不能把 HTTP P95 收益直接升为 verified。
后续顺序：恢复 Docker → 验收真实目标持续对照 → 实现能跟上负载的 SQL／锁采集 → 再做正式六案例模型评估。

## 重跑入口

准备仅包含公开参数的 timed-load.json：

```json
{"concurrency":4,"warmup_seconds":10,"duration_seconds":60,"max_requests_per_level":20000,"request_timeout_seconds":15}
```

```powershell
uv run --locked python scripts/run_independent_retest.py `
  --source-home <上一轮记录目录> --out-home <新的独立目录> `
  --service-image <同源码冻结镜像> --timed-load-config <timed-load.json>
```

它复用上一轮模型选择的索引配方和公开场景，不读取 case.json 或评分答案。
启动前确认 Docker 已就绪、平台 DSN 配置有效；测试依次运行，避免固定目标端口和负载干扰。
请求上限改变属于显式测试预算变更，不能把上限耗尽的结果当成完整 60 秒实验。
