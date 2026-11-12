# 第 7 步 BookStack 第 2 次运行分析

第 2 次使用 b47f7ff，约 65 秒结束。35 次逻辑调用均在网络 I/O 前失败，SDK 尝试数 35，上报用量为 0。预算仍把每次尝试当作可能已发送，按预留上界共计入 767,799 token。编译报告将 04 标成 GREEN，将 08 和 10 标成 NO_UI。04 的上游文件只有空 entities 和空 requirements，是 02 在首次通过前写入的占位文件。[编译报告](../../compiler/outputs/bookstack-app-20261112-101211-run2/.arc/compilation.json) · [事件日志](../../compiler/outputs/bookstack-app-20261112-101211-run2/compilation_events.jsonl) · [编译日志](../../compiler/outputs/bookstack-app-20261112-101211-run2/compiler.log)

## 传输与预算

- 回环测试在 b47f7ff 上复现了 SyncByteStream 断言。OpenAI 3.41.0 的 HTTP 客户端来自 httpx2 2.16.0，旧编译器传给它的是 httpx 0.28.1 的自定义传输层。两者的流类型不兼容，断言发生在网络 I/O 之前。
- 现在保留 SDK 自己构造的默认同步客户端及其 HTTP 传输，在它已经选好的连接池上包装现有网络后端。包装按每次连接、TLS 握手、写入和读取重新计算剩余时间，结构上同时适配 httpcore 1.0.9 和 httpcore2 2.16.0。若 SDK 的私有连接池接口发生变化，继续使用其默认传输，发出 RuntimeWarning 与 model_transport_fallback 事件。该回退仍有请求级 I/O 超时，但不保证逐次重算绝对截止时间，发出前判定也限于明确的错误。
- 网络后端在首次尝试写入非空请求字节前设置写入标记。若出错时尚未走到该边界，或异常链能确认连接未建立，退回预留的 token。请求可能已部分写入或读取超时且没有 usage 时仍按上界结算。明确的兼容参数拒绝和 HTTP 401/403 没有 usage 时按零结算。网关若上报 usage，则按实际量结算。SDK 尝试数始终用于限制重试，进入 HTTP 钩子的本地失败也计一次尝试。
- 维持 requirements.txt 的 OpenAI 版本声明。锁定环境由 uv.lock 复现 OpenAI 3.41.0，另用 OpenAI 2.8.1 实测其原生 httpx 路径。固定到单个 HTTP 系列会限制平台依赖选择，而且无法取代运行时兼容检查。后续 SDK 若改动私有后端接口，会走有提示的原生回退。

## 熔断与阶段报告

默认阈值 3，可用 COMPILER_MODEL_FAILURE_THRESHOLD 设置正整数。按逻辑调用的最终结果计数，重复同类型的本地发出前错误、连续 HTTP 401/403、连续连接建立失败分别累积。成功或其他类型的结果会中断当前计数。触发后拒绝新的模型调用和 SDK 重试，已经在途的请求可完成结算。当前阶段和总报告标为 MODEL_CIRCUIT_OPEN，后续选中阶段标为 SKIPPED_MODEL_CIRCUIT_OPEN。报告的 model_circuit 包含类别、原因、阶段、连续次数及阈值，入口沿用编译失败退出码 0 的约定。

02 和 07 到首批设计通过后才写出可供下游消费的设计。04 对旧的全空 schema 占位文件返回 MISSING_PREREQUISITES。真正通过校验的无表设计会有已接受的叶子映射，仍可生成并验证空数据库。失败批次已接受的相邻设计和既有候选回滚规则继续生效。

## 回归证据

- compiler/tests/test_sdk_loopback.py 使用标准库 HTTP 服务，只监听 127.0.0.1。文本和视觉都用实际模型包装器、真实 SDK 和 SDK 原生传输请求 /v1/chat/completions。覆盖 JSON 与 usage、截止前的慢响应、跨过绝对截止的分段响应、普通 400、拒绝连接、回退后成功、注入本地断言，以及 401/403 熔断和成功清零。
- 端到端的编译回归以两次回环 401 触发熔断，报告保留原因，04 标记跳过，后续没有发出请求。04 的独立回归确认旧占位 schema 不会触发运行时验证。
- 锁定环境定向回归退出 0，55 通过、16 个子测试通过。强化分段响应断言后再次执行两条截止时间用例，退出 0，两条通过。OpenAI 2.8.1 与 httpx 0.28.1 的独立环境回环回归退出 0，14 通过，包含强化后的分段响应断言。
- 全量回归使用 STAGED11_REAL_CHECKS=0，选择 compiler/tests 与 offline_eval/tests，并排除 timeout_stops_descendants。退出 0，169 通过、1 跳过、1 未选择、38 个子测试通过。跳过项需要 ARC_DB_TEST_NODE_MODULES。四份完整合成用例的 11 阶段均为 GREEN，部分失败用例保留逐叶验收结果。产物位于 compiler/outputs/staged11-run2-full/。
- 第 3 次真实生成由组长在沙箱外执行。回环回归与真实运行命令见 [运行手册](RUN_BOOKSTACK.md#第-3-次运行)。

回归从仓库根目录执行，锁定环境通过 uv run --project compiler --locked --with pytest==9.2.0 运行 pytest。独立旧版 SDK 使用 uv run --no-project --with openai==2.8.1 --with pytest==9.2.0 --with python-dotenv --with rich --with Pillow --with PyYAML，指定 PYTHONPATH 为 compiler，执行同一测试文件。产物位于 compiler/outputs/staged11-run2-regressions/ 和 compiler/outputs/staged11-run2-legacy-final/。

## 文件

- 传输、预算、编译状态和 CLI：model_io.py、budget.py、compiler.py、main.py。
- 设计发布、04 缺前置判断、回滚和配置：pipeline/db_schema.py、pipeline/database.py、stages/frontend/ui/synthesis.py、shared/agent/recovery.py、shared/project/provenance.py、compiler/.env.example。
- 验证与记录：新增 compiler/tests/test_sdk_loopback.py，更新 compiler/tests/test_run1_regressions.py、PROGRESS.md、RUN_BOOKSTACK.md，新增本分析。
