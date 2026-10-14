# M7.15 最终验收与 M7.16 架构决策准备

## 基线与环境

- 分支：`codex/m7-local-llm-parenting-assistant`
- 本轮代码基线：`193f167f24a7ea4f42a8a237f6fbfd7acef000d9`
- 本轮候选提交：待提交
- A：Qwen2.5-Coder 7B + C
- B：Qwen3 4B + `semantic_focus`
- C：确定性快速通道 + 受限 LLM 回退，`deterministic_routing=true`、`sensitive_routing=true`
- Camera Reply：false

Git fetch 在当前执行器因 `.git/FETCH_HEAD` 权限错误未能更新；现有远端跟踪分支与
本地基线一致，未发现远端新提交。未跟踪 `Interactive`、`test.sh` 保留。

## 固定任务集

新增冻结 fixture：`tests/fixtures/m7_architecture_matrix_v1.json`，20 条合成任务，
覆盖开始、单组件、混合组件、亲喂、纠错、结束、确认、取消、查询、模糊表达、否定/引用、
超时、Gateway 不可用、过期草稿和重复确认。A/B/C 的模型、提示词及两个路由开关均
显式记录；未根据模型结果修改题目或评分规则。

## 本轮证据

| 项目 | 结果 |
|---|---|
| 快速通道/敏感路由聚焦回归 | 29 passed |
| Python 全量 | 2618 passed，1 expected visual-corpus skip |
| PostgreSQL 16 v2 集成 | 23/23，沿用 M7.13 新鲜证据 |
| 双仓库 consumer-contract | 4/4，沿用 M7.14 新鲜证据 |
| A/B/C 20-task 真实 PG 对照 | NOT_RUN，本轮不重复大规模模型负载 |

历史真实模型结果仅作为背景：A 完成 3/12，B 完成 6/12，均为零权威保存；不可与
本轮 C 的单元回归直接宣称优胜。C 尚无新的真实 PostgreSQL 20-task 量化结果。

## 安全与竞态审查

FakeExecutor 已按 M6 语义返回 accepted_pending、needs_confirmation、saved、cancelled、
query_result 和 state_conflict。路由层不执行写入，Orchestrator 只提交经 Registry
校验的候选；proposal/phase 校验拒绝无草稿确认。草稿修改、取消、过期、重复确认和
最终 Gateway 权威校验继续由 M6/Gateway 负责，未创建第二状态机。

## 架构决策

确定性优先方案降低固定语法的模型依赖和延迟，并保留 LLM 处理非固定表达；但目前
只有软件回归和历史模型证据，缺少 C 在冻结 20-task + 隔离 PostgreSQL 的新鲜 A/B/C
对照。因此建议 M7.16：先运行一次固定任务集的隔离对照，记录 LLM 调用比例、P50/P95、
错误确认/取消和权威保存，再决定是否冻结 C 为默认。当前不得切换默认路径，
`SOFTWARE_RELEASE_CANDIDATE=false`。
