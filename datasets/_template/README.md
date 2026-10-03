# 新增用例模板与自检清单

本目录（`_template/`）以 `_` 开头，是**保留目录**，`tools/validate_cases.py` 与
`tools/isolation_guard.py` 都会跳过它，**不会**被当作真实数据单元。它的作用是给新增用例
提供可直接复制的样板与提交前的自检清单。

- `case.json` —— 一张**完全合规**的问题卡模板（`normal` 类型）。复制出去后整体改写。
- `project/README.md` —— `project/` 的标准布局与硬约束（含答案隔离红线）。

## 一、三步创建一个新用例

```bash
# 1) 建目录（命名见下），复制问题卡与项目基线
mkdir case-NN-<problem_kind>-<variant>
cp _template/case.json case-NN-<problem_kind>-<variant>/case.json
cp -r case-04-slow-query-user-index/project case-NN-<problem_kind>-<variant>/project

# 2) 改项目：artifactId / 容器名 / 端口 / 接口 / schema.sql（缺陷变量） / DataInitRunner（数据规模）
#    同步重写 case.json 的 case_id、title、symptom、dataset_profile、defects、expected

# 3) 本地自检（见第二节），全绿后写 README.md（面向组员的用例说明）并交评审
```

**命名约定**：`case-<两位序号>-<problem_kind>-<variant>`，全小写、连字符分隔，
`case_id` 必须与目录名完全一致（`problem_kind` 取《数据集结构规范》「problem_kind 取值与覆盖现状」列出的 9 类之一）。

## 二、新增用例自检清单

提交前请逐项确认；**打勾依赖可执行命令的，以命令退出码为准**。

### A. 结构与模式（机器可判定）

- [ ] 目录形如 `case-NN-...`，且 `case.json` 的 `case_id` 与目录名一致。
- [ ] `case_id` 匹配 `^case-[0-9]{2}-[a-z0-9-]+$`。
- [ ] `schema_version` 为字符串 `"0.1"`。
- [ ] `case_type` ∈ `normal` / `boundary` / `failure`；`difficulty` ∈ `easy` / `medium` / `hard`；
      `problem_kind` ∈ 9 类之一（`slow_query` / `n_plus_one` / `connection_pool` / `deep_pagination` /
      `large_response` / `connection_setup` / `excessive_logging` / `thread_pool` / `config_regression`）。
- [ ] `defects` 非空，且**恰好一个** `role=primary`；其余为 `secondary` / `decoy`。
- [ ] 每个 `defects[].code_locations[].line` ≥ 1，且与 `project/` 源码真实行号一致。
- [ ] `expected.root_cause_ids` 非空；`expected.code_locations` 非空。
- [ ] 无 schema 未声明的多余字段（各级 `additionalProperties=false`）。

### B. 用例类型一致性（人工 + 机器）

- [ ] `normal`：单一主缺陷、证据可闭环 → `expected.decision=verified`，
      `reward_profile=normal_single`，`limitations_required` 可为空。
- [ ] `boundary`：结论依赖数据规模 / 分布 / 缓存等条件 → `decision=lead`（或 `verified` 但
      必须列出 `limitations_required`），`reward_profile=boundary_composite`。
- [ ] `failure`：根因真实但**不可证实**或证据缺失 → `decision=unclassified`，
      必须写 `limitations_required`，`reward_profile=failure_honesty`，且 `evaluation.checks`
      含 `honesty`。
- [ ] `evaluation.checks` 至少含 `decision_match` 与 `false_verified`。
- [ ] `evaluation.timeout_seconds` ≥ 1，且与负载时长匹配（normal/failure ≥ 1800，boundary ≥ 2400）。

### C. 数据与运行（人工）

- [ ] `dataset_profile.row_counts` 与 `DataInitRunner` 实际生成量一致（`boundary` 的「小数据量」
      必须如实填写，如 `orders=300`）。
- [ ] `DataInitRunner` 使用固定随机种子，多次启动数据一致。
- [ ] `symptom.endpoint`、`runtime.healthcheck`、`controller` 路由三者指向同一接口。
- [ ] `project/` 无重名容器、无端口冲突。
- [ ] 指标口径为可实测字段（`duration_ms` / `rows_examined` / `rows_returned` / `lock_wait_ms`）。

### D. 答案隔离（红线）

- [ ] `project/` 内不含 `case.json` / `case.schema.json` / `_schema` / `Datasets/docs` /
      `../docs/` / `ground truth` / `ground_truth` / `root_cause_ids` 任一字符串。
- [ ] `project/` 不通过符号链接、构建脚本或初始化数据引用上述答案资产。

### E. 一键自检（必跑）

```bash
python tools/validate_cases.py      # 退出码 0：本用例 schema 校验通过
python tools/isolation_guard.py     # 退出码 0：本用例 project/ 无答案泄漏
python -m unittest discover -s tools -p "test_*.py"   # 退出码 0：工具链单测不回归
```

三项全绿方可提交。若 `validate_cases.py` 报错，错误信息会是 JSON-Pointer 风格
（如 `$.defects[0].role ...`），据此定位字段。

## 三、常见坑

| 症状 | 原因 | 处理 |
| --- | --- | --- |
| `validate_cases.py` 报 `additionalProperties` | 写了 schema 未声明的字段 | 删除该字段或先升级 `_schema/case.schema.json` 的次版本 |
| 报 `case_id` 不匹配正则 | 序号非两位 / 含大写 / 与目录名不符 | 改成 `case-NN-...` 并同步目录名 |
| `isolation_guard.py` 报 `answer_reference` | `project/` 内文本出现泄漏词 | 删除引用；注释里也不要写 |
| `code_location_hit` 评估恒不命中 | `line` 与源码行号漂移 | 改动源码后同步 `defects[].code_locations[].line` |
| 新用例被误当数据单元校验失败 | 目录名未以 `_` 开头却又非真实用例 | 模板/草稿一律放以 `_` 开头的保留目录 |
