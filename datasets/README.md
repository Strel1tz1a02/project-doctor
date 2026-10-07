# Datasets

本目录是后端性能诊断 Agent（`project-doctor`）的评估数据集。每个数据单元是一个带已知缺陷的可运行后端项目，配一张记录 ground truth 的问题卡，供组员对 Agent 进行测试与评估。

## 目录说明

| 路径 | 作用 |
| --- | --- |
| `使用说明.md` | 面向组员与 Agent 的入口文档：数据集构成、快速开始、评分要点 |
| `docs/数据集结构规范.md` | 数据单元的目录组织与问题卡字段约定 |
| `docs/Agent评估方法.md` | 评估指标、打分流程与三类样例判定标准 |
| `_schema/case.schema.json` | 问题卡的机器可读 JSON Schema |
| `tools/validate_cases.py` | 问题卡校验脚本（纯标准库），CI 对全部用例执行 |
| `tools/isolation_guard.py` | 答案隔离守卫：断言 `project/` 内不含任何评测方资产，CI 强制执行 |
| `tools/guard_sut_separation.py` | SUT 隔离守卫：断言被测系统 `src/project_doctor` 未引用金标准，CI 强制执行 |
| `_template/` | 新增用例模板（`case.json` 样板 + `project/` 布局）与**新增用例自检清单** |
| `<case-id>/` | 一个数据单元：`case.json` + `README.md` + `project/` |

`docs/`、`_schema/`、`_template/` 以及任何 `_` 开头的名字为保留项，不作为数据单元。数据单元的命名、字段与验收要求以《数据集结构规范》为准；新增用例从 `_template/` 起手，并按其中的自检清单逐项确认。

> **本目录的位置与只读性**：数据集以「方案 B」并入 `project-doctor` 仓库的 `datasets/` 子目录，金标准与被测系统（SUT）同处一仓。因此 `datasets/` 为**只读金标准**——被测 Agent 与 SUT 源码（`src/project_doctor`）**一律不得引用**本目录；该约束由 `tools/guard_sut_separation.py` 在 CI 中强制。CI 工作流位于宿主仓库根的 `.github/workflows/datasets-validate.yml`（详见 `tools/README.md`）。

## 数据单元索引

| case_id | 用例类型 | 问题类型 | 难度 | 期望结论 | 状态 |
| --- | --- | --- | --- | --- | --- |
| `case-01-slow-query-fullscan` | `normal` | `slow_query` | easy | `verified` | 已归档，校验通过 |
| `case-02-slow-query-composite` | `boundary` | `slow_query` | hard | `lead` | 已归档，校验通过 |
| `case-03-slow-query-unreproducible` | `failure` | `slow_query` | medium | `unclassified` | 已归档，校验通过 |
| `case-04-slow-query-user-index` | `normal` | `slow_query` | easy | `verified` | 已归档，校验通过 |
| `case-05-slow-query-skewed-status` | `boundary` | `slow_query` | medium | `lead` | 已归档，校验通过 |
| `case-06-slow-query-undersized` | `failure` | `slow_query` | medium | `unclassified` | 已归档，校验通过 |
| `case-07-n-plus-one-order-user` | `boundary` | `n_plus_one` | medium | `lead` | 已归档，校验通过（等待 Agent 支持） |
| `case-08-deep-pagination-large-offset` | `boundary` | `deep_pagination` | medium | `lead` | 已归档，校验通过（等待 Agent 支持） |
| `case-09-connection-pool-leak` | `boundary` | `connection_pool` | medium | `lead` | 已归档，校验通过（等待 Agent 支持） |
| `case-10-large-response-unbounded` | `boundary` | `large_response` | medium | `lead` | 已归档，校验通过（等待 Agent 支持） |
| `case-11-connection-setup-per-request` | `boundary` | `connection_setup` | medium | `lead` | 已归档，校验通过（等待 Agent 支持） |
| `case-12-excessive-logging-sync-debug` | `boundary` | `excessive_logging` | medium | `lead` | 已归档，校验通过（等待 Agent 支持） |
| `case-13-thread-pool-no-verifiable-defect` | `failure` | `thread_pool` | medium | `unclassified` | 已归档，校验通过（等待 Agent 支持） |
| `case-14-config-regression-pool-size` | `boundary` | `config_regression` | medium | `lead` | 已归档，校验通过（等待 Agent 支持） |

> `problem_kind` 的取值域已在 `_schema/case.schema.json` 中预留为设计文档划定的 **9 类**性能问题；当前 **9 类均已落地对应用例**：`slow_query`（6 例，`case-01`–`case-06`）、`n_plus_one`（`case-07`）、`deep_pagination`（`case-08`）、`connection_pool`（`case-09`）、`large_response`（`case-10`）、`connection_setup`（`case-11`）、`excessive_logging`（`case-12`）、`thread_pool`（`case-13`）、`config_regression`（`case-14`）。详见《[数据集结构规范](docs/数据集结构规范.md)》「problem_kind 取值与覆盖现状」。

全部用例共用同一套 Spring Boot + MyBatis + MySQL 技术栈，按「正常 / 边界 / 失败」三类各含 ≥2 个用例，构成一个完整的判定谱系：

- **正常（`verified`）**：
  - `case-01` 只保留单一主缺陷（缺 `(status, created_at)` 复合索引），用于验证 Agent「能证实唯一根因」；
  - `case-04` 为同类的第二个变体（`orders` 除主键外无任何索引），覆盖「表无可用索引 + 按 `user_id` 过滤」的入口。
- **边界（`lead`）**：
  - `case-02` 在同一项目内叠加前导通配符、N+1、深分页等组合缺陷，主缺陷可证实、其余不可证实，用于验证 Agent「只给 lead 而不强行 verified」；
  - `case-05` 为「缺索引」的第二个变体，通过 `status` 分布倾斜使索引收益随取值波动、难以稳定证实，用于验证 Agent 在「缺陷真实但收益依赖数据分布」时不过度下结论；
  - `case-07` 为 `n_plus_one` 问题类型的**预置用例**：列表接口在 `for` 循环中逐条查询用户信息，形成 `1+size` 次数据库往返，开销随列表条数线性增长、单条 SQL 无计划问题，故不可能产出 `verified`，用于在问题类型扩展前检验 Agent「识别调用次数放大并如实声明限制」（等待 Agent 支持）；
  - `case-08` 为 `deep_pagination` 问题类型的**预置用例**：分页接口使用大偏移 `LIMIT offset, size`，深页须扫描并丢弃近 20 万行，开销随翻页深度线性增长、且索引已存在无需补索引，故同样不可能产出 `verified`，用于检验 Agent 不把「有慢查询症状」误判为「缺索引」（等待 Agent 支持）；
  - `case-09` 为 `connection_pool` 问题类型的**预置用例**：高并发导出接口持续占用连接、连接池被耗尽，表现为获取连接等待时间陡增，缺陷真实但收益随并发波动、难以稳定证实（等待 Agent 支持）；
  - `case-10` 为 `large_response` 问题类型的**预置用例**：`GET /api/orders/all` 一次性返回全表、响应体无上限，序列化与网络开销随数据量放大，而单条 SQL 无计划问题（等待 Agent 支持）；
  - `case-11` 为 `connection_setup` 问题类型的**预置用例**：每次请求都新建并关闭数据库连接，失去连接复用收益，开销随请求数线性增长（等待 Agent 支持）；
  - `case-12` 为 `excessive_logging` 问题类型的**预置用例**：同步 `FileAppender` 以 debug 级别逐行打印大结果集，日志 I/O 阻塞业务线程，属同步日志放大（等待 Agent 支持）；
  - `case-14` 为 `config_regression` 问题类型的**预置用例**：连接池最大连接数被配置回归调小，并发下形成排队等待，缺陷落在配置而非代码（等待 Agent 支持）。
- **失败（`unclassified`）**：
  - `case-03` 的数据规模与接口与 `case-01` 一致，但 `orders` 已具备复合索引且无真实缺陷，用于验证 Agent「在证据不足时拒绝下结论、不编造根因」；
  - `case-06` 保留与 `case-04` 相同的真实缺陷（缺索引），但数据规模仅 300 条、缺陷「真实但不可证实」，用于验证 Agent 不对不可证实的缺陷强行下结论；
  - `case-13` 为 `thread_pool` 问题类型的**预置用例**：线程池队列在压力下排队，但环境波动使该现象不可稳定复现，且项目内另有一个 `select_star` 诱饵缺陷，用于验证 Agent 在「诱饵干扰 + 现象不可稳定复现」时拒绝编造根因（等待 Agent 支持）。

三类期望结论分别为 `verified` / `lead` / `unclassified`，与《Agent 评估方法》中正常、边界、失败三类样例一一对应。新增数据单元请遵循 `case-<两位序号>-<问题类型>-<变体>` 命名，从 `_template/` 复制样板起手，按其中自检清单确认后在本表中登记。

## 答案隔离

问题卡中的 `defects` 与 `expected` 是评测方资产。运行 Agent 时只挂载数据单元的 `project/` 目录，`case.json`、用例级 `README.md`（维护者文档）、`docs/`、`_schema/` 均不得对被测模型可见。

该约定不止停留在文档层面：`tools/isolation_guard.py` 会扫描每个 `project/`，
一旦发现敏感文件、越界符号链接、版本库目录或对答案资产的引用即判失败，
并由 `.github/workflows/validate-cases.yml` 在每次变更时强制执行。
