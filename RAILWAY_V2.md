# 12306 v2：先修结构，再验完整功能

本轮沿用 `arc-compiler-railway-v1.zip`，以用户确认正常的 Stack Overflow v2 包作为其他五题基线。BookStack 热修复保持撤回。

## 新方法

v1 的完整新生应用最终为59/142。至少63个失败停在个人中心子菜单：父级链接跳转后，菜单只存在于首页组件，导致子页面不再拥有导航。普通修复反复修改链接文字或改成 summary，不能解决共用布局，且破坏原通过场景。

v2 在前端生成/构建后、完整公开验收前，增加独立的结构修复阶段：

1. 用真实 Chromium 登录、刷新、进入个人中心，核对 Notice，再连续打开乘客、订单、用户信息及账户安全，并刷新子页面。
2. 如果链路通过，直接继续，不调用布局修复模型。
3. 如果链路因布局失败，从 TypeScript AST 提取实际 App、菜单所属组件、现有链接目标及路由。模型只返回这些组件和两个允许的新布局组件的完整声明，不重写整份应用。
4. 写入前核对所有原路由路径/顺序、原页面组件、登录保护组件、App 中原有 provider/组件均保留。拒绝修改范围外的业务组件，拒绝多段任意顶层代码。
5. 构建后重走短链路，最多两次结构候选。失败则恢复原App，记录诊断并继续原公开验收；登录/API失败单独报告，不浪费布局修复预算。

该方法允许一次完成布局结构调整，同时保留其余页面和后端源码。完整验收仍负责业务功能，短链路不能替代142项测试。

## 改动文件

| 文件 | 作用 |
| --- | --- |
| `compiler/infrastructure/tasks/railway_components.mjs` | 提取并受限替换指定组件；保护路由、页面、guard/provider以及其余原业务源码。 |
| `compiler/infrastructure/tasks/probe_railway_navigation.mjs` | 真实浏览器跨页导航/刷新检查，使用声明的测试账户及独立内存数据库，输出失败步骤和真实页面信息。 |
| `compiler/infrastructure/tasks/railway_navigation.py` | 最多两次组件候选，构建、浏览器核验、恢复与独立报告，调用后恢复模型预算和客户端配置。 |
| `compiler/infrastructure/tasks/profile.py` | 新开关默认关闭。 |
| `compiler/infrastructure/compact.py` | 只在12306开启独立结构阶段。 |
| `compiler/infrastructure/tasks/railway12306.py` | 明确持久布局契约，通用完整验收修复由五轮减为三轮；section 前置需求指向真实个人中心入口。 |

## 验证记录

| 方式 | 结果 | 说明 |
| --- | ---: | --- |
| v1 新生应用的既有完整报告 | 59/142 | 本轮同产物对照起点。 |
| 对这份应用运行结构修复 | 59→81/142，0 skipped | 两次组件候选约42.55秒，完整复测147.06秒；没有新增原通过场景的失败，后端未修改。 |
| 从冻结v2 ZIP解包、空目录重新调用模型生成 | 首轮104，最终105/142（73.9%） | 退出码0，PARTIAL，0 skipped；首次导航门槛即GREEN，布局阶段零模型调用。 |

最终各轮完整验收为104、104、104、105。前两个修复候选未增加通过数被回滚，第三个增加一项且保留所有原通过场景。此轮在冻结包解压后使用空目录运行，过程中没有变更运行源码，因此可作为最终ZIP的一次完整新生结果。

| 单次本地完整生成 | v1历史记录 | 冻结v2 |
| --- | ---: | ---: |
| 最终通过数 | 59/142 | 105/142 |
| 总耗时 | 1479.67秒 | 803.86秒 |
| 模型报告Input tokens | 650800 | 440663 |
| 模型报告Output tokens | 65032 | 48051 |
| 模型报告Total tokens | 715832 | 488714 |

这两次运行的通过数增加46项，用时减少约45.7%，模型报告token量减少约31.7%。两次属于不同生成产物和单次样本，v1还有收尾脚本同步的历史限制，不是严格随机种子控制的稳定性对照；不能据此承诺每次平台得分。token统计包含报告的缓存输入，费用以平台账单为准。v2的导航阶段用时5.41秒，常规完整验收及三轮修复用时490.08秒。

测试使用 `deepseek-flash`、`https://api.arc-bench.com/v1`，推理配置none，密钥从本地环境读取。真实生成启动后没有继续修改或重打包运行源码，以避免混淆候选版本。

同产物81/142仍有61项失败，涉及乘客新增、搜索条件/站点/金额、订单筛选、账户安全等。菜单恢复让下游错误可见，并不代表这些功能自动通过。另行单独运行未支付订单检查，乘客创建能继续，但仍发现 Pay 被生成为link而需求要求button，说明必须继续核对真实业务语义。该单例结果不能替换完整测试成绩。

最终新生剩余37项中，17项停在 Add new passengers 弹窗，4项涉及 G1001 行断言，2项涉及 Order details，另有 logo、搜索与预订细节。这些需要继续核对业务校验、前置数据及控件语义，不能把所有乘客弹窗失败直接认定为同一问题；本轮不称全通过。

## 隔离与测试

其他五题配置文件与 `arc-compiler-stackoverflow-v2.zip` 逐字节一致；BookStack、Ctrip、Keep、PrestaShop、Stack Overflow 的正常请求轨迹也与该包一致。它们没有重新线上评测，不能据此保证每次生成得分相同。

仓库相关Python检查34项通过。独立ZIP检查33项通过、1项跳过（完整需求位于ZIP外，已经在仓库验证）；七组Node检查通过。新增检查包括真实浏览器发现子页菜单消失、登录刷新、AST拒绝丢路由/保护/组件及超范围修改、候选失败恢复与模型设置恢复。

## 交付与证据

- 智能体包：`D:/软工大作业/arc-compiler-railway-v2.zip`，包含六题，611条目。
- 同产物应用/结构报告：`compiler/outputs/railway-v2/replay/.arc/railway_navigation.json`。
- 同产物完整测试：`compiler/outputs/railway-v2/layout-verification.json`。
- 结构修复日志：`compiler/outputs/railway-v2/gate-retry.log`。
- 冻结ZIP的解包目录：`compiler/outputs/railway-v2/compiler/`。
- 新生应用与完整日志：`compiler/outputs/railway-v2/fresh/`、`fresh.log`、`fresh/compiler.log`。
- 新生最终摘要：`compiler/outputs/railway-v2/fresh-summary.json`；完整报告：`fresh/.arc/acceptance.json`、`fresh/.arc/compilation.json`；导航报告：`fresh/.arc/railway_navigation.json`。
- 五题请求轨迹对照：`compiler/outputs/railway-v1/baseline-traces.json`、`compiler/outputs/railway-v2/new-traces.json`。

所有成绩均为本地公开用例结果，v2尚无新线上成绩。一次新生不能证明稳定通过率，也不能把不同产物的最高分合并成一个版本成绩。

最终包4,528,169 bytes，611条目；SHA256：`2c83fd42b3268f1f7c659fb16b4822655922de5cf8f08d99b9a935bfd87c2fb8`。ZIP校验和源码一致性检查通过，不含.env、API Key、outputs、node_modules或.git。
