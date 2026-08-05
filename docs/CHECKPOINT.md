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

2026-08-05 小米优先交付刷新：本地 `codex/basic-usable-alpha` 在 `08963d6`
之后执行完整软件门禁，316 个 Python 测试与 70 个 Node 浏览器测试通过，
`git diff --check` 及跟踪媒体/运行数据边界检查通过。该证据仅确认可交付软件包，
不替代 i9、MJSXJ17CM、三浏览器、两台 Android 与 24/72 小时实机验收。

本阶段固定为只读监测；单一光学来源的控制资格为 `ineligible`，不存在空调、
加湿器、风扇、插座或其他执行器 API。

## Visual risk R1 checkpoint

2026-08-05 已从 `stable/xiaomi-alpha` 的 `125fb44` 建立本地功能分支
`codex/xiaomi-alpha-visual-risk-core`，完成纯确定性风险核心：严格拒绝模型自由
文本和额外字段；遮脸、趴睡、离床三条轨道相互独立；单次或低于 `0.70` 的候选
不能告警；两次有效候选及两次明确安全结果均要求至少 10 秒跨度；成人介入只记录
一次且不能自动恢复；持续事件不重复告警；重启只恢复已打开风险并清空连续计数。

R1 不读取摄像头、不调用 M2/Ollama、不写数据库或媒体、不发送通知。软件测试
只能证明规则契约，不能证明真实识别准确率。下一闸门是 R2 安全帧链路：床区
必填、15% 裁剪、隐私遮罩先于模型/写盘、有界内存帧环和单飞调度。

本轮新鲜门禁证据：Python `343 passed`，Node 浏览器 `70 passed`，
`git diff --check` 退出码为 0。Python 输出仍有一项既有的 FastAPI/Starlette
弃用警告，本阶段未增加运行时警告。
