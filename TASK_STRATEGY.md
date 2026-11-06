# 六项任务独立调优与统一调度方案

2026-11-05 已以 v8 为基线完成第一轮拆分。六个任务配置和统一注册表已经接入入口，第一轮保持 v8 行为；随后针对 Keep 与 PrestaShop 的线上失败进行了独立调优。

## 当前使用方式

直接使用原来的 main.py 命令。自动模式根据需求匹配结果选择任务配置，日志显示 Task strategy，输出报告新增 task 字段。

| 任务 | 独立配置文件 | 当前前端策略 |
| --- | --- | --- |
| 12306 | compiler/infrastructure/tasks/railway12306.py | 大输入分开生成 |
| BookStack | compiler/infrastructure/tasks/bookstack.py | 旧版联合生成 |
| Ctrip | compiler/infrastructure/tasks/ctrip.py | 大输入分开生成 |
| Keep | compiler/infrastructure/tasks/keep.py | 强制分开生成，TSX 上限 24000、CSS 上限 10000 |
| PrestaShop | compiler/infrastructure/tasks/prestashop.py | 强制分开生成，TSX 上限 32000、CSS 上限 10000 |
| Stack Overflow | compiler/infrastructure/tasks/stackoverflow.py | 强制分开生成，TSX 上限 32000、CSS 上限 10000 |

每人优先修改自己负责的文件。任务模块中的 PROFILE 可以指定完整提示词、生成方式、各阶段 token 上限、完整提案次数、样式提案次数、构建修复和验收修复指导。四个原来共用通用提示词的任务各有独立 GUIDANCE 字符串，初始为空。

共享的 prompts.py 保存 v8 通用提示原文。修改这个文件会影响引用它的任务，应作为共享基础修改处理。要单独更换某题的完整提示词，在该任务模块的 PROFILE 中指定。

## 拆分验证

- 直接从原始 v8 ZIP 提取编译器，捕获十组确定性运行轨迹，保存为 tests/fixtures/v8_task_traces.json。
- 原始 v8 轨迹快照仍用于核对 BookStack、Ctrip、12306 和默认流程。Keep、PrestaShop、Stack Overflow 单独检查强制分开生成及独立预算，另外检查网关重试、局部修复和回滚。
- 对照包括提示词哈希、请求内容哈希、token 预算、完整提案次数和验收参数。
- 用六份真实需求核对自动入口、强制 compact 入口和 YAML 重新导出后的任务匹配。

上述验证用于确认拆分的行为一致性。当前版本的通过率和生成随机性还需要真实模型生成与线上评测来衡量。

## 目标

每项任务独立保存提示词、生成步骤、修复指导和预算，统一入口根据输入需求选择对应配置。修改一项任务时，通过独立文件和测试记录控制影响范围。

## 当前结构

```text
compiler/
  main.py
  infrastructure/
    tasks/
      registry.py
      bookstack.py
      keep.py
      prestashop.py
      stackoverflow.py
      railway12306.py
      ctrip.py
    compact.py
    compact_acceptance.py
    shared/
```

入口确定任务类型后取得配置，再调用编译流程。分类使用需求根节点、需求树结构和已知指纹，复用现有需求匹配逻辑。未知输入使用明确的默认流程或报出无法识别，禁止静默进入任意已知任务。

## 各任务配置

每份配置包含后端提示词、前端提示词、修复指导、联合或分开生成策略、输出预算、重试预算、公开验收匹配。确有必要时，允许任务使用独立生成步骤。

模型调用、进程管理、文件工具和打包接口继续作为共享基础。共享基础出现修改时需要六项回归。

第一轮从 v8 原样迁移策略；当前 Keep 与 PrestaShop 的调优参数已独立设置。bookstack_profile.py 和 prestashop_profile.py 保留为旧导入路径的兼容层，实际配置分别位于 tasks/bookstack.py 和 tasks/prestashop.py。

## 减小随机性的措施

- 固定模型、接口、依赖、需求版本、提示词和输出预算，保存每次运行的配置与版本号。
- 将稳定的应用骨架、接口约定、数据库表示保留下来，把模型修改限制到确有需求变化的部分。可先约定类型化 API 契约，减少前后端分别猜测字段。
- 本地调优区分同产物复测与从空目录重新生成。前者用于检查代码修复，后者用于衡量生成稳定性。
- 对重要候选至少执行三次独立生成，比较平均值、最低值、生成失败次数和耗时。一次最好成绩不足以表明稳定性提升。
- 独立配置可以减少任务之间的回退风险，但不能让模型输出完全确定。降低采样参数需要确认接口实际支持。

## 小组分工和集成

可以由三人各负责两个任务，每人使用独立 Git 分支，优先修改自己负责的任务模块。每项交付包含配置改动、可复现命令、需求版本、模型配置及完整验收结果。

集成负责人维护注册表和共享基础。先合并一个任务并核对其他任务配置，再逐个合并。整合后用同一份智能体 ZIP 从各自需求输入重新生成六项应用。

## 实施顺序

1. 已完成固定 v8 基线并保存可复现记录。
2. 已完成六任务注册表、策略原样迁移和分流回归。
3. 先在 PrestaShop 和 BookStack 上分别调优，核对相互影响。
4. 扩展另外四项，并由各负责人保存独立结果。
5. 同一提交版本完成六项完整验收后打包。

## Keep 与 PrestaShop 的本轮调优

两项配置支持 CSS 规模指导、两轮局部构建修复和暂时性网关故障重试。Keep 额外强调原生按钮、aria-expanded、精确可访问名称和图标隐藏语义。零通过阶段可以保留失败诊断有变化且未扩大失败集合的候选以继续修复，报告记录 zero_progress；其他四题默认关闭该选项。

## PrestaShop v3

PrestaShop 配置增加 Country 下拉框、金额区域、统一商品卡片的生成约束；修复最多四轮、优先六类失败，所有编辑锚点失配时可以重试一次。Keep 继续使用两题 v2 的配置。独立重新生成的本地结果为 77/86，同产物修复为 52/86，具体开销见 PROJECT_STATUS.md。

## Stack Overflow v1

用户提供线上运行及产物后，确认 50 个失败中有 42 个被顶部个人入口错误显示邮箱阻塞。该题独立配置强调身份、导航、区域归属与父子关系，启用已有故障恢复和修复回滚。进一步增加状态标签关联、常量 INSERT 预检和核心 HTTP 契约验证：公开业务读取、注册/登录/会话恢复及 SQL 结构先通过检查，再生成前端。三项检查只为 Stack Overflow 启用，其他五题配置不变，测试核对默认流程不会调用它们。详细分析、各轮成功与下降的结果见 [STACKOVERFLOW_OPTIMIZATION.md](STACKOVERFLOW_OPTIMIZATION.md)。

## Stack Overflow v2

增加明确初始数据清单与公共搜索/详情覆盖检查，避免遗漏历史问题；关联共享操作的前置需求，并按失败组已验证次数调整修复优先级。新增 feed 区域的保守 AST 关联。当前同一产物验证为 25 → 50（自动语义修正）→ 53/66（四轮模型修复）；此前完整新生成为 25/66，最终 ZIP 尚未再次从空目录完整生成或线上复评。其他五题配置不变。详见 [STACKOVERFLOW_V2.md](STACKOVERFLOW_V2.md)。
