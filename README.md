# Baby Monitor Local

基于小米智能摄像机 2 云台版（MJSXJ17CM）、Intel i9 Mac 和指针式温湿度计构建的本地优先婴儿监控系统。

## 当前可试用版本

`codex/basic-usable-alpha` 已提供基础可用闭环：

- 256GB microSD 全天循环录像；
- 密码保护的实时 MJPEG 网页和当前截图；
- go2rtc 摄像头在线状态；
- 两台 Android ntfy 测试通知；
- Tailscale Serve 私有外网访问；
- 米家 App 继续承担声音、双向语音、云台和历史回放。

安装说明：[基础可用 Alpha 快速开始](docs/runbooks/ALPHA_QUICKSTART.md)

## 项目目标

- 256GB microSD 负责全天循环录像，写满后覆盖最早内容。
- Mac 负责低负载智能分析、事件截图/短片、环境读数、网页和告警。
- 两台 Android 手机可在外网安全查看，并通过 ntfy 与企业微信/微信辅助通道接收通知。
- Mac 故障时，米家 App 与 microSD 基础监控仍继续工作。
- 智能检测仅提供候选提醒，不承担呼吸、心率、窒息或医疗级告警。

## 已确认硬件与场景

- 摄像头：小米智能摄像机 2 云台版，型号 MJSXJ17CM。
- 主机：Intel i9 Mac，全天运行。
- 录像：256GB microSD 全天循环录像。
- 环境表：WS2021 指针式温湿度计，长期固定在主画面边缘。
- 房间：宝宝与成人同房，宝宝睡独立婴儿床；夜间完全黑暗，可能有蚊帐。
- 网络：Mac 与摄像头同一稳定 Wi-Fi；需要外出查看。
- 客户端：两台 Android 手机。

## 文档

- [基础可用 Alpha 快速开始](docs/runbooks/ALPHA_QUICKSTART.md)
- [正式设计规格](docs/superpowers/specs/2026-08-04-baby-monitor-local-design.md)
- [第一版实施计划](docs/superpowers/plans/2026-08-04-baby-monitor-local-v1.md)
- [迭代路线图](ROADMAP.md)
- [安全边界](SECURITY.md)

## 分支策略

- 默认分支：`main`
- M0 基线分支：`codex/bootstrap-baby-monitor-v1`
- 基础可用 Alpha：`codex/basic-usable-alpha`
- 后续功能分支：`codex/<stage>-<feature>`

## 安全边界

公开仓库不包含真实家庭音视频、宝宝影像、室内布局、米家凭据、ntfy Token 或私网信息。运行时机密只保存在本机被 Git 忽略的 `runtime/` 目录。
