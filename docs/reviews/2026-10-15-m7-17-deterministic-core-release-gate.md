# M7.17 确定性核心发布候选验收（2026-10-15）

## 基线与边界

- 分支：`codex/m7-local-llm-parenting-assistant`
- 起始提交：`bcb90f773a0f1aea264217702f1352656f5edf8d`
- Camera Reply=false；未访问家庭音视频、PTZ 或生产 Baby Care 数据库。
- `Interactive`、`test.sh` 保持未跟踪，未修改。

## CI

上次运行 `38566678804` 初始的 `go2rtc-patch` 因 Go 模块下载的瞬时网络错误失败。
按要求只重跑失败 Job；同一运行最终 `contracts=success`、`go2rtc-patch=success`，
状态为 SUCCESS：
https://github.com/lpearf-pixel/baby-monitor-local/actions/runs/38566678804

## 软件证据

| 门禁 | 结果 | 证据 |
|---|---|---|
| UNIT_PASS | PASS | 完整 Python `2619 passed, 1 skipped`；skip 为既有不完整视觉语料 |
| M7/M6 聚焦 | PASS | 相关 Router/Orchestrator/Gateway/Session 测试 `43 passed` |
| Baby Care v2 隔离测试 | PASS | Node24 + pnpm10.17.1 + PostgreSQL16，5 文件 `23/23 passed` |
| CI 必需门禁 | PASS | Actions run 38566678804 重跑成功 |
| OLLAMA_SIMULATED_OUTAGE_PASS | PASS | 受控不可用客户端下，确定性测试不调用 LLM；不可判定输入安全返回不可用/澄清；相关回归包含在 43 项中 |
| REAL_OLLAMA_PASS | NOT_RUN | 本轮未触碰 M3 隧道或真实模型 |
| HARDWARE_ACCEPTANCE | PENDING | 未启用家庭设备 |

## 端到端结论

本轮未能把 M7 `M7BabyCareGateway` 接到一次性 PostgreSQL API 运行实例并执行真实
Text → deterministic routing → M6 → signed Gateway → Baby Care → PostgreSQL 链。
现有 23/23 是 Baby Care 自身隔离 Voice Care 集成门禁；M7 的确定性测试仍使用
Gateway 边界替身，因此不能报告 `POSTGRES_END_TO_END_PASS`。

未形成真实权威记录数量、组件内容或查询一致性证据；不伪造为 PASS。确定性内存链
的已有证据仍显示母乳 60 ml、配方奶修正后 40 ml、重复确认拒绝，但只作为
`UNIT_PASS`/边界证据。

异常矩阵的安全规则由 M6/Gateway 回归覆盖：无草稿、取消/过期/版本不匹配、重复
确认、查询隔离、模糊输入、直接哺乳不换算毫升和失败不返回 saved。数据库故障与
并发确认的 M7→真实 API 证据仍 BLOCKED。

## M8 接口冻结（仅文档契约）

- ASR 输入：短文本、会话身份和单调请求序号；不携带媒体或原始转写持久化。
- M7 输出：`accepted_pending`、`needs_confirmation`、`saved`、`cancelled`、
  `clarification`、`state_conflict`、`temporarily_unavailable`。
- 待确认摘要只由 M6/Gateway 权威状态生成；模型不得生成摘要、签名、ID 或版本。
- 确认必须绑定当前 proposal/version；取消、过期、修改后旧确认失效。
- AudioSink/TTS 失败只返回不可用状态，不改变护理事务结果；摄像头回复仍独立关闭。

## 发布决策

- `DETERMINISTIC_CORE_READY=false`：真实 PostgreSQL 端到端链尚未通过。
- `LLM_ASSISTANT_READY=false`：本轮未做真实 Ollama 验收。
- `SOFTWARE_RELEASE_CANDIDATE=false`。
- 最小后续任务：在不接触生产环境的前提下，补一个真实 M7BabyCareGateway
  到隔离 API/PG 的单次运行器，再复跑相同异常矩阵；不新增状态机或模型实验。
