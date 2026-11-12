# 第 1 步现场核对

基线为目标 worktree `staged-11pass` 的 `1c4082ffda9bf7c38f1ca6beedc392710daa6a56`、教师 `b5ac6598139d0cb32c4adb0146945014b6ce4039`、小组 main `ac8fc86ab36f97dcb3be92c2e46f1f0555b1be6b`。目标起始工作区干净，`.git` 指向 CS3604 的 worktree 元数据。目标根、compiler 与已跟踪文件未发现仓库级 AGENTS.md。课程/评测约定沿用实施说明第 3 节。仅在目标 worktree 写入。Python 3.13.9、Node v26.13.0、npm 11.20.0。全局 uv 访问被拒，隔离安装的 uv 0.13.7 可执行。目标 compiler/.env 不存在，两个连接环境变量均未设置。

## 教师阶段、输入与下游

| 阶段 | 输入 | 输出与下游 | 验证和失败 |
| --- | --- | --- | --- |
| 00_project_initialization | 输入/输出目录、端口、应用模板 | 生成前后端、deploy.sh、Git 仓库；后续实现写入 | 检查模板与路径；异常交给 Compiler |
| 01_explore_requirement | YAML、参考图 | requirements.json、visual_analysis.json；02/03/05/07 等读取 | RequirementTree 校验 ID；图路径去重、按 5 张并发，视觉错误有诊断 |
| 02_build_db_schema | requirements.json、检索出的已有 schema | db_schema.json，含逐需求字段关联；03/04/05/07 读取 | SchemaAgent 校验新增实体、字段和关联，单叶最多 5 轮，保存成功项 |
| 03_infer_db_obligations | requirements.json、db_schema.json | db_obligations.json，逐需求/步骤读写；05/09 读取 | ObligationAgent 检查字段存在及关联，归一化读写，逐叶容错 |
| 04_implement_db | schema、requirements、00 模板 | 逐表 SQL、启动数据、initialize.ts、db_checks.json；06/10 运行时消费 | 依赖组排序、NativeFileTools 限写；初始化/重启等实际 DB 检查 |
| 05_design_backend_apis | requirements、schema、obligations、检索与共享约定 | backend_apis.json、shared_conventions.json；06/07/09/10 读取 | 单叶 native agent；validate_backend_design 检查完整性及契约，失败保留已接受产物 |
| 06_implement_backend_tdd | 05 API 契约及 DB 上下文、模板、SQL | 后端实现、HTTP 测试、backend_tdd.json；真实后端供 10 使用 | 每唯一 API 的 RED、构建、GREEN 和累计回归；报告/快照保留失败 |
| 07_design_ui | requirements、视觉、schema、API | ui_design.json，含页面/元素/数据和需求关联；08/09/10 读取 | propose_json 重试，apply_proposal 校验与逐需求发布 |
| 08_implement_ui | 07 设计与上下文、模板 | 页面源码、存在性测试、ui_checks.json；10 复用 | 按需求—页面实现，类型/Chromium 检查和已接受需求回归；空 UI 有专门状态 |
| 09_design_frontend_triggers | requirements、schema、API、UI、义务 | frontend_triggers.json；10 读取 | 校验触发器来源、读写和步骤映射；空 UI 时生成空设计 |
| 10_implement_frontend_tdd | 原 YAML、触发器、UI、API 与可运行应用 | 需求验收测试、行为实现、frontend_e2e.json | 可修共享基线；逐需求生成/复核/实现，运行真实服务 E2E，保留已接受结果 |

依据：T 的 `infrastructure/compiler.py`、`infrastructure/pipeline/*.py` 与其导入的阶段实现。Compiler 以三元组调度，从磁盘交接。任务级 `TaskFailures` 聚合后报告 `COMPLETED_WITH_FAILURES`；普通异常标失败后继续调度，只有中断立即传播。汇总只把 FAILED/COMPLETED_WITH_FAILURES 判不完整。重跑回退上一阶段成功检查点。当前输出路径检查只阻止位于输入目录内，尚不认证生成目录身份。CLI 普通失败 0、参数错误 2、中断 130，保留。

## 模型与进程入口

- 01 `VisualModel.analyze → propose_json → VisualModel.generate_json → model_io.invoke`；图像压缩与去重保留。ThreadPoolExecutor.map 未传 ContextVar，视觉统计缺口留到第 3 步。
- 02/03/05 分别在 `schema_agent.py`、`obligation_agent.py`、`design_agent.py` 调 `TextModel._request` 处理 native tool calls；单轮一请求，最多 5 轮。04 的 `implementation_agent.py` 对单表与启动数据用同入口，调用一次后校验编辑。
- 07/09 `synthesis.py → propose_json → generate_json → _request`；06/08/10 `run_file_agent → generate_json → _request`。上下文索引、NativeFileTools/FileTools、BackendRetriever/SchemaRetriever 处理检索、读文件和扩权；一次外层尝试可能有多次读取、上下文请求或纠错。10 包含基线修复、生成验收、失败复核及实现。
- 两种客户端汇入 `model_io.invoke → chat.completions.create`。文本对 token 参数和 reasoning 有兼容重试；视觉重试 reasoning；SDK max_retries=2。events.py 记录阶段/任务/动作与计价，pricing.json 的 deepseek-flash off_peak 为 1/0.02/4 CNY 每百万 token。这些无法限制统一 HTTP 次数、token、墙钟时间，处理留到第 3 步。
- `shared/project/dependencies.py` 启动 npm 安装；database/testing 跑 npm 构建和 SQLite 检查；backend/testing 跑类型检查、构建和 HTTP runner；frontend/ui/testing、frontend/triggers/testing 执行 Node Playwright、Chromium 安装和 UI/E2E；`utils/processes.py` 封装 Popen/超时/taskkill；`shared/project/git.py` 单独调用 git 初始化、快照、回滚。生成应用还保留 deploy.sh。

## 旧运行时题目耦合及处理

`main.py` 的 --profile 与自动路由 → `compact_acceptance.bundled_suite` 按原文 SHA 或根名/需求场景树哈希查 acceptance_cases/index.json → `tasks/registry.py` 选择六种 profile → `compact.py` 消费专用提示、输入裁剪、探针、源码改写和修复；显式 compact 也在内部重新查。bookstack_profile/prestashop_profile 是专用入口引用。Ctrip navigation/services、railway navigation 又直接借用公开套件 runner。verify_app 原先靠同一指纹，根 scripts/inspect_task_route.py 做路由诊断。input/tests 是另一套公开测试，须移出 compiler。阶段内按需求 ID 哈希命名生成测试文件与按题选行为无关。

| 机制/源 | 可复用条件 | 后续落点 |
| --- | --- | --- |
| compact.py 的构建诊断及 repair_implicit_any.mjs | 有明确 TS7006 和可验证的修复点；不保留 storefront 路由修正 | 06/08/10 |
| compact.py 的截断检测与 TSX/CSS 拆分思路 | 以输出大小与依赖拆分；不沿用 Ctrip/12306 专用切块 | 生成阶段；第 4/5 步 |
| compact_acceptance.py 的诊断截取、失败分类、候选比较与恢复 | 使用原需求生成的冻结验收；回退包括新增/删除；公开测试仅离线 | 06/10 |
| tasks/validate_sql_inserts.mjs 及 initial_world.py 的启发 | 校验幂等/持久化；只从需求明确前置条件提取数据；旧提取器含业务假设，原样归档 | 04 |
| tasks/probe_backend_contract.mjs 与 prompts.py | 校验接口字段、错误形状、身份会话与所有权；会话规则仅在需求要求时生效 | 05/06/10 |
| tasks/prompts.py、各 profile 的页面/导航检查经验 | 按需求的角色/名称、原生控件、导航、保存取消；真实浏览器验证白屏；不迁移业务组件、路径和商品常量 | 07/08/10 |
| tasks/ctrip_*、railway_*、bookstack.py、prestashop.py、keep.py、stackoverflow.py | 题目专用，连同探针、源代码改写、专用初始世界原样归档 | 无直接迁移 |

## 导入与测试清单

逐文件清单见 [import-manifest.json](import-manifest.json)。提交一仅写教师固定 Git blob，删旧 13 个编号脚本、entrypoints/targets/旧 obligations 和待恢复模板 .gitignore。保留旧 compact 和题目资料供提交二归档；不导入教师 playground/course_exercises/arc-bench、外层 .gitignore 或打包脚本。提交二的文件类别见 manifest：恢复模板两处差异，保留教师同步 copy-db 与原 deploy；统一连接、锁定六项直接依赖，调整测试和文档，把公开评测、历史代码和样例移到 compiler 之外。所有目标路径都在 CS3604-staged11。

逐 blob 比较：31 个共有测试及配套文件完全相同（按 Python 文件是 29）；G 多出 26 个测试及夹具（含 MJS、JSON），按 Python 测试统计 14 个。G 的 requirements.txt 已是 6 项，pyproject/lock 仍含 Python Playwright；教师另带 fastapi/uvicorn。Node Playwright 保留。教师打包有 .env 例外，G 无；保留 G 的脚本。模板差异为 G 的 .gitignore、router 与异步 copy-db，deploy.sh 相同。

原版测试实跑见 [upstream-pytest.txt](upstream-pytest.txt)。命令 `python -m pytest -p no:cacheprovider --continue-on-collection-errors -q tests`，在 T 用隔离 Python 依赖和禁用字节码/pytest 缓存执行，退出 1。66 失败、59 通过、6 跳过、11 错误，另有 21 个通过的 subtest。缺失入口/类型：api_wiring、bounded_context、file_agent、file_tools、implementation_recovery、independent_acceptance、obligation_integrity、portability、test_repair、validation_policy；frontend_flow 还错误收集了导入的 test_run_status。运行期失败涉及 compiler/pipeline_continuation/design_continuation/schema_evolution 的旧编号/调度接口、backend_contracts 的旧验证调用、context_discovery 的旧检索协议、database_runtime 的旧恢复签名、frontend_flow 的旧契约/文件权限、git_checkpoints 的旧调度/工具签名、stress_test 的旧 runtime 函数签名，以及 console_logging 的编码/SDK 对象差异。保留原件，兼容的行为断言迁到当前接口。

规模与历史数据：实施说明中的六份输入统计和 I+9L+D+2A+H 为规模估算，不能当实测调用数或预算承诺。PROJECT_STATUS/TASK_STRATEGY/CTRIP_V5_RELEASE 的 compact 成绩是历史快照或同产物复测，后续须绑定版本。隐藏题数、网关实际价格和真实生成质量未验证。
