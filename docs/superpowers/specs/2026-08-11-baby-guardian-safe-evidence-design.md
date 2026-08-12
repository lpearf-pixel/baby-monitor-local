# Baby 守护安全证据设计

**日期：** 2026-08-11

**状态：** 已批准，进入实施

**上位规格：** `2026-08-11-baby-guardian-event-core-design.md`

## 1. 目标与范围

本切片为已确认的 Baby 风险事件保存可回看的本地证据：一张事件截图，以及由
隐私处理后安全帧生成的低帧率动画 WebP。先完成方案 A；以后方案 B 可用独立的
FFmpeg 原始视频环形缓存替换短片生成器，但必须继续使用本切片的事件 ID、证据
状态和查询契约。

本切片不发送通知、不新增 Dashboard 页面、不保存普通全天录像、不处理声音、
不改变模型、风险规则、实时 FPS 或 i9 服务。

## 2. 输入和时间窗

唯一媒体输入是 `VisionFramePolicy` 已完成床区裁剪、隐私遮罩、缩放和大小限制的
`PreparedAnalysisFrame`。原始摄像头帧不得进入证据组件。

- `alert_opened` 创建新事件时立即锁定打开时刻前 10 秒内的安全帧。
- 以最接近事件打开时刻且不晚于该时刻的安全帧生成 JPEG 截图。
- 打开后继续收集安全帧，直至至少覆盖 30 秒或进程关闭。
- 帧环仍保持每 2 秒最多一帧、40 秒和 21 帧上限；证据采集器每个活动事件最多
  保留 21 帧。三个风险同时打开时最多 63 帧，不建立无界队列。
- 没有可用截图帧时事件仍然有效，证据状态记为 `failed`，使用固定失败码。

## 3. 证据格式与存储边界

截图保存为质量受控 JPEG。短片保存为动画 WebP，帧持续时间固定为 2000ms，循环
播放，使用 Pillow 编码；它可直接由现代浏览器显示且无需 FFmpeg。文件只位于
配置的 `data_dir/guardian-evidence` 下。

事件 ID 不直接作为目录名。目录键为 `sha256(event_id)` 的十六进制摘要：

- `<digest>/snapshot.jpg`
- `<digest>/clip.webp`

写入先落同目录临时文件、`fsync` 后原子替换；目录权限为 `0700`，文件权限为
`0600`。数据库只保存上述相对键，不保存绝对路径。日志不得输出相对键、摘要、
绝对路径、图片内容或底层异常文本。

## 4. 数据契约

在现有 `events.sqlite3` 新增 `visual_risk_evidence`，每个风险事件最多一行：

- `event_id`：外键关联 `visual_risk_events`
- `state`：`collecting | ready | failed | interrupted`
- `started_at`、`updated_at`：带时区
- `capture_deadline`：`started_at + 30 seconds`
- `snapshot_key`、`clip_key`：可空、严格相对键
- `frame_count`：非负且不超过 21
- `failure_code`：仅允许固定值或空

迁移可重复执行。打开同一事件的重复回调返回现有证据记录，不重新覆盖文件。
worker 启动时把遗留的 `collecting` 记录改为 `interrupted`，避免把重启前未完成的
短片展示为完整证据。

## 5. 组件边界与数据流

`AnalysisFrameRing.snapshot_window()` 只读返回指定时间窗内的安全帧。

`GuardianEvidenceStore` 管理证据数据库行；`GuardianEvidenceFiles` 只负责受控目录
和原子媒体写入；`GuardianEvidenceRecorder` 组合两者并维护有界的活动采集状态。

`VisualWorker` 在安全帧成功加入帧环后调用 `on_safe_frame`。事件管道只有在
`alert_opened` 真正创建新事件后调用 `on_event_opened(event, transition)`；重复
回调不会重启采集。所有媒体回调异常都在边界内吞掉并转换为固定日志码，不能中断
视觉 worker 或风险持久化。

## 6. 结构化日志

沿用 `baby_guardian` JSON-line schema，只增加固定事件码：

- `guardian.evidence_started`
- `guardian.evidence_ready`
- `guardian.evidence_failed`
- `guardian.evidence_interrupted`

允许字段仅为 `event_id`、`observed_at`、`state`、`result`、`frame_count`。禁止文件
路径、证据键、摘要、异常文本、模型原文、图片或网络信息。日志失败不改变证据结果。

## 7. 故障处理

- 截图或短片编码/写入失败：更新为 `failed`，保留已经成功原子写入的文件，不抛出。
- SQLite 失败：输出固定 `guardian.evidence_failed`，不暴露异常文本，不影响风险事件。
- worker 重启：启动恢复将 `collecting` 改为 `interrupted`，已 `ready` 记录不变。
- 摄像头在后 30 秒断流：保持 `collecting`；进程关闭时改为 `interrupted`，不伪造
  完整短片。
- 恢复风险不会提前截断证据采集；仍收满后 30 秒，保留告警之后的恢复过程。

## 8. 验证与后续接口

测试只使用程序生成的 JPEG，覆盖时间窗、边界帧、并发三风险上限、原子权限、
动画 WebP 可读性、幂等打开、30 秒完成、重启中断、失败隔离、日志 allowlist、
worker 和生产接线。不得使用家庭媒体或真实标识。

下一切片消费 `ready`/`failed` 状态和 `event_id` 实现风险 ntfy；再后续实现已认证
Dashboard 查询、两位家长确认和误报反馈，最后提供统一 macOS 验收脚本。
