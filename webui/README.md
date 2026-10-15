# Project Doctor 诊断评测台（webui）

比赛演示用的单页 Web 控制台：把完整用例「跑一遍」，展示 45 例评测矩阵、逐例详情与
汇总结论。**独立第三方目录**，与 `src/project_doctor`（SUT）和 `datasets/`（评测器）平级，
不进 SUT 依赖，不引入任何新依赖，不改 `pyproject.toml` / `uv.lock`，不改 `run_eval.py`。

## 启动

```bash
uv run python webui/server.py
# 或指定端口：uv run python webui/server.py --port 8080
```

浏览器打开 <http://127.0.0.1:8080>。

- 顶部徽章实时显示能力探测结果：Docker / 平台 DB（`PROJECT_DOCTOR_PLATFORM_DSN`）/
  AGH CLI / Agnes key 文件（`agh/model.local.json`）。
- 「运行」默认走**离线评分**：用 `datasets/evaluation/fixtures/run-bundle` 的 14 份
  黄金运行包跑冻结评测器，其余 31 例如实标「缺失运行包」。这是本机（无 Docker / 无
  AGH / 未设 DSN）唯一可验证的路径。
- 真跑按钮在 Docker + DB + AGH + Agnes key 全部就绪时才可用。

## 配置

把 `config.example.json` 复制为 `config.json`（gitignore，不提交），按演示机填写：

```json
{
  "cases_root": "datasets",
  "runs_dir": "datasets/evaluation/fixtures/run-bundle",
  "out_dir": "webui/out",
  "host": "127.0.0.1",
  "port": 8080,
  "agh_cli": "path/to/agh-cli.js",
  "agh_home": "",
  "agh_profile": "local-dev",
  "instructions": "agh/diagnosis-instructions.md",
  "run_home_root": "runtime-data/demo-runs",
  "per_case_timeout_seconds": 300
}
```

- 所有相对路径以仓库根为基准解析。
- `agh_cli` 是 AGH 入口（`node $aghCli`）。**密钥不放这里**：Agnes key 仍在 AGH
  profile / `agh/model.local.json`（已 gitignore），DB 密码仍走 `PROJECT_DOCTOR_PLATFORM_DSN`。

## 两种运行模式

| | 离线评分 | 真跑（AGH） |
|---|---|---|
| 触发 | 任何机器 | 演示机（Docker+DB+AGH+key 就绪） |
| 评分 | `run_eval.run(..., only_bundled=勾选)` | 逐例 `node $aghCli` → 导出运行包 → `run_eval.run(..., only_bundled=False)` 严格评分 |
| 进度 | 秒级完成 | 逐例推进（约 30–180s/例） |
| 数据 | 14 份黄金运行包 | 45 份真实运行包 |

### 真跑路径（需演示机联调，本机无法端到端验证）

`webui/agh_runner.py` 的逐例流程：

1. `node <agh_cli> -p agh/diagnosis-instructions.md --mode json --profile <agh_profile> --cwd datasets/<case_id>/project`，`AGH_HOME` 可选注入。
2. 从 `<run_home_root>/<case_id>/`（或目录下 `bundle.json` 命中该 case 的目录）定位运行目录。
3. `scripts/export_evaluation_run.py --home <运行目录> --case-id <id> --out webui/out/<run_id>/runs/<id>.json` 导出运行包。
4. 全部结束后用 `run_eval.run(..., only_bundled=False)` 严格评分。

**注意**：AGH 的运行目录输出位置是外部契约，`run_home_root` 默认假设
`runtime-data/demo-runs/<case_id>`。若演示机 AGH 布局不同，改 `config.json` 的
`run_home_root` 即可，无需改代码。任一一例失败会继续下一例，最终如实汇总。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/cases` | 45 例元数据（case_id/title/type/difficulty/problem_kind/symptom/expected_decision） |
| GET | `/api/env` | 能力探测（Docker/DB/AGH/key/runs_dir） |
| POST | `/api/run` | `{mode, only_bundled, case_ids?}` → `{run_id}` |
| GET | `/api/runs` | 运行摘要列表 |
| GET | `/api/runs/<id>` | 状态 + 进度 + 完成后的 `report` |
| GET | `/api/runs/<id>/case/<case_id>` | 单例评分结果 |

## 隔离与诚实性

- 复用 `datasets/evaluation/run_eval.py` 的 `run()` 与 `scripts/export_evaluation_run.py`，
  不修改这两个文件。评分结果落盘 `webui/out/<run_id>/report.json`，可与
  `python datasets/evaluation/run_eval.py --runs ... --out ... --only-bundled` 逐字段比对。
- 「缺失运行包」是一等状态如实展示（`cases_missing_bundle`），不假装通过。真跑补齐
  45 份运行包前，`overall_passed` 保持 false，与设计文档的诚实口径一致。
- 无密钥入代码；`webui/out/` 与 `config.json` 已 gitignore。
