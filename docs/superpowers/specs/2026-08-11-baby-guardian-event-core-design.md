# Baby 守护事件核心设计

**日期：** 2026-08-11

**状态：** 已批准，进入实施

**上位规格：** `2026-08-04-baby-monitor-local-design.md`、`2026-08-05-visual-risk-core-design.md`

## 1. 目标与范围

本切片把现有 `VisualRiskStateMachine` 产生的确定性 `RiskTransition`
接入本地持久化和可诊断日志，使遮脸、趴睡和离床候选第一次具备重启可恢复的
事件身份。它不改变模型、置信度、10 秒确认/恢复规则、实时 FPS 或摄像头链路。

本切片包含：风险事件打开与恢复、成人介入审计、打开事件恢复、按事件查询、
结构化日志和生产 worker 接线。本切片不包含截图、短片、ntfy 风险通知、
Dashboard、家长确认或误报反馈；这些后续都引用本切片生成的 `event_id`。

## 2. 方案选择

采用独立的视觉风险生命周期表，并与现有通用 `events.sqlite3` 数据库共存。
不把生命周期塞入自由格式 `metadata_json`，也不创建第二个事件数据库。

- `visual_risk_events` 保存一个风险从打开到恢复的稳定记录；同一风险最多一个
  打开事件。
- `visual_interventions` 保存成人介入，即使当时没有打开风险也保留。
- `visual_risk_interventions` 把一次介入关联到当时所有打开风险。
- 现有 `events` 与 `event_acknowledgements` 不在本切片迁移；家长确认阶段将以
  `visual_risk_events.event_id` 建立专用确认表，避免破坏旧数据契约。

## 3. 输入与状态映射

唯一输入是已由风险状态机验证的 `RiskTransition`：

| 转换 | 持久化行为 | 日志行为 |
|---|---|---|
| `watch_started` | 不写长期事件 | `guardian.transition_observed` |
| `watch_cleared` | 不写长期事件 | `guardian.transition_observed` |
| `alert_opened` | 原子创建或返回同类现有打开事件 | observed + `guardian.event_opened` |
| `recovered` | 原子关闭同类打开事件；无打开事件时安全忽略 | observed + recovered/ignored |
| `adult_intervention` | 幂等保存介入并关联所有打开事件 | observed + `guardian.intervention_recorded` |

事件 ID 使用随机 UUID，不包含时间、摄像头、宝宝或家庭标识。介入 ID 从固定的
规则版本、转换种类和观察时间生成稳定 SHA-256 摘要，使同一回调重放保持幂等。

## 4. 数据契约

`StoredVisualRiskEvent` 是严格、不可变契约，字段为：

- `event_id`
- `risk_kind`: `face_not_visible | prone_candidate | outside_candidate`
- `state`: `open | recovered`
- `severity`: 固定为 `high`
- `opened_at`、`updated_at`、可空 `recovered_at`
- `confidence`
- `rule_version`
- `adult_intervention_count`

时间必须带时区；恢复时间不得早于打开时间；打开事件不得包含恢复时间。
SQLite migration 必须可重复执行，启用 foreign keys，并提供完整性检查。

## 5. 重启恢复

启动时先迁移数据库，再读取所有打开事件并构造 `RiskSnapshot`。风险状态机仅恢复
打开风险，候选计数和恢复计数仍按既有规则清零。数据库若有同一风险多个打开事件，
唯一索引会拒绝产生该状态；启动读取也拒绝未知风险类型。

## 6. 结构化日志

日志写到 worker 的 stderr，由 launchd 现有日志文件收集。每行是紧凑 JSON，
固定包含：

- `schema_version=1`
- `component="baby_guardian"`
- `code`
- `observed_at`
- 允许时包含 `event_id`、`risk_kind`、`transition_kind`、`state`、
  `rule_version`、`result`

禁止记录模型原文、reason codes、图像、视频、文件路径、异常文本、token、URL、
摄像头标识、私网地址或家庭标识。日志输出失败不得反向中断 worker。

## 7. 故障与隔离

- 数据库写入失败：输出 `guardian.persistence_failed`，不抛出到视觉 worker；
  后续同类转换仍可再次尝试。
- 日志写入失败：吞掉日志异常，不改变数据库结果。
- 重复 `alert_opened`：返回现有打开事件，不创建第二条。
- 无打开事件的 `recovered`：不伪造历史，输出脱敏 ignored 日志。
- 时间倒退或非法契约：由严格契约/存储拒绝，生产管道转换为脱敏失败日志。

## 8. 验证与后续接口

合成测试覆盖 migration、打开、恢复、三类风险独立、重复回调、成人介入关联、
无风险介入、重启快照、数据库故障隔离、日志字段 allowlist 和生产接线。
不使用家庭媒体或真实标识。

后续切片依次消费同一 `event_id`：事件截图/短片 → ntfy → Dashboard 查询与两位
家长确认/误报 → 统一 macOS 验收脚本与诊断包。性能门和声音识别继续后排。
