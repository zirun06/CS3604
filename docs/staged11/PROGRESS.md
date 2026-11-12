# staged-11pass 实施进度

## 第 1 步 · 现场核对与导入清单

核对固定基线、课程契约、阶段产物、模型与进程入口、题目耦合、可迁移机制及上游测试。逐文件导入清单已生成，所有拟写路径都在目标 worktree。

证据见 [BASELINE.md](BASELINE.md)、[import-manifest.json](import-manifest.json)、[upstream-pytest.txt](upstream-pytest.txt)。原版测试已有失败，提交二按实际接口迁移仍适用的断言并保存旧测试。后续仍需实测非空合成需求和工作区提交权限。

## 第 2 步 · 导入及小组适配

导入提交 `6e0296d` 的 156 个上游 blob 经逐文件核验，小组适配单独提交为 `0a8cc05`。恢复小组模板差异，统一模型连接，重锁依赖，把公开套件及旧策略移出运行目录并迁移测试。见 [导入核验](import-result.json)。

两份非空合成输入均走完 11 阶段，见 [产物与哈希](synthetic-evidence.json)。沙箱内 pytest 89 通过、2 跳过，组长在沙箱外独立复核为 90 通过、1 跳过。真实构建、编译后 SQLite 和本机 HTTP 通过，完整 Playwright 未完成。见 [命令记录](COMMANDS.md) 和 [交付总结](SUMMARY.md)。

组长确认可进入第 3 步。此前本节及两份交付文档的中文曾被写成问号，现已用 UTF-8 重写并回读核对。

## 第 3 步 · 全局预算、反馈统计和安全续跑

接通四项可配置预算，覆盖 native 请求、视觉并发、SDK/兼容重试和本地进程。新增逐次验证反馈、测试生成/复核成本归属和阶段首反馈。输出身份和检查点来源验证已用真实临时 Git 仓库测试。

离线回归 114 通过、1 跳过、1 未选择。补测最终验证时间预留的相关套件 36 通过。两种续跑的 schema 字节一致，预算停止后报告非 GREEN，产物保留。无真实模型请求。详情见 [第 3 步记录](STEP3.md) 和 [离线证据](step3-evidence.json)。

本轮结束于第 3 步。真实 Windows 进程清理、数据库重启及完整 Playwright 留待沙箱外复验，执行目录和命令见第 3 步记录。


## 第 4a 步前置修复：合成夹具和 Node 预检

- 08 和 10 的合成页面都保留 `UI-count` 根与 `UI-button`。10 的端到端测试点击按钮、等待 `/api/note-count` 返回 HTTP 200，并确认状态从 Ready 变成 0。mock 编辑识别已经应用的内容，避免重放失效的旧文本。
- 编译开始记录 `node --version`；模板依赖不兼容时写入 `compiler.log` 和 `.arc/compilation.json` 的 `node_preflight.warning`，不中止。
- 替换本地检查（`STAGED11_REAL_CHECKS=0`）：`tests/test_staged_pipeline.py` 5 通过、退出码 0；两份合成输入均断言 11 阶段 GREEN。
- 真实检查：组长报告修复前 Node 22 下 08、10 失败；修复后未在沙箱内运行。请在 `compiler/` 用 PowerShell 执行：

  ```powershell
  $env:PATH = (Resolve-Path 'outputs/node22/node_modules/node/bin').Path + ';' + $env:PATH
  node --version
  $env:STAGED11_REAL_CHECKS = '1'
  uv run --locked --with pytest==9.2.0 python -m pytest -p no:cacheprovider -q tests/test_staged_pipeline.py -k original
  ```

  真实检查仍使用 mock 模型。移除 `-k original` 可复验两份合成输入。


## 第 4a 步：五个设计阶段分批

- 02、03、05、07、09 接入同一规划器和批次执行器。保留原产物及逐条校验；04、06、08、10 的调用粒度不变。弃用的单叶 agent 执行代码移除，继续复用原有数据库字段校验、后端契约及逐条设计校验。
- 六份 YAML 的叶子、场景、步骤已独立核验集合一致且没有重复。离线清单、旧／新调用估算与路径见 [STEP4A.md](STEP4A.md)。
- 多叶子用例走完 11 个阶段；02 的截断拆批和 03、05、07、09 的同批调用可查 [step4a-mock.json](step4a-mock.json)。`compiler/tests/test_design_batches.py` 覆盖过大输入、逐条后端校验与跨模块共享约定。
- 替换本地检查的全量回归（`-k 'not timeout_stops_descendants'`）退出码 0：123 通过、1 跳过、1 未选择，另有 38 个子测试通过。跳过项需要 `ARC_DB_TEST_NODE_MODULES`；未选择项是沙箱内的 Windows 进程树检查。
- 未运行真实 Node／SQLite／Chromium 合成复验；命令见前置修复记录。未调用模型 API，未做 4b。
- 清理弃用代码后，最终针对 `test_design_batches.py` 与 `test_staged_pipeline.py` 的复跑为 10 通过、退出码 0。六份规划在独立目录重生成，哈希逐份一致。实际运行命令见 [STEP4A.md](STEP4A.md)。
