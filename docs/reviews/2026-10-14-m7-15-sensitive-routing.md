# M7.15 敏感确认/取消确定性路由

基线：`4cf8c304d9aeab03266cf7d88546d118d6612160`

## 实施

新增 opt-in `sensitive_routing`，默认仍为 `false`。路由只接受无引用、无冲突、
完整的明确表达：当前草稿确认、当前草稿取消/拒绝保存，以及明确结束护理。
确认必须同时满足 `phase=needs_confirmation` 和当前 proposal 标识；没有有效草稿、
草稿被修改/取消/过期时不调用 executor。含糊的“嗯/行/好了”、引用的确认句、
查询、纠错及多意图冲突继续走原有 LLM 安全路径或澄清。

变更文件：

- `services/voice/m7_sensitive_router.py`
- `services/voice/m7_orchestrator.py`
- `tests/voice/test_m7_sensitive_router.py`

## 验证

- 新增/相关聚焦测试：24 passed
- M7/M6 扩展回归：70 passed
- 完整 Python：**2613 passed, 1 expected visual-corpus skip**，274.46s
- `py_compile`：通过
- `git diff --check`：通过

真实 Ollama 合成探针（不保存模型原文）显示：Qwen2.5-Coder+C 有确认/取消混淆
和短句超时；Qwen3+`semantic_focus` 仍有结束/确认边界混淆。确定性路由只负责
明确表达识别，所有执行仍经过 Tool Registry、M6 和 Gateway；本轮未改变默认 C、
未自动确认、未写入生产数据库。

结论：敏感路由具备安全拦截证据，但尚无足够证据证明端到端模型任务成功率已达
发布目标，因此不升级为默认路径，`SOFTWARE_RELEASE_CANDIDATE=false`。
