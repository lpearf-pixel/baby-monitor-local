# M7.18 真实 Gateway 集成收口（2026-10-15）

## 调用链审查

当前真实业务边界为：

`M7Orchestrator -> M6ToolExecutor -> M7SessionBridge -> M6SessionGateway`

`M7BabyCareGateway` 实现了 v2 envelope、设备签名、lease、session/version、proposalDigest、
幂等 requestId 和响应 code 校验；`V2VoiceCareGateway` 已限制 schemaVersion=2。
但是当前 M7 Python 测试入口没有 HTTP transport、隔离 Baby Care API 启动器或 PostgreSQL
连接配置。现有测试中的 Gateway 是内存协议替身，不能证明真实 API 写入。

Baby Care 仓库已有独立的 Node24/pnpm10.17.1/PostgreSQL16 Voice Care 集成测试，但该测试
直接在 Baby Care app.inject/服务边界内运行，没有从 M7 文本入口进入 `M7BabyCareGateway`。
因此本轮不把两者拼接为虚假的端到端 PASS，也没有修改生产 API、数据库或协议。

## 本轮验证

- 远端与本地基线：`fa804569d2d4e680034265d8113b173a1d20ff86`。
- M7/M6/Gateway/session 聚焦回归：`43 passed`。
- 已有完整 Python 门禁：`2619 passed, 1 skipped`；skip 为既有视觉语料不完整。
- Baby Care 独立 Node24 + pnpm10.17.1 + PostgreSQL16 Voice Care 门禁：`23/23 passed`。
- CI `38627307582`：SUCCESS。
- 真实 M7→HTTP API→PostgreSQL：`BLOCKED`，没有可执行 Runner，未声称保存。

## 业务安全结论

内存边界测试仍覆盖母乳 60 ml、配方奶修正为 40 ml、proposal/version 校验和重复确认
拒绝；这不是权威持久化证据。取消、过期、版本冲突、并发确认、事务失败和查询只读的
真实数据库效果本轮均未重新宣称通过。

## 最小后续实现

新增一个仅面向一次性隔离环境的 Runner：由 Node24 启动 Baby Care API，明确随机端口、
临时 PostgreSQL16 数据库和合成设备/lease 身份；M7 通过 HTTP transport 调用现有
`M7BabyCareGateway`，再以权威查询验证记录。Runner 必须拒绝生产 URL/非临时数据库，
完成后清理所有资源。不得新增状态机、Mock 持久化或自动确认。

## 状态

- `POSTGRES_END_TO_END_PASS=false`（本轮未通过，状态为 BLOCKED）。
- `DETERMINISTIC_CORE_READY=false`。
- `LLM_ASSISTANT_READY=false`。
- `SOFTWARE_RELEASE_CANDIDATE=false`。
- Camera Reply=false，家庭硬件验收仍挂起。
