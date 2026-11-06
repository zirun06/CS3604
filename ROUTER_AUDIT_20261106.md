# PrestaShop / Stack Overflow 版本与分流审计

2026-11-06。审计对象是推荐包`arc-compiler-ctrip-v5.zip`及当前`compiler/`。包SHA256为`189fb42115fe617195a9a972ca438a5405ffcb7c79de5cdc6f3047e78816c4bd`，逐文件核对工作目录与ZIP一致。本轮只增加诊断脚本和报告，没有修改运行源码或重打提交包，没有调用模型重新生成应用。

## 结论

未发现Ctrip调优改写两题独立配置、或本地原六套需求被误送到Ctrip分支的证据。但当前是**共享编译器的配置分流**，不是每题一套独立冻结编译器，更不是自动复用每题历史最高分应用。线上34.49/0的具体原因尚不能在缺少本次运行日志和产物时确定。

## 对比了哪些版本

| 对象 | 当前与历史包对比 |
| --- | --- |
| PrestaShop配置 | 与`arc-compiler-prestashop-v3.zip`的`infrastructure/tasks/prestashop.py`逐字节相同。 |
| Stack Overflow配置 | 与`arc-compiler-stackoverflow-v2.zip`的`infrastructure/tasks/stackoverflow.py`逐字节相同。 |
| 入口/分流器 | `main.py`、`tasks/registry.py`与以上两包都相同。 |
| 通用提示词、模型客户端、依赖声明/锁 | `tasks/prompts.py`、`shared/models/text.py`、`requirements.txt`、`uv.lock`均相同。依赖声明相同不代表线上运行环境的预装版本一定相同。 |
| 公开测试 | PrestaShop套件56个文件、Stack Overflow套件54个文件与各自历史包相同；这是文件数，不是用例数。 |
| 共享编译流程 | `compact.py`变化，增加12306/Ctrip的条件步骤和输入处理；这两题的`railway_contract`与`ctrip_contract`均False。 |
| 共享验收修复 | 相对Stack Overflow v2完全相同；相对PrestaShop v3增加了可选的共享helper归组、初始数据和协议重试。PrestaShop未开启这些新开关，基础修复提示词也相同。不能把共享文件变化说成整个系统没有任何改动。 |

相对于最初`arc-compiler-v8-task-split.zip`，两题配置确实都已变化：后续自己的专用调优早已合入。不能把“相对专用优化版未变”误说成“相对最早v8未变”。

确定性模拟捕获的正常生成轨迹：PrestaShop当前对比其v3、Stack Overflow当前对比其v2，两者分别完全相同。核对了提示词/请求载荷哈希、token预算、提案次数和传入验收阶段的参数。它不是两次真实模型运行结果相同的证明，也不覆盖所有异常路径。

当前两题都强制分开生成，后端/前端/CSS预算为26000/32000/10000。PrestaShop四轮验收修复、优先六组失败；Stack Overflow四轮、优先一组，另启用初始数据索引、SQL/HTTP检查和状态语义修正。这些参数与各自上述历史包一致。

## 现在到底怎样路由

默认平台命令`python main.py <input> --output-dir <output>`走auto：

1. 读取requirements.yaml。
2. `bundled_suite`先按全文SHA256匹配已知公开套件；失败后按根name、全部需求ID与场景ID构成的结构指纹匹配。
3. `select_profile`用套件目录名查六任务注册表，取得对应PROFILE。
4. 共同调用`compile_compact`，按配置切换提示词、预算、修复策略和专用步骤。
5. 识别不到就返回generic；目前不会明确报“某已知任务未匹配”。

这不是LLM分类器，也不依据输入目录名称切换；平台将目录改为`requirements-source`本身不会影响识别。`--profile`是auto/compact/staged模式开关，不是六题选择开关，当前没有显式`--task`参数。显式staged会绕过当前任务策略路径。

## 路由实测

本地六份真实需求：6/6正确。重新导出YAML（格式/顺序变化但保留结构）：6/6正确。

分别对每题仅修改根name、或仅改一个场景ID：12/12退回generic。这是复现到的识别容错缺口；尚无证据证明本次线上输入发生了这些变化。

因此，若小组预期是“识别任务后调用各自冻结版本的完整编译器”，当前实现**尚未达到这种隔离程度**。只改自己的PROFILE可以隔离配置；修改共享`compact.py`、`compact_acceptance.py`、模板、客户端或环境变量仍需跨任务核对。

## 怎样核对本次低分

先看生成日志的准确行：

```text
[compiler] Task strategy: prestashop
[compiler] Task strategy: stackoverflow
```

并核对产物`.arc/compilation.json`的`task`字段。若为generic，先处理识别和输入版本；若正确，重点看生成阶段是否退出、预检/构建/部署错误，以及Playwright首个共同失败。0分可能是生成失败或运行时白屏/公共入口阻塞，不能只凭0分认定路由错误，也不能只凭配置相同认定必然是模型波动。

34.49若来自平台Score，还应与Tests、Features及实际passed/failed分别记录，不能直接和本地通过数77/86相减比较。

此前Stack Overflow v2的53/66是同产物修复结果；历史完整新生成曾17/66、25/66，不能把53当作该包每次都能独立生成的稳定分数。

本次需要的证据：实际上传包名/哈希，以及两题运行链接或日志/生成ZIP。已向用户请求，暂未收到本轮材料。不据此擅自回滚两题或改推荐包。

## 建议的真正router边界

- 业务任务识别与公开测试版本匹配分开：任务类型可用明确task_id、规范化名称等可审计元数据识别；是否能使用旧套件单独判断，避免新需求修订丢失专用策略或错用旧测试。
- 支持显式任务覆盖，并与需求身份交叉核对；识别不确定时明确报出，不静默退回通用流程。
- 若需要强隔离，注册表应指向每题冻结的完整engine版本/适配器，而不只是PROFILE。共享基础升级单独管理；该结构仍不能保证模型输出与历史高分应用相同。
- 每次生成记录task、匹配原因、需求指纹、engine版本、非敏感模型设置及预算，使线上结果能追溯到实际分支。

本轮没有直接改变生产router，避免审计过程中改变被审计版本。

## 可复用诊断

仓库新增只读脚本`scripts/inspect_task_route.py`，无模型调用。在仓库根目录执行：

```powershell
python scripts/inspect_task_route.py requirements/arc-bench-web--stackoverflow --expected-task stackoverflow
python scripts/inspect_task_route.py requirements/arc-bench-web--prestashop --expected-task prestashop
```

它输出实际suite、任务、关键开关和指纹；与expected-task不符时退出2。用于本地真实输入，不代替线上日志。

证据位于`compiler/outputs/router-audit/`：`code-comparison.json`、`suite-comparison.json`、`routing-matrix.json`、三份`trace-*.json`、`settings.json`、`package-verification.json`和历史源码diff。现有9项任务配置检查通过；全部检查为本地只读/模拟审计，没有重新生成应用。
