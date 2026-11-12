# 第 6 步：候选包与解包验证

候选包：`compiler/outputs/staged11-step6/compiler-staged11.zip`（`outputs/` 忽略，不进入提交）。

| 项目 | 结果 |
| --- | --- |
| ZIP 大小 | 280,374 字节 |
| SHA-256 | `9c62357b75c201ad75005afbb283ab83c24dc511681ee05eaaec631c365128d2` |
| 文件／目录 | 144 个文件、28 个目录，共 172 个条目；解包文件合计 722,408 字节 |
| 根目录 | `.env.example`、`.gitattributes`、`.gitignore`、`README.md`、`infrastructure/`、`main.py`、`principle.md`、`pyproject.toml`、`requirements.txt`、`scripts/`、`uv.lock` |
| 内容审计 | 无 `.env`、旧 compact、公开评测、`offline_eval/`、`tests/`、`input/`、`outputs/`、缓存、`node_modules/`、`.venv/`、文档证据或生成数据库；`.env.example` 的连接地址和密钥为空 |
| 解包完整性 | ZIP CRC 校验、路径／重复条目／链接检查通过；提取到新空目录后逐文件 SHA-256 相等 |

[包审计清单](step6-package-audit.json) 有完整的 144 个文件名、字节数、哈希及每条扫描规则。首包查出 README 的具体题目路径，以及模板内嵌的 `backend/tests/`。将 README 改为通用示例，把生成应用需要的 HTTP 测试支持源移到编译器 support 目录。00 仍复制到生成应用的 `backend/tests/support/context.ts`，06 仍在同路径发布。空的旧模板目录在包规则中明确排除。

## 全文件扫描

| 模式 | 结果 |
| --- | --- |
| 题目名称、别名、`arc-bench-web--` 前缀；公开用例路径及旧路由标记 | 0 命中。另人工检查大小写敏感的 `\bKeep\b`，31 处均是英文普通动词 |
| 旧索引的 6 个需求 SHA 和 6 个公开套件 SHA | 0 命中 |
| `INSERT … VALUES`、邮箱、显式口令／会话字面量 | 1 处，是 04 探针写入的隔离持久化标记，不是应用业务数据 |
| HTTP(S) URL | 命中 432 行。逐项分类：锁文件中的 PyPI／文件下载域名，其余是本机回环地址；无写死的模型网关 |
| `sk-…`、GitHub token、AWS/Slack 形态、长 Bearer、非空 `OPENAI_API_KEY=` | 0 命中；不在证据中记录任何命中值 |

这是文件级内容与模式审计，不能证明能识别任意混淆或未知密钥形态。

## 干净环境和入口实测

从解包目录用 Python 3.13.9 的独立 venv 按 `requirements.txt` 安装，24 个包，`uv pip check` 退出 0。第一次纯缓存解析缺少 PyYAML 的 CPython 3.13 wheel；允许联网访问软件包索引后安装成功。联网只用于依赖安装。

[解包执行记录](step6-unpacked.json) 保留每条子命令和实际退出码。验证器复制外部的合成输入夹具，在 Python 隔离模式下只加入解包目录，断言运行时模块的物理文件均来自解包目录；禁止 mock 过程的 HTTP 请求，禁止 Git 向上查找源码仓库。测试夹具不是交付依赖。

| 验证 | 实际退出码 | 结果 |
| --- | ---: | --- |
| `python main.py --help` | 0 | 显示全部 11 个阶段 |
| 导入全部 `infrastructure/` Python 模块 | 0 | 105 个，均来自解包根 |
| `--stage 00_project_initialization` | 0 | 只运行 00，GREEN；模板、`deploy.sh` 和应用测试支持文件存在 |
| 无阶段参数，多表／多 API／多页面合成输入 | 0 | 00–10 全部 GREEN；替换本地检查，mock 模型 |
| `--from-stage 09_design_frontend_triggers` | 0 | 从上一检查点恢复，09 和 10 均 GREEN |
| `--stage not-a-stage` | 2 | argparse 报错 |
| 分别缺少 API Key、Base URL | 0 | 01 失败、报告非 GREEN，提示设置 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL` |
| 模拟 `KeyboardInterrupt` | 130 | 明确报告中断 |
| 解包目录向上查找 Git 根 | 128（预期） | 不借用源码仓库 |

默认合成运行约 41.15 秒、16 次逻辑 mock 调用、0 次实际模型 HTTP 请求。没有付费模型 token；这个用时不是实际生成速度。

## 部署检查修复

Windows 离线工具改为暂停启动、先加入专有 Job Object、再恢复执行。由 Job 的成员计数判断存活并回收后代，启动器退出不影响回收。保持编译运行时 `stop_process()` 不变。[Microsoft Job Objects 文档](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) 说明了子进程的归属和整组终止行为。

临时目录清理最多重试五次，普通文件锁错误不能吞掉部署结果；工具始终发布一份 JSON，失败时带 `cleanup.residual_path`，部署成功但清理失败返回 1。受控 Windows 测试真的创建了退出的启动器和持有 SQLite 的子进程；另外模拟了持续文件锁及启动前异常。首次手工探针直接删除数据库时遇到了短暂占用，最终测试用正式重试路径通过。

在沙箱外，从 worktree 根目录复跑真实 Git Bash（`$app` 指向上轮真实检查的 `test_nonempty_pipeline_handoff3/application`）：

```powershell
$env:PATH = (Resolve-Path 'compiler/outputs/node22/node_modules/node/bin').Path + ';' + $env:PATH
$env:PYTHONPATH = (Resolve-Path 'compiler').Path
$app = (Resolve-Path '<上轮真实检查目录>/test_nonempty_pipeline_handoff3/application').Path
uv run --project compiler --locked python offline_eval/check_deployment.py $app --bash 'C:/Program Files/Git/bin/bash.exe'
```

需要同时看到 `status=GREEN` 和 `cleanup.status=GREEN`，再核对没有留下监听进程或数据库临时目录。若要补跑本轮未选的进程树测试，在 `compiler/` 执行 `uv run --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q tests/test_portability.py -k timeout_stops_descendants`。

## 命令及退出码

- 在 `compiler/`：`python -X utf8 scripts/package.py --output outputs/staged11-step6/compiler-staged11.zip`，退出 **0**。
- 在根目录：`python -X utf8 offline_eval/audit_candidate.py compiler/outputs/staged11-step6/compiler-staged11.zip --report docs/staged11/step6-package-audit.json --extract compiler/outputs/staged11-step6/unpacked`，早期审计退出 **1**，修正包内容后退出 **0**。删除空模板目录的 PowerShell 命令被沙箱策略拦截；保留目录，通过忽略规则实现排除。
- 创建独立环境：`uv venv --python <本机 Python 3.13.9> <clean-venv>`，退出 **0**；从解包根运行 `uv pip install --python <clean-venv/Scripts/python.exe> -r requirements.txt`，带 `--offline` 首次退出 **1**，联网安装退出 **0**；`uv pip check --python <clean-venv/Scripts/python.exe>` 退出 **0**。
- 在 `compiler/outputs/staged11-step6/unpacked/`：`../clean-venv/Scripts/python.exe -I -B -X utf8 ../../../../offline_eval/verify_unpacked.py --compiler . --work ../verification2 --fixture ../../../tests/test_staged_pipeline.py`，退出 **0**。首个验证器版本只在 stderr 找连接报错且普通失败继续到了 npm，退出 **1**；最终改为仅运行 00／01，并检查两个输出流和阶段状态。
- 根目录测试：`uv run --project compiler --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q -rs --tb=short compiler/tests offline_eval/tests -k 'not timeout_stops_descendants'`，退出 **0**，142 通过、1 跳过、1 未选择、38 个子测试通过。使用仓库内 uv 缓存和替换检查模式。唯一跳过项缺少 `ARC_DB_TEST_NODE_MODULES`。
- 最终部署修补后，单独运行同一 pytest 前缀加 `offline_eval/tests/test_deployment_cleanup.py`，退出 **0**，3 通过。

- 另把同一 ZIP 解到源码仓库之外的全新系统临时目录，复制验证器与合成夹具，以同一干净 venv 执行同一套检查；外部执行退出 **0**。报告见 step6-unpacked.json 的 outside_worktree，原始日志复制到忽略目录的 outside-worktree/。
