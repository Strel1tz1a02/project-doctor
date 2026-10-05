# 六个慢查询案例真实 AGH 测试

结论：六例真实模型均完成诊断到报告调用，最终 5 个任务 completed、1 个 partial；实际结论全部 lead。仅 2/6 的整体状态与数据集期望一致，该数字不是正式评估通过率。两个正例未 verified，两个反例未 unclassified，首交付诊断验收仍未满足。

提交 d83707d 已推送 origin/main，中文描述：修复环境准备超时与取消收尾，完成真实AGH慢查询联调。

使用 Agnes 3.0 Flash，经官方中国网关调用 AGH 私有配置与 pd MCP。用户授权六例公开 project 源码；每例仅一次索引实验，标准答案不发送模型。模型自主提出假设、选配方并调用业务工具。

## 已发现问题

1. 正例扫描量与耗时均下降，仍受部分锁覆盖与测量波动限制，不能升级 verified。
2. 第三例已有索引且实验无显著收益，仍产生 lead；诊断规则没有把反例归为 unclassified。
3. 第三例 finish-1 成功返回 completed 并拆除容器，模型继续以 finish-2、finish-3 收尾，平台恢复已停 DB 失败，将任务降为 partial。AGH 最终 blocked（退出码 4）。同操作 ID 幂等不能替代任务终态保护。
4. 报告缺 agh_session_id、tool_call_id；独立 session.jsonl 与工具日志可追溯，但自动关联未完成。
5. 本地评估器测试 122 passed、1 skipped、1 failed；冻结均分 0.8895 与实际 round(0.88945, 4)=0.8894 不一致。未修改数据与期望。

## 运行适配与审计

原始六例 project 文件 SHA-256 核对一致。只在忽略目录副本添加 SQL 标记、就绪探针、Docker 配置、实验配方及 JDBC 批量写入改写；原始 Java/SQL 不变。数据量未扩大，两组均使用相同初始化配置。负载为串行 warm-cache，每组 5 次预热与 5 次正式请求，不代表数据集定义的并发 4、60 秒 cold_after_restart 正式验收。

第三例镜像构建因依赖等待超过 600 秒，Windows buildx 子进程持有管道阻碍超时返回；核对进程归属后终止该构建子进程，后续复用已验证 Maven 缓存离线编译。恢复脚本第一次遇到编码错误，意外重放前两例；已确认返回原任务、各仍只有一个 run_experiment 调用，未新增实验。最终日志含该重放，首次模型耗时分别为 169.297、286.299 秒，重放耗时不是首次运行时间。

本地制品：runtime-data/agh-suite-20261006/，包含匿名 sut-01 至 sut-06 的 bundle、报告、原始源码哈希与 session.jsonl；未提交运行制品和密钥。模型消费公开源码，不消费 case.json、评估器或标准答案；期望仅在模型结束后由评估侧核对。

## 最终结果

每例有效实验为两组各 5 次预热、5 次正式测量，总计 10 个正式请求、10 个预热请求。每例最多一次实际索引干预；第五例另有一次错误路由引发的基线预热失败，未进入索引干预。

| 案例 | 期望 | 实际 | 任务 | 配方 | 已核验证据制品 |
|---|---|---|---|---|---|
| case-01-slow-query-fullscan | verified | lead | completed | recipe:status-created | 68 |
| case-02-slow-query-composite | lead | lead | completed | recipe:user-created | 278 |
| case-03-slow-query-unreproducible | unclassified | lead | partial | recipe:status-created | 78 |
| case-04-slow-query-user-index | verified | lead | completed | recipe:user-created | 68 |
| case-05-slow-query-skewed-status | lead | lead | completed | recipe:status-created | 78 |
| case-06-slow-query-undersized | unclassified | lead | completed | recipe:user-created | 68 |

实验本身的恢复校验六例均通过，正式样本均为 10，证据制品文件大小及 SHA-256 六例均核对通过。第三例最终收尾失败不等同于实验恢复失败。六例最终任务以及第五例首轮失败任务的容器均由平台清理；本轮复查残留为 0。总计 638 个不同制品引用（按任务分别计数）。

## 主查询实测

耗时是 SQL 五次测量中位数，单位毫秒；扫描量是 rows_examined 中位数。

| 案例 | 基线 → 索引 SQL 耗时 | 基线 → 索引扫描量 | 判断限制 |
|---|---|---|---|
| sut-01 | 45.613 → 0.531 | 200020 → 20 | 锁覆盖不足；基线与候选相对极差超阈值 |
| sut-02 | 137.227 → 127.020 | 94732 → 94732 | 选择 user-created；主查询扫描量未降，收益约 7% |
| sut-03 | 0.355 → 0.469 | 20 → 20 | 已有可用索引，无显著改善；仍错误保留 lead |
| sut-04 | 50.193 → 0.270 | 200003 → 3 | 锁覆盖不足；基线波动超阈值 |
| sut-05 | 60.733 → 0.632 | 200020 → 20 | 主查询改善，COUNT 剩余代价；锁覆盖与波动未过门槛 |
| sut-06 | 0.307 → 0.358 | 320 → 320 | 300 条数据下无收益，扫描量未降；仍错误保留 lead |

第二例生成 22 个 finding，其中大量为按用户主键查询，反映当前规则按含字面值的 SQL 分组、对每个非 verified 模板默认生成 lead，噪声较多。其 lead 状态符合期望，不代表已找到预期索引方案或声明完整限制。

第六例模型最终解释称耗时降低、索引缺失为主要来源，但实际中位耗时 0.307 → 0.358 ms，扫描量 320 → 320。程序保留 lead 没有误升 verified，但模型总结仍存在事实误读；需要依据结构化对照值约束生成。

## 本轮异常与收尾

第五例首轮 task-bbbf4e8af7938a29e7229268：测试适配误用 /api/orders/recent，公开 Controller 实际为 /api/orders/by-status；预热业务断言失败、正式样本 0、未执行索引干预。首轮报告与 trace 已另存 first-attempt-*，任务 partial，恢复及自动清理通过。修正运行清单路由后另建任务补测，没有改动数据量、应用业务源码或判定门槛。

第三例 task-0e313e49c6c8c5314b2933d9：AGH 模型 finish-1 → completed，随后 finish-2 → partial、reconcile-1、finish-3 → partial；最终 AGH blocked，退出码 4。不是容器残留；根因是平台没有防止对 completed 任务以新操作 ID 重复恢复已拆除 DB。

其他五例 AGH 正常完成。临时 server.py 已恢复到测试前备份、suite-active.json 已删除、suite 私有 daemon 无残留；本轮启动的 pd-platform-live-20261005 已停止，数据与容器保留。未操作其他项目容器。

## 验收边界与下一步

本轮证明真实模型能自主提出假设、选择配方、调用工具、产生证据与报告；没有产生 verified，也没有把反例归为 unclassified。本轮不是数据集定义负载的完整正式评估：使用串行预热负载，未独立复测，未运行完整评分器或测得模型实际费用。先修任务终态收尾保护、反例分级和事实约束，再完善可靠锁证据与重复测量；保持现有证据门槛。

代码已 push；本验收文档为测试后新增，尚未提交。运行日志与密钥保持 Git 忽略。
