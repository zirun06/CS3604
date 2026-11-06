# Ctrip travel services 独立调优

日期：2026-11-06。本轮基于 `arc-compiler-railway-v2.zip`，只调整Ctrip分支；保留12306 v2及其余四题已有逻辑，BookStack热修复保持撤回。

## v2补充：前端会话同步与日期入口

当前候选为 `D:/软工大作业/arc-compiler-ctrip-v2.zip`，623条目、4553210 bytes，SHA256 `ee1f2383f452833bb46653f18e8807a52730d7a886e996b8cfbf737975bc67a2`。下文v1包信息属于先前候选。

v1的冻结新生运行中断，退出码1073807364；已记录的验收为33→33（拒绝）→58，不应称为一次完成的新生结果。进一步审查发现：登录接口成功，但根App和页面分别使用首次加载的会话副本，导航不随登录更新。另有日期文本框未绑定已有日历按钮事件、外置pointer-enter/click处理函数互相抵消的问题。

v2仅在Ctrip中增加下列修正：识别本地fetch帮助函数和实际读取`/api/session`的挂载effect，成功登录/注册/退出后发出会话变更事件，订阅方重新查询服务器；不以guest Cookie伪造已登录状态，不让会话读取再次发出变更事件。日期框仅复用同一字段中唯一已有Choose date按钮的真实事件；账户按钮支持识别同一组件中外置的pointer-enter/click函数，保留其他副作用。导航探测优先验证登录、账户菜单、刷新和退出，再检查机场服务。

会话修复后的同产物完整复测为70/152、82失败、0跳过，报告`compiler/outputs/ctrip-v1/session-sync-verification.json`。随后应用pointer事件修正，完整复测为**96/152（63.2%）**、56失败、0跳过，相对70通过版本无通过用例回退，报告`compiler/outputs/ctrip-v2/previous-artifact-verification.json`。这份应用已接受过模型修复，不是新生结果。不得把96或原产物81作为v2独立生成成绩。

v2冻结ZIP解包、空目录完整新生已结束：**101/152（66.4%）**、51失败、0跳过，退出码0，1085.36秒。首轮95，第一次修复101获保留；随后102与99两个候选均被拒绝并恢复101，其中102候选新增4个通过但回退3项（登出、错误旧密码、历史隐私）。最终101相对首轮95没有已通过用例回退。它是一次本地完整独立生成记录，尚无v2线上成绩，不能保证重复生成或线上结果相同。

新生的前端第一候选曾出现布尔属性TypeScript错误，局部修复后仍失败，第二候选通过。导航短检查在Log in点击时超时，被标为BLOCKED_BY_SESSION并交常规验收处理；因此不能声称该轮导航短检查GREEN。后续完整验收验证了大部分账户业务与航班动态。剩余51项包括More services子入口（机场指南7项、报销凭证6项）、历史订单详情、注册成功状态、已选乘客与业务文本等。完整失败清单在`final-audit.json`，未修改或跳过公开用例。

正式证据目录：`compiler/outputs/ctrip-v2/compiler-frozen/`、`fresh/`、`fresh.log`、`fresh-summary.json`和`final-audit.json`。使用deepseek-flash与指定网关，密钥只从本机环境读取。运行全程未修改冻结源码；结束后再次核对ZIP、仓库运行源码和冻结解包源码，逐文件一致。

检查：31项相关Python检查、11组Node检查全部通过；源代码与ZIP一致、密钥排除、其余五题配置及正常请求轨迹与railway-v2一致，详见`compiler/outputs/ctrip-v2/package-audit.json`、`python-checks.json`及`node-checks.json`。

## 线上产物的共同故障

用户提供 `73406c645ab0-template.zip` 及2026-11-05 21:14:56开始的日志，平台及产物保留成绩为29/152（19.1%）。日志中的公开修复候选未带来收益，并出现75秒模型超时。

从 `.arc/acceptance.json` 分组发现：36项停在Personal center链接、10项停在Orders、23项停在Book flight标题、11项涉及重复More services、9项停在Flight status、7项涉及短信登录切换。它们是共用环节阻塞，不能当作123项彼此独立的功能缺陷。

后端会话查询使用 sessions INNER JOIN users，导致 user_id=NULL 的匿名会话查询不到。发送验证码后，下次校验创建了另一匿名会话，从而显示 Verification code not sent。另有时钟固定返回基准时间的问题。

前端的问题包括：Orders/Personal center链接被设为menuitem；悬停先打开My account、随后点击又关闭；标题拼成Book flight JD5162；缺失Flight results标题；航班号没有独立文本；主页重复More services。必须保留角色例外：**Log out明确要求menuitem，Orders/Personal center明确要求link，并处于menu容器中。**

## 实现

| 文件 | 变化 |
| --- | --- |
| `compiler/infrastructure/tasks/ctrip.py` | 独立会话、验证码、初始数据、时钟、业务及UI契约；前后端生成保留独立预算，CSS上限10000；按前置步骤分组的三轮公开验收修复。 |
| `compiler/infrastructure/tasks/ctrip_context.py` | 对重复长行建立共享字典，保留全部原需求/场景；索引Given中的全部明确启动记录，保持不同业务数据集与所有权。 |
| `compiler/infrastructure/tasks/prepare_ctrip_source.mjs` | 只对被匿名会话函数使用的session resolver修正nullable JOIN；修正静态时钟、角色、标题/独立航班号、重复入口和悬停/点击冲突。可重复执行。 |
| `compiler/infrastructure/tasks/probe_ctrip_backend.mjs` | 独立内存数据库中的真实HTTP闭环：匿名Cookie、发送前拒绝验证码、发送后保留会话、注册、凭证登录/恢复、退出。 |
| `compiler/infrastructure/tasks/ctrip_components.mjs` | 只允许替换实际Global navigation所属组件，保护原业务页面、App、路由和provider。 |
| `compiler/infrastructure/tasks/ctrip_navigation.py`、`probe_ctrip_navigation.mjs` | 最多两次完整导航组件提案，真实浏览器验证服务入口、机场目录、账户menu及链接、刷新与Log out menuitem；失败恢复原App。 |
| `compiler/infrastructure/tasks/profile.py`、`compiler/infrastructure/compact.py` | 默认关闭的ctrip_contract，仅由Ctrip开启以上步骤。 |

需求输入从302034字符缩为231271字符，减少约23.4%，39条共享文本。自动还原检查确认parsed YAML与原需求完全一致。完整原文仍负责套件匹配与验收，不修改公开测试或断言。

新增HTTP探测的最小协议写入Ctrip后端指导，包括session、register/send-code、register/verify-mobile、register/complete、login/password、logout。公开查询与匿名业务仍允许访问，私有数据必须验证真实用户ID，不能把存在guest cookie当作登录。

## 验证方式分开记录

| 方式 | 结果 | 边界 |
| --- | ---: | --- |
| 用户原线上产物 | 29/152 | 平台结果与产物报告一致。 |
| 早期归一化试验 | 74/152 | 对Log out角色处理过宽，出现一项回退；该规则已修正，不作为最终交付结果。 |
| 最终规则与导航修正后的同产物完整复测 | 81/152（53.3%） | 71失败、0跳过；原通过用例没有回退。不是智能体重新生成分数。 |

早期导航短链路没有覆盖menu容器和机场目录，候选虽通过短链路，完整分数仍为74，且出现入口回退。因此已把menu容器、目录入口和悬停登出加入正式探测，修正后重新完整验证为81。中间曾启动的生成原型已停止，不参与最终计分；正式运行使用 `compiler-final/` 和空目录 `fresh-final/`。

最终包的新生验证使用deepseek-flash、https://api.arc-bench.com/v1，文本/视觉推理none，密钥从本机环境读取。新生结果另行记录，不能用81/152替代。

## 其他五题与检查

12306、BookStack、Keep、PrestaShop、Stack Overflow配置文件与railway v2逐字节一致；正常编译请求轨迹的提示词/载荷散列、预算和验收参数也一致。它们未重新线上评测，配置不变不保证每次模型生成分数相同。

仓库40项相关Python检查通过。独立ZIP检查38项通过、2项跳过（两套完整需求在ZIP外，已在仓库验证）；11组Node检查通过，包含真实SQLite nullable session、真实HTTP注册链路、错误Cookie与未发送验证码探测、真实浏览器跨页导航、受限组件替换与候选恢复。

## 路径

- 提交候选：`D:/软工大作业/arc-compiler-ctrip-v1.zip`。
- 原产物诊断：`compiler/outputs/ctrip-v1/online/`。
- 同产物修正副本：`compiler/outputs/ctrip-v1/replay/`。
- 最终同产物复测：`compiler/outputs/ctrip-v1/replay-final-verification.json`。
- 最终导航报告：`replay/.arc/ctrip_navigation.json`；日志：`navigation-final.log`。
- 正式解包编译器：`compiler/outputs/ctrip-v1/compiler-release/`。
- 正式新生应用、日志、摘要：`fresh-release/`、`fresh-release.log`、`fresh-release-summary.json`。
- 五题请求对照：`baseline-traces.json`、`new-final-traces.json`；包核对：`package-audit.json`，均在 `compiler/outputs/ctrip-v1/`。

早期生成还暴露了全局JSON Content-Type污染HTML/JS/CSS的问题。已增加仅作用于API的MIME中间件修正，以及后端阶段的HTML响应检查；`fresh-final/`那份候选因此停止，后续直接修复只算同产物实验。正式独立新生改在 `fresh-release/`，包含该修正；不能把两份候选混记。

最终包623条目、4,551,318 bytes。ZIP校验、源码一致性与密钥排除检查通过；不含.env、API Key、outputs、node_modules或.git。精确校验值见 `package-release-audit.json`。
