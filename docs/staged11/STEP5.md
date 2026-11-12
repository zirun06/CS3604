# 第 5 步：通用机制与验收规则

本轮保留 06、10 的测试先生成、再实现流程，保持原有生成和复核时机。只扩展检查、候选接受和提示约束。组长在沙箱外报告 4b 提交 `dc8044f` 的 4 份合成输入 11 阶段全绿；那是迁移前的结果，与本轮复验分开。

| 机制与来源（`offline_eval/legacy/compiler/infrastructure/`） | 落点与适用条件 |
| --- | --- |
| `tasks/validate_sql_inserts.mjs` 的重复执行思路 | 04 扩展原 `DatabaseChecks`，在临时文件数据库中比对重复初始化和关闭后重启的业务表行，并检查独立的保留标记和外键；不改变生产初始化与既有种子来源规则。 |
| `tasks/prompts.py:BACKEND_PROMPT`、`tasks/probe_backend_contract.mjs` | 05 明确路径、参数和 JSON 成功／错误字段；06 的测试在原始需求明确要求时检查 Cookie 往返、会话恢复和所有权隔离。10 复用浏览器 fixture，观测实际同源 HTTP 的方法、路径、具体路由参数、状态和 JSON 形状。 |
| `tasks/prompts.py:FRONTEND_PROMPT` | 07 把角色、导航和路由上下文纳入设计；08 使用原生按钮／链接、精确可访问名称和单一共享导航；10 等保存值载入后才开放编辑、按契约读取响应、按需求恢复受保护会话及处理保存／取消。没有由题目名启用的规则。 |
| `compact_acceptance.py:run_suite` 的浏览器错误和页面证据 | 08、10 的最终验收分别运行确定性 Chromium 渲染探针，要求可见内容，无未捕获 JS 异常或脚本／文档加载失败。静态路由逐个访问；带参数的路由在报告中列出，交给有具体对象 ID 的业务场景。探针不证明页面业务正确。 |
| `compact.py:repair_implicit_parameters`、`repair_implicit_any.mjs` | 06、08、10 只对已编辑且有写权限的应用 TS/TSX 源文件响应 TS7006；用 TypeScript AST 定位未标注参数，只补原来已隐式推断的 `any`，不关闭严格检查。修完重跑同一门禁。实跑模板固定版本 5.9.2。 |
| `compact.py` 的输出边界识别 | 保留 4a／4b 各多单元生成入口的截断拆批；01 识别单图截断，沿用原次数上限要求更短的完整描述。不能再拆的单表、页面、单验收单元及共享基线不改变语义边界。 |
| `compact_acceptance.py:REPAIR_PROMPT`、`repair_with_acceptance` | 06、10 在原文件恢复机制上增加逐候选快照。优先根据证据修影响最多用例的共享阻塞点；失败候选回退，含本轮新增及删除文件。10 以冻结的可执行测试和通过集合判定改进。 |
| 模板既有 `deploy.sh` | 新增独立离线入口 `offline_eval/check_deployment.py`，实际运行该脚本的安装、构建和生产启动，探测健康接口、构建后的 HTML 和 JS 入口，使用隔离文件数据库。部署入口不借用公开评测套件，也不把部署当作编译器阶段内的展示验证。 |

有意未迁移：`repair_storefront_route_params()`、`ctrip_navigation.py`／`ctrip_services.py`／`railway_navigation.py` 的组件和路线重写、`initial_world.py` 的题目数据推断、各题 GUIDANCE 内控件名和业务规则、公开测试套件选择及指纹匹配。它们依赖题目、布局或固定样例；前置数据仍由 4b 的原文证据和插入校验约束。通用 API 形状检查只处理内联结构和常见基本类型，不充当完整 JSON Schema 验证器；认证和所有权的业务语义仍由适用场景断言验证。

## 四种检查分别报告

- **展示检查（08）**：前端开发服务器、确定性元素存在性测试和渲染探针；不启动业务后端，不要求业务已实现。
- **业务 E2E（10）**：真实后端、独立文件数据库和实际浏览器。接口监测随编译器 fixture 执行；业务断言仍以原始需求为准。
- **文件持久化（04）**：复用原数据库探针，单独记录 `persistence_check`。先记录真实业务行，再关闭并重新初始化或启动并比对；`startup_check` 只表示启动与健康接口，`database_check` 表示数据库初始化等检查。
- **最终部署**：独立运行 `deploy.sh`，用健康接口与生产资产确认部署流程。不能用它替代业务或浏览器验证。

## 10 阶段六条验收规则

1. 在编写验收测试前写出 `.arc/acceptance/coverage.json`，按需求、场景、步骤保留原始 Given／When／Then、设计角色与名称、应有和已连线的数据库写入、验收项 ID 及测试路径。矩阵是可追溯关系，不把提示中的验收项自动算成已执行断言。
2. 原有生成和必要复核完成后冻结文件字节，记录 SHA-256；实现和修复只写应用文件。候选执行前后校验冻结文件，包括已接受的回归套件。
3. 原有复核阶段确有改动时，在 `.arc/acceptance/test_revisions.jsonl` 单独记录原始需求、触发复核的失败证据、修改前后哈希及统一差异。实现阶段不复核或改写测试。
4. 候选需类型检查、真实服务器测试、既有 UI／业务回归及构建通过相应门禁；比较固定测试身份与通过集合。拒绝减测试、跳过、不稳定、启动失败、以前通过的用例回归。除本来就全绿的接手路径，接受候选必须新增通过项。
5. 零通过时至多允许 **两次**有不同可执行失败证据且构建成功的中间候选，记录为 `INTERMEDIATE`，不会冒充已接受需求。修复耗尽且还有原先全绿的单元时，复验后保留这些单元。
6. 每次实现候选用原快照机制记录并恢复内容，覆盖改动、新增和删除。候选比较日志为 `.arc/acceptance/10-*.json`，拒绝的文件归档保存在 `.arc/failures/`；中间证据和工作区恢复分开。

[离线失败测试](../../compiler/tests/test_step5_acceptance.py) 运行了实际的 wire 检查和渲染断言回调（后者用最小 DOM 代替浏览器），用文件 SQLite 验证丢行被拒绝，并验证会话用例回归、测试清单改变、跳过、启动失败、构建失败、冻结破坏、零推进上限和新增／删除文件的恢复。

## 沙箱外复验

在 `CS3604-staged11\compiler` 下用 PowerShell：

```powershell
$env:PATH = (Resolve-Path 'outputs/node22/node_modules/node/bin').Path + ';' + $env:PATH
node --version
$env:STAGED11_REAL_CHECKS = '1'
uv run --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q tests/test_staged_pipeline.py -k artifact
```

移除 `-k artifact` 可验证四份合成输入。测试仍使用 mock 模型。要补测 Windows 进程树，用相同目录执行 `uv run --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q tests/test_portability.py -k timeout_stops_descendants`。

部署需在 worktree 根目录操作，使用一份可以重新安装和构建的生成应用，必要时改用本机 Git Bash 实际路径：

```powershell
$env:PATH = (Resolve-Path 'compiler/outputs/node22/node_modules/node/bin').Path + ';' + $env:PATH
$env:PYTHONPATH = (Resolve-Path 'compiler').Path
uv run --project compiler --locked python offline_eval/check_deployment.py '<生成应用目录>' --bash 'C:\Program Files\Git\bin\bash.exe'
```


## 命令与退出码

在 worktree 根目录，测试命令前缀为 `compiler/outputs/staged11-tools/bin/uv.exe run --project compiler --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q -rs --tb=short`，使用仓库内 uv 缓存、`STAGED11_REAL_CHECKS=0` 和 `compiler/outputs/staged11-step5-*` 下独立的 `--basetemp`。

| 实际命令或追加参数 | 退出码 | 实测结果 |
| --- | ---: | --- |
| `compiler/tests/test_staged_pipeline.py -k 'original or artifact'` | 2 → 0 | 第一次因接线处缺括号未收集；修复后 2 通过、5 未选择 |
| `compiler/tests/test_step5_acceptance.py` | 0 | 11 通过 |
| `compiler/tests -k 'not timeout_stops_descendants'` | 0 | 140 通过、1 跳过、1 未选择，另有 38 个子测试通过 |
| `node --check`（新增两份 MJS）、`node --experimental-sqlite -e ...` | 0 | 语法及本机 Node SQLite 可用 |
| 全局 TS 7.0.2 上的诊断修复试跑 | 1 | 全局版本没有迁移脚本所用的 TS AST API；随后使用模板固定版本重验 |
| `npm.cmd install --offline --prefix compiler/outputs/staged11-step5-ts-probe --no-audit --no-fund --ignore-scripts typescript@5.9.2` | 0 | 从本地缓存安装模板固定版本 |
| 临时 TS/TSX 诊断修复：`node <tsc> --strict --noEmit frontend/src/probe.ts`，经 `recheck_types` 调 AST 修复后复验 | 2 → 0 | 真实 TS7006 消失；修复脚本退出 0 |
| `node <现有 workspace tsc> --noEmit -p <临时配置>` | 0 | 实际编译两种渲染 spec、业务 fixture、E2E 配置与合成应用前端 |
| `PYTHONPATH=compiler python offline_eval/check_deployment.py --help` | 0 | 入口可调用；未在沙箱运行部署 |
| `git grep -niE` 检索运行时题目名、指纹和专用修复标记 | 1 | 无匹配 |
| Python AST、UTF-8 回读、`git diff --cached --check` | 0 | 通过 |

全量的既有 SQLite 集成测试缺少 `ARC_DB_TEST_NODE_MODULES`，仍由测试自行跳过；进程树用例未在沙箱内选择。读取外部复验产生的 `claude-real4b` 目录被权限拒绝，未绕过。对编译器本身的证据见 [step5-evidence.json](step5-evidence.json)：四个 mock 合成输入均 11 阶段 GREEN、一个实际冻结候选通过及两个新增／删除回滚记录。真实 Chromium、完整 Node SQLite 探针和 `deploy.sh` 均待沙箱外复验。本轮未调用模型 API，未做第 6 步打包。
