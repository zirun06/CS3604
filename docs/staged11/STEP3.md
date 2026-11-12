# 第 3 步 · 运行预算、验证反馈与续跑保护

本轮从 `19683a0` 继续，沿用已导入的 11 阶段、模型 SDK 及 Node 检查入口。模型 HTTP 均由本地 mock 传输返回。第 4 步及以后仍未开始。

| 验收项 | 本轮证据 |
| --- | --- |
| 全局调用与重试计数 | native `_request()` 一次逻辑调用，真实走到 mock 传输三次，分别为原请求、SDK 重试、兼容重试。另测 HTTP 次数耗尽、文件读取与上下文检索连续请求、截断、usage 缺失、模型回报超预算、SDK 退避超过时限。 |
| 视觉并发和耗时 | 视觉提交前预留调用、HTTP 和 token 额度。两图一槽时只提交一图，关联阶段、需求 ID 和批次仍可读，成功图产物保留。子进程 mock 验证了剩余超时、清理调用和过期不启动。 |
| 状态与恢复 | 临时应用仓库中分别验证模型额度耗尽、墙钟过期和中断。已有产物保留，模型额度耗尽后确定性阶段仍执行，过期后后续阶段只登记。总报告非 GREEN。 |
| 续跑安全 | `--stage` 仅运行选定阶段，`--from-stage` 运行到末尾。两条路径均实测 Git 回滚并比较 schema 字节。源码/输入/父目录、未标记仓库、改变的 YAML、参考图、源码、配置和应用产物不能作为有效续跑依据。 |
| 反馈统计 | 事件中包含检查类型、阶段、需求或视觉批次、耗时、结果及用例来源。生成与复核的调用数及各类 token 独立按测试文件归集。阶段报告给出分类次数、总耗时、通过率和首次可执行反馈时间。 |

以上证据见 [step3-evidence.json](step3-evidence.json) 及 `compiler/tests/test_budget*.py`。证据中的时间和 token 来自离线夹具，不代表真实模型性能或账单。

## 配置与报告口径

- 在进程环境或 `compiler/.env` 设置 `COMPILER_BUDGET_CALLS`、`COMPILER_BUDGET_HTTP_ATTEMPTS`、`COMPILER_BUDGET_TOKENS`、`COMPILER_BUDGET_SECONDS`。可以同时开启四项，未设置的维度不限制。调用数为入场的逻辑调用，兼容回退与 SDK 重试不另记逻辑调用，但每次通过 HTTP 出口都扣一次 HTTP 额度。
- token 预留采用 UTF-8 文本字节数、协议余量、图像预估和限制后的输出上限。图像每张默认预留 4096，可用 `COMPILER_IMAGE_TOKEN_RESERVE` 修改。每次 HTTP 响应按实际 usage 结算，usage 缺失则保留预留扣款，使用量在统计中标明缺失。网关若报告超过预估的实际量，记录真实值并阻断后续模型请求，无法撤销已经发生的用量。缓存计入输入，推理计入输出，均不重复相加。
- 保留随阶段向后释放的额度。墙钟预留最多 5 秒用于收尾，有阶段 10 时模型另让出最多 30 秒供集成检查。HTTP 各 I/O 阶段、SDK 退避、安装、构建和测试的等待会根据剩余时间收紧。同步 I/O、进程清理和最终报告或 Git 写入可能发生在名义截止之后，不作硬实时承诺。
- `COMPILER_PRICE_TABLE` 可指定同结构 CNY JSON 价表，报告记录所用文件和内容。费用为估算，缺 usage 或价格时标明不完整。实际模型开销未验证。
- `compilation_events.jsonl` 记录逐次验证。阶段报告的 `validations` 提供分类统计，`first_validation_seconds` 从阶段开始计到首条可执行检查的通过或失败，依赖安装和未执行项不参与首反馈。通过率分母为通过加失败，未执行另计。测试作者的用量附在该测试的验证事件中，回归反复运行同一测试不会重复计入全局模型开销。数据库探针区分初始化与启动，浏览器与 HTTP 套件记录其整体执行结果。
- 回滚只接受目标路径匹配的生成仓库和完整检查点。检查点绑定输入、源码及生效配置的 SHA-256，设计产物和应用文件绑定实际暂存的 Git blob。配置摘要不含 API Key。第 3 步前生成的输出没有新身份记录，需另建新输出再验证。

## 实际命令

除特别注明，工作目录为 `LAB/CS3604-staged11`。uv 使用 worktree 内隔离副本。pytest 运行前设置 `PYTHONUTF8=1`、`PYTHONDONTWRITEBYTECODE=1`、`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，uv 缓存在 `compiler/outputs/uv-cache`。

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| UTF-8 严格读取三份修复文档，检查中文和连续问号，再本地提交 | 0 | `19683a0`，第 1 步段落字节未变 |
| `uv run --project compiler --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q -rs --tb=short compiler/tests/test_budget.py compiler/tests/test_console_logging.py compiler/tests/test_compiler.py` | 0 | 31 通过 |
| 首次 `pytest compiler/tests/test_budget_boundaries.py` | 1 | 截断夹具 token 上限太小，在发包前被正确拦截。修正夹具后复测通过 |
| `pytest compiler/tests/test_budget_pipeline.py --basetemp compiler/outputs/staged11-budget-git`（同一 uv 环境） | 0 | 10 通过 |
| `uv run --project compiler --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q -rs --tb=short compiler/tests -k "not timeout_stops_descendants" --basetemp compiler/outputs/staged11-step3-verified` | 0 | 114 通过、1 跳过、1 未选择。跳过为原有独立 DB 测试的依赖配置缺失 |
| `pytest compiler/tests/test_budget.py compiler/tests/test_budget_boundaries.py compiler/tests/test_console_logging.py --basetemp compiler/outputs/staged11-step3-boundaries`（同一 uv 环境，补测最终验证预留） | 0 | 36 通过 |
| UTF-8 读取 100 个运行时 Python 文件后 AST 解析，`node --check compiler/outputs/staged11-step3-probe.mjs` | 0 | 静态检查通过 |
| 离线事件、状态、续跑产物摘要提取与 UTF-8 回读 | 0 | 写入 step3-evidence.json |
| `git diff --check` | 0 | 变更格式检查通过 |

## 沙箱外验证

工作目录为 `D:\爱学习\课程\大三上\软件工程项目管理\LAB\CS3604-staged11\compiler`。以下验证命令均不需要模型 API。

1. 真实 Windows 进程树清理：`uv run --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q tests/test_portability.py -k timeout_stops_descendants`。本轮主动未选择该用例，未改动原测试的跳过规则。
2. 用 Node 22 和可用的 Chromium 执行合成输入的真实 Node/浏览器检查。设置 `$env:STAGED11_REAL_CHECKS='1'` 后运行 `uv run --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q tests/test_staged_pipeline.py -k original`。合成测试继续使用 mock 模型，真实运行 `tsx`、SQLite、构建、HTTP 和浏览器检查。运行后清除该变量。
3. 若要单独复测数据库重启，可将 `ARC_DB_TEST_NODE_MODULES` 指到已安装的生成应用 `node_modules`，然后运行 `uv run --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q tests/test_database_runtime.py`。当前该项沿用原测试的前提。

待验证：真实网关计价和图像 token 误差、真实 Windows 清理和完整浏览器时序。候选打包、部署、批处理改造和 BookStack 生成均不在本轮。
