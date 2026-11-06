# Ctrip v5冻结版本说明

验证日期2026-11-06。本分支用于审阅和复现已推荐版本，不继续修改冻结编译器。

## 思路

1. 六题用不可变PROFILE维护提示词、生成拆分、预算、修复指导和专用检查，统一入口按已知需求指纹选择策略。
2. 优先修复共用前置环节：guest会话、验证码、登录刷新、菜单、准确标题和控件语义。专用HTTP检查、AST修正和浏览器探测减少同类失败。
3. 无损缩减重复需求文本，索引Given明确启动数据；不把普通UI创建示例当作预置业务记录。
4. 导航通过后，限定机场/报销既有组件处理15项服务用例，再进行全量验收。通过数必须增加且无已有通过回退，否则恢复已验证候选。

## 代码索引

| 文件 | 职责 |
| --- | --- |
| compiler/main.py | CLI与auto/compact/staged流程。 |
| compiler/infrastructure/tasks/registry.py | 已知套件与六题PROFILE映射。 |
| compiler/infrastructure/tasks/ctrip.py | Ctrip提示词、预算、开关和前置依赖。 |
| compiler/infrastructure/tasks/ctrip_context.py | 无损需求上下文与Given索引。 |
| compiler/infrastructure/tasks/prepare_ctrip_source.mjs | 语义、事件、字段文本及类型修正。 |
| compiler/infrastructure/tasks/probe_ctrip_backend.mjs | 注册/会话/登录/退出与HTML响应类型检查。 |
| compiler/infrastructure/tasks/ctrip_navigation.py | 受限导航修复、浏览器验证和回滚。 |
| compiler/infrastructure/tasks/ctrip_components.mjs | 限定组件替换、保护其他页面/路由/provider。 |
| compiler/infrastructure/tasks/ctrip_services.py | 机场/报销分区修复。 |
| compiler/infrastructure/compact.py | 共用生成骨架及专用步骤接线。 |
| compiler/infrastructure/compact_acceptance.py | 公开验收、失败分组、修复与回退保护。 |

## 真实验证及限制

冻结ZIP在空目录完整生成：47→120→122获保留，最后122候选不保留；最终122/152（80.3%），30失败、0跳过、退出0、940.72秒。模型deepseek-flash，指定网关，密钥从本机环境读取，源码全程未改。

该轮导航短检查仍FAILED，服务阶段BLOCKED_BY_NAVIGATION；最终122来自后续全量修复。127/152及125/152是同产物实验，不是重新生成或线上成绩。

36项相关Python和11组Node检查通过。验证摘要位于docs/evidence/ctrip-v5/。生成应用和原始模型IO日志没有上传；本次整理不额外调用模型重新生成应用。

仍有30项失败，包含城市/日期、搜索/预订、订单、安全设置及部分服务记录，具体清单见docs/evidence/ctrip-v5/final-audit.json。

其他五题配置和正常请求模拟轨迹与先前基线一致，但不等于每次生成分数相同。router仍与已知公开套件指纹绑定，未知修订可能退回generic；线上图片对应包/run ID未确认，测试统计口径也待核对。

v6固定菜单实验完整新生113/152，未采用其运行代码。BookStack已撤回热修复也不合入；相关文档仅为历史记录。

## 发布核对

releases/arc-compiler-ctrip-v5.zip为原始冻结包：576个文件、49个目录条目，总4560932 bytes，SHA256 189fb42115fe617195a9a972ca438a5405ffcb7c79de5cdc6f3047e78816c4bd。compiler/逐文件一致。

仓库级文档、诊断工具与证据位于compiler/外，不改变冻结源码。提交前检查源码/ZIP一致、六题需求完整、无真实密钥/.env/输出目录。

若重新打包，Git换行规范化、文件时间戳可能改变二进制ZIP哈希；需要精确复用原包时使用releases/冻结ZIP。
