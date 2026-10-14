# M7.10 高频失败修复与安全闭环

日期：2026-10-14
分支：`codex/m7-local-llm-parenting-assistant`
基线：`ebe3803654533e1b3d3900494547ff9bf9919a14`

## P0 基线

- 当前默认路径仍为 Qwen2.5-Coder 7B + C；Qwen3 `semantic_focus` 仅为实验路径。
- CI `38492116973`：success，HEAD `e4c6a324365672175c0edbe8b7994bdd119e852e`。
- Qwen2.5-Coder digest：`dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364`。
- Qwen3 digest：`0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`。
- Camera Reply=false；未访问家庭音视频、生产数据库或硬件。

## P1 失败簇与修复

M7.9 固定 168 条记录了 27 次 Tool Registry rejection、4 次确认/取消意图不匹配；独立 200 条记录了 15/80 明确奶量错误与 48/200 意图错误。集合可能重叠，未相加。

本轮证据支持的缺陷是确定性层缺少意图—工具族一致性校验。`validate_candidate` 现在使用闭合映射：查询只能路由只读工具，确认/取消只能路由其对应工具族，feeding update 只能追加或纠错；未知意图或跨族组合返回 `intent_tool_mismatch`，不进入 executor。模型输出、Schema 合法与业务语义正确仍分别统计，模型失败不被此修复掩盖。

## P2 安全回归

新增回归覆盖：

- `feeding_query` + `add_feeding_component` 被拒绝；executor 调用数为零。
- `care_confirm` + 写入工具、`care_cancel` + confirm、`feeding_update` + 查询工具均被拒绝。
- 明确取消继续使用快速路径；已保存草稿的重复确认返回 `state_conflict`，不会新增权威事件。
- 混合喂养 60 ml 母乳 + 30 ml 配方奶，纠正配方奶为 40 ml 后，结束、明确确认只产生一次保存；组件不合并。
- 直接哺乳只保留时长字段；查询和歧义路径不构造写入候选。

## 验证

- 聚焦 M7：`17 passed`（orchestrator + tools），随后完整 M7 聚焦：`50 passed`。
- 独立 200 条历史证据：意图 `152/200`，明确奶量 `65/80`，工具合法 `154/200`，P50/P95/max `1038/1601/1715 ms`；Wilson 95% 区间分别为 69.63–81.39%、71.34–88.29%、70.69–82.29%。这不是本轮重新调参后的盲测，仍低于发布目标。
- 固定 168 条历史证据：意图 `144/168`，工具合法 `140/168`；其中 27 个拒绝和 4 个确认/取消不匹配已作为本轮缺陷输入。
- Baby Care 隔离 PostgreSQL 234/234、Voice Care v2 27/27 为历史证据，本轮未重跑生产或隔离数据库。
- Camera Reply=false；没有改变 M6/Gateway 契约、SSH、Guardian、go2rtc 或默认 C 路径。

## 结论

本轮关闭了确定性工具路由安全缺口，并证明模型/业务闭环仍未达到 95% 意图与 99% 明确奶量目标。`SOFTWARE_RELEASE_CANDIDATE=false`，不得部署家庭环境。下一步应在不调 holdout 的前提下继续分析模型语义失败；不得通过放宽 Registry、确认或奶量校验提高指标。
