# 第 7 步：BookStack 真实运行手册（尚未授权执行）

从 `CS3604-staged11` 根目录用 PowerShell 操作。先等组长确认单次和累计预算、API 连接、文本和视觉模型、网关价格及图片支持。**不要在聊天、Git 或日志中填写密钥；只在 `compiler/.env` 本地填写。**

```powershell
$root = (Get-Location).Path
Set-Location (Join-Path $root 'compiler')
$env:PATH = (Resolve-Path 'outputs/node22/node_modules/node/bin').Path + ';' + $env:PATH
node --version
git --version
uv sync --locked
if ($LASTEXITCODE -ne 0) { throw 'Python dependencies failed' }
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
```

使用经复验的 **Node 22.23.5**，模板要求 22 系列至少 22.12。还需要 npm、Git、Python 3.11+ 和 uv。若本机未使用上面的隔离目录，先把本机 Node 22 的目录放在 PATH 首位。编辑 `.env` 中的 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`MODEL`、`VISUAL_MODEL`；文本与视觉共用一个连接。需要时设置 `MODEL_REASONING`、`VISUAL_REASONING`（起点均为 `low`）和 `COMPILER_PRICE_TABLE`。系统已注入的同名变量优先。

建议的**单次讨论起点**如下，不是已批准预算，也不是保证能跑完的额度。4a＋4b 的 BookStack 首轮估算为 111–195 个逻辑调用；修复、发现新上下文和截断可能增加调用。

| 变量 | 建议起点 | 含义 |
| --- | ---: | --- |
| `COMPILER_BUDGET_SECONDS` | 1800 | 一次编译的墙钟时间，含本地检查 |
| `COMPILER_BUDGET_TOKENS` | 1000000 | 一次编译的 token 总预算，发出前做预留 |
| `COMPILER_BUDGET_CALLS` | 120 | 逻辑模型调用，包括读取上下文和修复 |
| `COMPILER_BUDGET_HTTP_ATTEMPTS` | 150 | 实际请求次数上限，重试和协议回退也计入 |
| `MAX_OUTPUT_TOKENS` | 24000 | 文本单次输出上限，含推理 token；以网关支持为准 |

另行确认累计 token 或金额上限，以及到达上限的停止条件。累计预算需要逐次扣除，包含连接探测、失败请求、诊断和所有重跑。定价表用 `currency: CNY`、`unit_tokens` 和每个模型的 `input`、`cached`（可选）、`output`；用网关确认的价格覆盖随包提供的估算表。

确认授权后先做最小连接探测，先文本，只有文本通过且预算允许才做单图。以下命令会请求模型，**本轮未执行**。它分别限制一次实际 HTTP 尝试并保存记录：

```powershell
$rev = (git rev-parse HEAD).Trim()
if (git status --porcelain) { throw 'Freeze and commit the compiler before a paid run' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$record = Join-Path $root "compiler/outputs/bookstack-evidence-$stamp"
$app = Join-Path $root "compiler/outputs/bookstack-app-$stamp"
New-Item -ItemType Directory -Path $record -ErrorAction Stop | Out-Null
$env:ARC_PROBE_RECORD = $record
$env:ARC_SOURCE_REVISION = $rev
$env:ARC_PROBE_KIND = 'text'
$probe = @'
import os
from pathlib import Path
from infrastructure.shared.models.text import TextModel
from infrastructure.shared.models.vision import VisualModel
from infrastructure.shared.project.provenance import effective_settings
from infrastructure.utils.budget import RunBudget, budget_scope
from infrastructure.utils.files import save_json
from infrastructure.utils.presentation.events import begin_run, finish_run

out = Path(os.environ["ARC_PROBE_RECORD"])
kind = os.environ["ARC_PROBE_KIND"]
folder = out / ("probe-" + kind)
source = Path("../requirements/arc-bench-web--bookstack").resolve()
settings = effective_settings()
if not settings.get("OPENAI_API_KEY") or not settings.get("OPENAI_BASE_URL"):
    raise SystemExit("Set OPENAI_API_KEY and OPENAI_BASE_URL in compiler/.env")
os.environ["MAX_OUTPUT_TOKENS"] = "512"
with budget_scope(RunBudget({"calls": 1, "http_attempts": 1, "tokens": 16000, "seconds": 60})):
    run, _ = begin_run(folder, source, None, settings)
    model, status = None, "FAILED"
    try:
        if kind == "text":
            model = TextModel()
            assert model.generate_json('Return only {"ok":true}', {}) == {"ok": True}
        else:
            model = VisualModel()
            assert isinstance(model.analyze(source / "reference/book.png", max_attempts=1), dict)
        status = "GREEN"
    finally:
        if model is not None:
            model.client.close()
        save_json(folder / "report.json", {"status": status, "revision": os.environ["ARC_SOURCE_REVISION"],
            "kind": kind, **finish_run(run, status)})
print("Probe GREEN:", kind)
'@
$probe | uv run --locked python -
if ($LASTEXITCODE -ne 0) { throw 'Text probe failed; inspect evidence and budget' }
$env:ARC_PROBE_KIND = 'image'
$probe | uv run --locked python -
if ($LASTEXITCODE -ne 0) { throw 'Image probe failed; confirm the cause before full generation' }
```

如果确认同一网关不支持图片，记录原因，继续使用同一连接。当前入口没有“仅跳过视觉”开关；先确认第 7 步的跳过办法，别拿整批图像请求反复探测。预算仍足且配置已确认后，从空输出目录启动：

```powershell
$env:COMPILER_BUDGET_SECONDS = '1800'
$env:COMPILER_BUDGET_TOKENS = '1000000'
$env:COMPILER_BUDGET_CALLS = '120'
$env:COMPILER_BUDGET_HTTP_ATTEMPTS = '150'
$env:MAX_OUTPUT_TOKENS = '24000'
if (Test-Path $app) { throw 'Choose a new output directory' }
[IO.File]::WriteAllText((Join-Path $record 'revision.txt'), $rev + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
uv run --locked python main.py '../requirements/arc-bench-web--bookstack' --output-dir $app
Get-Content -Encoding UTF8 (Join-Path $app '.arc/compilation.json')
```

普通编译失败也可能退出 0，按报告状态判断。保留非完整结果；只有应用已可运行，才继续构建、部署和公开评测：

```powershell
Set-Location $root
$env:PYTHONPATH = (Resolve-Path 'compiler').Path
$deploy = uv run --project compiler --locked python offline_eval/check_deployment.py $app --bash 'C:\Program Files\Git\bin\bash.exe'
$deployExit = $LASTEXITCODE
[IO.File]::WriteAllLines((Join-Path $record 'deployment.json'), [string[]]$deploy, [Text.UTF8Encoding]::new($false))
if ($deployExit -ne 0) { throw 'Inspect deployment.json before proceeding' }
$suite = (Resolve-Path 'offline_eval/public/8189d63bbffef9e873d3c27589dbe26532f44afa2d485d3e9d1d8c593f7e7274').Path
uv run --project compiler --locked python offline_eval/verify_app.py $suite $app --report (Join-Path $record 'public-acceptance.json')
```

每次保存：冻结的提交、ZIP 哈希、模型名及参数、已确认的预算和价格表（不含密钥）、探测报告、`.arc/compilation.json`、`compilation_events.jsonl`、`compiler.log`、`.arc/acceptance/` 与失败归档、部署 JSON、公开用例通过／失败／跳过数、实际 token／费用／耗时。标注“新生成”“同产物诊断”或“同配置重复运行”；最终成绩必须来自一次从空目录完整生成。35/35 是目标，当前无真实结果。
