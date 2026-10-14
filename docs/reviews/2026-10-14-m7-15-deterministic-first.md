# M7.15 确定性优先快速通道

基线：`4cf8c304d9aeab03266cf7d88546d118d6612160`

## 设计与范围

在已有 opt-in `sensitive_routing` 之上新增 `deterministic_routing`，默认关闭。
它复用 `parse_m6_utterance`，只把完整、单一、无引用/否定/模糊词的受限语法转换
为 `M7ToolCall`：开始、结束、明确奶种+数量、亲喂时长、明确纠错和当前草稿查询。
确认/取消继续经过敏感路由；追加、总量表达、多组件一句话、模糊数量、引用和
否定不猜测，交给现有 LLM 或澄清。所有候选仍经过 Tool Registry、M6 和 Gateway。

没有新状态机、Schema 或权威字段；默认 C 模式不变。

## 验证

- 快速通道、敏感路由和现有 M7 工具：**28 passed**
- 完整 Python：**2617 passed, 1 expected visual-corpus skip**，277.47s
- `py_compile`、`git diff --check`：通过
- PostgreSQL 16 与 Voice Care v2：沿用 M7.13 新鲜证据（23/23），本轮未改数据库层
- 双仓库 consumer-contract：沿用 M7.14 新鲜证据（4/4）

快速通道覆盖率只针对明确固定语法，不能代表自然语言总体准确率。此前真实模型
12 任务结果仍为 Qwen2.5 C 3/12、Qwen3 focus 6/12；本轮没有用自动确认或扩大
拒绝范围重算模型成绩。

结论：确定性优先架构值得作为 opt-in 实验继续，但尚未完成新的 A/B/C 隔离端到端
量化，因此不切换默认路径，`SOFTWARE_RELEASE_CANDIDATE=false`。
