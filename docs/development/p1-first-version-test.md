# P1 初版项目测试日志（2026-10-03）

对 P0 公共基线做第一次完整真实接入验证，覆盖三层：静态测试套件、真实 MySQL 存储回环、
Docker 端到端（真实容器 + 真实 MySQL + 一次请求 + 回滚校验）。三层全部通过。

## 1. 测试环境

| 项 | 值 |
| --- | --- |
| 主仓库 | `D:\agent2\project-doctor`（Python 3.13 + uv，锁文件 `uv.lock`） |
| 目标演示仓库 | `D:\agent2\slow-query-demo\slow-query-demo`（Spring Boot 3.2.5 + MyBatis） |
| 本地 MySQL | 9.5，`127.0.0.1:3306`，项目库 `project_doctor`，专用用户 `pd` |
| Docker | Desktop 29.8.1（WSL2），镜像 `project-doctor-target:latest`、`mysql:8.4` |
| 网络 | 国内镜像源（daocloud / xuanyuan / 1ms）；JDK 17 + Maven（阿里云镜像） |

## 2. 测试流程与结果

### 2.1 静态测试套件

```powershell
uv run --locked pytest -q
```

结果：**186 passed, 3 skipped**（4.36s）。3 项跳过均为环境门控或系统限制：

- `tests/integration/runtime/test_store.py::test_store_round_trip`（需 `PROJECT_DOCTOR_PLATFORM_DSN`）
- `tests/integration/runtime/test_target_probe.py::test_target_probe_end_to_end`（需 `PROJECT_DOCTOR_TARGET_REPO`）
- `tests/runtime/test_artifacts.py`（符号链接需开发者模式或提权）

### 2.2 真实 MySQL 存储回环

先清理固定 `task_id="task-1"` 的残留（该测试非幂等），再运行：

```powershell
$env:PROJECT_DOCTOR_PLATFORM_DSN = "<项目库 DSN，见本地配置，不落库>"
uv run --locked pytest tests/integration/runtime/test_store.py::test_store_round_trip -v
```

结果：**1 passed**（0.96s）。跑后再次清理 `task-1` 残留。

### 2.3 Docker 端到端（真实容器）

```powershell
$env:PROJECT_DOCTOR_TARGET_REPO = "D:/agent2/slow-query-demo/slow-query-demo"
uv run --locked pytest tests/integration/runtime/test_target_probe.py::test_target_probe_end_to_end -v
```

流程：`compose up --wait` → 基线快照 → 一次请求（断言 200 + 业务字段）→ 回滚 → 摘要校验。

结果：**1 passed**（33s）。

## 3. 发现并修复的问题

端到端测试实际暴露 4 个真实问题，均已修复并加回归测试：

| # | 问题 | 根因 | 修复 |
| --- | --- | --- | --- |
| 1 | `docker compose up` 报非法 YAML | `db_env` 拼接缺尾随换行，把 `MYSQL_USER` 与 `volumes:` 粘成一行 | 补尾随换行 + 回归测试 |
| 2 | 端口未发布（`18080:8080` 为空） | 网络 `internal: true` 静默禁用端口发布 | 改为普通桥接网络 + 回归测试 |
| 3 | 回滚后摘要不一致 | 基线快照在种子写入完成前抓取（app 监听 ≠ 种子完成） | `up --wait` 增加 db/app 健康检查；app 用 `/tmp/ready` 就绪标记 |
| 4 | 种子极慢（5 分钟仅 3 万条） | JDBC 缺 `rewriteBatchedStatements=true`，25 万条 INSERT 逐条往返 + 每次 fsync | 加该参数，种子降到秒级 |

## 4. 变更文件

- `project-doctor`：`src/project_doctor/integrations/docker/compose.py`、
  `tests/runtime/test_environment.py`
- `slow-query-demo`：`DataInitRunner.java`（写 `/tmp/ready` 就绪标记）、
  `application.yml`（加 `rewriteBatchedStatements=true`）

镜像 `project-doctor-target:latest` 已按新源码重建。

## 5. 遗留与注意

- `test_store_round_trip` 使用固定 `task_id="task-1"` 且非幂等，重跑前需清理对应行。
- 端到端测试使用预构建镜像 `project-doctor-target:latest`；修改目标演示源码后需
  `docker build -t project-doctor-target:latest .` 重建。
- 慢查询（N+1、深分页）不在本次范围，见 `docs/development/p0-baseline.md`。
