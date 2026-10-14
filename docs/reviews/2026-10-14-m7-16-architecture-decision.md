# M7.16 确定性优先架构决策（2026-10-14）

## 范围与环境

本轮以 `2df8a89` 为起点，冻结 20 条合成护理任务矩阵，不修改原有输入或评分标准。
补充了每项任务的 M6 初始阶段、组件、proposal/version、合成照护人、时间/过期条件、
期望工具、数据库结果和禁止副作用。`Interactive`、`test.sh` 及家庭运行配置未纳入提交。

代码复核删除了 Router 中无效的重复草稿判断；测试 FakeExecutor 的结果码改为匹配
M6 语义。新增的确定性链测试经过 `M7Orchestrator -> M6ToolExecutor -> M7SessionBridge`
和 Gateway 边界，未把单独返回 `saved` 的替身测试当作持久化证据。

约束：Camera Reply=false；不访问家庭音视频、PTZ、Guardian、SSH 隧道或生产 Baby Care
数据库。

## 确定性链结果

合成混合喂养链：开始 → 母乳 60 ml → 配方奶 30 ml → 配方奶修正为 40 ml → 结束 →
确认 → 重复确认 → 查询。M6 执行器/Gateway 边界测试通过；最终草稿保留两个独立组件
（母乳 60、配方奶 40），第二次确认返回 `state_conflict`，权威事件计数为 1。
该证据是内存 Gateway 边界证据，不等同于真实 PostgreSQL 保存。

## 隔离 PostgreSQL 16

使用临时命名容器、全新数据库、Node 24、pnpm 10.17.1 和 baby-care
`cb9a86f3e4c83b637e331b30e0bbf8bdde938891` 检出，未连接现有容器或生产数据库。

命令实际结果：5 个集成测试文件、23/23 通过（Vitest 4.1.10，34.30 秒），覆盖 v2
事务、确认、幂等、回滚及跨产品 Voice Care 路径。容器和临时工作目录在退出时清理。

## A/B/C 模型比较

本轮没有重新运行 20 条真实模型矩阵：模型健康检查/完整批量运行未在本轮形成新的可复现
证据，因此不能把历史 12 条探针外推为 M7.16 的 20-task 成绩，也没有用 Mock 结果填充。

| 指标 | A Qwen2.5+C | B Qwen3+semantic_focus | C 确定性+受限回退 |
|---|---:|---:|---:|
| 20-task 完整成功率 | NOT_RUN | NOT_RUN | NOT_RUN |
| PostgreSQL 持久化 | NOT_RUN | NOT_RUN | NOT_RUN |
| 错误权威保存/重复保存 | 0* | 0* | 0（确定性内存链） |
| P50/P95 | NOT_RUN | NOT_RUN | NOT_RUN |

`*` 仅表示历史模型探针没有产生权威保存，不是本轮 20-task 验收成绩。历史诊断为
Qwen2.5+C 3/12、Qwen3 6/12，不能与本轮矩阵直接比较。

## 架构结论

- 确定性快速通道对明确、低歧义的固定护理表达可复用现有 M6 解析器，并保留
  Tool Registry、M6 和 Gateway 安全门。
- 含糊数量、引用/否定、多意图、模型不可用和复杂查询必须澄清或走受限回退；
  不应继续堆叠关键词规则。
- 本轮没有新的 A/B/C 公平 20-task 证据，不能证明 C 相对 A/B 的实质收益，也不能
  冻结为默认路径。
- M7 软件发布候选继续为 `false`。M8 入口条件是一次不调参的、真实 Ollama
  可复现的 20-task A/B/C 对照，加上同一隔离 PostgreSQL 证据；在此之前 C 只保持
  opt-in，默认仍为 Qwen2.5-Coder + C。

## 验证摘要

- 聚焦 Python：30 passed。
- 隔离 PostgreSQL/Voice Care：23 passed / 23。
- `git diff --check`、变更 Python 编译检查：待提交前执行。
- 家庭硬件验收、真实语音播放和生产数据库：未执行。
