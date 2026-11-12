# 第 4a 步：设计阶段分批

本轮完成 02、03、05、07、09。04、06、08、10 的实现调用粒度保留原状。前置夹具修复独立提交为 `310a4c1`；真实检查的复跑命令和修复前结果见 [PROGRESS.md](PROGRESS.md)。

## 规划和执行

| 完成标准 | 实现及证据 |
| --- | --- |
| 从顶层模块出发，按大小、依赖和共享线索分批 | [批次规划器](../../compiler/infrastructure/stages/requirements/batching.py)。同批最多 6 条叶子、24,000 个紧凑 JSON 字符（含祖先背景）；超大的模块分拆。优先安排依赖已就绪的叶子；同模块优先把显式引用、名称词和页面／图像线索重叠的叶子放在一起。循环依赖用固定的源顺序打破，依赖关系保留在清单里。 |
| 跨模块共享约定和符号目录 | [批次执行器](../../compiler/infrastructure/shared/agent/design_batches.py) 在首批前写入 `.arc/design_catalog.json`，记录身份、会话、命名、错误、数据五类共用规则和源符号归属；后续批次看到已接受的字段、API、模块、页面、元素、触发器及具体共享约定。05 记录具体决策，遇到已存在 ID 的矛盾决策会反馈纠正。[跨模块测试](../../compiler/tests/test_design_batches.py) 覆盖先建立再复用。 |
| 五个设计阶段真实按批请求，仍逐条归属校验 | 02 逐条检查持久字段；03 校验需求和步骤读写；05 用 `validate_backend_design` 检查已有和新增关联、调用图及需求／步骤义务；07、09 按叶子应用现有 UI／触发器逻辑并检查精确步骤归属。批次结果全部通过后才写入业务产物。批次编号和叶子 ID 也进入已有运行统计。 |
| 超大输入和截断 | 组装后的请求超过 96,000 个 JSON 字符时，在发送前拆多叶子批次；模型返回 `finish_reason=length` 时，按原始大小拆成两个子批重试。其他错误仍走现有反馈机制。单叶是校验边界：不拆原始步骤；过大的单叶会在清单标出，单叶输出截断则明确失败。 |
| 六份原始 YAML 覆盖完整 | [离线规划脚本](../../compiler/scripts/plan_design_batches.py) 独立遍历原始树，对比三组完整标识（叶子、需求＋场景、需求＋场景＋步骤），并断言没有重复。各清单有输入哈希、每批字符数、显式依赖、共享候选和逐项源路径。路径里的开头数字是逐层的 `children` 下标。没有做重复文本压缩，叶子输入原样保留。 |

[多叶子 mock 的实际运行证据](step4a-mock.json)：同一批两条叶子，02 第一次响应截断，`B001.a`、`B001.b` 依次通过；03、05、07、09 各一次调用，仍有两条叶子与两条步骤的关联。两份原合成输入和多叶子合成输入使用真实编译管线、mock 模型和替代本地检查；修复后在真实 Node／SQLite／Chromium 下的状态待组长复验。

## 六份离线清单及调用量

| 题目 | 叶子／场景／步骤 | 批次数 | 最大批输入字符 | 五个设计阶段各自调用：旧 → 新 | 全流程首轮调用：旧 → 新 |
| --- | ---: | ---: | ---: | ---: | ---: |
| [BookStack](step4a-plans/arc-bench-web--bookstack.json) | 24 / 35 / 35 | 10 | 15,820 | 24 → 10 | 313–391 → 243–321 |
| [Keep](step4a-plans/arc-bench-web--keep.json) | 16 / 33 / 33 | 8 | 23,605 | 16 → 8 | 216–268 → 176–228 |
| [PrestaShop](step4a-plans/arc-bench-web--prestashop.json) | 55 / 86 / 86 | 16 | 22,986 | 55 → 16 | 约 700–880 → 501–680 |
| [Stack Overflow](step4a-plans/arc-bench-web--stackoverflow.json) | 52 / 66 / 66 | 18 | 23,812 | 52 → 18 | 约 650–820 → 482–651 |
| [Ctrip](step4a-plans/arc-bench-web--ctrip.json) | 97 / 152 / 152 | 24 | 23,607 | 97 → 24 | 约 1230–1550 → 869–1185 |
| [12306](step4a-plans/arc-bench-web--12306.json) | 93 / 142 / 142 | 28 | 23,943 | 93 → 28 | 约 1170–1470 → 840–1143 |

六份输入均无超过 24,000 字符的单叶批次。表中旧区间采用实施说明第 3 节的写法；各 JSON 中保留同一公式的未取整结果。新估算把第 3 节中的 `5L` 换为 `5B`：全流程 `I + 4L + D + 2A + H + 5B`。01 图像分析是 `I`、04 是 `D+L`、06 是 `2A`、08 是 `H`、10 是 `3L`。离线不知道 09 哪些批无可交互页面，先按每批一次计；请求扩大导致的运行时拆批、上下文查询、修复和重试不在估算内。字符数也不是 token 数。

## 复跑

在 worktree 根目录执行离线规划：

```powershell
& compiler/.venv/Scripts/python.exe -X utf8 compiler/scripts/plan_design_batches.py requirements docs/staged11/step4a-plans
```

在 `compiler/` 可分别复跑规划／校验测试和真实检查。沙箱外真实检查仍使用 mock 模型：

```powershell
$env:PATH = (Resolve-Path 'outputs/node22/node_modules/node/bin').Path + ';' + $env:PATH
node --version
$env:STAGED11_REAL_CHECKS = '1'
uv run --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q tests/test_staged_pipeline.py -k original
```

移除 `-k original` 可运行所有合成用例。真实生成、真实模型输出截断率、运行时间和实际模型调用量尚未验证。


## 命令与退出码

本地 pytest 统一从 worktree 根目录执行，使用 `compiler/outputs/staged11-tools/bin/uv.exe run --project compiler --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q -rs --tb=short`；`STAGED11_REAL_CHECKS=0`，`UV_CACHE_DIR` 指向仓库内现有缓存，`--basetemp` 分别指向下表所列目录（均在 `compiler/outputs/` 下）。

| 追加参数或独立命令 | basetemp | 退出码 | 结果 |
| --- | --- | ---: | --- |
| `node --version` | — | 0 | 本机默认 v26.13.0 |
| `compiler/tests/test_staged_pipeline.py` | `staged11-step4a-fixture` | 0 | 前置修复：5 通过 |
| `compiler/tests/test_staged_pipeline.py` | `staged11-step4a-handoffs` | 0 | 接入批处理：5 通过 |
| `compiler/tests/test_staged_pipeline.py -k multi` | `staged11-step4a-multi` | 0 | 1 通过、5 未选择 |
| `compiler/tests/test_design_batches.py` | `staged11-step4a-unit` | 0 | 4 通过 |
| `compiler/tests -k 'not timeout_stops_descendants'` | `staged11-step4a-pytest` | 0 | 123 通过、1 跳过、1 未选择、38 子测试通过 |
| `compiler/tests/test_design_batches.py compiler/tests/test_staged_pipeline.py` | `staged11-step4a-final-targeted` | 0 | 清理弃用代码后复验：10 通过 |
| `compiler/.venv/Scripts/python.exe -X utf8 compiler/scripts/plan_design_batches.py requirements docs/staged11/step4a-plans` | — | 0 | 六份覆盖证明生成成功；重生成逐文件哈希一致 |
| `git diff --cached --check`，UTF-8 回读、Python AST 与 JSON 解析 | — | 0 | 暂存文件通过 |
| 对运行时代码 `git grep -niE` 检索任务名及指纹标记 | — | 1 | 没有匹配 |

全量回归唯一跳过项要求配置 `ARC_DB_TEST_NODE_MODULES`；Windows 进程树检查因沙箱限制未选择。后者可在沙箱外的 `compiler/` 单独执行 `uv run --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q tests/test_portability.py -k timeout_stops_descendants`。前置修复首次普通 `git add` 退出 1（测试目录被忽略）；随后精确使用 `git add -f`，退出 0。
