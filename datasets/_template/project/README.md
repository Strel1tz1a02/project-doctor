# project/ 模板骨架

本目录是数据单元中 `project/` 的**占位模板**，说明被测项目应有的结构。
它本身不需要可构建——真正的起手方式是：

```bash
# 1. 从最近的同类用例复制一个可编译的基线（推荐 case-04，纯索引缺失、最简）
cp -r ../case-04-slow-query-user-index/project ./case-NN-<problem_kind>-<variant>/project

# 2. 按需改名（artifactId / 容器名 / 包名 / 接口路径）
#    务必同步修改 pom.xml、docker-compose.yml、application.yml、schema.sql
```

> 为什么复制现成项目而不是从空模板构建：现成项目已经验证过「可构建 + 可运行 + 可注入缺陷」，
> 复制后只改变量能最大程度避免引入环境类噪声。

## 标准布局

```
project/
├─ pom.xml                        # Maven 构建，artifactId 建议 order-<variant>
├─ docker-compose.yml             # 仅 MySQL 等依赖服务，容器名 <variant>-mysql，端口唯一避免冲突
├─ README.md                      # 面向被测 Agent 的项目说明（不含根因/答案）
└─ src/main/
   ├─ java/com/example/slowquery/
   │  ├─ SlowQueryApplication.java        # Spring Boot 启动类
   │  ├─ controller/OrderController.java  # 暴露症状接口（endpoint 与 case.json 一致）
   │  ├─ service/OrderService.java
   │  ├─ mapper/OrderMapper.java          # 缺陷代码位置（path:line 以此为准）
   │  ├─ model/Order.java                 # 实体
   │  ├─ dto/OrderVO.java
   │  └─ init/DataInitRunner.java         # 启动时按固定随机种子生成数据集
   └─ resources/
      ├─ application.yml                  # 指向本用例独立的 MySQL
      └─ schema.sql                       # 建表语句（索引的有/无即缺陷变量）
```

## 硬约束

1. **端口与容器名唯一**：多个用例可能在不同时刻被同时构建，compose 容器名不得重名。
2. **数据可复现**：`DataInitRunner` 必须使用固定随机种子；`dataset_profile.row_counts`
   与实际生成量一致（含 `boundary` 用例的「小数据量」）。
3. **端点自洽**：`controller` 暴露的路由、`symptom.endpoint`、`runtime.healthcheck`
   三者必须指向同一个接口。
4. **缺陷落在可定位的行**：`defects[].code_locations[].line` 必须与源文件实际行号一致，
   且注释/空行变动后要同步更新 `case.json`。
5. **答案隔离（最重要）**：本项目内**不得**出现以下任何字符串或其引用：
   `case.json`、`case.schema.json`、`_schema`、`Datasets/docs`、`../docs/`、
   `ground truth`、`ground_truth`、`root_cause_ids`。
   提交前运行 `python tools/isolation_guard.py` 自检（见上级 README 自检清单）。
