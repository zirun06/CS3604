# 离线公开验收

这里的公开用例只在应用生成并构建后单独运行。评测脚本需要显式指定用例目录，不读取需求或根据指纹选题。

从仓库根目录运行（PowerShell）：

```powershell
$env:PYTHONPATH = (Resolve-Path compiler).Path
uv run --project compiler --locked python offline_eval/verify_app.py <用例目录> <应用目录> --report <报告路径>
```

从 `public/` 选择明确对应的套件目录。历史 SHA 目录及原索引留作溯源。使用 `--grep` 可以选择标题匹配的场景。评测使用独立的 Playwright 工作区，并以测试端口和内存数据库启动已构建应用。

`legacy/` 保留旧 compact 代码、专用配置、旧测试、样例及路由诊断供查证。其 imports 和命令对应历史版本。需要运行旧版时使用历史发布分支。
