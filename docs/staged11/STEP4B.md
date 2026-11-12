# 第 4b 步：实现阶段分批

本轮只改 04、06、08、10 的实现粒度及其共用规划、恢复和统计入口。4a 的六份源覆盖清单仍适用。组长反馈：4a 的上一版提交在沙箱外、Node 22.23.5 的真实检查中 6 个测试通过。以下 4b 的实测结果与这份历史复验分开记录。

## 完成标准和证据

| 阶段 | 分组依据、验收和产物 |
| --- | --- |
| 04 | DDL 按外键连通组件及依赖顺序分组，每表仍用独立 SQL 文件、原有原生工具权限和 SQLite 检查。启动数据按前置证据涉及的表分组；模型只收到原文里的前置段落和 Given，不收到 When/Then。每条新增 INSERT 都要带来源 ID、原文引句和具体标识，校验后写入单表种子文件；联合初始化失败时尝试逐叶保留有效种子。真实应用仍执行原有 Node/SQLite 初始化检查。批次记录为 `.arc/implementation_batches_04_ddl.json` 和 `implementation_batches_04_seed.json`。 |
| 06 | 按路由族、共享业务模块和持久实体分组。每批生成一组 HTTP 测试并实现，逐 API 确认测试与实现结果；每轮只回归同批保留项和最多三个相关的已接受 API，阶段末运行完整接受集合与构建。测试生成有明确写路径；实现时验收测试只读。记录为 `.arc/implementation_batches_06.json`，原 `backend_tdd.json` 保留需求、API 和测试路径。 |
| 08 | 按共享布局、路由族、共用元素或需求聚合页面，每个页面以完整设计一次进入批次；每页生成一份确定性存在性测试，验证当前页和所有先前接受页。记录为 `.arc/implementation_batches_08.json`，原 `ui_checks.json` 保留需求到页面的验收归属。 |
| 10 | 按共享页面、布局、触发器和 API 聚合需求。一次生成多份独立的需求验收测试，集中复核未通过的测试，然后按批接通交互；保留 UI、既有 E2E、受影响的后端 HTTP 和最终构建检查。记录为 `.arc/implementation_batches_10.json`，原 `frontend_e2e.json` 保留逐需求结果。 |

[共同执行器](../../compiler/infrastructure/shared/agent/implementation_batches.py) 复用 4a 的源树索引、共享约定和符号目录、输入尺寸目标与分割规则。实现批按**实际产物依赖**重新组织；各报告把每条源叶子、场景和步骤映射到有效实现批，继承本叶的所有相关批。不适用的阶段用空列表；映射不声称某个 API 单独覆盖该叶的所有步骤。

[四阶段 mock 证据](step4b-mock.json)：两条叶子、两张外键相关表、两个 API、两个共用布局的页面。替换本地检查时 11 个阶段全绿，04 调用 2 次（DDL、启动数据），06 调用 2 次（测试、实现），08 调用 1 次，10 调用 3 次（生成、复核、实现）。模型调用数由合成测试的 mock 入口计数，替代检查不等同于真实 Node 或浏览器结果。

## 恢复和统计边界

- **按可验证单元接受。** 一批共享代码如果能编译、通过需要保护的接受集合，且部分当前单元通过，则保留该工作区和已通过单元的测试。失败单元独占的 SQL 或测试文件会归档并恢复，只把待修单元放进子批。若共享文件无法编译、接受集合回归失败，或没有单元通过，无法认定任何新实现可保留；恢复到批前快照后再拆。终局失败保留原因及归档路径。
- **输入和输出。** 组装后的多单元请求超过 96,000 个 JSON 字符时先拆；收到 `finish_reason=length` 则不应用截断响应，按输入大小拆分后重试。单个表、API、完整页面或需求验收是最小单元，不能继续拆时明确报告失败。预算耗尽走原有预算边界。
- **统计。** 同一次调用保留批次 ID 和全部关联需求。模型生成和复核成本以文件组为单位保存，某次验证命中同组多份文件时，只计一次该组的调用和 token。[预算边界测试](../../compiler/tests/test_budget_boundaries.py) 通过离线 SDK transport 检查；[恢复与来源测试](../../compiler/tests/test_implementation_batches.py) 覆盖部分接受、回滚、截断、禁止用 When/Then 作种子来源及统计落盘。
- **边界。** 前置证据筛选与 SQL 校验是结构检查，不证明任意自然语言和 SQL 完全等价；实际业务行为依然由各阶段验收检查。06 的中间回归有上限，较远的共享回归可能到阶段末全量时才暴露，届时阶段不会报 GREEN。

## 六题首轮调用估算

| 题目 | 02／03／05／07／09 各批数 | 04 DDL＋seed 批数 | 06 API 批数 | 08 页面批数 | 10 验收批数 | 原始 → 4a → 4a＋4b |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BookStack | 10 | 2–6 ＋ 6–12 | 6–24 | 4–24 | 6–12 | 313–391 → 243–321 → **111–195** |
| Keep | 8 | 1–4 ＋ 4–8 | 4–16 | 3–16 | 4–8 | 216–268 → 176–228 → **88–144** |
| PrestaShop | 16 | 4–14 ＋ 14–28 | 14–55 | 10–55 | 14–28 | 约 700–880 → 501–680 → **200–393** |
| Stack Overflow | 18 | 4–13 ＋ 13–26 | 13–52 | 9–52 | 13–26 | 约 650–820 → 482–651 → **196–378** |
| Ctrip | 24 | 7–25 ＋ 25–49 | 25–97 | 17–97 | 25–49 | 约 1230–1550 → 869–1185 → **340–678** |
| 12306 | 28 | 6–24 ＋ 24–47 | 24–93 | 16–93 | 24–47 | 约 1170–1470 → 840–1143 → **332–657** |

[机器可读估算](step4b-estimates.json) 有各阶段的批数、模型调用量及三种口径。假定表数约 0.25L–0.5L、API 数 L–2L、需求与页面组合数 H 为 L–2L；假定每个独立页面平均对应 2 个需求与页面组合。每组 2–4 张表、2–4 条有前置证据的叶子、2–4 个 API、1–3 个页面或 2–4 条 E2E 叶子。六份 YAML 有前置证据的叶子数可直接计算，离线还不知道其中哪些会涉及 DB；10 先按全体叶子有 UI 估算。

00 无模型调用，01 每张图一次，设计阶段每批一次，04 每个 DDL 或 seed 批一次，06 每 API 批两次，08 每页面批一次，10 按初始需复核算每批三次。区间用于容量规划，可能随真实生成的依赖、上下文拆分、已有行为 GREEN、修复重试和基线修复变化。

## 沙箱外真实复验

在 `CS3604-staged11\compiler` 下执行：

```powershell
$env:PATH = (Resolve-Path 'outputs/node22/node_modules/node/bin').Path + ';' + $env:PATH
node --version
$env:STAGED11_REAL_CHECKS = '1'
uv run --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q tests/test_staged_pipeline.py -k artifact
```

移除 `-k artifact` 复跑全部合成用例和 Node 预检断言。仍使用 mock 模型。沙箱外的进程树检查可在同一目录运行 `uv run --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q tests/test_portability.py -k timeout_stops_descendants`。


## 本地命令与退出码

pytest 从 worktree 根目录运行：`compiler/outputs/staged11-tools/bin/uv.exe run --project compiler --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q -rs --tb=short`。使用仓库内 `compiler/outputs/uv-cache`，`STAGED11_REAL_CHECKS=0`，`--basetemp` 各自指向 `compiler/outputs/staged11-step4b-*`。

| 追加参数或独立命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `compiler/tests/test_staged_pipeline.py -k 'artifact or original'` | 1 → 0 | 初次发现文件组统计键不能 JSON 序列化；修复后 2 通过，5 未选择 |
| `compiler/tests/test_implementation_batches.py compiler/tests/test_budget_boundaries.py` | 1 | 测试调用 `finish_stage` 漏传参数；补齐后下列专项与全量通过 |
| `compiler/tests/test_implementation_batches.py -k authoring` | 0 | 1 通过 |
| `compiler/tests/test_implementation_batches.py compiler/tests/test_budget_boundaries.py compiler/tests/test_design_batches.py compiler/tests/test_budget_pipeline.py -k 'not cli_resumes'` | 0 | 26 通过、2 未选择 |
| `compiler/tests -k 'not timeout_stops_descendants'` | 1 → 0 | 第一次同时还有源码编辑，checkpoint 测试的来源匹配断言未通过；固定源码后 129 通过、1 跳过、1 未选择，另有 38 个子测试通过 |
| `compiler/.venv/Scripts/python.exe -X utf8 compiler/scripts/plan_design_batches.py requirements docs/staged11 --implementation-estimates` | 0 | 六题估算落盘 |
| 同一规划脚本不带估算参数，输出到独立目录 | 0 | 六份 4a 原计划重生成后哈希一致 |
| 运行时代码 `git grep -niE` 检索题目名与指纹标记 | 1 | 未命中 |
| UTF-8 回读、Python AST 和 JSON 解析、`git diff --cached --check` | 0 | 通过 |

既有 SQLite 集成测试缺少 `ARC_DB_TEST_NODE_MODULES`，仍由测试自身跳过。Windows `taskkill` 测试未在沙箱内选择。未运行 4b 的真实 Node／SQLite／Chromium 模式，也未调用模型 API、未做第 5 步。
