# 第 7 步 BookStack 第 1 次运行分析

## 第 1 次运行

源码 05f1d8d，模型 deepseek-flash，Node 22.23.5，空目录启动。2251 秒后以 COMPLETED_WITH_FAILURES 结束。78 次逻辑调用、84 次 HTTP 尝试、492,973 个上报 token，内置价格估算约 0.905 元。06、09、10 缺前置产物。该轮未部署或运行公开用例。[编译报告](../../compiler/outputs/bookstack-app-20261112-080627-run1/.arc/compilation.json) · [事件](../../compiler/outputs/bookstack-app-20261112-080627-run1/compilation_events.jsonl) · [编译日志](../../compiler/outputs/bookstack-app-20261112-080627-run1/compiler.log) · [运行配置](../../compiler/outputs/bookstack-evidence-20261112-080627/run1-config.txt)

| 问题 | 独立核对 |
| --- | --- |
| 失败传播 | 03 的 10 个批次中 9 个接受。单叶 B003 缺少义务，05 仍按所有叶子索引义务，触发 KeyError。05 的产物未生成，06、09、10 的文件级前置检查随即拦截。04 的种子生成超时是另一条失败链。 |
| 预算差额 | 1,396,078 = 492,973（67 次有 usage）+ 903,105（17 次未上报 usage 的请求按上界结算）；收尾时在途预留为 0。上界包括按序列化请求字节计的文本、图像预留与请求的输出上限。旧文本上限为 24,000。日志里缺少这 17 次的服务端计费信息。07 的拒绝来自阶段 token 额度，旧公式按后续阶段个数最多留总量的 25%。 |
| 超时 | 旧请求钩子对连接、写入、读取和连接池一律取剩余时间的四分之一。04 种子批的最终错误在约 31 秒后，07 两个批次约 88 和 38 秒后。组长独立测得网关首字节 14–21 秒。旧公式能解释短探测的 15 秒读超时，日志没有每次请求的服务端首字节时间。 |
| 时间 | 02 和 03 共约 1601 秒，占 2400 秒额度约 67%。02 分 10 批、调用 15 次，03 分 10 批、调用 26 次。两者串行，后续实现可用时间被压缩。 |
| 推理 | 154,632 个输出 token 中 128,223 个用于推理，约 83%。02 的 58,943 个输出 token 中 52,947 个用于推理。推理对真实结果质量和响应时间的影响由下一轮复测。 |
| 重试 | 03 的 17 次拒绝包括 9 次 JSON 尾随内容、6 次缺 steps 和 2 次步骤义务与叶义务不一致。B003 前四次是 JSON 尾随内容，第五次才缺 steps。旧提示要求嵌套的逐叶产物，落盘却是平坦映射。旧反馈会附带整段无效响应。02 多出的 5 次调用来自 B003 的 2 次有效上下文查询及 1 次类型不合法的查询，以及 B008 的 2 次 JSON 尾随内容。 |

## 改动与依据

1. 03 按完整叶子发布义务并列出未接受的叶子及缺失步骤。05 和 09 在各自报告里标注上游缺口，继续其余叶子。06 汇总契约缺口并按 API 的表和外键依赖过滤，10 汇总触发器设计和所需 API 的缺口。04 的种子或 DDL 请求耗尽 SDK 重试后，复用批次的快照、失败归档和拆分逻辑。04 只把依赖已齐全的表纳入初始化与数据库验证，阶段报告继续保留失败。
2. 每次 HTTP 请求仍在发出前原子预留输入与输出。用量已上报时按实结算。连接尚未建立、端点明确以 400/422 拒绝兼容参数时，缺 usage 按 0 结算，HTTP 尝试仍计数。读取超时等不明确结果仍按上界结算。文本请求采用紧凑 JSON，阶段上限直接应用到请求，事件记录输入和输出预留、上报量、结算量及未处理原因。保守估计仍可能高于账单，预算的上界保证依赖网关遵守输出上限及图像预留能覆盖其输入计费。
3. 读取可用完整的剩余模型窗口，连接最多 10 秒、写入最多 15 秒、连接池最多 5 秒，并逐次将套接字操作限制在同一个绝对截止时间。SDK 退避也检查余量。同步传输沿用锁定的 HTTPX 0.28.1 和 httpcore 1.0.9，绝对截止时间通过替换连接池的网络后端实现。探测窗口改为 240 秒，仍限制一次实际请求。[运行手册](RUN_BOOKSTACK.md)
4. 03 默认 3 路。各批次读取固定 schema 并独立校验，主线程按原批次顺序发布，单批失败留在自己的报告中。截断或批次反复拒绝时可拆分。令牌预留竞争时，等待其他在途请求结算或阶段截止。02 增量维护 schema，05 复用已接受的契约和共享约定，07 复用页面和元素，09 复用已有触发器，保留串行。并发下请求取得额度的顺序可能变化，预算宽裕时同一组模型响应的发布结果保持一致。交互暂停模式用单路。
5. DeepSeek 文本初次设计、测试生成和按契约实现使用 none，校验失败后的纠错、文件修复及显式验收测试复核使用 low。其他文本模型默认由提供方决定，视觉仍为 low。用 MODEL_REASONING 和 MODEL_REPAIR_REASONING 分别覆盖初次和修复，VISUAL_REASONING 单独控制视觉。显式配置的现有 .env 会覆盖默认值，第 2 次命令设置进程级变量。06、10 仍先写测试再实现。
6. 03 的模型输入逐叶列出 expected_step_ids，要求单个 JSON 对象，其中 requirements 和 steps 是同级映射，按对应 ID 校验。设计批次的纠错发送具体错误与必要细节，日志保留原响应，重试请求省略整个错误样例。每次提案的接受或拒绝会记录 design_proposal 事件，03 由主线程写发布检查点。02 的共享 schema 与上下文查询协议保持原样。

## 默认配额与第 2 次运行

阶段权重依次为 1、13、14、12、10、9、12、7、7、5、10。40 分钟时先留 5 秒写最终报告，按 2395 秒分配。权重设定给 02、03 共 26%，04、06、08、10 共 39%。阶段提前结束后，剩余时间可由后续阶段使用。只跑部分阶段时，对选中阶段重新归一化。四个实现阶段的模型窗口末尾最多留 30 秒给本地检查，检查受阶段总截止时间约束。

| 阶段 | 00 | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 名义时间份额（秒，约） | 24 | 311 | 335 | 287 | 240 | 216 | 287 | 168 | 168 | 120 | 240 |
| 从运行开始累计截止（秒，约） | 24 | 335 | 671 | 958 | 1198 | 1413 | 1700 | 1868 | 2036 | 2156 | 2395 |

COMPILER_STAGE_WEIGHTS 可覆盖编号到权重的映射，例如 {"02":16,"03":12}。COMPILER_STAGE_OUTPUT_CAPS 可覆盖文本阶段编号到输出上限的映射，默认 02/04 为 8192，03 为 6144，05–10 为 12288，并受 MAX_OUTPUT_TOKENS 约束。视觉请求原有输出上限为 4096。COMPILER_OBLIGATION_WORKERS 接受 1 到 16，默认 3。建议第 2 次继续用 2400 秒、150 万 token、220 次逻辑调用、280 次 HTTP 尝试及 MAX_OUTPUT_TOKENS=24000，沿用同一文本和视觉模型。先用默认权重和 03 并发度，保留可比较的事件与用量。

预计 09 和 10 能在有前置产物时实际尝试，个别需求缺口会按叶子显示。02 过去耗时 853 秒，新截止时间约为 671 秒（含之前阶段），完整 schema 取决于初次关闭推理后的响应时间与提案质量。11 阶段全绿还取决于 04/06/08/10 的真实本地检查。优先比较阶段耗时、首次提案通过率、并发 HTTP 尝试与峰值用量，以及 10 的逐条验收。应用可运行后再做部署和公开验收。[运行手册](RUN_BOOKSTACK.md)

## 离线证据

- 新增 test_run1_regressions.py 覆盖阶段时间权重、重复读取的绝对截止时间、输出上限及 usage 结算、推理模式、并发预算等待、串并行产物一致和批次失败隔离、种子回滚。
- test_staged_pipeline.py 新增 partial-obligations 用例。替换检查模式下，03、05、06、09、10 标为 COMPLETED_WITH_FAILURES。06 接受另一叶的 API，10 一条 GREEN、一条 FAILED。完整合成用例仍检查 11 阶段全部 GREEN。


替换检查的局部回归证据位于 `compiler/outputs/staged11-step7-regressions/`，其中合成应用的 `.arc/compilation.json`、`backend_tdd.json`、`frontend_e2e.json` 和 `compilation_events.jsonl` 可核对逐条结果。测试从仓库根目录执行，统一设 `STAGED11_REAL_CHECKS=0`，使用 `compiler/outputs/staged11-tools/bin/uv.exe` 与本地缓存。

| 命令或范围 | 退出码 | 结果 |
| --- | ---: | --- |
| `uv run --project compiler --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q -rs --tb=short compiler/tests offline_eval/tests -k 'not timeout_stops_descendants' --basetemp compiler/outputs/staged11-step7-final` | 0 | 154 通过、1 跳过、1 未选择、38 个子测试通过，耗时 421.92 秒 |
| `uv run --project compiler --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q -rs --tb=short compiler/tests/test_run1_regressions.py compiler/tests/test_console_logging.py compiler/tests/test_staged_pipeline.py -k 'not unseen and not original and not artifact and not multi_leaf' --basetemp compiler/outputs/staged11-step7-regressions` | 0 | 34 通过、4 未选择、16 个子测试通过 |
| `git diff --check` | 0 | 补丁格式检查通过 |
| `git grep -in -E 'bookstack\|ctrip\|prestashop\|stackoverflow\|12306\|arc-bench-web--\|acceptance_cases\|bundled_suite\|select_profile' -- compiler/infrastructure compiler/main.py` | 1 | 无匹配 |

全量结果中，四份完整合成输入的 11 阶段全部 GREEN，部分失败用例另有逐叶结果。全量产物位于 `compiler/outputs/staged11-step7-final/`。跳过项需要 ARC_DB_TEST_NODE_MODULES。早期回归发现测试夹具依赖旧推理默认值，部分失败用例也漏接了入口约定的退出码 0，均已修正。

本轮没有实际模型调用。Node 22、npm、真实后端、Chromium 和网关超时路径由组长在沙箱外复验。沙箱内全量命令排除 Windows `timeout_stops_descendants`，该测试的代码和选择条件未改动。可在编译器目录执行下面的复验命令。

```powershell
$env:PATH = (Resolve-Path 'outputs/node22/node_modules/node/bin').Path + ';' + $env:PATH
$env:STAGED11_REAL_CHECKS = '1'
uv run --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q tests/test_staged_pipeline.py
uv run --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q tests -k timeout_stops_descendants
```

## 变更文件

| 路径 | 文件 |
| --- | --- |
| compiler | .env.example |
| compiler/infrastructure | compiler.py |
| compiler/infrastructure/pipeline | backend_apis.py、backend_implementation.py、database.py、db_obligations.py |
| compiler/infrastructure/shared/agent | design_batches.py、loop.py、proposals.py、recovery.py、tasks.py |
| compiler/infrastructure/shared/models、shared/project | text.py、provenance.py |
| compiler/infrastructure/stages/backend、stages/database | context.py、implementation_agent.py、obligation_utils.py |
| compiler/infrastructure/stages/frontend/triggers | implementation.py、synthesis.py |
| compiler/infrastructure/utils | budget.py、presentation/model_io.py |
| compiler/tests | test_console_logging.py、test_staged_pipeline.py、新增 test_run1_regressions.py |
| docs/staged11 | PROGRESS.md、RUN_BOOKSTACK.md、新增 STEP7_RUN1.md |
