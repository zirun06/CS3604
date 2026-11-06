# BookStack 零分诊断与修复

> 已撤回：用户于 2026-11-05 更正版本归属，确认 arc-compiler-stackoverflow-v2.zip 的 BookStack 正常。本文仅保留为错误归因期间的历史试验记录，不再作为当前修改或提交建议。BookStack 运行源码已恢复为旧 v2，热修复包已移至 compiler/outputs/bookstack-hotfix-withdrawn/，不得合入 12306 调优包。

日期：2026-11-05。输入为用户提供的 `584acc5ef842-template.zip` 及运行日志。交付包为 `D:/软工大作业/arc-compiler-stackoverflow-v2-bookstack-hotfix.zip`，保留原 v2 包供对照。

## 已确认的原因

日志正确选择了 `bookstack-full-track`，没有进入 Stack Overflow 专用处理。生成应用的 `frontend/src/App.tsx` 在 `App()` 顶层调用 `useNavigate()`，但 `frontend/src/main.tsx` 只渲染 `<App />`，没有 Router。App 中虽然导入了 BrowserRouter，却未实际渲染。

浏览器实测正文为空、导航数量为零，并出现运行时异常。非压缩诊断明确报错：`useNavigate() may be used only in the context of a <Router> component.` 因此大量测试在共同入口处失败，并非 35 项功能分别失效。

原检查只验证构建、API health 和 HTML 中的 root 容器，不能证明 React 成功渲染。此前仅根据配置未变推断 BookStack 不受影响，验证不足；但现有证据也不能将此次白屏归因为 Stack Overflow 的专用逻辑误路由。

日志还记录了一次联合前端输出在 16000 tokens 处截断。后续提案能构建成功，但运行时仍白屏。

## 本轮代码变更

| 文件 | 改动与目的 |
| --- | --- |
| `compiler/infrastructure/tasks/ensure_router_context.mjs` | 检查实际使用的 Router provider 与 consumer。在生成 App 使用 Router、但没有 provider 时，在入口补 BrowserRouter；保存原入口，可重复执行，后续 App 自带 provider 时恢复入口，避免嵌套。业务 App 源码保持原样。 |
| `compiler/infrastructure/tasks/probe_frontend_runtime.mjs` | 用真实 Chromium 打开应用，检查 JS 异常及 Login、Shelves、Books 导航是否渲染且入口唯一。 |
| `compiler/infrastructure/compact.py` | 前端构建前执行入口检查，构建后执行浏览器检查；失败反馈给原来的完整提案重试流程。浏览器依赖在临时验收工作目录准备并清理。 |
| `compiler/infrastructure/tasks/profile.py` | 增加默认关闭的入口与浏览器检查开关，以及可选的联合输出预算。 |
| `compiler/infrastructure/tasks/bookstack.py` | 只在 BookStack 开启两项检查，联合前端输出上限由 16000 提至 24000。原始前后端提示词、联合生成方式、三次提案及 legacy 验收逻辑保留。 |

与 `arc-compiler-stackoverflow-v2.zip` 比较，新包仅新增两个运行辅助脚本及三个测试，修改上述三个 Python 运行文件和 `tests/test_task_profiles.py`。其余五题配置文件及入口 main.py 均字节一致。共享代码增加了开关分支，但其他题默认不开启；这不等于已重新线上验证其他五题的分数。

## 验证与结果

| 验证方式 | 结果 | 说明 |
| --- | --- | --- |
| 用户提供的原线上产物 | 首次验收 0/35 | 编译和启动健康检查通过，但浏览器白屏。 |
| 同一份产物仅修复 Router 后复测 | 7/35 | 证明白屏被修复；其他功能及语义入口问题仍在，不能把此数当作新包生成分数。 |
| 从最终新 ZIP 解包、空目录调用模型重新生成 | 31/35，88.6% | 退出码 0，耗时 788.14 秒，最终状态 PARTIAL；为本地公开验收结果，尚无线上复评。 |

重新生成使用 `deepseek-flash` 和 `https://api.arc-bench.com/v1`，密钥从本机环境读取。首个前端提案被新浏览器检查以重复 Login 入口拦截，后续提案正常通过。首轮验收 31/35；两次修复请求超时，末次候选仍为 31/35，被回滚，保留原通过集合。参考图片分析请求也有超时，本次未取得有效图片分析结果。

剩余四项：新建书架取消后的返回位置、删除书架后的列表标题、草稿详情缺少 Delete Draft 操作、匿名首页缺少最近更新页面入口。两项标题断言期望 `Shelfs`，实际显示 `Shelves`；取消流程还存在目的页面差异。这些仍未解决，不应写为全通过。

最终 ZIP 解包后的 29 项 Python 检查、6 组 Node 检查通过，覆盖 Router 补齐与恢复、真实页面异常和重复入口、浏览器失败后的重试，以及已有 Stack Overflow 契约、状态、区域和 SQL 检查。BookStack 原始提示词与请求载荷散列仍与 v8 参考轨迹一致；前端预算和检查流程有意改变。

## 证据与交付

- 新提交包：`D:/软工大作业/arc-compiler-stackoverflow-v2-bookstack-hotfix.zip`
- 大小：4,512,021 bytes；606 个 ZIP 条目。
- SHA256：`990bd024157271ecebcef60f8cc3f7e273d17bbb71a682db87ab6019a454f6b7`
- 从最终 ZIP 解包的编译器：`compiler/outputs/bookstack-hotfix/compiler/`
- 独立生成应用及报告：`compiler/outputs/bookstack-hotfix/fresh/.arc/`
- 独立生成日志：`compiler/outputs/bookstack-hotfix/fresh.log`
- 运行摘要：`compiler/outputs/bookstack-hotfix/fresh-summary.json`
- 原产物 Router 修复复测：`compiler/outputs/bookstack-zero-audit/router-fixed-verification.json`

上传的是智能体 ZIP，不是上述生成应用目录。新包仍包含六题；本轮只针对 BookStack 修改配置，保留 Stack Overflow v2 及其他题现有逻辑。原包和零分产物均未覆盖。
