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

## Visual frame R2a checkpoint

2026-08-05 在同一视觉功能分支完成安全帧边界：缺少床区时固定返回
`VISUAL_BED_ZONE_REQUIRED`；所有点均为 `0..1` 归一化坐标，退化多边形被拒绝；
床区外接矩形每边按自身宽高扩展 15% 并限制在源图范围；隐私多边形先在裁剪图中
涂黑，再缩放并编码为固定 `960×540`、JPEG 质量 80、单帧不超过 1 MiB。

只有 `PreparedAnalysisFrame` 可以进入 40 秒/21 帧内存环；进程退出后普通帧消失，
不会写入磁盘。每次复核可按约 2 秒间隔选最近四帧，样本不足时返回空结果。
所有像素测试使用程序生成四色图，不含家庭画面。

R2a 仍未接入真实捕获 worker，也未实现断流/冻结复核、单飞调度、M2/Ollama、
SQLite 事件证据、ntfy 或 Dashboard 反馈；这些边界继续阻止将当前代码描述为可用
的自动照护告警。

R2a 新鲜门禁证据：Python `367 passed`、Node 浏览器 `70 passed`，Python
编译、部署/工具 Shell 语法和 `git diff --check` 均通过；仍只有一项既有
FastAPI/Starlette 弃用警告。

## Visual capture R2b checkpoint

2026-08-05 在同一视觉功能分支完成 R2b 软件核心。go2rtc 新增固定、按需启动的
`analysis` 逻辑流，由现有 `source` 生成 `960×540`、1 FPS MJPEG；视觉帧源只连接
loopback、固定读取 `analysis`，一个迭代器在生命周期内只持有一条 HTTP/MJPEG
响应，避免每两秒重新建立 Xiaomi CS2 会话。

worker 每两秒最多接受一帧，只有经过床区裁剪和隐私遮罩的
`PreparedAnalysisFrame` 能进入40秒内存环和未来模型调度器。普通复核至少间隔
10秒，加急复核至少间隔5秒；任一时刻最多存在一个 Future，忙碌时跳过本轮而不
积压帧或请求。传输失败使用1/2/4/8秒有界退避，停止事件可以中断等待。

断流与冻结由确定性模块负责。连续60秒源失败才形成 `source_offline`；冻结必须
同时满足隐私处理后 JPEG 摘要、感知哈希、亮度、噪声和尺寸连续60秒完全一致，
并在主动重连后的第一帧仍一致。黑暗、低对比或宝宝静止本身不能判定冻结；恢复
需要有效且发生变化的帧连续20秒。所有转换只输出稳定枚举和持续时间，不包含图片、
路径、地址或底层异常文本。

R2b 没有添加 Ollama/SSH、真实线程池、SQLite、通知、Dashboard 路由、事件媒体、
launchd 或自动控制。只有 R3 提供真实本地模型后端后才会部署独立视觉 worker，
避免出现“进程在运行但没有复核能力”的假健康状态。

内部 worker、状态机或回调异常与摄像头传输失败分开计数；只有打开或读取流失败
才能进入 `source_failed`，内部异常仅形成脱敏 `worker_internal_error`，避免
伪造摄像头离线证据。

R2b 新鲜门禁证据：Python `402 passed`、Node 浏览器 `70 passed`；Python 编译、
部署/工具 Shell 语法、`git diff --check`、跟踪 runtime/媒体/数据库边界、GitHub
Token 候选和私钥标记检查均通过。仍只有一项既有 FastAPI/Starlette 弃用警告。
这些证据不代表真实摄像头连续取流、M2 模型准确率或家庭夜间场景已验收。
