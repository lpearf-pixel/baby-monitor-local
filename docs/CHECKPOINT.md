# Hybrid HD Checkpoint

Draft PR #4 已实现并自动化验证 H.265 原码优先、VideoToolbox 按需兼容流、
profile 绑定票据、无黑屏播放器回退以及可审计 go2rtc 双补丁构建。

当前仍保持 Draft：Linux CI 不能替代 Intel i9、M2 Chrome/Safari 与 Android
Chrome 实机门禁。下一步是在 i9 执行安装、构建、源流与消费者检查，再提交
三浏览器的 native/compat profile、切换耗时、画面细节、编码器启停和
`PTZ_DISABLED` 结果；实机通过前不宣称发布完成。

## Environment monitoring checkpoint

环境监测规格和实施计划已批准，软件链路已经实现：WS2021 schema v2
Dashboard 标定、每分钟一次的独立 gauge worker、连续五帧读表、严格
`EnvironmentReading`、SQLite WAL 历史、确定性普通/严重/不可读/恢复事件、
24 小时与 7 天趋势，以及只含文字和鉴权 HTTPS 链接的 ntfy 环境通知。

当前仍未通过 Intel i9 实机门禁。必须在本地完成一次真实表盘标定，并记录
30 组白天对照、夜视/反光/遮挡拒绝、24 小时无积压运行、Qwen/M2 离线隔离、
负载降级和两台 Android 通知内容检查。真实画面、表盘参考图、标定 JSON、
SQLite、Token、私网地址和本地绝对路径不得提交或粘贴到 PR。

本阶段固定为只读监测；单一光学来源的控制资格为 `ineligible`，不存在空调、
加湿器、风扇、插座或其他执行器 API。
