# Baby Monitor Local

基于小米智能摄像机 2 云台版（MJSXJ17CM）、Intel i9 Mac 和指针式温湿度计构建的本地优先婴儿监控系统。

## 当前可试用版本

当前 Xiaomi Alpha 与 Guardian 功能线已提供基础可用闭环：

- 256GB microSD 全天循环录像；
- 密码保护的 1× 1280×720、10 FPS MJPEG 网页预览和当前截图；
- 2×/3× 优先透传已验证的 2560×1440 H.265 原码，浏览器以 `native`
  MSE 硬件解码；不兼容时才按需使用 `source_compat` 与 VideoToolbox 转为
  2560×1440 H.264，最后一个 `compat` 消费者离开后停止编码；
- 网页查看器支持全屏、1×/2×/3× 清晰变焦和鼠标/单指拖动；
- M2 Mac 通过局域网访问 i9 Dashboard；
- M2 通过 SSH 隧道访问仅限本机的 go2rtc 配置页；
- 两台 iPhone ntfy 文字通知；
- 后续使用 Tailscale Serve 实现私有外网访问；
- 米家 App 继续承担声音、双向语音、云台和历史回放。

网页方向键已具备 Basic Auth、方向白名单、单飞互斥和限流的安全控制骨架，
但真实 MJSXJ17CM 电机协议尚未完成公开证据、仿真 fixture 和最小左右回位
门禁，因此生产适配器默认返回 `PTZ_DISABLED`，不会向摄像头发送猜测指令。
门禁完成前，物理云台继续使用米家 App。

安装说明：[基础可用 Alpha 快速开始](docs/runbooks/ALPHA_QUICKSTART.md)

## 统一命令

仓库脚本不依赖 Git 可执行位，不需要手工修改文件权限。统一使用：

```bash
make alpha-update
make alpha-install
make alpha-start
make alpha-guardian-scene-test
make alpha-stop
make alpha-status
make alpha-logs
```

现有安装升级为高清预览：

```bash
make alpha-update
make alpha-quality-hd
make alpha-quality-info
make alpha-source-check
make alpha-go2rtc-info
make alpha-subtype-probe
make alpha-subtype-apply
```

包含混合高清代码的更新需要安装 WebSocket 依赖与带 `hvc1/udp4` 补丁的固定
go2rtc 构建，再事务式加入 `source_compat`：

```bash
make alpha-update
make alpha-install
make alpha-quality-hd
```

恢复升级前配置：

```bash
make alpha-quality-rollback
```

`make alpha-quality-hd` 会先备份本机 `runtime/go2rtc.yaml`，再把 Xiaomi `source` 调整为 HD、保持传输自动协商，并把 `live` 设置为 1280×720、10 FPS。所有状态输出只包含派生信息，不打印完整 Xiaomi URI、账号、Token、DID 或局域网地址。

`make alpha-subtype-probe` 会安全探测 MJSXJ17CM 的 `0–5` 画质编号并比较源尺寸；完成、失败或中断后都恢复原配置，不会自动采用推荐值。

Intel i9 实机探测已确认 `subtype=3` 通过 `cs2+udp` 提供 `2560×1440 H.265`
原生源。`make alpha-subtype-apply` 会事务式应用该编号，并验证原生源至少
达到 `1920×1080`、实时流为 `1280×720`、连续 MJPEG 与 Dashboard 都正常；
任一门禁失败都会自动恢复旧配置。成功后仍可用
`make alpha-quality-rollback` 手工撤回。

`make alpha-update` 会在当前仓库设置 `core.fileMode=false`，避免 macOS 上脚本权限位变化形成无意义的 Git 冲突。

Voice Care v1 的 Gate V0 只验证本机入站音频能力，不启用哭声分类、护理记录
写入或摄像头反向语音：

```bash
make alpha-voice-v0-test
make alpha-voice-v0-probe
make alpha-voice-v0-stability
```

软件门只使用内存中的合成 Opus；两个实机门分别接收 60 秒和 10 分钟的固定
loopback 音频流，将解码后的 PCM 立即丢弃，并在退出时释放独立 ffmpeg
消费者。命令只输出 codec、采样率、声道、时长和字节计数等有界指标，不输出
流地址、凭据或音频内容。

小米摄像头固定语音回复默认关闭。软件测试与状态查询不会播放声音：

```bash
make alpha-voice-camera-test
make alpha-voice-camera-status
```

只有 `make alpha-voice-camera-probe` 会在成人守候摄像头时播放一秒生成音，并要求
在终端精确输入 `YES`；它不录音、不保存生成音，也不会自动启用生产回复。通过后，
仍须在忽略的本机设置中把 `voice_care.camera_reply_enabled` 设为 `true`，然后只重启
Voice。要回滚则把该值恢复为 `false`，同样只重启 Voice；仅当 go2rtc 协议构建本身
失败时，才使用独立的 `make alpha-go2rtc-rollback`。

## 公开视觉回归语料

视觉模型或 Guardian 视觉链路变更后，可用固定公开素材重复执行解码、抽帧、当前
`VisualWorker`、候选状态和隔离 Guardian 投影。仓库只跟踪严格 manifest、许可记录、
checksum、转换配方和工具；下载视频、准备文件、逐帧数据与结果都保存在被忽略的
`runtime/test-corpus/visual`，不会提交到 Git。

```bash
make alpha-visual-corpus-validate
make alpha-visual-corpus-prepare
make alpha-visual-regression
make alpha-visual-regression-compare
make alpha-visual-corpus-codec-gate
make alpha-visual-regression-long
```

当前第一批为 11 段、3 个公开来源，覆盖白天、模拟 IR、活动、遮挡、成人入画、
婴儿床广角和房间广角。`WIDE-02`、`OCC-03`、`NEG-01`、`NEG-02` 尚缺合规素材，
因此状态为 `PARTIAL`，baseline promotion 会安全拒绝。补齐后只能用候选输出给出的
精确 digest 显式执行：

```bash
make BASELINE_SHA256=<candidate-sha256> alpha-visual-regression-promote
```

公开文件回放只用于可重复回归，不代表婴儿检测或风险判断准确，也不替代真实
MJSXJ17CM、原生红外、家庭场景和人工安全验收。

## 项目目标

- 256GB microSD 负责全天循环录像，写满后覆盖最早内容。
- Mac 负责低负载智能分析、事件截图/短片、环境读数、网页和告警。
- 两台 iPhone 后续通过私有远程访问安全查看，并通过 ntfy 接收通知。
- Mac 故障时，米家 App 与 microSD 基础监控仍继续工作。
- 智能检测仅提供候选提醒，不承担呼吸、心率、窒息或医疗级告警。

## 已确认硬件与场景

- 摄像头：小米智能摄像机 2 云台版，型号 MJSXJ17CM。
- 主机：Intel i9 Mac，全天运行，由 M2 Mac 通过 SSH 维护。
- 录像：256GB microSD 全天循环录像。
- 环境表：WS2021 指针式温湿度计；自动定位模型通过私有实机门后可在画面内竖直移动。
- 房间：宝宝与成人同房，宝宝睡独立婴儿床；夜间完全黑暗，可能有蚊帐。
- 网络：i9、M2 与摄像头位于同一可信局域网；后续需要外出查看。
- 客户端：M2 Mac 与两台 iPhone。

## 文档

- [基础可用 Alpha 快速开始](docs/runbooks/ALPHA_QUICKSTART.md)
- [Intel macOS 小米 CS2 实机排查](docs/runbooks/XIAOMI_CS2_MACOS_TROUBLESHOOTING.md)
- [高清 MJPEG 预览设计](docs/superpowers/specs/2026-08-04-hd-mjpeg-preview-design.md)
- [正式设计规格](docs/superpowers/specs/2026-08-04-baby-monitor-local-design.md)
- [第一版实施计划](docs/superpowers/plans/2026-08-04-baby-monitor-local-v1.md)
- [迭代路线图](ROADMAP.md)
- [安全边界](SECURITY.md)

## 分支策略

- 默认分支：`main`
- M0 基线分支：`codex/bootstrap-baby-monitor-v1`
- 基础可用 Alpha：`codex/basic-usable-alpha`
- 后续功能分支：`codex/<stage>-<feature>`

## 当前视频边界

Dashboard 的 1× 保留 1280×720、10 FPS MJPEG；切换到 2×/3× 时，才通过
绑定 profile 的一次性票据和同源 WebSocket 中继。浏览器支持 HEVC MSE 时请求
`native`，直接消费 `source` 的 2560×1440 H.265；否则请求固定的 `compat`，
由 go2rtc 的 `source_compat` 按需启动 VideoToolbox 1440p H.264 编码。多端共享
一个 compat producer，最后一个消费者离开后自动停止；go2rtc 端口仍不开放到
局域网。

目标层首帧可用前，当前画面一直保留；native 失败最多自动转入一次 compat，
最终失败继续使用 MJPEG，不显示黑屏。
稳定 1× 只有 MJPEG 消费者，稳定 2×/3× 只有 MSE 消费者，2× 与 3× 之间复用
同一连接。拖动只改变浏览器显示，不会改变摄像头朝向。全屏可通过按钮或双击
当前画面进入，按 `Esc` 退出后自动恢复 1× 居中并安全释放 HD 连接。

## 安全边界

公开仓库不包含真实家庭音视频、宝宝影像、室内布局、米家凭据、ntfy Token 或私网信息。运行时机密只保存在本机被 Git 忽略的 `runtime/` 目录。
