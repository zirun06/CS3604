# 第 7 步 BookStack 真实运行手册

从 `CS3604-staged11` 根目录用 PowerShell 操作。真实生成由组长在沙箱外执行。已确认单次预算为 40 分钟、150 万 token、220 次逻辑调用，累计先按 3 次完整运行、约 450 万 token 管理。**不要在聊天、Git 或日志中填写密钥；只在 `compiler/.env` 本地填写。**

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

使用经复验的 **Node 22.23.5**，模板要求 22 系列至少 22.12。还需要 npm、Git、Python 3.11+ 和 uv。若本机未使用上面的隔离目录，先把本机 Node 22 的目录放在 PATH 首位。编辑 `.env` 中的 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`MODEL`、`VISUAL_MODEL`；文本与视觉共用一个连接。需要时设置 `MODEL_REASONING`、`VISUAL_REASONING`（文本初次提案 `none`、修复 `MODEL_REPAIR_REASONING=low`、视觉 `low`）和 `COMPILER_PRICE_TABLE`。系统已注入的同名变量优先。

组长批准的单次预算如下，累计先按三次完整运行、约 450 万 token。4a＋4b 的 BookStack 首轮估算为 111–195 个逻辑调用；修复、发现新上下文和截断可能增加调用。

| 变量 | 建议起点 | 含义 |
| --- | ---: | --- |
| `COMPILER_BUDGET_SECONDS` | 2400 | 一次编译的墙钟时间，含本地检查 |
| `COMPILER_BUDGET_TOKENS` | 1500000 | 一次编译的 token 总预算，发出前做预留 |
| `COMPILER_BUDGET_CALLS` | 220 | 逻辑模型调用，包括读取上下文和修复 |
| `COMPILER_BUDGET_HTTP_ATTEMPTS` | 280 | 实际请求次数上限，重试和协议回退也计入 |
| `MAX_OUTPUT_TOKENS` | 24000 | 文本单次输出上限，含推理 token；以网关支持为准 |

当前累计额度约 450 万 token，按 3 次完整运行管理。连接探测、失败请求、诊断和所有重跑都纳入用量记录。分别记上报 token 和无 usage 的保守结算，并按网关账单核对差额。定价表用 `currency: CNY`、`unit_tokens` 和每个模型的 `input`、`cached`（可选）、`output`；用网关确认的价格覆盖随包提供的估算表。

新连接先做文本探测，通过且预算允许时再做单图探测。以下命令分别限制一次实际 HTTP 尝试并保存记录。第 2 次沿用已探测连接时可直接执行下一节。

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
with budget_scope(RunBudget({"calls": 1, "http_attempts": 1, "tokens": 16000, "seconds": 240})):
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

如果同一网关不支持图片，先记录探测原因。当前入口需要视觉阶段产物，整批图像请求会消耗已确认预算。

## 第 2 次运行

第 1 次已用同一连接完成文本和图片探测。连接配置一致时，从仓库根目录复制以下命令，用新的输出目录启动。阶段默认配置见 [运行分析](STEP7_RUN1.md)。

```powershell
$root = (Get-Location).Path
Set-Location (Join-Path $root 'compiler')
$env:PATH = (Resolve-Path 'outputs/node22/node_modules/node/bin').Path + ';' + $env:PATH
node --version
$rev = (git rev-parse HEAD).Trim()
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$record = Join-Path $root "compiler/outputs/bookstack-evidence-$stamp-run2"
$app = Join-Path $root "compiler/outputs/bookstack-app-$stamp-run2"
New-Item -ItemType Directory -Path $record -ErrorAction Stop | Out-Null
$env:COMPILER_BUDGET_SECONDS = '2400'
$env:COMPILER_BUDGET_TOKENS = '1500000'
$env:COMPILER_BUDGET_CALLS = '220'
$env:COMPILER_BUDGET_HTTP_ATTEMPTS = '280'
$env:MAX_OUTPUT_TOKENS = '24000'
$env:MODEL_REASONING = 'none'
$env:MODEL_REPAIR_REASONING = 'low'
$env:VISUAL_REASONING = 'low'
if (Test-Path $app) { throw 'Choose a new output directory' }
$encoding = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText((Join-Path $record 'revision.txt'), $rev + [Environment]::NewLine, $encoding)
$log = [IO.StreamWriter]::new((Join-Path $record 'run2-console.log'), $false, $encoding)
try {
    uv run --locked python main.py '../requirements/arc-bench-web--bookstack' --output-dir $app 2>&1 |
        ForEach-Object { $line = [string]$_; $log.WriteLine($line); Write-Host $line }
    $compileExit = $LASTEXITCODE
} finally {
    $log.Dispose()
}
Write-Host "Compiler exit code $compileExit"
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
