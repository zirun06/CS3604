# 第 1–2 步命令与退出码

| 命令或检查 | 退出码 | 实测结果 |
| --- | ---: | --- |
| 三个仓库的 `git rev-parse HEAD`、目标 `git status --porcelain=v1` | 0 | 小组起点 1c4082f，老师 b5ac659，小组 main ac8fc86，起始工作区干净 |
| `python --version`、`node --version`、`npm.cmd --version` | 0 | Python 3.13.9、Node 26.13.0、npm 11.20.0 |
| 全局 `uv --version` | 启动被拒 | WinGet 路径拒绝执行 |
| `python -m pip --disable-pip-version-check install --no-cache-dir --target compiler/outputs/staged11-tools uv pytest -r compiler/requirements.txt` | 0 | 安装隔离工具 |
| 教师目录 `python -m pytest -p no:cacheprovider --continue-on-collection-errors -q tests` | 1 | 59 通过、66 失败、6 跳过、11 错误，使用隔离工具依赖，详见 [基线清单](upstream-pytest.txt) |
| `git archive b5ac659 main.py infrastructure tests` 与逐 blob 核验 | 0 | 156 个文件逐字节相同，移除 19 个旧路径 |
| `git add -A`、`git commit` | 0 | 提交一 6e0296d，提交二 0a8cc05 |
| `uv lock --python <本机 Python>`、`uv sync --locked --python <本机 Python>` | 0 / 0 | 重锁并安装，移除 Python Playwright |
| `python main.py --help`、`python offline_eval/verify_app.py --help` | 0 / 0 | 平台入口和离线命令可用，离线命令通过 PYTHONPATH=compiler 使用通用工具 |
| `python main.py <合成需求> --output-dir outputs/staged11-stage00 --stage 00_project_initialization` | 0 | 创建模板、Git 及单阶段 GREEN 报告 |
| 同一入口传 `--profile auto` | 2 | 旧参数被拒绝 |
| 导入及依赖审计 | 0 | 99 个运行时 Python 文件可导入，418 个归档 blob 一致，六个 YAML 可解析，见 [审计结果](import-result.json) |
| `git check-ignore --no-index compiler/tests/test_staged_pipeline.py compiler/.env compiler/infrastructure/shared/project/templates/.gitignore` | 0 | 排除测试和私有 .env，保留模板 .gitignore |
| 合成用例早期迭代、首次迁移后的 pytest | 1 | 修正 mock 契约、Node 依赖探测替身及旧日志和读取断言 |
| `uv run --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q -rs tests --tb=short --basetemp outputs/staged11-pytest-pass` | 0 | 沙箱内 89 通过、2 跳过、38 个通过的 subtest，136.88 秒。组长随后在沙箱外独立复核为 90 通过、1 跳过 |
| 仓库根 pytest `--collect-only -q` | 0 | 仅收集 compiler/tests 的 91 项 |
| `npm.cmd install --prefix outputs/node22 --no-audit --no-fund node@22` | 0 | 隔离 Node v22.23.5 |
| `STAGED11_REAL_CHECKS=1` 合成测试 `-k original`，系统 Node 26 | 1 | better-sqlite3 无相应预编译包，node-gyp 写入本机目录被拒 |
| 同一真实检查，隔离 Node 22 | 1（中止） | npm 依赖和 Chromium 已下载，老师 cpSync 返回 EIO，随后在阶段 08 的 Playwright 处中止，报告为 RUNNING |
| Node 22 独立复制测试，`cpSync` / `await cp` | 1 / 0 | 同一路径同步复制失败、异步成功，故恢复小组异步模板 |
| 合成应用 `npm.cmd install --include=dev --no-audit --no-fund`、`npm.cmd run build` | 0 / 0 | 真实前后端构建，SQL 已复制到 dist |
| 同一应用 `npm.cmd run db:init` | 1 | tsx 的 Windows 用户信息查询 uv_os_get_passwd 返回 ENOMEM |
| Node 22 `node backend/dist/db/setup.js`、`node -e <SQLite SELECT>` | 0 / 0 | 编译后的 SQLite 初始化和查询成功 |
| Node 22 `node backend/dist/server.js` 与本机 HTTP GET | HTTP 200 | 返回 `{"count":0}`，检查脚本退出 0 |
| `taskkill /PID <测试自建进程> /T /F` | 1 | 沙箱内 Access denied。组长确认沙箱外的真实清理测试通过 |
| `git diff --check` | 0 | 最终差异检查通过 |

完整本机日志保存在被 Git 忽略的 `compiler/outputs/`，包括 staged11-upstream-pytest.log、staged11-pass.log、staged11-real.log、staged11-real22.log、staged11-build-smoke.log、staged11-http-smoke.log。中止的真实检查可在相应输出目录查看 compiler.log。产物摘要见 [合成证据](synthetic-evidence.json) 和 [构建后检查](compiled-smoke.json)。
