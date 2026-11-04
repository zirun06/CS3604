# 最近改动与验证记录

整理日期为 2026-11-04。仓库中的编译器以 `arc-compiler-full-track-v11-prestashop.zip` 为基准。

## 最近改动

- **统一入口。** `compiler/main.py` 接收任务输入目录和输出目录。自动模式保留 BookStack 的原始 full-track 生成与修复配置，其他较大的任务使用 compact 流程。compact 根据需求文本指纹或需求树结构匹配公开用例。
- **生成与修复。** 前端和后端构建后会执行启动检查。PrestaShop 优先联合生成 TSX 和 CSS，在输出截断或浏览器检查失败时可以分开生成。公开验收最多执行三轮候选修复，仅在通过数增加、跳过数不增加且已通过用例没有回退时保留候选。
- **PrestaShop 白屏修复。** 在 v8 的线上产物中复现了 `/api/bootstrap` 返回热门商品原始 ID 和名称、漏掉价格的故障。React 调用 `toFixed()` 时异常退出。对该产物的修复让接口返回完整的商品列表，并恢复了常用导航入口。
- **v11 浏览器检查。** PrestaShop 在交付生成结果前会用 Chromium 检查全局导航和热门商品是否实际渲染。修复可以检查并编辑前后端的接口契约。完整公开验收负责购物车等细节。如果首次修复后仍为零通过，流程会尝试重新生成前端，仍为零时在报告中标为 `ZERO_PASS`。

## PrestaShop 验证

| 版本或产物 | 环境与验证方式 | 通过数 |
| --- | --- | ---: |
| v8 线上生成产物 | ARC-Bench 运行记录中的公开验收 | 0/86 |
| 同一线上产物直接修复 | 本地构建后重跑完整公开用例 | 37/86 |
| v9 | 从 ZIP 解包后调用模型重新生成，本地验收 | 57/86 → 74/86 |
| v10 | 从 ZIP 解包后调用模型重新生成，本地验收 | 35/86 → 47/86 |
| v11 | 从最终 ZIP 解包，复放一份此前被启动检查拦截的生成候选，本地验收 | 18/86 → 19/86 → 42/86 |

这些数字来自不同的生成产物或验证方式。v11 的 42/86 是候选复放结果，v11 的新线上提交分数尚未核实。现有记录显示应用能启动与功能通过率需要分别验证。

## 六项任务历史基线

下表是原始 full-track 本地运行记录，用于后续复测对照。当前 Git 仓库的六题整体得分需要用同一提交版本重新评测。

| 任务 | 原始 full-track 本地通过数 |
| --- | ---: |
| 12306 | 83/142 |
| BookStack | 35/35 |
| Ctrip | 93/152 |
| Keep | 32/33 |
| PrestaShop | 64/86 |
| Stack Overflow | 20/66 |

## 复现入口

从 `compiler/` 执行以下命令。将任务目录名改为其他任务即可复测。

```powershell
uv run --locked python main.py ../requirements/arc-bench-web--prestashop --output-dir outputs/prestashop
uv run --locked python -m infrastructure.verify_app ../requirements/arc-bench-web--prestashop outputs/prestashop --report outputs/prestashop/.arc/retest.json
```

已生成应用需要先完成构建，才能单独用 `verify_app` 重跑公开用例。核对编译阶段和验收结果时，分别查看输出目录的 `.arc/compilation.json` 与 `.arc/acceptance.json`。
