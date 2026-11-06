# Ctrip v6：固定通用菜单交互，保留模型业务生成

2026-11-06。本轮仅Ctrip，其他五题的配置及正常请求轨迹保持railway-v2不变。前期方法和完整记录见CTRIP_V5.md、CTRIP_V3.md。

**结论：v6保留为实验，当前推荐仍为v5。** v6冻结空目录独立新生113/152，低于v5的122/152，不能因版本号更大就推荐上传。`compiler/`已逐文件恢复到v5上传ZIP一致；v6变更另外保存在仓库`experiments/ctrip-v6/`及冻结ZIP，未丢弃。

v5冻结独立新生已经达到122/152（80.3%），相比v2的101/152（66.4%）提高21项。它仍经历了菜单关闭竞态，导航短检查失败后靠全量模型修复恢复。因此v6进一步固定菜单机制，减少这一公共故障的生成波动。

## 核心改动

新增`compiler/infrastructure/tasks/stabilize_ctrip_menu.mjs`，在Ctrip前端构建前执行。通过AST找到Global navigation实际使用的本地共享菜单组件，仅支持有真实label/children且具有menu语义的组件；含业务API调用、useSession/useContext或业务事件参数的组件跳过。

保留原参数签名、调用方label/children、原路由、API、登录态和主要CSS类名，只替换菜单的状态与事件机制：悬停/点击明确打开，跨越菜单间隙不关闭；点击外部、按Escape、选择链接/动作时关闭；一个菜单打开时通知同级菜单关闭；支持普通children与close回调renderer，清理全部document/window监听。使用已有React导入，不引入新依赖。重复执行不重复替换。

这不是预置整套Ctrip答案。业务内容、账户数据、后端和页面继续由需求生成；稳定的只是通用控件。后续仍有原导航检查、受限机场/报销组件修复以及全部152项验收与回退保护。

## 验证

- 真实React浏览器测试验证了CSS箭头不污染名称、快速悬停点击、16px菜单间隙、点击外部、Escape、同级菜单协调、render-function children与原链接目标。
- 替换实际产物菜单后，完整导航检查GREEN；同产物全套复测125/152，分数未回退。该副本来自v4检查点并已接受服务修复，不算独立新生。
- 36项相关Python、12组Node检查全部通过。

冻结ZIP空目录独立生成已结束：**113/152（74.3%）**、39失败、0跳过、退出0、978.77秒。77→92→104→113均获保留，无首轮通过用例回退。导航首次GREEN，零模型导航修复；局部服务11→13/15，第二候选未保留；全量首轮40项停在日期按钮入口，后续三轮修复仍未解决全部业务问题。

单次记录证明固定菜单解决了本轮共用导航故障，未证明全系统分数更高或更稳定。业务生成差异仍影响航班/日期/预订等用例，不能把菜单稳定等同于业务正确。

证据：`compiler/outputs/ctrip-v6/compiler-frozen/`、`fresh/`、`fresh.log`、`fresh-summary.json`及`final-audit.json`。运行全程冻结源码未改，结束后逐文件与原ZIP一致。统一deepseek-flash与https://api.arc-bench.com/v1，密钥从本机环境读取。

## 包

`D:/软工大作业/arc-compiler-ctrip-v6.zip`，627条目，4565909 bytes。

SHA256：`34ff976c8bc229135bb60e588f592ddac2d762d6240a360b08af50179ec99fc4`。

ZIP完整性、运行源码一致性、密钥排除与其他五题轨迹核对通过。详见`compiler/outputs/ctrip-v6/package-audit.json`。没有新的线上分数。
