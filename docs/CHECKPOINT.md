# Hybrid HD Checkpoint

Draft PR #4 已实现并自动化验证 H.265 原码优先、VideoToolbox 按需兼容流、
profile 绑定票据、无黑屏播放器回退以及可审计 go2rtc 双补丁构建。

当前仍保持 Draft：Linux CI 不能替代 Intel i9、M2 Chrome/Safari 与 Android
Chrome 实机门禁。下一步是在 i9 执行安装、构建、源流与消费者检查，再提交
三浏览器的 native/compat profile、切换耗时、画面细节、编码器启停和
`PTZ_DISABLED` 结果；实机通过前不宣称发布完成。
