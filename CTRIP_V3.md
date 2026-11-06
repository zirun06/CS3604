# Ctrip v3：共享控件契约与服务分区修复

2026-11-06。基于Ctrip v2，仅调整Ctrip。目标是减少整页随机重写，把可以确认的公共故障变为可重复的规则，再将剩余机场/报销问题限制在对应组件内。

## v4补充：装饰字符不能改变菜单名称

v3冻结独立生成首轮26/152，第一次公开修复仍26，候选被拒绝。该轮已因确定的共用控件缺陷停止，属于未完成实验，不能称为完整独立生成成绩。源码没有在运行中修改，记录见`compiler/outputs/ctrip-v3/withdrawn.json`。

该次生成的Dropdown使用CSS `::after {content: "▾"}`；浏览器将箭头纳入My account等菜单按钮的可访问名称，页面文本有My account但精确按钮匹配失败，进而导航阶段误判会话阻塞并跳过服务修复。真实浏览器fixture已复现：保留同样箭头、给真实标签显式aria-label后，登录、账户菜单、刷新、退出与公共服务链路全部通过。

v4对全局指定菜单按钮及真实`aria-haspopup="menu"`、单个string标签表达式的共享组件设置显式名称，不改显示文本或装饰。相关类型、幂等性和带CSS装饰的浏览器正反检查已通过。其他v3规则保留。

当前冻结包为`D:/软工大作业/arc-compiler-ctrip-v4.zip`，625条目、4560719 bytes，SHA256 `6e7240decbaac1b296ae0444f8a5b87b2ded1608b44c51b517e179088dad442b`。独立生成正在`compiler/outputs/ctrip-v4/compiler-frozen/`、`fresh/`运行，日志`fresh.log`、结果`fresh-summary.json`。运行中不改冻结源码。36项Python检查通过；五题配置及正常请求轨迹、源码与ZIP一致和密钥排除核对通过。不得把v3同产物127/152记作v4新生分数。

## 改动

- `prepare_ctrip_source.mjs`：账户菜单修正扩展到Global navigation中的Flights/More services；必须能证明同一个状态在悬停时打开、随后点击又取反才修改。导航之外同名按钮不受影响。
- 基于TypeScript真实类型，只为混合文本中的string/number字段建立独立span；对象、数组、JSX及未知类型不包装，文本和业务值不变，重复运行不增加嵌套。地址/资料/发票/航班动态不再将所有字段混成一个不可单独识别的文本。
- 仅把机场命名区域内、事件确实调用本组件useNavigate返回值的纯跳转按钮转换为已有Link，复用真实目标；C字母筛选按钮保持按钮。订单View details保留原路由并具有按钮语义；报销订单和机场巴士记录用真实业务标识生成Record名称。推断记录名称时不穿过嵌套函数，避免把map回调变量错误引用到外层。
- 对React布尔属性中类型为string与boolean联合的表达式显式使用Boolean，保持原JS真假含义，避免这类类型错误触发整份前端重生成。
- `probe_ctrip_navigation.mjs`：首页Log in点击、凭证表单、提交登录分开记录。入口点击超时不再误判为后端会话失败；短检查的动作等待改为4秒，公开验收超时和断言不变。
- 新增`ctrip_services.py`：导航通过后，独立运行REQ-8/9的15项服务用例，最多两轮完整组件提案。只允许修改实际持有机场列表/详情、巴士、报销区域的既有组件；提供真实后端服务响应代码和已有类型。不能修改App、全局导航、账户、安全页面、路由或后端。只保留通过数增加且没有原通过用例回退的候选；失败恢复当前最优组件，再进入原三轮全量验收。
- `ctrip.py`：补充真实字段文本边界、所有导航菜单悬停/点击规则、机场链接与天气、报销记录名称，以及注册完成后转到登录页仍保留成功status的提示。

没有修改测试、固定测试生成的随机名字或把业务状态伪造成通过；API Key不写入源码/包。

## 验证边界

| 方式 | 结果 | 含义 |
| --- | ---: | --- |
| v2冻结ZIP完整独立生成 | 101/152 | 上一版本本地成绩，线上仍待用户验证。 |
| v2应用副本上的v3规则 | 114/152 | 新增14项通过；一项回退为进入应用前ERR_CONNECTION_FAILED，随后复测恢复。 |
| 增加机场/报销角色契约 | 123/152 | 同产物完整复测，无原101通过回退。 |
| 局部服务修复后 | 126/152 | 服务用例11/15→14/15，其余失败含巴士记录名称。 |
| 最终规则同产物复测 | **127/152（83.6%）** | 25失败、0跳过，原101通过全部保留；不是重新生成成绩。 |

v3冻结ZIP空目录独立生成已停止，未完成；正式独立验证转为上文的v4。统一使用deepseek-flash和https://api.arc-bench.com/v1，密钥从本机环境读取。

## 检查与交付

36项相关Python检查、11组Node检查通过。其他五题配置逐字节及正常请求轨迹与railway-v2一致；它们没有重新评测，配置相同不保证每次模型生成成绩相同。

包：`D:/软工大作业/arc-compiler-ctrip-v3.zip`，625条目，4560128 bytes。

SHA256：`debf2e55488b414e5476c56b44cebcf885065f2f0a8dde1f32e272a6e7e5d6f7`。

证据在`compiler/outputs/ctrip-v3/`：`replay-final-verification.json`、`replay/.arc/ctrip_services.json`、`package-audit.json`、`request-traces.json`、`python-checks.json`、`node-checks.json`。`compiler-frozen/`和`fresh/`用于冻结包新生验证，`replay/`用于同产物实验，不混记。
