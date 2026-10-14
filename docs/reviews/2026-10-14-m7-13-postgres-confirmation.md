# M7.13 PostgreSQL 门禁与 LLM 确认链专项

日期：2026-10-14
baby-monitor-local：`d1579de0ba0027e6f1f7d4dabea2f69ab8e212c6`
baby-care：`cb9a86f3e4c83b637e331b30e0bbf8bdde938891`
Camera Reply：`false`

## P0：隔离 PostgreSQL 16

在全新临时 PostgreSQL 16 容器和 `node:24-bookworm-slim` 中使用 Node 24、pnpm
10.17.1、全新数据库和合成身份运行；已有 Baby Care、Guardian 容器未停止或修改。

五个 M7 相关集成文件（v2 integration、cross-product、session、contract、promotion）
通过 **5 files / 23 passed**，覆盖签名、设备、Lease、事务、混合喂养 60 ml 母乳 +
30 ml 配方奶、直接哺乳时长、幂等、取消、撤销和失败回滚。确认前没有权威记录，
确认后仅产生一条权威记录。

旧的 23 个 setup HTTP 500 的根因是运行环境使用 Node 22.23.1，而当前 Baby Care
门禁要求 Node 24；不是通过改断言或跳过测试解决。切换到 Node 24 后，上述 23 项
全部通过。

Baby Care API 全量在相同 Node24/PG16 隔离方式下，排除一个需要同时读取
baby-monitor-local tracked artifact 的跨仓库 consumer-contract 文件后为
**50 files / 230 passed**。完整 API 运行的 4 个失败均集中在该 artifact-contract：
它需要双仓库 checkout 的字节一致、source identity、symlink 和 untracked-artifact
场景；单独 baby-care archive 不能满足该跨仓库前置条件。这四项不是 PostgreSQL
迁移或业务 API 失败，仍应在双仓库工作区门禁中执行，不能标为 API 全量通过。

## P1：确认链证据

现有真实 Ollama 12 场景证据保持不变，未重复家庭或模型负载：Qwen2.5-Coder+C
完成 3/12，Qwen3+`semantic_focus` 完成 6/12；两者均为 **0 authoritative saves**。
失败发生在模型候选/工具路由/结束提案之前或确认序列未完成，不能将模型自然语言
回复当作已保存。确定性 M6/M7 流程的独立回归为 **63 passed**，覆盖结束提案先于
确认、可信草稿摘要、单次保存、重复确认冲突、取消失效、修改后重新确认、查询只读
和直接哺乳时长不换算毫升数。

因此本轮没有新增语义后门或模型修复。内存合成 Gateway 的安全证据不能替代
PostgreSQL 权威保存；两种真实模型仍未达到发布目标。

## 状态与后续

- `POSTGRES_INTEGRATION_PASS=YES`：23/23 v2 集成和 230/230 非 artifact API 测试。
- `POSTGRES_API_FULL_PASS=NO`：4 个跨仓库 consumer-contract 前置失败待双仓库门禁重跑。
- `LIVE_MODEL_EVALUATED=YES`，但确认链未完成，不能宣称端到端保存通过。
- `SOFTWARE_RELEASE_CANDIDATE=false`，`HARDWARE_ACCEPTANCE_PENDING`。
- 下一步仅在双仓库工作区重跑 consumer-contract，并重新执行 Baby Care API 全量门禁；
  不得连接生产数据库或家庭设备。
