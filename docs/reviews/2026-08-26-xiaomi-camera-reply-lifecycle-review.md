# 小米摄像头答复中断、异常转动审查与修复任务书

日期：2026-08-26

审查代码基线：`origin/codex/voice-care-v1-gate-v1` @
`4d479b84b2e67b180d9be009ca45217558f18d6c`

相关失败计划：
`docs/superpowers/plans/2026-08-26-xiaomi-camera-reply.md`

状态：静态根因链已缩小，等待本地 Codex 先完成无实机 RED/诊断；Camera Reply
继续 disabled，旧 V3 计划不得重新执行

范围：只调查和修复固定 go2rtc 小米 MISS backchannel 生命周期、错误传播及
Camera Reply 的失败关闭边界；不处理 PTZ、摄像头设置、Baby Care 写入或自由文本 TTS

## 1. 审查结论

这次故障已经有明确的工程处理方向，但不能把所有现象都写成同一个已证实根因。

已经证实：

1. 旧的 CS2 channel-3 payload 复制错误已通过确定性 Go 测试修复；一秒生成音调在
   MJSXJ17CM 实机播放成功，所以该旧错误不是连续交互失败的剩余主因。
2. V3E 首批实机交互中，操作者观察到交互卡住和摄像头异常转动；聚合证据记录到
   4 次本地 `CAMERA_REPLY_COMPLETE`，随后共享 CS2 UDP source 出现 read timeout，
   Voice 摄像头音频输入继而 EOF。
3. 当前 Python `stop()` 只发送：

   ```text
   POST /api/streams?dst=source&src=
   ```

   该请求会停止 go2rtc 的内部 FFmpeg source，但固定上游实现不会因此向小米设备
   发送 `cmdSpeakerStop`。
4. 固定上游每次添加 backchannel track 都调用 `StartSpeaker()`，然后固定等待一秒；
   每次 `WriteAudio()` 的错误均被丢弃。
5. 固定上游已经声明 `cmdSpeakerStartRes = 0x107` 和
   `cmdSpeakerStop = 0x108`，但只实现了 `StartSpeaker()`，没有实现
   `StopSpeaker()`，也没有在正常答复结束时消费/确认 speaker-start response。
6. CS2 command channel 0 的 pop buffer 固定为 10。buffer 满时
   `dataChannel.Push()` 返回错误，CS2 worker 随即退出并关闭 command channel 0
   和 media channel 2。该静态链能直接解释“连续答复后共享视频/音频连接终止，
   Voice audio EOF”的现象。
7. 当前 Camera Reply 路径和项目补丁没有调用 `cmdMotorReq = 0x112`。因此没有证据
   表明 Baby Monitor 主动发送了 PTZ/电机转向命令。

强假设：重复 `StartSpeaker()` 的响应没有被消费，同时每次答复没有协议级 stop，
残留 sender/缓冲写入继续占用同一条 CS2 连接；达到某个固件响应或 channel-buffer
边界后，CS2 worker 退出，进而造成 source timeout 与 Voice EOF。

仍未证实：摄像头转头的精确机械原因。它可能是固件在 speaker session 异常、CS2
连接重建或设备自恢复时的动作，也可能是摄像头自身的人形追踪、巡航或休眠策略。
在没有 command-level 关联证据前，不得把它描述成已找到的 PTZ bug。

## 2. 失败链路

当前正常发送路径为：

```text
Voice fixed response code
  -> CameraReplyOutput.deliver_code()
  -> LoopbackCameraReplyTransport.start()
  -> POST /api/streams?dst=source&src=ffmpeg:<fixed>#audio=opus#input=file
  -> streams.Stream.Play(src)
  -> Xiaomi Producer.AddTrack()
  -> Client.StartSpeaker()
  -> fixed time.Sleep(1 second)
  -> Sender handler -> Client.WriteAudio()
```

当前停止路径为：

```text
CameraReplyOutput._deliver_rendered()
  -> LoopbackCameraReplyTransport.stop()
  -> POST /api/streams?dst=source&src=
  -> streams.Stream.Play("")
  -> stop internal FFmpeg producer
  -> no Xiaomi StopSpeaker command
  -> no bounded confirmation that sender/session is closed
```

当前 `CAMERA_REPLY_COMPLETE` 只证明 Python 看到 start HTTP 成功、等待了本地媒体时长，
并看到 stop HTTP 成功。它不证明：

- 摄像头消费了全部 Opus 包；
- `WriteAudio()` 没有失败；
- `cmdSpeakerStartRes` 已被消费；
- `cmdSpeakerStop` 已发送；
- 历史 sender 已清除；
- 人确实听到完整答复。

这解释了为什么日志可以先出现 4 次 `COMPLETE`，随后才暴露 CS2 timeout 和 EOF。

## 3. 上游静态证据

固定提交：`b465651a94c1f637d566a8c660b4fad102b35153`

### 3.1 `pkg/xiaomi/miss/backchannel.go`

- `Producer.AddTrack()` 每次先调用 `p.client.StartSpeaker()`；
- 存在上游注释 `TODO: check this!!!` 和固定一秒 sleep；
- 所有 codec handler 都以 `_ = p.client.WriteAudio(...)` 丢弃发送错误；
- 添加 sender 后没有对称的 speaker stop/session release。

参考：
`https://github.com/AlexxIT/go2rtc/blob/b465651a94c1f637d566a8c660b4fad102b35153/pkg/xiaomi/miss/backchannel.go`

### 3.2 `pkg/xiaomi/miss/client.go`

- 存在 `cmdSpeakerStartReq`、`cmdSpeakerStartRes`、`cmdSpeakerStop`；
- 只实现 `StartSpeaker()`；
- `WriteAudio()` 把加密音频写入 CS2 channel 3；
- `cmdMotorReq` 只声明，没有被当前 Camera Reply 路径调用。

参考：
`https://github.com/AlexxIT/go2rtc/blob/b465651a94c1f637d566a8c660b4fad102b35153/pkg/xiaomi/miss/client.go`

### 3.3 `pkg/xiaomi/miss/cs2/conn.go`

- channel 0 是容量 10 的 command response buffer；
- channel 2 是 incoming media；channel 3 是 outgoing audio；
- channel push 失败会终止共用 worker；worker 退出会关闭 channel 0 和 channel 2；
- `WriteCommand()` 只等待 CS2 DRW ACK，不等同于消费和验证
  `cmdSpeakerStartRes`。

参考：
`https://github.com/AlexxIT/go2rtc/blob/b465651a94c1f637d566a8c660b4fad102b35153/pkg/xiaomi/miss/cs2/conn.go`

### 3.4 `internal/streams/play.go`

- `Play("")` 只停止 stateInternal source；
- 对已有 Xiaomi producer 的正常路径没有调用设备级 backchannel stop；
- source 自然结束与显式 empty-source stop 都缺少可观察、可传播的 speaker settlement。

参考：
`https://github.com/AlexxIT/go2rtc/blob/b465651a94c1f637d566a8c660b4fad102b35153/internal/streams/play.go`

### 3.5 `pkg/xiaomi/miss/producer.go`

- `Producer.Stop()` 调用 `StopMedia()` 并关闭整条 connection；
- 正常答复结束不会调用该方法，因为项目只停止内部 FFmpeg source；
- 直接依赖 `Producer.Stop()` 解决扬声器生命周期会同时破坏 incoming media，不能作为
  正常答复的 stop 方案。

参考：
`https://github.com/AlexxIT/go2rtc/blob/b465651a94c1f637d566a8c660b4fad102b35153/pkg/xiaomi/miss/producer.go`

## 4. 假设优先级

| 优先级 | 假设 | 当前证据 | 下一步最小证明 |
| --- | --- | --- | --- |
| H1 | command response 未消费，channel 0 最终塞满并终止共享 worker | 强静态证据，现象与 timeout/EOF 一致 | 固定提交 fake CS2 连续响应 RED，证明旧代码在有界次数内失败 |
| H2 | 缺少 `StopSpeaker` 和单会话状态导致重复 start、残留 sender 或 stop 后继续写 | 强静态证据，旧实现明显不对称 | 连续 20 次 start/write/stop 生命周期测试 |
| H3 | 异步发送错误被吞掉，使本地误报 COMPLETE | 已证实代码行为 | 注入 `WriteAudio` 错误并要求 stop/HTTP/Python 返回失败 |
| H4 | 摄像头转动是 speaker/reconnect 固件副作用 | 与时间相关，但无 command-level 证据 | 软件修复通过后，单步受控实机相关性测试 |
| H5 | `cs2+udp` 本身不适合 backchannel | 尚无证据；单音已通过 | 仅在 H1-H3 全部关闭后才允许比较 TCP；不得先切协议 |

一次只验证一个假设。H1/H2/H3 没有确定性软件证据前，不允许继续家庭实机播放。

## 5. 推荐处理方案

### 方案 A：修复固定 go2rtc backchannel 生命周期（推荐）

继续使用当前固定 go2rtc commit 和 `cs2+udp`，通过项目现有受审计 patch 增加最小的
协议生命周期修复：

1. 为 Xiaomi Client 增加对称、幂等且有界的 `StopSpeaker()`，发送已有
   `cmdSpeakerStop`。
2. 增加 command-response 消费/分发边界，保证 channel 0 不会因 speaker/start-media
   响应无人消费而塞满。已知 response 必须解析为固定 command code；未知、乱序、超时
   或解密失败均 fail closed。
3. 用显式 speaker session 状态代替“每次 AddTrack 都 start + 固定 sleep”：至少区分
   `closed`、`starting`、`active`、`stopping`、`failed`，同一 generation 只允许一个
   active sender。
4. `StartSpeaker` readiness 优先由有界的 `cmdSpeakerStartRes` 证明。不能在没有测试的
   情况下继续依赖任意 sleep；如果固定固件确实不返回该 response，必须由 RED/PCAP 或
   fake fixture 证明，并在正式规格中选择另一项有界条件。
5. 答复自然结束、显式 `Play("")`、取消、超时和 source 异常都必须进入同一个
   idempotent settlement：禁止 stop 后继续向 channel 3 写入。
6. 不再丢弃 `WriteAudio()` 错误。记录第一个固定 stage 错误，使 stream stop HTTP 和
   Python adapter 能返回 `AMBIGUOUS`/`UNAVAILABLE`，而不是虚假的 COMPLETE。
7. stop 成功至少表示：内部 source 已停止、该 generation 不再写包、speaker-stop
   command 已获得 CS2 transport ACK、session 已进入 closed。它仍不等于“人听到了”。
8. 旧 acceptance marker 必须因 patch digest 变化自动失效。除非 marker schema
   本身需要表达新的生命周期版本，否则不要额外扩展 schema。

优点：修复与现有架构最接近，不增加第二条摄像头连接，不改变已通过的 receive/video
路径。

风险：需要精确处理 command-response 与 sender 关闭并发，不能只补一行
`StopSpeaker()`。

### 方案 B：独立 backchannel 连接

接收流和答复使用两条独立 Xiaomi connection，使答复失败不直接终止 incoming media。

暂不推荐：固定固件是否允许稳定双连接尚无证据；它会扩大凭据、连接、重连和摄像头资源
边界，且仍需正确实现 speaker start/stop。只有方案 A 的 session 隔离经测试证明无法在
共用连接上安全实现时，才重新设计方案 B。

### 方案 C：长期保留 i9 speaker

这是当前安全、已通过实机验收的产品方案。Camera Reply 可以永久保持 optional/disabled；
不应让它阻塞 Voice 口令、Baby Care 数据闭环或 P5 的 i9-speaker 发布范围。

## 6. 本地 Codex 任务合同

### 当前状态

- Repository：`lpearf-pixel/baby-monitor-local`
- 基线：`origin/codex/voice-care-v1-gate-v1` @ `4d479b8`
- Camera Reply：V3E failed closed，private flag `false`，marker 不接受
- 当前可用输出：Intel i9 speaker
- 当前 source：回滚后 PASS

本地 Codex 必须重新执行 `git status`、`git rev-parse HEAD`、分支和最近提交检查；如果
本地已有更新，以真实 HEAD 为准，但不得把本任务误用到旧设计分支。

### 目标

先用纯软件、纯合成测试证明或推翻 H1-H3；证据成立后，形成新的 Camera Reply
lifecycle 正式规格和实施计划。只有规格批准后才实现最小补丁。任何软件实现阶段均保持
真实 Camera Reply disabled。

### 允许范围

调查阶段可读取：

```text
patches/go2rtc-macos-hybrid-hd.patch
packages/monitoring/go2rtc_build.py
tools/go2rtc_build.py
services/voice/camera_reply.py
tools/voice_camera_reply.py
internal fixed upstream go2rtc source at the pinned commit
tests/monitoring/test_go2rtc_build.py
tests/voice/test_camera_reply.py
tests/tools/test_voice_camera_reply.py
```

经新规格批准后，预计补丁可能涉及以下固定上游路径；最终 allowlist 必须由实际最小 diff
确定，不能预先放宽为目录级：

```text
pkg/xiaomi/miss/client.go
pkg/xiaomi/miss/backchannel.go
pkg/xiaomi/miss/producer.go
pkg/xiaomi/miss/cs2/conn.go
internal/streams/play.go
对应的 *_test.go
```

### 禁止事项

- 不得在调查或软件实现阶段设置 `camera_reply_enabled: true`；
- 不得运行 `make alpha-voice-camera-probe` 或发送任何真实摄像头音频；
- 不得调用、添加或试探 PTZ/motor command；
- 不得改摄像头 URI、Mi Home 设置、巡航、人形追踪、休眠或 microSD 设置；
- 不得先切换 `cs2+tcp`、升级 go2rtc 或引入第二条设备连接；
- 不得用重启完整 Alpha、循环重试或降低门禁掩盖生命周期失败；
- 不得修改 Voice wake/ASR/VAD/ECAPA、Baby Care、Guardian、gauge、Dashboard；
- 不得记录 raw command payload、家庭音频、transcript、地址、设备 key、URL 或凭据；
- 不得修改 `main`、`stable/xiaomi-alpha`；未经单独批准不 push、PR 或 merge。

## 7. 严格 RED/证据顺序

### Task 1：复现 command-channel 堵塞链

在固定上游提交的临时 synthetic fixture 中，构造 fake CS2 command/media connection：

1. 连续注入超过 channel 0 有界容量的 speaker/start response；
2. 证明旧代码没有持续消费者；
3. 证明旧 `dataChannel.Push()` 最终返回 `pop buffer is full`；
4. 证明 worker 随后关闭 media channel，incoming `ReadPacket()` 返回 EOF/原始错误；
5. 测试不得连接真实网络或摄像头。

建议固定测试名：

```text
TestRepeatedSpeakerResponsesDoNotCloseMediaChannel
```

旧代码预期 RED：有界次数后 media channel 被关闭，或测试超时表明 command response
无人消费。不要先写生产修复再补测试。

### Task 2：复现不对称 speaker 生命周期

用记录 command code 和 channel-3 写入的 fake Conn，锁定以下 RED：

```text
TestSpeakerLifecycleStartsAndStopsExactlyOnce
TestSpeakerLifecycleRejectsOverlappingStart
TestSpeakerLifecycleStopsWritesAfterStop
TestSpeakerLifecycleSurfacesFirstWriteError
TestRepeatedSpeakerLifecycleLeavesNoActiveGeneration
```

至少连续 20 次 synthetic start/write/stop。每次必须满足：

- start request = 1；
- accepted start response = 1（如果正式设计采用 response gate）；
- stop command = 1；
- stop 以后 channel-3 writes = 0；
- active generation = 0；
- pending command responses = 0；
- 第一次写错误会使该 session fail closed。

### Task 3：复现 Streams stop 没有协议 settlement

针对 `internal/streams/play.go` 增加 fake internal source 和 fake Xiaomi consumer：

```text
TestPlayEmptySettlesBackchannelBeforeSuccess
TestPlayEmptyPropagatesBackchannelStopFailure
TestNaturalSourceEndSettlesBackchannelOnce
TestCancelAndNaturalEndDoNotDoubleStop
```

旧代码预期 RED：`Play("")` 只停止内部 source，不调用 backchannel stop；自然结束也没有
可传播 settlement。

### Task 4：根因判定门

完成 Tasks 1-3 后只允许得出以下三种结论之一：

1. `H1_H2_CONFIRMED`：静态链和 RED 均成立，进入方案 A 的正式规格；
2. `H1_REJECTED_H2_CONFIRMED`：buffer 链未复现，但 start/stop/session 缺陷成立，规格
   只修 H2/H3；
3. `ROOT_CAUSE_NOT_PROVEN`：不能继续写生产补丁，增加聚合诊断后停止，不操作实机。

不得把一个仅验证 `StopSpeaker()` 序列化的单元测试冒充完整根因证据。

## 8. 软件实现与验证要求

只有新的正式规格经批准后才进入实现。实现必须遵循：

1. 先为每一个确定行为保留失败测试，再做单一最小 GREEN；
2. patch build 的 `ALLOWED_PATCH_CHANGES` 使用精确文件和 numstat；
3. patch precondition/postcondition 必须验证固定提交中的旧行为和新行为；
4. build 在 `go build` 前运行新增的固定 upstream package tests；
5. 任何 command timeout、未知 response、写失败、stop 失败或 generation 冲突都让
   Camera Reply unavailable，不触发 i9 的 post-send 重复答复；
6. Camera Reply 失败不得终止 Voice input worker；如果共享 source 已坏，Voice 只报告
   `voice_audio_unavailable`，不得自动重启完整 Alpha；
7. 软件 gate 不接触 loopback go2rtc 实例和真实摄像头。

建议验证命令：

```bash
.venv-alpha/bin/python -m pytest -q tests/monitoring/test_go2rtc_build.py
.venv-alpha/bin/python -m pytest -q tests/voice/test_camera_reply.py tests/tools/test_voice_camera_reply.py
make alpha-voice-camera-test
make alpha-voice-test
.venv-alpha/bin/python -m compileall -q packages services tools
git diff --check
```

完成整个软件切片后再运行：

```bash
.venv-alpha/bin/python -m pytest -q
node --test tests/frontend/*.test.mjs
```

最终 tracked diff 必须扫描并确认没有凭据、私有地址、家庭音频、transcript、runtime
media、SQLite、真实 settings 或设备信息。

## 9. 聚合诊断要求

新增诊断只能包含固定 code、整数计数、布尔值和有界 latency：

```text
speaker_state
speaker_session_generation
speaker_start_requests
speaker_start_responses
speaker_stop_commands
speaker_write_failures
speaker_stop_failures
pending_command_responses
residual_sender_count
last_failure_stage
producer_generation
```

`last_failure_stage` 只能来自闭集：

```text
none
command_response
speaker_start
audio_write
source_end
speaker_stop
stream_settlement
connection_closed
```

禁止输出 response body、command payload、音频 bytes、URL、源配置、异常文本或本地路径。

## 10. 实机门（当前不执行）

软件 gate、正式规格和计划通过后，还需要用户单独批准实机门。届时只能由登录 Intel i9
图形用户、无宝宝在场、成人守在摄像头旁执行，并按以下增量停止线推进：

1. D0：确认 flag 仍为 false，source、Voice/i9 speaker、Dashboard、Mi Home、microSD
   都正常；记录摄像头是否在没有 Camera Reply 时也会自行转动。
2. D1：只发送 1 次短生成音调；要求 start/response/stop 为 1/1/1，source PASS，
   无残留 sender、无异常转动。
3. D2：发送 3 次短生成音调，每次之间完成 source 和 session-closed 检查；这一步仍不
   开启日常 Voice camera output。
4. D3：累计超过旧故障边界的 6 次短交互，要求零 timeout、零 EOF、零重复、零残留、
   零异常转动。
5. D4：重新执行旧 V3E 的完整 wake/dialogue/timeout/negative matrix。

任一步出现摄像头转动、source timeout、audio EOF、stop 不确定、残留 sender 或重复答复，
立即停止 Voice-only、恢复 flag=false、废弃 marker，只恢复 i9 speaker；不得继续下一步，
不得自动重试或重启完整 Alpha。

如果 D0 在 flag=false 且没有任何 backchannel consumer 时仍出现转动，应把转动问题从
Camera Reply 拆出，单独检查 Mi Home 人形追踪、巡航、休眠和固件行为；Baby Monitor
仍不得发送 PTZ 命令。

## 11. 完成标准

软件生命周期修复只有同时满足以下条件才可申请实机门：

- H1-H3 有明确 RED 和 GREEN，或被证据明确排除；
- 每次 session 都有对称 start/response/stop 或正式规格批准的等价有界条件；
- 连续至少 20 次 synthetic 生命周期无 command backlog、残留 sender 或 stop 后写入；
- `WriteAudio` 和 stop 错误能够传播到固定失败状态；
- `Play("")` 和自然结束都只 settlement 一次；
- patch 范围、digest、upstream tests 和 build provenance 全部通过；
- Camera Reply 默认和真实本地 settings 均保持 disabled；旧 marker 无效；
- Voice/i9 speaker 行为和全仓测试不回归；
- 文档只记录聚合证据，没有家庭/设备敏感数据；
- 未经批准没有真实摄像头操作、push、PR、merge 或 protected-branch 修改。

即使软件测试全部通过，也只能写“软件生命周期门通过”，不能写“摄像头问题已解决”。
只有 D1-D4 受控实机门全部通过后，才能重新声明 Camera Reply delivered。

## 12. 给本地 Codex 的最短指令

```text
读取 AGENTS.md、SUMMARY.md、docs/STATUS.md、docs/CHECKPOINT.md、docs/NEXT.md、
旧 Camera Reply spec/plan，以及
docs/reviews/2026-08-26-xiaomi-camera-reply-lifecycle-review.md。

以最新 origin/codex/voice-care-v1-gate-v1 为基线，先按审查文件 Tasks 1-4 做纯软件
根因证明，不修改真实 settings、不启用 Camera Reply、不运行实机 probe。

先写 RED，证明或推翻 command-channel 堵塞、缺少 StopSpeaker、残留 sender 和错误吞掉
这四条链。完成后根据证据写新的正式 spec 与实施 plan，检查 git diff，并向我汇报结论。
规格未批准前不要写生产修复。不要 push、PR、merge 或修改 main/stable。
```
