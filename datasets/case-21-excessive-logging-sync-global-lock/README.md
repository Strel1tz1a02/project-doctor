# case-21-excessive-logging-sync-global-lock

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例：问题类型尚未被 Agent 支持，只能给 `lead`） |
| `problem_kind` | `excessive_logging` |
| `difficulty` | `medium` |
| 期望结论 | `lead`（并显式声明限制；**等待 Agent 支持**） |
| 来源 | 改编自 [sirupsen/logrus](https://github.com/sirupsen/logrus)（MIT，`source=adapted`） |

设计意图：项目存在**一个真实、机制明确的结构性缺陷**——`GET /api/orders/audit-report` 经 `OrderService.auditReport()` → `orderMapper.findOrdersByUser()` 取回订单后，在**热路径上逐行**调用 `AuditLogger.log(...)`；而 `AuditLogger.log` 的每次写入都先获取**同一把静态全局锁**（`static final ReentrantLock MU`），并在持锁期间**同步 `out.flush()` 刷盘**后才释放。

结果：所有并发请求的日志写入被串行化在同一把锁上，且每次写入都付出一次同步刷盘的固定开销。`size` 越大、并发越高，锁竞争与刷盘次数越多，单请求耗时越接近串行叠加、吞吐上不去。真正的开销在**写盘与锁竞争**，而不在 SQL 执行计划本身。

与 `slow_query` 系用例不同，本用例的缺陷**不是靠执行计划**体现的：查询按 `user_id` 走 `idx_orders_user_created` 且带 `LIMIT`，执行计划毫无问题。真正的成本是「把日志写盘放在请求热路径上，且写入持全局锁同步刷盘」。理想情况下可由「并发梯度下的吞吐 / 日志路径时延」证实，但当前 Agent 的 `ProblemKind` 仅支持 `slow_query`（且 `Finding.verified_requires_structural_evidence` 要求 `kind == "slow_query"`），因此**在本用例上不可能产出 `verified`**，期望结论只能是 **`lead`**，并必须显式声明限制。

用例用于在 Agent 扩展问题类型之前，先检验其是否能：

1. 识别「SQL 计划无问题、耗时却在日志写盘上」这一 `excessive_logging` 特征；
2. 给出正确的定位（热路径日志调用点 / 持全局锁同步刷盘的写入方法）；
3. 如实声明「无法证实为 `verified`」及原因（等待 Agent 支持新问题类型），而非勉强下结论或误报 `false_verified`。

## 上游来源与原汁原味的保留

- 上游：`sirupsen/logrus`（**MIT**）——Go 生态广泛使用的结构化日志库。其写入路径为**库固有设计**：`Entry.write()` 中先 `entry.Logger.mu.Lock()` 取格式化器再 `Unlock()`，随后**再次加锁序列化写**：`entry.Logger.mu.Lock(); defer entry.Logger.mu.Unlock(); if _, err := entry.Logger.Out.Write(serialized); err != nil { ... }`；`Entry.log(...)` 中亦 `logger.mu.Lock(); reportCaller := logger.ReportCaller; ... logger.mu.Unlock()`，随后 `newEntry.fireHooks(hooks)`、`newEntry.write()`。即**每次写入都持有全局 `Logger.mu` 互斥锁并同步 `Out.Write`**。
- 上游关键位置（pinned `master@6ef0748d1177dadaeee9aa79ffef604570f487d7`，逐行已核）：
  - `logger.go:45` —— `mu mutexWrap`（`Logger` 结构体内的全局互斥锁字段，`logger.go:44` 注释 “Used to sync writing to the log. Locking is enabled by Default”）；`logger.go:63-66` 定义 `type mutexWrap struct { lock sync.Mutex; disabled bool }`；`logger.go:68-78` 的 `Lock()/Unlock()` 即对 `mw.lock`（`sync.Mutex`）加解锁。
  - `entry.go:373` —— `func (entry *Entry) write()`；`entry.go:378-380` 先 `entry.Logger.mu.Lock()` 取格式化器再 `Unlock()`；**`entry.go:389-391` —— `entry.Logger.mu.Lock(); defer entry.Logger.mu.Unlock(); if _, err := entry.Logger.Out.Write(serialized); err != nil { ... }`**，即在全局 `Logger.mu` 下同步 `Out.Write` 落盘。
  - `entry.go:311` —— `func (entry *Entry) log(level Level, panicAfter bool, msg string)`；`entry.go:323-326` 的 `logger.mu.Lock(); reportCaller := logger.ReportCaller; ... logger.mu.Unlock()`。
- **证据强度说明（如实标注）**：该机制现已**逐行定位并确认**（见上）；但 logrus 并**没有**记录该机制的单一 issue/PR——它是**库的既有设计**（同步写 + 全局锁），而非被上游标记为缺陷。因此本用例的机制采用「结构同构迁移」而非「同 issue 复现」，并在本用例中把它构造成真实缺陷（热路径逐行日志 + 全局锁同步刷盘）。
- 保留的原汁原味：
  - **「同步写入 + 全局锁串行化」** 这一机制逐字迁移：`AuditLogger.log` 用 `static final ReentrantLock MU` 把每次写入串行化在同一把锁上，并在持锁期间同步 `out.flush()` 刷盘（对应 logrus 持 `Logger.mu` 全局互斥锁 + 同步 `Out.Write`）；
  - 「日志写入被所有调用方共享同一把锁」的语义保留：`AuditLogger` 为单例 `@Component`，全局锁为 `static`，与 logrus 的进程级 `Logger.mu` 一致；
  - 保留日志逐条落盘、`logs/audit.log` 持续增长的可观测现象。
- 按数据集约定的改造：上游 logrus 为 **Go 日志库而非服务**，须**自建最小调用方**才能构成可运行的服务（属加工成分，已如实标注）；本项目按统一骨架改写为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0，调用方为 `OrderService.auditReport` 的逐行热路径日志；判分指标统一为可实测字段 `duration_ms`（`improvement.metric` 同）；数据规模按数据集约定设定为 `orders=200000`。

主缺陷所在行的原文：

```java
        MU.lock();
```

## 目录结构

```text
case-21-excessive-logging-sync-global-lock/
├─ case.json                # 问题卡（ground truth）
├─ README.md                # 本文件（含答案，隔离）
└─ project/                 # 被测项目（Spring Boot + MyBatis + MySQL），唯一暴露给 Agent 的目录
   ├─ pom.xml
   ├─ docker-compose.yml
   ├─ README.md             # 面向 Agent 的项目说明（已脱敏）
   └─ src/main/...
```

## 缺陷清单

`path` 均相对 `project/`。

| defect_id | role | kind | 位置 | 期望状态 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `d1` | primary | `sync_logging_lock` | `src/main/java/com/example/slowquery/log/AuditLogger.java:31` | `lead` | `log` 每次写入都获取同一把静态全局锁（`ReentrantLock MU`）并在持锁期间同步 `out.flush()` 刷盘；热路径逐行调用，导致所有并发请求的日志写入被串行化在同一把锁上、每次写入都付出同步刷盘开销，吞吐随并发塌陷；与 SQL 计划无关 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `n_plus_one` / `connection_pool`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万订单）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/orders/audit-report?userId=123&size=500"
```

## 评估要点

- 关键观察：`audit-report` 的 P95 随 `size` 增大而升高；并发越高，单请求耗时越接近串行叠加、吞吐上不去；`logs/audit.log` 增长很快。
- 可证实性：**无法**由单变量索引实验证实（查询走 `idx_orders_user_created` 且带 `LIMIT`，执行计划无问题），故期望 `lead` 而非 `verified`。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- 边界判定：期望 `decision_match = under`（`lead`），`false_verified = false`；
  `limitation_declared = true`（须覆盖 `limitations_required` 的 3 条，含「等待 Agent 支持」）。
- 若 Agent 强行给出 `verified`，触发 `false_verified` 硬闸门 → 总分为 0，按「误判」单独统计。
- **待支持标注**：当前 `ProblemKind` 不含 `excessive_logging`，本用例归档为「等待 Agent 支持」；待 Agent 扩展问题类型、并支持以并发梯度吞吐 / 日志路径时延等证据闭环后，可重判为 `normal`。

## 与其它用例的关系

- 与 `case-12-excessive-logging-sync-debug`（`excessive_logging`）同属「日志拖慢接口」谱系：`case-12` 用 `logback-spring.xml` 的同步 `FileAppender`（`immediateFlush=true`）逐行 `DEBUG` 打印；本用例为真实项目改编（自建 `AuditLogger` 的**全局锁 + 同步 flush**，对应上游 logrus `sync_logging_lock`），二者共享统一骨架便于对照。
- 与 `case-09-connection-pool-leak` / `case-14-config-regression-pool-size` 的区别：后两者的耗时来自连接池等待；本用例的耗时来自**日志写入的锁竞争与同步刷盘**，与连接池无关。
- 与 `case-07-n-plus-one-order-user`、`case-18` / `case-19` / `case-20` 同属「问题类型待 Agent 支持」的预置用例，均为 `boundary / lead`。
