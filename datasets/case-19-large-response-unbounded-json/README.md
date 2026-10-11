# case-19-large-response-unbounded-json

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例：问题类型尚未被 Agent 支持，只能给 `lead`） |
| `problem_kind` | `large_response` |
| `difficulty` | `medium` |
| 期望结论 | `lead`（并显式声明限制；**等待 Agent 支持**） |
| 来源 | 改编自 [openclaw/openclaw](https://github.com/openclaw/openclaw) PR #97536（MIT，`source=adapted`） |

设计意图：项目存在**一个真实、机制明确的结构性缺陷**——`GET /api/providers/releases` 经 `ProviderReleaseService.listAll()` → `ProviderReleaseMapper.findAllReleases()` **无分页**地 `SELECT *` 取回 `provider_releases` 全表约 5000 行，并**逐行序列化含 `payload`（约 6 KB JSON）的完整实体**，单次响应体约 30 MB，远超上游约定的 **16 MiB 上限**。真正的开销在**结果序列化与网络传输**，而不在 SQL 执行计划本身。

与 `slow_query` 系用例不同，本用例的缺陷**不是靠执行计划**体现的：全表扫描无 `WHERE`，`provider` 上已建索引也不会改变返回量。真正的成本是「把全表塞进一个响应体」的序列化与传输。理想情况下可由「响应字节数 / 返回行数随数据规模增长」证实，但当前 Agent 的 `ProblemKind` 仅支持 `slow_query`（且 `Finding.verified_requires_structural_evidence` 要求 `kind == "slow_query"`），因此**在本用例上不可能产出 `verified`**，期望结论只能是 **`lead`**，并必须显式声明限制。

用例用于在 Agent 扩展问题类型之前，先检验其是否能：

1. 识别「响应体过大」这一**非 SQL 计划层**的问题特征；
2. 给出正确的定位（无分页的查询方法）；
3. 如实声明「无法证实为 `verified`」及原因（等待 Agent 支持新问题类型），而非勉强下结论或误报 `false_verified`。

## 上游来源与原汁原味的保留

- 上游：`openclaw/openclaw` PR #97536（**MERGED**，**MIT**）《fix(signal): bound GitHub release info JSON response with readProviderJsonResponse》——Signal 发布信息 JSON 使用无界 `await response.json()` 解析，未强制 **16 MiB** 上限；修复改为 `readProviderJsonResponse` 并引入 `read-response-with-limit.ts`（16 MiB cap）。
- 上游关键位置（问题存在时）：`extensions/signal/src/install-signal-cli.ts:304/306`（`await response.json()` → `readProviderJsonResponse`）、`src/agents/provider-http-errors.ts:312`、`packages/media-core/src/read-response-with-limit.ts:96`（16 MiB 上限）；核验当日 HEAD `main@0a687e8e01df582cd0f20e917a4c89dfd93458ab`。
- 保留的原汁原味：
  - **无上限读取 release 信息 JSON** 这一机制逐字迁移：`ProviderReleaseMapper.findAllReleases()` 无界地取回全表 release 记录（含完整 `payload`）；
  - 领域名保持不变：`provider_releases`（release 表）、`payload`（release 信息 JSON 体）、`release_tag`；`providers = {signal, github, npm, pypi, maven}` 保留上游的 provider 概念（含 `signal`）；
  - 上游的 **16 MiB 上限**语义在 `expected_fix` / `limitations_required` 中原样保留为「应施加的响应体上限」。
- 按数据集约定的改造：上游为 TypeScript / Node.js（`packages/`、`extensions/` monorepo），本项目按统一骨架改写为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0；判分指标统一为可实测字段 `duration_ms`；数据规模按数据集约定设定为 `provider_releases=5000`（每条约 6 KB payload，合计约 30 MB > 16 MiB）。

## 目录结构

```text
case-19-large-response-unbounded-json/
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
| `d1` | primary | `unbounded_response` | `src/main/java/com/example/slowquery/mapper/ProviderReleaseMapper.java:24` | `lead` | `findAllReleases` 无分页地 `SELECT *` 返回全表约 5000 行，并逐行序列化含约 6 KB `payload` 的完整实体，单次响应体约 30 MB（> 上游 16 MiB 上限）；瓶颈在序列化与网络传输，而非 SQL 计划本身 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `n_plus_one` / `connection_pool`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 5000 条 provider_releases，每条 payload 约 6 KB）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/providers/releases"
```

## 评估要点

- 关键观察：单次请求耗时高且响应体巨大（约 30 MB），耗时与返回行数 / 响应字节数近似正相关；数据量越大越明显。
- 可证实性：**无法**由单变量索引实验证实（全表 `SELECT *` 无 `WHERE`，计划本身无问题，补索引也不改变返回量），故期望 `lead` 而非 `verified`。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- 边界判定：期望 `decision_match = under`（`lead`），`false_verified = false`；
  `limitation_declared = true`（须覆盖 `limitations_required` 的 3 条，含「等待 Agent 支持」）。
- 若 Agent 强行给出 `verified`，触发 `false_verified` 硬闸门 → 总分为 0，按「误判」单独统计。
- **待支持标注**：当前 `ProblemKind` 不含 `large_response`，本用例归档为「等待 Agent 支持」；待 Agent 扩展问题类型、并支持以响应字节数 / 返回行数等证据闭环后，可重判为 `normal`。

## 与其它用例的关系

- 与 `case-10-large-response-unbounded`（`large_response`）同属「大响应」谱系：`case-10` 为手工构造（`orders` 表、20 万行、`remark` 大字段），本用例为真实项目改编（`provider_releases` 表、5000 行 × 约 6 KB `payload`、对应上游 16 MiB 上限），二者共享统一骨架便于对照。
- 与 `case-08` / `case-18`（`deep_pagination`）的区别：后两者耗时来自「扫描并丢弃 offset 行」；本用例关注**无分页地返回全表**导致的响应体过大（序列化 / 传输代价）。
- 与 `case-07-n-plus-one-order-user` 同属「问题类型待 Agent 支持」的预置用例，均为 `boundary / lead`。
