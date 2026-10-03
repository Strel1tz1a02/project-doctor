# 验收修复计划

用户已授权修复验收发现。当前会话直接实施，不使用子 agent。

1. 修正 reconcile 对正式 load_operation 返回值的判定，running/needs_reconcile 保持未决，隔离状态写入数据库。增加真实加载器与 SQLite schema 的跨模块回归。
2. 制品 ID 使用路径、类型、版本和内容摘要生成；sha256 继续只表示内容。验证不同路径同内容可进入 B gate。
3. HTTP 为每次请求生成独立 X-Project-Doctor-Request-Id；目标 SQL 标记约定包含 request=<32 位十六进制 ID>。SQL 查询和解析均要求精确关联，无标记不采集历史。验证旧请求与背景 SQL 被排除。
4. LOCK_TIME 仅保留于原始制品，不作为总锁等待；缺失完整证据降级。参数未知的 SQL 不执行替代参数 EXPLAIN。
5. 增加 A 内部 gateway.fingerprint，观测前后从真实 dump 计算，不复制 spec。核对运行时状态漂移与恢复。
6. 预算包含观测制品；recipe 强制受控引用及路径范围校验；修正 B 启动测试前提和格式检查。
7. 运行 scripts/check.ps1；更新验收结果与接入限制。真实目标、MySQL、AGH 无依赖时保留未验证状态。

重点复核：中断状态不误判、隔离持久化、相同计划跨路径、历史 SQL 污染、未知锁等待与参数均不生成充分证据。
