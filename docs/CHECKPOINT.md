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

## Visual frame health alert checkpoint

2026-08-08，Intel i9 对真实小米源执行了受控断流与恢复验收。新的
`source_offline` 事件只发送一次离线通知；恢复需要有效且变化的画面满足既有
20 秒恢复窗口，随后只发送一次恢复通知。最终持久化状态为 `recovered`，离线与
恢复投递标记均为 `1`。这证明“确定性断流判定 → SQLite 事件 → ntfy → 手机 →
恢复”闭环已在实机通过，修复后的 ntfy JSON 数字优先级已生效。

本结果不包含 Topic、Token、摄像头标识、私网地址、画面或本地数据库。它只证明
源健康通知，不证明 Baby 姿态、遮脸、离床识别准确率，也不替代现场照看。此次
输出尚未同时记录 gauge 与实时指标在断流期间的连续性，因此视觉告警计划的 Mac
边界仍保留这一项旁路服务检查；不需要再次模拟 Baby 风险事件。

## Visual runtime R3 checkpoint

2026-08-06 在同一视觉功能分支完成 R3 软件接线。配置默认关闭；启用时必须存在
本机私有 `bed_zone`。模型标签固定为 `qwen3-vl:8b-instruct-q4_K_M`，i9 只允许
访问 `http://127.0.0.1:11435/api/chat`，不能通过配置或 HTTP 请求替换 endpoint、
模型或提示词。每次只发送四张已完成床区裁剪与隐私遮罩的内存 JPEG，单帧最多
1 MiB、总计最多 4 MiB；禁用环境代理，20秒超时，关闭 streaming/thinking，
温度为0，五分钟 keep-alive。

模型响应必须匹配固定模型、完成状态和严格 `VisualReview` schema v1。原始输出、
底层异常、图片、路径和 endpoint 不进入日志或健康状态。连续3次失败或持续60秒
才形成一次 `model_degraded`，连续2次成功才形成一次 `model_recovered`；失败复核
不会推进遮脸、趴睡或离床证据，成功复核仍由 i9 确定性状态机进行两次/10秒确认。

生产视觉 worker 现在拥有一条连续 `analysis` 连接和一个模型执行线程，作为独立
launchd job 运行；受限 SSH 隧道是另一个 job，仅允许 i9
`127.0.0.1:11435` 转发到 M2 `127.0.0.1:11434`，使用 BatchMode、严格 host key
核对、单一 `-L` 和专用 mode 400/600 密钥。视觉或隧道故障不会重启 Dashboard、
go2rtc、gauge worker 或 M2 Ollama。

R3 新鲜软件门禁：Python `451 passed`、Node 浏览器 `70 passed`；Python 编译、
Shell 语法、Make dry-run 和 `git diff --check` 通过，仅保留既有 Starlette/httpx
弃用警告。M2 已下载模型但 `ollama ps` 空闲为空是正常现象，不构成真实推理门禁。

## Realtime visual R3.5 checkpoint

2026-08-06 已实现默认关闭的轻量实时视觉路径。启用时 worker 只消费独立的
`analysis_realtime` 5 FPS 本机流；每个安全帧进入 OpenCV/可选专用模型，但 Qwen
内存环仍最多每 2 秒加入一帧，常规复核仍为 10 秒一次。语义 watch 在帧环预热后
可立即请求一次受现有 5 秒限流和单飞门约束的紧急复核。

快速层只输出 `watch_opened/candidate_cleared`，无法创建或恢复现有高风险告警。
模型文件固定大小与 SHA-256，只有显式 `make alpha-realtime-models-install` 才下载；
模型缺失、版本不符或推理失败时，姿态/人脸语义保持不可用，运动、画面质量、断流、
冻结和常规 Qwen 路径继续工作。所有自动化图像均为程序生成。

本检查点仍不是 i9 实机通过。现有安装器会保留用户的 `runtime/go2rtc.yaml`，因此
启用前必须人工审查并加入 `analysis_realtime`，再记录空床、玩偶、成人、夜视、
遮挡、蚊帐和正常翻身各至少 10 次，以及 P50/P95、CPU 和 5→3→1 FPS 降级证据。

2026-08-07 复审修正后新鲜软件门禁：Python `510 passed`、Node 浏览器
`70 passed`；Python 编译、Shell 语法、schema 解析和 `git diff --check` 均通过，
仅保留既有 Starlette/httpx 弃用警告。姿态人数改由 PAF 连接后的骨架分组生成；
模型/负载降级状态、降载下逐帧源健康检查、持续模糊遮挡和 3 FPS 截止时间均有
合成回归测试。此结果仍不替代 i9 实机和家庭场景验收。

2026-08-07 已补齐脱敏生产性能观测面：负载控制器只保留最近 10 秒、最多 51 个
处理耗时样本并输出 nearest-rank P50/P95/最大值；worker 通过单槽 latest-wins
后台 publisher 原子写入 mode `0600` 的本地 schema-v1 状态文件，慢磁盘和 `fsync`
不再阻塞实时分析或候选评估。状态命令严格区分 available、unavailable、stale 和
invalid，拒绝额外/重复字段、布尔伪装数值与非有限数值，并且不输出路径、异常、
画面或候选结果。`alpha-visual-status` 在指标失败时仍完整报告既有 worker、隧道和
bridge 状态，最后再以非零码 fail closed。

本轮新鲜软件门禁：Python `558 passed`、Node 浏览器 `70 passed`；Python 编译、
schema 解析、Shell 语法、Make dry-run、`git diff --check`、跟踪 runtime/媒体/数据库
边界及 Token、私钥、私网地址字面量扫描均通过，仅保留既有 Starlette/httpx 弃用
警告。该证据不代表 i9 性能门完成；必须部署本提交后连续运行至少 10 分钟，记录
当前 5/3/1 FPS 档位、样本数、P50/P95/最大值。5 FPS 要求 P95 不超过 `180ms`，
自动稳定在 3 FPS 时要求 P95 不超过 `300ms`；1 FPS、stale、invalid 或模型 degraded
均不得通过首期门。

仍待在 i9/M2 本地生成专用 SSH 密钥、核对 host key、安装隧道、填写真实床区，
并验证四帧真实响应、冷/热加载、P95≤8秒、白天/黑暗/蚊帐/成人/空床/模拟遮挡、
断开 M2 降级与恢复。R3 不保存事件媒体、不发送风险 ntfy、不提供 Dashboard
反馈；这些属于 R4。本阶段不能宣称医疗监护、无人照护或家庭准确率已经通过。
