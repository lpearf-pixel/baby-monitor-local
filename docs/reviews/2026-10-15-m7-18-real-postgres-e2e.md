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

## 实际 Runner（本轮实现）

Runner 文件：`tools/m7_real_gateway_e2e.py`，API Harness：`tools/m7_baby_care_harness.mjs`。
执行命令：`.venv-alpha/bin/python tools/m7_real_gateway_e2e.py`（本轮因安全矩阵未闭合
退出码为 1；输出仍包含每个隔离场景的脱敏结果）。

Runner 自动创建临时 PostgreSQL16 容器和 Node24/pnpm10.17.1 API 容器，随机映射 HTTP
端口，生成临时 Ed25519 身份/lease，调用真实 `M7BabyCareGateway` HTTP transport，
并用容器内 `psql` 查询权威数据。所有容器在退出时清理。

PostgreSQL 端口同样使用随机宿主端口，并绑定 `127.0.0.1`；API 容器通过
`host.docker.internal` 访问该端口。Runner 不接受固定生产地址或外部数据库标识。
M7 确认所需的 phase/proposal presence 来自 M6 Coordinator snapshot，不再由测试
手动伪造有效确认状态。

固定链和安全矩阵实际输出：

```text
RUNNER_EXECUTED=true
POSTGRES_END_TO_END_PASS=true
SAFETY_MATRIX_PASS=false
authority_records_before=0
authority_records_after=1
components=expressed_breast_milk:60, formula:40
duplicate_result=state_conflict
no_draft_confirm=state_conflict
cancel_result=accepted_pending
cancel_then_confirm=state_conflict
authority_records_after_safety=1
llm_calls=0
bad_identity_result=temporarily_unavailable
gateway_unavailable_result=temporarily_unavailable
concurrent_codes=temporarily_unavailable,saved
concurrent_authority_records=2
rollback_result=temporarily_unavailable
rollback_count=2
rollback_recovery=saved
rollback_recovered_count=3
tampered_digest_result=rejected
old_version_result=rejected
tamper_authority_records=3
response_lost_result=temporarily_unavailable
response_lost_authority_records=4
same_request_replay=temporarily_unavailable
replay_authority_records=4
expired_result=state_conflict
expired_authority_records=4
```

并发场景一请求 `saved`、另一请求为既有 `temporarily_unavailable`，权威记录只增加一条；
事务触发器导致失败事务无记录，解除故障后同一草稿安全恢复；错误 digest/旧版本、过期
确认、错误身份和不可达 Gateway 均未增加记录。服务器已提交但客户端丢响应的场景也只
产生一条记录，但用原 requestId 重放返回 `temporarily_unavailable`，没有返回原来的
`saved` 权威结果。这是当前真实跨仓库幂等恢复阻断，不能用“记录已存在”冒充协议闭环。

## 状态

- `RUNNER_IMPLEMENTED=true`。
- `RUNNER_EXECUTED=true`。
- `POSTGRES_END_TO_END_PASS=true`（固定混合喂养链）。
- `SAFETY_MATRIX_PASS=false`（除响应丢失后的原 requestId 重放恢复外，其余本轮场景均通过 fail-closed 断言）。
- `DETERMINISTIC_CORE_READY=false`（幂等恢复契约仍未闭合）。
- `LLM_ASSISTANT_READY=false`。
- `SOFTWARE_RELEASE_CANDIDATE=false`。
- Camera Reply=false，家庭硬件验收仍挂起。
