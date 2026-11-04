# ARC-Bench 课程项目

一个需求编译智能体。它读取需求 YAML 和参考图，生成 React、Express 和 SQLite 应用，并使用随包提供的公开 Playwright 用例验证应用。

- [compiler/](compiler/) 包含智能体入口、编译阶段、依赖锁文件、应用模板、公开用例和打包脚本。
- [requirements/](requirements/) 包含 12306、BookStack、Ctrip、Keep、PrestaShop 和 Stack Overflow 六套完整的需求 YAML 及参考图。
- [PROJECT_STATUS.md](PROJECT_STATUS.md) 记录最近的改动、线上故障和分开统计的本地验证结果。

## 本地运行

需要 Python 3.11+、Node.js 22.12+（含 npm）、Git 和 uv。下面从仓库根目录开始，使用 PowerShell。

```powershell
cd compiler
uv sync --locked
Copy-Item .env.example .env
```

在本机的 `compiler/.env` 填写模型服务配置和 API Key。已有 `.env` 时直接编辑该文件即可。然后运行一个任务：

```powershell
uv run --locked python main.py ../requirements/arc-bench-web--prestashop --output-dir outputs/prestashop
```

换用 `requirements/` 下的其他任务目录即可运行同一个智能体。编译和公开验收报告写入相应输出目录的 `.arc/compilation.json` 和 `.arc/acceptance.json`。

## 导出 ARC-Bench 上传包

在 `compiler/` 下运行以下命令。评测平台运行时提供任务输入和模型配置。

```powershell
uv run --locked python scripts/package.py --output ../arc-compiler-full-track.zip
```

在 ARC-Bench 上提交生成的智能体 ZIP。该 ZIP 的根目录包含 `main.py` 和 `requirements.txt`。GitHub 仓库另外保存了供本地复现的六套任务输入。

## 来源

编译器基于课程提供的 `code-philia/requirement-compilation-structure`，本地起点为上游快照 `885077b96a7d95b0cac77615896a4002b466aa48`。六套任务输入来自本地 ARC-Bench Web Application 导出。
