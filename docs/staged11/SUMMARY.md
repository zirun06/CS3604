# staged-11pass：第 1–6 步总结

编译器保留老师的 11 阶段入口，按需求和产物依赖分批，保留逐条验收、预算和恢复证据。第 1–6 步已完成本地离线改造。**BookStack 真实生成尚未进行，等待 API Key 和预算。** 第 7 步的命令和记录约定见 [RUN_BOOKSTACK.md](RUN_BOOKSTACK.md)。

| 阶段（完整名称见 `python main.py --help`） | 职责与主要产物 |
| --- | --- |
| 00 `00_project_initialization` | 加载 React／Express／SQLite 模板，建立生成应用 Git 检查点 |
| 01 `01_explore_requirement` | 读取需求树和参考图，写 `.arc/requirements.json`、`visual_analysis.json` |
| 02 `02_build_db_schema` | 按批设计实体、字段和需求归属，写 `db_schema.json`、共享符号目录 |
| 03 `03_infer_db_obligations` | 校验逐需求及逐步骤数据库读写义务，写 `db_obligations.json` |
| 04 `04_implement_db` | 按外键生成 DDL，按来源生成前置种子，写 SQL、初始化文件及 `db_checks.json` |
| 05 `05_design_backend_apis` | 按批设计 HTTP、内部模块、调用图和约定，写 `backend_apis.json`、`shared_conventions.json` |
| 06 `06_implement_backend_tdd` | 按业务能力分组生成 HTTP 测试并实现，写后端与 `backend_tdd.json` |
| 07 `07_design_ui` | 设计完整页面、元素、可访问名称及数据绑定，写 `ui_design.json` |
| 08 `08_implement_ui` | 按共享布局实现页面，不启后端跑存在性和确定性渲染检查，写 `ui_checks.json` |
| 09 `09_design_frontend_triggers` | 把交互连到 API 和前端状态，保留逐步义务验证，写 `frontend_triggers.json` |
| 10 `10_implement_frontend_tdd` | 按批生成、复核、冻结验收测试后实现交互，用真实后端验证，写 `frontend_e2e.json` 和验收证据 |

跨阶段证据包括 `.arc/compilation.json`、设计与实现批次清单、`.arc/acceptance/`、失败归档和 `compilation_events.jsonl`。预算限制逻辑调用、HTTP 尝试、token 和墙钟时间；验证记录区分类型、结果、耗时、测试来源、生成／复核资源及首次反馈时间。未完整阶段不会被报告为 GREEN，恢复会核对输入、编译器、配置和已提交产物。

[逐文件对照](step6-teacher-delta.json) 基于 [老师导入清单](import-manifest.json)，列出每个修改、移出或新增的编译器文件及原因。提交 `6e0296d` 原样导入老师 `b5ac6598139d0cb32c4adb0146945014b6ce4039` 的 156 个文件，`0a8cc05` 才做小组适配。归档的 418 个旧文件、原公开用例、索引与样例留在 `offline_eval/`；专用 GUIDANCE、指纹选路、业务组件改写和初始数据推断不进入运行时。保留小组的路由依赖与 Windows 异步复制适配，文本和视觉共用平台连接。

| 步骤 | 实现、验证及证据 |
| --- | --- |
| 1–2 | 教师 blob 导入、依赖与模板适配、历史归档。见 [基线](BASELINE.md)、[导入命令](COMMANDS.md)、[导入审计](import-result.json) |
| 3 | 预算、验证反馈统计、非完整状态与来源安全恢复。见 [STEP3](STEP3.md) |
| 4a | 按顶层模块、显式依赖和共享符号拆设计批，逐叶／场景／步骤验覆盖，输出截断可拆。六题规划和估算见 [STEP4A](STEP4A.md) |
| 4b | DDL 按外键、API 按能力、UI 按页面布局、E2E 按共享行为分批。保留可独立验证的成功单元，只缩小失败部分。见 [STEP4B](STEP4B.md) |
| 5 | 在已有数据库、浏览器、任务恢复和验收机制上增加持久化、白屏、契约、诊断修复与冻结测试。会话和所有权规则只有原需求明确时才应用；06/10 生成和复核时机不改。见 [STEP5](STEP5.md) |
| 6 | 验包、逐文件扫描、解包干净环境和完整 mock，修复 Windows 部署结果丢失与清理问题。见 [STEP6](STEP6.md)、[包清单](step6-package-audit.json)、[解包执行记录](step6-unpacked.json) |

**验证和局限。** 组长在沙箱外核对第 5 步提交 `3d3eac2`：全量 141 通过、1 跳过；Node 22.23.5 下真实 npm、SQLite、HTTP、Chromium 合成检查 7 通过，四份应用均 11 阶段 GREEN，约 18 分半。这是 mock 模型配真实本地检查。部署实际启动成功，但旧检查工具因 Windows 文件仍占用未能输出 JSON。第 6 步修复后本地真实 Windows 子进程和 SQLite 受控测试通过，真实 Git Bash 待组长复验。当前 ZIP 的真实部署还未验证。

本轮合并回归 142 通过、1 跳过、1 未选择；最后离线部署工具专项 3 通过。解包的 clean venv 逐个导入 105 个模块，`main.py --help` 显示 11 阶段，多产物合成输入 11 阶段 GREEN；阶段选择及续跑可用，普通失败 0、参数错误 2、模拟中断 130。缺连接时报告明确错误。同一 ZIP 也在源码仓库之外的全新系统临时目录通过相同检查。各命令和退出码在 STEP6。没有把浏览器、taskkill 或模型调用的替代验证当作真实结果。

**候选 ZIP。** `compiler/outputs/staged11-step6/compiler-staged11.zip`，280,374 字节，144 文件，SHA-256 `9c62357b75c201ad75005afbb283ab83c24dc511681ee05eaaec631c365128d2`。根入口与依赖清单齐全；没有配置密钥、旧实现、公开套件、开发测试、缓存、输入输出和证据。ZIP 留在忽略目录，未提交。

**资源。** 解包 mock 默认入口记录约 41.15 秒、16 次逻辑 mock 调用、0 次实际 HTTP、0 个已报告模型 token、无模型费用。六题的首轮调用区间见 [估算](step4b-estimates.json)，BookStack 为 111–195 次，非实测。费用按未缓存输入、缓存输入、输出各乘对应价格再除以计费 token 单位。随包估算表中的 flash 输出每百万 token 4 CNY；若按这个配置、总计 100 万 token 且全部为输出，示例上界是 4 CNY。这不是网关报价。当前缺真实 token 结构、价格、调用量、耗时、分数和重跑波动；不能用 mock 补齐。

**实现取舍。** 设计与实现各自按依赖规划，源 ID 和原文位置贯穿阶段，不做不可逆文本压缩。候选无独立证据时整体回退；已独立通过的单元保留，06 批内只做有关回归，阶段末再跑全量。10 在冻结同一组测试后比较候选，不能靠删测试或跳过取得更好分数。展示、业务、文件持久化和部署各报告自己的目标。

**实际状态。** 第 1–6 步源码和证据均做本地提交；未推送。模型 API 未调用，没有 BookStack 真实生成、公开评分、隐藏题验证或重复运行。开始第 7 步前需组长提供本地连接配置并确认文本／视觉模型、图片能力、单次及累计预算和实际价格表，再从冻结提交、空目录生成。
