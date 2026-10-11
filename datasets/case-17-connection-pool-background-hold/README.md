# case-17-connection-pool-background-hold

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例：问题类型尚未被 Agent 支持，只能给 `lead`） |
| `problem_kind` | `connection_pool` |
| `difficulty` | `medium` |
| 期望结论 | `lead` |
| 来源 | 改编自 [airas-org/airas](https://github.com/airas-org/airas) Issue #648（MIT，`source=adapted`） |

设计意图：后台任务在**轮询外部数据源的等待期间持续持有数据库连接**，连接持有范围跨越了整个 `sleep` 循环。并发触发多个后台任务时，持有连接的并发数超过池上限，其余任务在获取连接处阻塞直至超时。用例考察 Agent 是否能：

1. 识别「冷启动单任务正常、并发/任务数升高才恶化」的资源占用特征，并把它归因到**连接持有范围**而非慢 SQL；
2. 在问题类型尚未被 Agent 支持时给出 `lead` 结论并**显式声明限制**（不得伪造 `verified`）；
3. 不把连接池上限这类环境参数误判为代码根因。

## 上游来源与原汁原味的保留

- 上游：`airas-org/airas` Issue #648《[Bug fix] Refactor DB session management to prevent connection pool exhaustion in background tasks》。
- 固定版本：commit `main@89679ca8fac1dc6bd247f421aa87fd399a9a1411`（核验当日 HEAD；本用例对应**修复前**的行为）；许可证 MIT。
- 保留的原汁原味：
  - 上游为 Python + SQLAlchemy：长时间后台任务（最长约 100h）在 sleep / 轮询外部 API 期间**持续占用 DB Session**，触发 `SQLAlchemy.exc.TimeoutError: QueuePool limit reached`（默认池 15）；
  - 修复方向为短生命周期 Session（`with Session(self.engine) as session`），改动 `container.py` 与 `BaseRepository`——本用例把这一「在轮询等待期间长期持有连接」的调用链结构逐字迁移为 `BackgroundTaskService.runTask`：任务开始即 `dataSource.getConnection()`，跨越轮询 `sleep` 循环后才归还；
  - 并发触发多个后台任务 → 连接池耗尽的触发方式保持不变。
- 按数据集约定的改造：上游为 Python + SQLAlchemy，本项目按统一骨架改写为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0；判分指标统一为可实测字段 `duration_ms`；上游任务生命周期以小时计，本用例以 `POLL_ROUNDS=3 × pollIntervalMs=800ms` 的轮询等待在秒级稳定复现同类占用。

## 目录结构

```text
case-17-connection-pool-background-hold/
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
| `d1` | primary | `connection_hold` | `src/main/java/com/example/slowquery/service/BackgroundTaskService.java:51` | `lead` | `runTask` 在任务开始即获取连接并在轮询 `sleep` 期间持续持有，直到任务末尾才归还；并发任务数超过池上限 10 时其余任务获取连接超时 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `n_plus_one` / `jvm_gc_pause`。

> 说明：`application.yml` 中的 `hikari.maximum-pool-size: 10` 与 `connection-timeout: 3000` 是**环境参数**，用于让占用可观测，**不是**缺陷本身；主根因在 `BackgroundTaskService` 的连接持有范围（获取时机）。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万订单）
mvn spring-boot:run

# 3. 触发症状（并发触发 16 个后台任务，每个在轮询期间持有连接）
curl "http://localhost:8080/api/reports/background?tasks=16&pollIntervalMs=800"
```

## 评估要点

- 边界用例（问题类型 `connection_pool`，等待 Agent 支持）：**不可由单变量索引实验证实**；且当前 Agent 的 `ProblemKind` 仅支持 `slow_query`、`Finding.verified_requires_structural_evidence` 要求 `kind == "slow_query"`，故在本用例上不可能产出 `verified`。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- `decision_match`：期望 `lead`（Agent 若给出 `verified` 即触发 `false_verified` 硬闸门）。
- `limitation_declared`：必须声明三条 `expected.limitations_required`（并发窗口依赖、问题类型未支持、量化需连接池指标）。
- `false_verified` 硬闸门：任何为连接池问题伪造 `verified` 的输出直接判负。
- **待支持标注**：等待 Agent 支持 `connection_pool` 问题类型。

## 与其它用例的关系

- 与 `case-09` 同属 `connection_pool` / boundary / `lead`，但形态不同：`case-09` 是**连接泄漏**（正常路径下从不归还，跨调用累积）；本用例是**连接持有范围过大**（任务内跨越轮询等待持有、单次调用内并发即耗尽）。
- 与 `case-14`（连接建立开销）区分：本用例不是连接建立慢，而是占用时机与范围。
- 与 `case-16` 一致，均为「问题类型尚未被 Agent 支持」的 boundary 用例，显式要求声明限制。
