# M7.11 端到端护理任务可靠性验收

日期：2026-10-14
基线：`eacddd9d749539c4728319f4c97ff0cbcc92965b`
分支：`codex/m7-local-llm-parenting-assistant`

## 环境

- CI `38498636776`：success，HEAD `eacddd9d749539c4728319f4c97ff0cbcc92965b`。
- Ollama `0.32.11`，通过 `127.0.0.1:11435` 可达。
- Qwen2.5-Coder digest：`dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364`。
- Qwen3 digest：`0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`。
- 测试使用合成文本与内存隔离 Gateway；未连接 Baby Care 生产数据库、家庭音视频或硬件。

## 任务评测器

新增 `tools/m7_task_eval.py`，通过真实 `OllamaLanguageClient`、现有 `M7Orchestrator`、Tool Registry、M6 Coordinator 和合成 Gateway 运行 12 个任务场景。只输出聚合字段，不保存模型原文。覆盖开始、单组件、混合喂养、纠错、结束、确认、重复确认、取消、澄清、查询和直接哺乳。

真实模型结果：

| 方案 | 完整任务 | 完成率 | failed | rejected | P50/P95 (ms) | 权威保存 |
|---|---:|---:|---:|---:|---:|---:|
| Qwen2.5-Coder 7B + C | 3/12 | 25.0% | 6 | 14 | 1096/1534 | 0 |
| Qwen3 4B + semantic_focus | 6/12 | 50.0% | 0 | 8 | 748/1020 | 0 |

这只是 12 个合成任务的实时模型对照，不是发布级准确率，也不是 Baby Care 数据库验收。两组均未产生权威保存，因为模型没有稳定完成完整确认链；没有重复权威事件。`private_text_persisted=false`。

## 安全结论

- Tool Registry、M6 Coordinator 和 Gateway 仍是唯一执行边界。
- 查询走只读查询客户端；查询不调用 Gateway 写入。
- 取消和重复确认受状态机约束；重复确认返回 `state_conflict`。
- 未明确奶量进入澄清；直接哺乳只保留时长，禁止换算毫升。
- 本轮未重新执行 PostgreSQL 16、Baby Care API 234/234 或 Voice Care v2 27/27；这些仍是历史隔离证据，不得当作本轮新通过。

## 结论

Qwen3 在本轮小样本任务完成率和延迟上优于 Qwen2.5-Coder，但样本量不足、权威保存链未完成，且既有 200 条独立语义集仍低于 95%/99%目标。保持 Qwen2.5-Coder + C 为默认，Qwen3 仅实验；`SOFTWARE_RELEASE_CANDIDATE=false`，不得部署家庭设备。
