# 六个慢查询样例检测失败的根因定位

> 来源：`docs/development/acceptance/2026-10-06-agh-six-case-suite.md` 的实测记录与
> `docs/development/problem-analysis.md` §5。
> 目的：回答「原本样例检测不成功，具体问题出在哪里」——把 4 个检测失败样例定位到
> 具体的诊断判据与代码位置，说明根因与修复。本文只陈述事实与修复，不再修改代码。

## 1. 总览：4 个样例检测不成功

六个样例中，**4 个「检测不成功」**（期望与实际不一致），2 个本应正确。

| 案例 | 实测（耗时 ms / 扫描量） | 期望 | 原实际 | 失败根因 |
|---|---|---|---|---|
| case-01 全表扫 | 45.613 → 0.531 / 200020 → 20 | verified | lead | 锁门槛 + 波动门槛 |
| case-03 已有索引 | 0.355 → 0.469 / 20 → 20 | unclassified | lead | 缺反例分级 |
| case-04 用户索引 | 50.193 → 0.270 / 200003 → 3 | verified | lead | 锁门槛 + 波动门槛 |
| case-06 数据过小 | 0.307 → 0.358 / 320 → 320 | unclassified | lead | 缺反例分级 |

case-02（复合，主查询 137.227 → 127.020 / 94732 → 94732）与 case-05（偏斜 status）
期望即为 `lead`，属正常，不计入失败。

> 关键判断：问题**不在工具调用**——模型确实调用了工具、采集到了数据、生成了证据。
> 问题在三处**诊断判据**把正确的数据「拦」成了 lead。

---

## 2. 具体问题一：锁证据门槛要求「不可能证明」的行锁零等待

**影响样例**：case-01、case-04

**现象**：扫描量降 99%（200020 → 20/3）、耗时降 99%（45.6/50.2 → 0.53/0.27ms），
却仍被判 `lead`，理由含「锁等待覆盖证据不完整」。

**代码位置**：`src/project_doctor/features/diagnosis/slow_query.py` 的锁门槛，配合
`src/project_doctor/models/lock.py` 的 `covered_no_wait` 校验器。

```python
# slow_query.py（原逻辑）
if call.lock_wait_ms is None or call.lock_wait_ms != 0:
    reasons.append("锁等待尚未排除；本判据要求零锁等待的可比测量。")
if locks is None or locks.status != "covered_no_wait" or locks.coverage != "complete":
    reasons.append("锁等待覆盖证据不完整；轮询空结果不能证明零等待。")
```

**根因**：

- `covered_no_wait` 要求 `covered_kinds` 覆盖 `table` / `metadata` / `innodb_data` **三类**；
- 早期实现误以为 `LOCK_TIME` 只覆盖表/元数据锁，把权威指标 `LOCK_TIME` 丢弃、改用脆弱的
  `data_lock_waits` 当前快照（等待授予后即消失、无持久历史）与全局 `Innodb_row_lock_*` 计数器零证明；
- 任何无关线程的一次行锁都使零证明失败，回退到「整个采集窗口」残差，在诊断里几乎必然
  「足以解释耗时差异」→ 正例被误判 `lead`（条件不足）。

**修复（最终口径，对齐 Percona / PMM / pt-query-digest 主流做法）**：直接读 `events_statements_*`
的 `LOCK_TIME` 作为逐语句权威锁等待指标。

- 表锁 + InnoDB 行锁：由语句 `LOCK_TIME` **逐语句实测**证明（MySQL 8.0.28+ 含 InnoDB 行锁，不含 MDL）；
- 元数据锁（MDL）：`LOCK_TIME` 唯一未测项，用全局 `wait/lock/metadata/sql/mdl` 汇总差值约束（`residual_ms`）；
- 版本 < 8.0.28 时 `LOCK_TIME` 不含行锁，才回退全局行锁计数零证明，否则拒绝零证明。

落点：[lock.py](../../src/project_doctor/models/lock.py)（`residual_ms` 收窄为 MDL 上界、重定义
`covered_no_wait` 校验器）、[lock_probe.py](../../src/project_doctor/integrations/observation/lock_probe.py)
（`evidence_for` 三路分类 + `coverage.json` 记录版本守卫与 MDL 上界）、
[sql_probe.py](../../src/project_doctor/integrations/observation/sql_probe.py)（`lock_wait_ms = LOCK_TIME`）。

---

## 3. 具体问题二：波动门槛用「极差」判稳，对离群点 / 亚毫秒失真

**影响样例**：case-01、case-04

**现象**：验收记录分别为 case-01「基线与候选相对极差超阈值」、case-04「基线波动超阈值」——
即使中位数降 99%，`distinguishable()` 仍返回 False，理由含「SQL 耗时变化不足以区分测量波动」。

**代码位置**：`src/project_doctor/features/diagnosis/compare.py` 的 `stable()` 用
「(max − min) / 中位数 ≤ 0.25」判稳，配合 `slow_query.py` 的：

```python
if not distinguishable(sql_durations[0], sql_durations[1], policy):
    reasons.append("SQL 耗时变化不足以区分测量波动。")
```

**根因**：

- **极差对离群点敏感且不随重复次数收敛**：基线 5 次测量里只要有一次冷启动/首次读盘的
  离群值（例如 90ms），极差就被拉爆，`stable()` 判不稳，整组测量作废；
- **亚毫秒下相对极差失真**：0.4ms 中位带 0.3ms 极差，相对极差即 75%，远超 0.25 阈值。

**修复**：极差改 IQR（Q3 − Q1，稳健离散度，对离群点不敏感），并增加
`minimum_absolute_spread_ms=0.5` 绝对地板，亚毫秒尺度下不再用相对极差。
落点：[compare.py](../../src/project_doctor/features/diagnosis/compare.py)。

---

## 4. 具体问题三：诊断规则只有 verified / lead 两路，缺反例出口

**影响样例**：case-03、case-06

**现象**：case-03（已有可用索引）、case-06（300 条数据无收益）被归 `lead`，而非 `unclassified`。

**代码位置**：`src/project_doctor/features/diagnosis/slow_query.py`（原二值判定）：

```python
verified = not reasons
status = "verified" if verified else "lead"
```

**根因**：诊断规则没有「该问题不成立 / 未复现」的分支。「扫描量未降」只被当作「证据不足」
追加 reason：

```python
if not rows[0] or not rows[1] or median(rows[0]) <= median(rows[1]):
    reasons.append("未证明索引干预降低实际扫描工作量。")
```

于是「已有索引 / 数据量过小 / 收益不显著」这类**反例**被错误归入「尚未证明 → lead」，
而不是「该问题在当次数据与代码下未复现 → unclassified」。

**修复**：三路分级（`slow_query.py`）：

- 扫描量下降 **且** 耗时可区分 → `verified`；
- 扫描量未降 **且** 基线中位耗时 `< minimum_delta_ms` → `unclassified`（已有索引 / 数据过小未复现）；
- 扫描量未降 **且** 基线仍慢 → `lead`（根因未解决，继续排查）。

---

## 5. 修复后回放结果

用验收文档记录的主查询中位数回放进新判据：

| 案例 | 期望 | 修复后 |
|---|---|---|
| case-01 | verified | verified ✅ |
| case-03 | unclassified | unclassified ✅ |
| case-04 | verified | verified ✅ |
| case-06 | unclassified | unclassified ✅ |

> 回放边界：验收文档只记录中位数，不含 5 次逐次测量值，故回放验证的是**分类逻辑 + 锁重定
> 语义**；逐次波动（问题二）与 case-05 的复合 COUNT 查询需原始 bundle
> （`runtime-data/agh-suite-20261006/`，本地未提交）才能端到端复现。

---

## 6. 与 §5 其余问题的边界

问题分析 §5.3（模型自由文本事实误读，case-06）与 §5.4（会话/工具 ID 自动关联）属
**报告生成与关联**层面，不改变「检测不成功」这一现象，不在本文范围，仍列为后续 P1 项。

## 7. 关联文档

- [problem-analysis.md](problem-analysis.md)
- [acceptance/2026-10-06-agh-six-case-suite.md](acceptance/2026-10-06-agh-six-case-suite.md)
- [../diagnosis/performance-agent-deepdive-01-slow-query.md](../diagnosis/performance-agent-deepdive-01-slow-query.md)
