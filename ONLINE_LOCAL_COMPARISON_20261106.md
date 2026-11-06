# 本轮线上截图与本地记录对比

依据用户2026-11-06提供的六题截图。实际上传ZIP、run ID及线上需求/测试版本尚未确认；因此这是历史对照，不是相同应用在两种环境下的复测，不能直接据差值认定代码回退。

只比较Tests测试通过率。本地没有统一的Features或平台Score记录，不能用平台Score与本地通过率相减。

| 任务 | 本地独立生成/历史记录 | 线上Tests | 线上减本地（百分点） | 可比性 |
| --- | --- | ---: | ---: | --- |
| 12306 | railway-v2，105/142=73.9% | 69.0% | -4.9 | 当前继承配置的单次完整新生记录。 |
| BookStack | 原full-track历史基线35/35=100% | 94.3% | -5.7 | 仅历史参考，没有当前推荐包的同轮独立新生对照；已撤回热修复的31/35不纳入。 |
| Ctrip | 推荐v5，122/152=80.3% | 67.8% | -12.5 | 需先确认本次上传确实为v5；同产物127/152不纳入。 |
| Keep | two-task-v2独立生成30/33=90.9% | 78.8% | -12.1 | 标签修复后的同产物33/33不纳入。 |
| PrestaShop | prestashop-v3独立生成77/86=89.5% | 69.8% | -19.7 | 差距最大；同产物52/86不纳入。 |
| Stack Overflow | v2阶段历史独立生成17/66=25.8%、25/66=37.9% | 65.7% | 高于历史，不能当严格同版本差值 | 最终feed/前置映射改动后没有再次完整独立生成；53/66=80.3%为同产物修复，不是当前可比的新生成绩。 |

差值按原始分数计算后四舍五入，不用已舍入的百分比再次相减。各行不是同一次六题整包本地运行，不计算混合版本的“本地整体平均”。

## 主要发现

1. 不是六题普遍低于本地。PrestaShop、Ctrip、Keep下降较明显；12306较接近；BookStack仍高；Stack Overflow本轮优于现有可用独立生成历史，不能拿同产物53/66说它下降。
2. 本地独立生成大多只有一次或少数几次记录，是样本，不是稳定均值。版本/路由/输入口径未确认前，也不能仅以“模型波动”解释下降。
3. 同一公共入口失败可影响很多用例。要对照两份应用的失败集合和首次共同错误，才能区分生成差异、环境/部署差异、实际业务缺失或输入/测试版本差异。

## 新发现：测试数量/统计口径可能不同

直接统计本地公开spec中的test声明：12306 142、BookStack 35、Ctrip 152、Keep 33、PrestaShop 86、Stack Overflow 66，总计514。此前用户提供的平台竞赛页面显示515 tests；这不是当前页面的重新查询。

本地66条测试不可能以整数通过数得到四舍五入到一位小数的65.7%；44/67约为65.7%，但这只说明一种可能的分母，不能据此断言线上44/67。平台可能有额外用例、未执行/跳过项或不同统计方法。应取得实际passed/failed/skipped及需求YAML核对。

这与上一轮router审计有关：当前任务配置依赖已知套件的全文或需求树结构指纹；若线上确实增减了场景ID，可能退回generic。但额外平台检查不一定改变需求树，所以测试数量差1不能单独证明错分流。

## 耗时参考

| 任务 | 本地记录 | 线上截图 | 差值 |
| --- | ---: | ---: | ---: |
| 12306 | 803.86秒，约13分24秒 | 19分51秒 | 约+6分27秒 |
| Ctrip | 940.72秒，约15分41秒 | 23分50秒 | 约+8分9秒 |
| PrestaShop | fresh-summary总耗时719.78秒，约12分钟 | 18分23秒 | 约+6分23秒 |

本地脚本计时与平台Runtime可能覆盖不同阶段，环境与模型请求也不同，不能把差值全算成代码效率下降。PrestaShop文档另有718.93秒的阶段耗时合计，以上采用fresh-summary的总耗时。

## 建议排查顺序

先确认上传ZIP哈希、日志Task strategy及线上需求/测试数量，再按PrestaShop、Ctrip、Keep的顺序比较失败集合；不要先扩大模型预算或直接替换router。

本轮不改生产代码或推荐包。当前推荐仍是arc-compiler-ctrip-v5.zip，已有本地证据与本次线上截图分开保留。

## 本地证据

- compiler/outputs/railway-v2/fresh-summary.json
- compiler/outputs/ctrip-v5/fresh-summary.json
- compiler/outputs/two-task-v2/keep-summary.json
- compiler/outputs/prestashop-v3/fresh-summary.json
- compiler/outputs/stackoverflow-v2/fresh-summary.json、final-summary.json
- PROJECT_STATUS.md的原full-track历史基线、STACKOVERFLOW_V2.md的验证边界
- compiler/infrastructure/acceptance_cases/中的六题静态test声明数
