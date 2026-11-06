# 12306 独立调优与 BookStack 热修复撤回

日期：2026-11-05。基线为用户确认的 `D:/软工大作业/arc-compiler-stackoverflow-v2.zip`。

## 版本更正

用户更正：BookStack 有问题的是 PrestaShop v3 包，Stack Overflow v2 包的 BookStack 正常。因此撤回上一轮 BookStack 热修复，包括入口 Router 补齐、浏览器启动检查、前端 24000 token 调整及新增测试。运行源码恢复为旧 v2，热修复 ZIP 移至 `compiler/outputs/bookstack-hotfix-withdrawn/`。`BOOKSTACK_ZERO_FIX.md` 仅为已撤回的历史记录。

## 这次线上失败的证据

用户提供 `cff2766c1b4e-template.zip` 和 2026-11-05 21:14:54 开始的运行日志。首次公开验收为 **34/142，108 失败**，平台最终也为 34/142（23.9%）。三次修复没有成功应用：两次 429 明确报告免费额度耗尽/余额不足，另一次请求超时。额度问题不能通过提高修复次数解决，本轮小请求连通性检查成功，但不能保证后续平台额度和网关可用性。

从产物 `.arc/acceptance.json` 分组，76 项失败停在登录后 `Sign Out` 链接检查。生成后端读取 `req.cookies`，但模板 `createApp` 只安装 `express.json()`，没有 Cookie 解析；GET session 因而无法复用已登录 Cookie。前端同时把 `Sign Out` 生成为 button，违反需求的 link 语义。

另外九项左右的注册失败涉及 Nationality：自定义 Labeled 组件把 select 的全部 option 文本包含进标签，无法按指定标签定位。多项车次、过滤和预订失败涉及车次编号与站名直接拼接，导致独立身份文本或词边界缺失。不能把这些共同入口失败当作 108 个独立业务缺陷。

## 本轮实现

| 文件 | 具体作用 |
| --- | --- |
| `compiler/infrastructure/tasks/railway12306.py` | 12306 独立生成契约、完整初始数据说明、Cookie 会话、基准时钟、库存/订单确认/支付取消和 UI 语义指导；TSX/CSS 分开生成，CSS 上限 10000、两次提案；局部构建修复两次。 |
| `compiler/infrastructure/tasks/railway_context.py` | 对完全相同的长文本行建立共享字典，保留全部需求、场景、字段和原文引用；可机械还原 parsed YAML。索引 Given 中五类明确启动记录，不预置应由 UI 创建的乘客和当前订单。 |
| `compiler/infrastructure/tasks/prepare_railway_source.mjs` | 用 TypeScript AST 检查生成源码。在实际读取 cookies 时补解析中间件；实际控件补明确的 label 名称；保留已有名称；将带 handler 的 Sign Out button 转为阻止默认跳转的真实链接；给混有元数据的表格身份文本增加独立元素和明确空格。可以重复执行。 |
| `compiler/infrastructure/tasks/profile.py` | 新增默认关闭的 `railway_contract` 开关。 |
| `compiler/infrastructure/compact.py` | 只有该开关开启时整理输入，并在构建前执行 12306 源码检查；其他五题不进入这些分支。 |

输入文本由 404633 字符减少至 278139 字符，约减少 **31.3%**，111 条共享文本块。自动还原检查确认 parsed YAML 与原需求完全一致；没有删掉失败场景或修改测试。启动记录为 verified account directory 27 个视图、published services 9 个视图、station directory 5 个视图、travel guidance content 7 个视图、published transfer segments 1 个视图。视图应合并成同一个业务世界，而非重复账户/车次。

公开验收最多五轮；按共同失败步骤分组，优先提供两类失败及对应前置需求，允许一次编辑锚点/协议重试。候选必须增加通过数且保留全部原通过场景才能接受。传输暂时性错误允许一次重试；额度不足本身仍需服务端余额或额度恢复。

## 验证记录

| 验证方式 | 结果 | 边界 |
| --- | ---: | --- |
| 用户原线上产物 | 34/142 | 平台结果与产物首次验收一致。 |
| 同一产物应用首轮自动源码修正 | 80/142 | 不调用模型修改业务代码；原产物原样保留。 |
| 同一产物进一步修正文本词边界 | 91/142（64.1%） | 完整公开用例、0 skipped；这是同产物复测，不是独立生成或新线上分数。 |
| 本轮从空目录生成并修复 | 49 → 59/142（41.5%） | 退出码 0，PARTIAL，1479.67 秒；辅助脚本在修复阶段同步修正，见下文，不能写成最终 ZIP 从头到尾未改动的一次运行。 |

最终保留应用使用相同运行源码，在新鲜测试数据库中再次完整复测为 **59/142，83 失败，0 skipped**，用时169.47秒，没有继续改应用或调用模型。

重新生成使用 deepseek-flash、https://api.arc-bench.com/v1，文本/视觉推理为 none。各轮为 49、49、58、58、58、59 条通过；三个 58 条候选破坏了原来通过的个人中心入口，被恢复；最终 59 条候选保留原通过集合。全部验收耗时 1135.6 秒，五轮修复收益有限，不能称为效率已改善。日志中模型报告的 Input 为 650800 tokens、Output 为 65032、Total 为 715832；包含报告的缓存输入，不直接等同费用。

剩余 83 项失败中，38 项停在 Personal center menu 的 My Passengers、13 项停在 Ticket orders、8 项停在 Account security、4 项停在 User information；另有五项站点 Lhasa 选择失败。核心未解问题是个人中心菜单没有持久挂在各子页面，父级导航后菜单入口消失。下一轮应集中修改这项布局契约并核对站点查询，不能用重复增加修复轮数替代这项工作。新生结果和同产物 91/142 必须分开，不应承诺平台达到后者。

源码修正期间发现仅增加 span 仍不能保证 table cell 的 textContent 有词边界，因此增加显式空格，并用真实 React 服务端渲染验证 `G7 Station` 的文本边界。这项辅助脚本及测试在新生验证的修复阶段同步更新，并重新打包；不能把前期新生首轮成绩称为最终 ZIP 未改动的一次完整测试。

## 其他五题隔离

BookStack、Ctrip、Keep、PrestaShop、Stack Overflow 的独立配置文件与旧 v2 ZIP 逐字节一致。两份编译器分别运行确定性请求轨迹，五题的提示词散列、载荷散列、预算、提案次数和验收参数均一致。这证明本轮未改它们的正常编译请求路径，不代表它们已重新在线上评测。

代码检查：仓库中 31 项相关 Python 检查通过；独立 ZIP 中 30 项通过、1 项跳过（真实完整需求位于 ZIP 外，已在仓库验证）；五组 Node 检查通过，包括真实 HTTP Cookie 往返、畸形与重复 Cookie、标签、链接转换、React 渲染文本边界、已有 Stack Overflow 契约/区域/状态/SQL 检查。

## 路径

- 提交候选：`D:/软工大作业/arc-compiler-railway-v1.zip`，包含六题智能体。
- 用户产物与诊断：`compiler/outputs/railway-v1/online/`。
- 同产物修正副本：`compiler/outputs/railway-v1/replay/`。
- 80/142 报告：`compiler/outputs/railway-v1/replay-verification.json`。
- 91/142 报告：`compiler/outputs/railway-v1/replay-final-verification.json`。
- 新生应用与日志：`compiler/outputs/railway-v1/fresh/`、`fresh.log`、`fresh/compiler.log`。
- 新生摘要：`compiler/outputs/railway-v1/fresh-summary.json`。
- 新生保留应用最终复测：`compiler/outputs/railway-v1/fresh-final-verification.json`。
- 五题请求轨迹：`compiler/outputs/railway-v1/baseline-traces.json`、`new-traces.json`。

候选包大小 4,516,556 bytes，605 个条目。SHA256：`c7270806b2a3d846def2aef324a91b56df9891b35daec1fdceef99ea66bcc77b`。ZIP 校验通过，源码与当前工作目录一致，不含 .env、API Key、outputs、node_modules 或 Git 元数据。它是仍有明显功能缺口的实验候选，不是已证明稳定的高分版本。

密钥读取本机环境，不写入提交包或 Git；outputs 目录按仓库规则排除于提交包。
