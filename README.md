# CS3604 · ARC-Bench 需求编译智能体

本分支整理冻结版本 **Ctrip v5**。`compiler/`的全部文件与原始上传ZIP逐字节一致，包含六题统一入口；未合入v6实验代码或已撤回的BookStack热修复。

智能体读取需求YAML和参考图，生成React、Express、SQLite应用，并执行构建、协议检查、公开Playwright验收和受控修复。

## 上传与阅读

- **ARC-Bench上传包：** [releases/arc-compiler-ctrip-v5.zip](releases/arc-compiler-ctrip-v5.zip)。不要把整个GitHub仓库下载ZIP作为智能体上传。
- **版本思路与代码索引：** [docs/CTRIP_V5_RELEASE.md](docs/CTRIP_V5_RELEASE.md)。
- **详细调优记录：** [CTRIP_V5.md](CTRIP_V5.md)。
- **验证摘要：** [docs/evidence/ctrip-v5/](docs/evidence/ctrip-v5/)。

原始包SHA256：`189fb42115fe617195a9a972ca438a5405ffcb7c79de5cdc6f3047e78816c4bd`。

## 验证结果

| 验证方式 | 结果 | 边界 |
| --- | --- | --- |
| 冻结ZIP、空目录完整独立生成 | **122/152（80.3%）** | 30失败、0跳过、退出0、940.72秒；单次本地记录。 |
| v2应用副本的定点修复复测 | 127/152 | 同产物复测，不是独立生成成绩。 |
| v4验收前检查点副本修复 | 125/152 | 同产物复测，不是独立生成成绩。 |

本轮独立生成的导航短检查FAILED、服务阶段BLOCKED_BY_NAVIGATION，最终122来自后续全量验收修复，不能声称所有专用门槛均GREEN。

用户后续线上截图中Ctrip Tests为67.8%，但上传ZIP/run ID未确认，不能直接认作此冻结包的线上结果。Score、Tests、Features分开记录，见[线上对比](ONLINE_LOCAL_COMPARISON_20261106.md)。v6独立实验113/152未超过v5，只保留[记录](CTRIP_V6.md)，不包含其新增运行脚本。

## 目录与架构

```text
compiler/       智能体源码、模板、依赖、公开用例
requirements/   六题完整需求和参考图
releases/       原始冻结v5上传包
docs/           版本说明和验证摘要
scripts/        只读任务识别诊断
```

```text
main.py → 需求全文/结构匹配 → tasks/registry.py选择PROFILE
        → 共享compile_compact → 生成/构建/专用检查 → 验收与受控修复
```

当前是共享编译器的任务策略分流，不是六套完全隔离的engine。需求根名称或场景ID变化可能退回generic，见[分流审计](ROUTER_AUDIT_20261106.md)。

## 本地运行

需要Python 3.11+、Node.js 22.12+、npm、Git和uv。从仓库根目录执行：

```powershell
cd compiler
uv sync --locked
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

仅在本机`.env`填写自己的密钥：

```dotenv
OPENAI_BASE_URL=https://api.arc-bench.com/v1
OPENAI_API_KEY=填入自己的密钥
MODEL=deepseek-flash
MODEL_REASONING=none
VISUAL_REASONING=none
```

```powershell
uv run --locked python main.py ../requirements/arc-bench-web--ctrip --output-dir outputs/ctrip
```

替换需求目录即可运行其他题。输出报告为生成目录的`.arc/compilation.json`、`.arc/acceptance.json`；日志`Task strategy`应匹配当前任务。密钥、原始模型IO、生成应用和node_modules不提交。

从仓库根目录只检查分流、不调用模型：

```powershell
uv run --project compiler python scripts/inspect_task_route.py requirements/arc-bench-web--ctrip --expected-task ctrip
```

## 来源与后续

编译器基于课程参考实现`code-philia/requirement-compilation-structure`，上游起点`885077b96a7d95b0cac77615896a4002b466aa48`。分工与六题策略见[TASK_STRATEGY.md](TASK_STRATEGY.md)。

后续优先城市/日期、航班预订和订单契约，继续区分独立生成、同产物修复和线上评测，不以单次最好成绩代表稳定性。
