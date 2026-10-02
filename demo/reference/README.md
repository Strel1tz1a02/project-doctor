# 参考目标：slow-query-demo（合成接入形状）

本目录是 A0 产出物之一：把首个目标项目接入 Project Doctor 所需的**最小目标形状**。
实际的第一个目标是 `d:\agent2\slow-query-demo\slow-query-demo`（Spring Boot + MyBatis + MySQL），
本目录保存其中由 A 拥有、可独立核对的参考文件，供 B 冻结合同与离线测试使用。

## 目标仓库必须包含的内容

`DockerEnvironmentGateway.prepare` 会把 `Settings.target_repo_root` 整个 `copytree` 到隔离工作区，
再覆盖写入一份由 `render_compose` 渲染的 compose 文件并 `up`。因此目标仓库根目录需要：

| 文件 | 作用 | 本目录对应 |
| --- | --- | --- |
| `Dockerfile` | 构建 `project-doctor-target:latest`（EXPOSE 8080，读 `DB_*` 环境变量） | [Dockerfile](Dockerfile) |
| `recipes/orders-status-created.sql` | 干预配方；`recipe_ref="recipe:orders-status-created"` 经 `_resolve_recipe` 解析 | [recipes/orders-status-created.sql](recipes/orders-status-created.sql) |
| 应用源码 + 种子/迁移 | 首次启动建表并确定性造数 | 见 slow-query-demo 本体 |

`manifest.json` 是传给 CLI `--manifest` 的 `RepositoryManifest`（场景 + 未覆盖路径），
不属于目标仓库文件系统，而是运维/B 侧注入的清单。

## 与 slow-query-demo 本体的对应

- `Dockerfile` / `recipes/orders-status-created.sql` 已同时落在 slow-query-demo 根目录与 `recipes/`；
  本目录保留一份副本作为「参考形状」，避免目标仓库缺失时无处核对。
- `application.yml` 已改为 `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD` 环境变量驱动，
  缺省仍为 `localhost:3306/slow_query_demo` + `root/root`，独立开发行为不变。

## 已知接入注意事项（详见 docs/development/a/target-handoff.md）

1. 种子时机：`DataInitRunner` 在应用首次启动时造 5 万用户 + 20 万订单，`up --wait` 只等容器 running，
   不等种子完成；基线快照需在种子完成后采集，否则恢复后为空库。
2. `manifest.json` 的 `dataset.snapshot_id` 是占位符，首次 prepare 后需用 mysqldump 摘要回填，
   使 `spec.snapshot_id == scenario.dataset.snapshot_id`。
3. SQL→代码行采集（`SqlProbe`）尚未接入，观测 `sql_calls` 默认为空，B 的 gate 要求每条 SQL 带当前 commit 的
   `code_location`，须在真实联调前补 `performance_schema` 采集 + MyBatis 拦截器注入。
