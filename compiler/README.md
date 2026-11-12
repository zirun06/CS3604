# 11 阶段需求编译器

需要 Python 3.11+、Node.js 22.12+（含 npm）、uv 和 Git。在本目录安装六项 Python 运行依赖。

```powershell
uv sync --locked
Copy-Item .env.example .env
```

本地填入 `OPENAI_BASE_URL`、`OPENAI_API_KEY`。模型默认 `deepseek-flash`，可通过 `MODEL`、`VISUAL_MODEL` 设置模型名。文本和视觉共用连接信息。平台已注入的环境变量优先。

```powershell
uv run --locked python main.py "<requirements-directory>" --output-dir outputs/application
```

这条命令会请求模型。默认编排对所有输入相同，完整阶段名可用 `python main.py --help` 查询。

| 阶段 | 主要产物 |
| --- | --- |
| 00_project_initialization | 应用模板与 Git 检查点 |
| 01_explore_requirement | requirements.json、visual_analysis.json |
| 02_build_db_schema | db_schema.json |
| 03_infer_db_obligations | db_obligations.json |
| 04_implement_db | SQL、初始化、种子及 db_checks.json |
| 05_design_backend_apis | backend_apis.json、shared_conventions.json |
| 06_implement_backend_tdd | API、HTTP 套件与 backend_tdd.json |
| 07_design_ui | ui_design.json |
| 08_implement_ui | 前端页面、存在性测试与 ui_checks.json |
| 09_design_frontend_triggers | frontend_triggers.json |
| 10_implement_frontend_tdd | 前端行为、E2E 套件与 frontend_e2e.json |

`--stage` 重跑单个阶段，`--from-stage` 从选定阶段跑到末尾。两者会在生成应用的 Git 仓库回退到上一阶段的检查点。请把输出指向专用生成应用目录。查看 `.arc/compilation.json` 确认实际阶段状态。普通编译失败保留退出码 0，参数错误为 2，中断为 130。

公开评测由包外工具单独运行，编译器无需提供用例。发布时从本目录运行 `python scripts/package.py --output outputs/compiler.zip`，再核对包清单。

`tests/` 是开发验证目录，打包脚本通过本目录的忽略规则排除它。新增测试首次跟踪时用 `git add -f -- tests/<文件名>`。
