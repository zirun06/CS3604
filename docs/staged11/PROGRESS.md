# staged-11pass 实施进度

## 第 1 步 · 现场核对与导入清单

核对固定基线、课程契约、阶段产物、模型与进程入口、题目耦合、可迁移机制及上游测试。逐文件导入清单已生成，所有拟写路径都在目标 worktree。

证据见 [BASELINE.md](BASELINE.md)、[import-manifest.json](import-manifest.json)、[upstream-pytest.txt](upstream-pytest.txt)。原版测试已有失败，提交二按实际接口迁移仍适用的断言并保存旧测试。后续仍需实测非空合成需求和工作区提交权限。

## 第 2 步 · 导入及小组适配

导入提交 `6e0296d` 的 156 个上游 blob 经逐文件核验，小组适配单独提交为 `0a8cc05`。恢复小组模板差异，统一模型连接，重锁依赖，把公开套件及旧策略移出运行目录并迁移测试。见 [导入核验](import-result.json)。

两份非空合成输入均走完 11 阶段，见 [产物与哈希](synthetic-evidence.json)。沙箱内 pytest 89 通过、2 跳过，组长在沙箱外独立复核为 90 通过、1 跳过。真实构建、编译后 SQLite 和本机 HTTP 通过，完整 Playwright 未完成。见 [命令记录](COMMANDS.md) 和 [交付总结](SUMMARY.md)。

组长确认可进入第 3 步。此前本节及两份交付文档的中文曾被写成问号，现已用 UTF-8 重写并回读核对。
