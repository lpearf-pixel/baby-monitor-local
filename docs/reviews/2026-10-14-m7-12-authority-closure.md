# M7.12 确认链与权威记录闭环

日期：2026-10-14
基线：`d08d8b15139569b01c9c573bc47484bdce8bc6a9`
分支：`codex/m7-local-llm-parenting-assistant`

## P0/P1 审计结论

`tools/m7_task_eval.py` 的零权威保存来自真实模型任务未完成结束/确认序列，不是
Gateway 模拟器拒绝保存。确定性候选直接通过现有 `M7Orchestrator` → Tool Registry
→ `M6ToolExecutor` → `M7SessionBridge` → 隔离 Gateway，完成混合喂养、结束和明确确认。
模拟 Gateway 仅生成 synthetic session/proposal，不生成权威 ID、签名或数据库事件。

现有确定性回归还覆盖了 proposal 后的修正需重新确认、取消使旧确认失效、重复请求
幂等、上下文过期恢复、网关失败重试、查询只读及直接哺乳不换算毫升。

## 确定性闭环

定向 M6/M7 测试：`63 passed`。

- 母乳 60 ml + 配方奶 30 ml：组件分开保留，确认前无事件，确认后单次 `saved`。
- 相同 request ID 重放：返回既有结果，不重复更新。
- 重复确认：`state_conflict`，保存计数不增加。
- 取消后确认：`state_conflict`，旧 proposal 不能保存。
- 纠错：只替换目标组件，必须重新结束/确认。
- 直接哺乳：只记录 `durationMinutes`，无 `amountMl`。

这部分是内存隔离 Gateway PASS，不是 PostgreSQL PASS。

## 真实模型闭环

沿用 M7.11 真实 Ollama 12 场景：

- Qwen2.5-Coder + C：完整任务 3/12，P50/P95 1096/1534 ms，权威保存 0。
- Qwen3 + semantic_focus：完整任务 6/12，P50/P95 748/1020 ms，权威保存 0。

因此真实模型没有通过完整确认链；没有用自动确认或模拟保存填补结果。

## PostgreSQL 16 阻断

本轮创建了无持久卷 PostgreSQL 16 隔离容器。正式集成命令未能作为合格门禁执行：

- 本机 Node：`v22.23.1`，项目要求 Node `>=24`。
- 首次命令包含 Vitest 不支持的 `--runInBand`，明确失败。
- 去掉该参数后，23 个 Voice Care 集成测试均在 setup 阶段返回 HTTP 500；因此记为
  `POSTGRES_INTEGRATION_BLOCKED`，不是通过或跳过。
- 容器已删除；现有 baby-care 容器未触碰。

历史 Baby Care 234/234、Voice Care v2 27/27 证据保留为历史，不冒充本轮新通过。

## 结论

确定性内存闭环 PASS；真实模型确认链和 Node24/PostgreSQL 隔离验收未通过。保持
`SOFTWARE_RELEASE_CANDIDATE=false`、Camera Reply=false，不部署家庭环境。下一步先
提供 Node24 隔离环境并定位 setup 500，再重新执行 PostgreSQL 门禁；同时继续将真实
模型完整任务成功率作为独立阻断项。
