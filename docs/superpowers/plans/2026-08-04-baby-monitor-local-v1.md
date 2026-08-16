# Baby Monitor Local V1 Implementation Plan

> **For agentic workers:** implement task-by-task on feature branches. Each task must include tests, verification evidence, and a focused commit.

**Goal:** 在 Intel i9 Mac 上构建可长期迭代的本地优先婴儿监控 V1，同时保留米家 App 与 256GB microSD 的独立降级能力。

**Architecture:** 小米摄像头通过 go2rtc 提供单一音视频上游，FFmpeg 生成低帧率分析流和事件环形缓存；Python 服务分别处理表盘、音频、床区事件、通知和健康状态，FastAPI 提供鉴权网页，SQLite 保存事件与读数。全天录像只写入摄像头 microSD。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、OpenCV、ONNX Runtime、FFmpeg/ffprobe、go2rtc、SQLite、pytest、Playwright、ntfy、Tailscale、macOS launchd。

## 全局约束

- V1 优先使用 Intel i9 Mac 原生进程，不部署完整 Frigate NVR。
- 原始 2.5K 流不得持续满帧 AI；分析流为 640×360 或 960×540、3～5 FPS。
- 256GB microSD 是全天连续录像唯一主来源，写满后覆盖最早录像。
- Mac 事件短片默认前 10 秒、后 30 秒，保留 30 天且总配额 30GB。
- go2rtc 管理接口固定绑定 `127.0.0.1`，禁止公网端口映射。
- 两台 Android 通过 Tailscale 查看，通过 ntfy 接收主告警。
- 所有智能识别只能标注为候选提醒，不承担医疗级判断。
- 表盘低置信度必须输出 `unavailable`，不得使用旧值冒充新读数。
- 凭据只存储于 macOS Keychain 或本地 `.env`。
- 真实家庭音视频、宝宝影像和室内布局照片不得进入公开仓库。

## 预定目录

```text
apps/api/                  FastAPI、鉴权、状态与事件 API
apps/dashboard/            Android 优先响应式网页
services/stream/           go2rtc、FFmpeg、环形缓存
services/gauge/            温湿度表标定和读取
services/audio/            响度和哭声候选
services/vision/           床区运动、姿态、成人介入
services/events/           去重、升级、恢复、保留策略
services/notifications/    ntfy 和企业微信
services/watchdog/         Mac 与可选树莓派 2 心跳
packages/contracts/        共享 Pydantic 模型
config/                    示例配置和 JSON Schema
deploy/launchd/            macOS 服务定义
tests/                     单元、集成、回放、验收测试
tools/                     标定、安装、通知、负载工具
docs/runbooks/             安装、摆位、安全、恢复手册
```

## M0：安全仓库基线

### Task 1：配置契约与密钥边界

**交付：** `pyproject.toml`、严格 Pydantic 配置、JSON Schema、示例配置和配置测试。

**测试重点：** 缺少摄像头标识、go2rtc 非回环地址、负事件配额、YAML 中出现原始 token 时必须拒绝。

**完成条件：**

- `AppSettings.load(path)` 可读取合法配置。
- `analysis_fps` 限制在 1～5。
- 凭据字段只接受环境变量名或 Keychain 引用。
- `pytest tests/contracts/test_settings.py -v` 通过。

### Task 2：摄像头流探测与单上游分发

**交付：** ffprobe 探测器、go2rtc 配置生成器、视频/音频健康模型。

**测试重点：** H.265 视频、音频轨道、无音频、超时、错误 JSON。

**完成条件：**

- 所有 subprocess 调用使用参数数组，不经过 shell。
- 生成 `source`、`analysis`、`live` 三个逻辑流，但只建立一条摄像头上游连接。
- 管理接口仅监听 `127.0.0.1`。

### Task 3：事件数据库和共享契约

**交付：** SQLite 迁移、事件/读数/系统健康模型、两位家长独立确认。

**完成条件：**

- 时间统一保存为带时区 ISO 8601。
- `unavailable` 读数可明确入库。
- 数据库 `PRAGMA integrity_check` 返回 `ok`。

## M1：可看、可告警、可恢复

### Task 4：FFmpeg 环形缓存与事件短片

**交付：** 分段缓存、跨片段拼接、事件前 10 秒后 30 秒导出、30GB 配额策略。

**完成条件：**

- 可直接 stream-copy 时不重新编码。
- 导出失败不阻塞截图、文字事件和通知。
- 配额清理按低级别、普通、高级的顺序执行。

### Task 5：鉴权 API 和 Android 网页

**交付：** 登录、状态、事件、确认、实时画面接口和移动网页。

**完成条件：**

- 匿名请求全部拒绝。
- 两位家长均可查看并独立确认事件。
- 密码使用 Argon2 哈希。
- Playwright Android 视口测试通过。

### Task 6：健康监测、launchd 和资源降级

**交付：** 健康端点、摄像头断流判断、磁盘与进程检查、launchd 安装脚本、资源守卫。

**完成条件：**

- 摄像头断流持续 60 秒后发布事件。
- Mac 重启后服务自动恢复。
- 负载连续超限时依次将分析 FPS 从 5 降至 3、1，最后停用姿态模型；音频、表盘和断流检测继续工作。

### Task 7：Tailscale 安全部署

**交付：** Mac 和两台 Android 安装手册、最小 ACL、安全审计脚本。

**完成条件：**

- 无 `0.0.0.0:1984`。
- 无公网端口映射说明。
- 仓库凭据扫描通过。
- 只有鉴权应用端口可经 tailnet 访问。

## M2：环境和声音能力

### Task 8：WS2021 表盘标定工具

**交付：** Dashboard `2×/3×` 一次性标定向导、schema v2 四角透视模型、
版本化本地存储和合成表盘测试夹具。专项实施以
`2026-08-05-environment-monitoring-v1.md` 为准，不再开发第二套 CLI。

**完成条件：**

- 支持仪表面四角、两个表盘的圆心/针尖和每盘至少三个已知刻度点。
- 覆盖跨越 0° 和越界角度。
- 家庭参考图只放本地 `runtime/calibration/`，不提交仓库。

### Task 9：白天与红外夜视表盘读取

**交付：** 白天 HSV 红针读取、夜间灰度径向检测、5 帧中位数、置信度模型。

**完成条件：**

- 遮挡、反光、无针、角度不一致时返回 `unavailable`。
- 白天目标误差达到 ±1℃、±5%RH。
- 夜间不能达到稳定置信度时明确降级，不发布虚假环境告警。

### Task 10：响度与哭声候选

**交付：** 动态底噪、响度门、可替换 ONNX 分类器、时序状态机。

**完成条件：**

- 5 秒普通、10 秒高级、30 秒重复升级规则可测试。
- 静音、成人说话、短哭、持续哭和重复哭样本契约通过。
- 真实家庭录音不得提交仓库。

### Task 11：ntfy 和企业微信通知

**交付：** 双通道调度器、截图附件、优先级、幂等键、重试工具。

**完成条件：**

- 微信失败不阻塞 ntfy。
- 两台 Android 均能收到普通、高级、紧急和恢复测试通知。
- 点击通知经 Tailscale 打开对应事件。
- 环境事件是独立的纯文字通道，只含读数、时间、稳定原因码和鉴权链接；
  不发送宝宝画面、表盘截图、私网地址或本地路径。

## M3：床区智能与反馈闭环

### Task 12：区域配置、运动和成人介入

**交付：** `bed_zone`、`exit_boundary`、`privacy_mask`、`gauge_zone` 配置工具；低帧率运动检测；场景状态机。

**完成条件：**

- 小幅动作只记录。
- 连续明显翻动、坐起/站立、床内目标消失产生对应候选。
- 成人抱走时进入“成人介入”，避免重复离床通知。
- 蚊帐摆动不能单独触发高优先级事件。

### Task 13：事件协调、去重、升级和恢复

**交付：** 带版本号的确定性规则引擎。

**完成条件：**

- 同类事件合并而不轰炸。
- 严重度可升级。
- 环境正常持续 5 分钟后发布恢复事件。
- 不同来源的事件不会被错误吞并。

**后续实机阶段 G1：** 软件闭环和安全合成场景已经通过；真实宝宝准确率仍未
验收。环境 E1–E5 和三浏览器门完成后，只能在正常照护、成人持续监督下观察自然
发生的安全场景，不得摆拍遮脸、趴睡、离床或任何危险姿势。Codex 可准备脱敏清单、
验证状态/事件/通知契约并汇总闭合结果；真人负责现场监督和判断候选是否正确。
验收记录只包含固定分类和聚合计数，不包含画面、模型原文、床区坐标或家庭细节。
该门通过仅证明已观察场景，不构成医疗或无人照护保证。

### Task 14：每日报告和人工反馈

**交付：** 哭声、移动、环境、离线、确认、误报日报；`accurate`、`false_positive`、`missed_manual` 反馈。

**完成条件：**

- 无画面或不可读时间不计入睡眠候选。
- 报告明确区分“候选”和“家长确认”。
- 匿名化调参数据不含原始家庭音视频。

## M4：可靠性与发布

### Task 15：可选树莓派 2 独立看门狗

**交付：** ARMv7 轻量心跳服务和 systemd 单元。

**完成条件：**

- 超过 2 分钟无 Mac 心跳后通知，短暂丢包不报警。
- 恢复后只发送一次恢复消息。
- 不依赖 OpenCV、ONNX、FFmpeg 或视频流。

### Task 16：72 小时综合验收

**交付：** 自动采样器、验收清单、机器可读和 Markdown 报告。

**当前状态：** 尚未开始。先完成环境计划的 E1–E5 实机门，再完成 Hybrid HD
计划中的三浏览器实机门；其余发布前置条件满足后才进入本任务。不得用既有
10 分钟视觉性能结果或 24 小时环境结果替代本次 72 小时综合运行。

**场景：** 白天、红外夜视、蚊帐摆动、成人抱走、断网、摄像头断电、Mac 重启、磁盘配额、两台手机外网访问。

**发布门禁：**

- 设计规格中的 15 项验收条件全部有证据。
- 所有高风险红项转为 GitHub Issue 并阻止发布。
- 单元/集成/E2E 测试、`git diff --check` 和安全扫描通过。
- 通过后打 `v0.1.0` 标签。

## 分支和提交策略

- 稳定分支：`main`。
- 首个开发分支：`codex/bootstrap-baby-monitor-v1`。
- 后续分支：`codex/m0-config-baseline`、`codex/m1-stream-dashboard` 等。
- 每个任务形成一个独立可审查交付，不把多个无关模块塞进同一 PR。
- 所有真实账号、token、家庭图片和家庭录音必须在提交前扫描并排除。
