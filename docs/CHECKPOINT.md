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

同一断流时间窗内，环境数据库保留了 5 条 gauge 记录。恢复后 gauge、环境
watchdog 与 visual 三个 launchd 单元均为单次运行且从未退出，实时指标可用，
Alpha 健康接口正常；整个 Alpha 栈没有重启。因此视觉告警计划的 Mac 旁路连续性
边界已关闭，不需要再次模拟 Baby 风险事件。

本结果不包含 Topic、Token、摄像头标识、私网地址、画面、温湿度值或本地数据库。
它只证明源健康通知和旁路服务连续性，不证明 Baby 姿态、遮脸、离床识别准确率，
也不替代现场照看。

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

## Realtime visual launchd scheduling checkpoint

2026-08-09，i9 完整生产采样连续 60 个快照全部为 1 FPS，P50 为 `398.432ms`、
最差滚动 P95 为 `488.741ms`，模型始终 available。隔离分阶段 analyzer P95 为
`88.657ms`，而保留同一 worker 参数、配置、模型、连续真实帧和指标口径的前台
单变量实验达到 5 FPS 且 P95≤`180ms`；恢复 `ProcessType=Background` 后重新稳定
在 1 FPS、P50 约 400ms。因此性能差异定位到 visual worker 的 launchd 后台调度。

仓库把 visual job 单独改为 `Interactive`，没有修改 Ollama tunnel、gauge、watchdog、
模型、分析器或 5/3/1 FPS 门限。新增 `make alpha-visual-launchd-update`：只在旧 visual
job 已注册时执行，先校验新 plist、保留且不覆盖 `.r3-background.bak`，再替换并验证
单个 job；激活失败会恢复更新前 plist 并重新注册旧 job。模拟 launchd 成功与失败
路径已有 focused 回归，但 i9 尚需实际应用本提交，连续观察 3 分钟后再运行完整
10 分钟性能门。本检查点不能替代家庭场景准确率或无人照护安全验收。

本轮 focused 交付门禁为 `60 passed`；Python 编译、相关 Shell 语法、Make dry-run、
plist 解析、ASCII/LF、`git diff --check` 和本轮新增敏感内容扫描均通过。该结果只
证明软件配置与更新/回滚契约，不代表 i9 已部署或 10 分钟性能门已通过。

## Baby guardian R4 event core checkpoint

2026-08-11，在 `stable/xiaomi-alpha` 合并提交 `0df20ae` 上建立
`codex/baby-guardian-event-loop`，完成 Baby 守护事件核心。现有确定性状态机产生的
`alert_opened` 会为遮脸、趴睡或离床风险创建一个稳定 `event_id`；同类重复回调
返回已有打开事件，`recovered` 只关闭对应风险。成人介入即使没有打开风险也独立
留存，有打开风险时幂等关联到当时所有事件。

worker 启动时迁移本地 `events.sqlite3` 并恢复所有打开风险，但不恢复重启前的候选
或恢复计数。关键转换以单行 JSON 写入现有 launchd stderr 日志，只允许固定事件码、
时间、规则版本、状态、风险种类和事件/介入 ID；不记录模型原文、reason codes、
画面、路径、URL、地址、凭据或异常文本。SQLite 或日志输出失败不会终止视觉 worker。

本检查点只完成事件身份、生命周期、重启和诊断面。截图、前后短片、风险 ntfy、
Dashboard 事件查询、两位家长确认、误报反馈和统一 macOS 验收脚本尚未实现；声音
与实时性能门继续后排。focused 门禁与静态门禁结果以本分支最终提交记录为准。

## Baby guardian R4 safe evidence checkpoint

2026-08-11，在同一 Baby 守护功能分支完成方案 A 的安全事件证据。只有完成床区
裁剪、隐私遮罩、固定 `960×540` 处理和大小限制的 `PreparedAnalysisFrame` 可以
进入证据链。新风险事件立即保存最近安全帧为截图，锁定打开前 10 秒安全帧，并在
后续安全帧覆盖 30 秒后生成低帧率动画 WebP；风险提前恢复也不会截掉恢复过程。

每个活动事件最多保留 21 帧，三个风险不会建立无界队列。事件 ID 只用于生成
SHA-256 目录摘要，不直接进入文件名；证据目录为 `0700`、文件为 `0600`，同目录
临时写入、`fsync` 后原子替换。SQLite 只保存严格相对证据键和
`collecting/ready/failed/interrupted` 状态。worker 重启或正常停止时，未完成短片
会明确标记为中断，不能伪装成完整证据。

截图、WebP、SQLite 或日志失败不会回滚风险事件或终止视觉 worker；结构化日志只
输出固定状态、结果、事件 ID 和帧数，不包含文件路径、证据键、摘要、图片、异常
文本或网络信息。所有媒体测试均使用程序生成的彩色 JPEG，不含家庭画面。

本检查点没有发送风险 ntfy，也没有新增 Dashboard 查询、家长确认、误报反馈、
30 天/30GB 清理任务或方案 B 的 FFmpeg 原始视频缓存。新鲜 focused 与静态门禁
结果以本分支最终提交记录为准。

## Baby guardian R4 risk ntfy checkpoint

2026-08-11，在同一 Baby 守护功能分支完成风险文字 ntfy 软件链。新风险打开、风险
恢复以及关联到打开风险的成人介入先以稳定幂等 ID 写入 `events.sqlite3` outbox；
watch、重复打开和没有关联风险的成人介入不创建通知。视觉分析回调不执行网络请求，
独立 daemon dispatcher 每次只处理一条待发记录。

两台 Android 复用同一个私有 topic。负载只含事件 ID、白名单风险中文名、状态、
严重度、时间和证据状态，不包含截图、WebP、证据键、文件路径、私网地址、摄像头
URI、模型原文、异常文本、token 或未鉴权链接。当前 Dashboard 尚无经过鉴权的风险
事件查询，因此本阶段不发送 `click`；后续查询接口完成后再加入。

单次 HTTP 投递复用现有最多三次的短重试；一轮仍不可用时，本地 outbox 分别等待
5 秒、30 秒后重试，第三轮失败终止为 `retry_exhausted`。成功和永久拒绝均为不可变
终态，worker 重启不会重发；配置、网络、SQLite、notifier 线程或日志失败不会终止
视觉 worker，也不会回滚已保存的风险或证据。

本检查点只证明软件契约和合成测试，不证明两台 Android 已真实收到通知。真实 topic、
token、两机订阅、通知显示和断网恢复将放入统一 macOS 验收脚本。Dashboard 事件查询、
两位家长确认、误报反馈、30 天/30GB 清理、方案 B、声音和性能门仍待后续切片。

## Baby guardian option A startup and automatic test checkpoint

2026-08-12，在同一 Baby 守护功能分支完成方案 A 的统一启动和自动验收入口。
`make alpha-guardian-start` 继续复用既有幂等 Alpha 启动路径，随后有界检查
go2rtc、Dashboard、visual worker、environment watchdog、gauge worker、固定实时
模型、当前视觉指标，以及在语义复核启用时的 Ollama bridge。任一必需组件失败均
返回非零，输出只含固定组件名和状态码，不显示配置、地址、路径、异常或日志内容。

`make alpha-guardian-test` 按 repository、software、installation、service、media、
isolation 六阶段运行完整自动门禁。它聚合全部仍可安全执行的结果，不发送 ntfy
测试消息，不创建模拟风险，不写真实事件、证据或媒体数据库。安装、服务或摄像头
缺失在用户执行的 i9 验收中是 FAIL，不会静默伪装为 PASS。

本检查点的新鲜软件门禁为 Python focused `177 passed`、Node `70 passed`；Python
编译、三份新增 Shell 的 Bash 语法与 ASCII/LF、Make dry-run、`git diff --check`、
跟踪 runtime/媒体/SQLite 和敏感字面量检查均通过。当前开发容器没有替代 Intel i9
运行这两个命令，因此真实画面、已安装 launchd 服务和两台 Android 收件仍未由本
检查点证明；真实通知属于后续方案 C/实机验收，不包含在方案 A 中。

## Baby guardian R4 authenticated event Dashboard checkpoint

2026-08-13，在公开检查点 `08dbc90` 上建立独立功能分支
`codex/baby-guardian-event-dashboard`。新增只读 `GuardianEventQueryService`，使用
centralized `data_dir` 定位 `events.sqlite3`，以 SQLite read-only URI 和
`query_only` 模式联查事件与证据状态。查询先固定选择最新 20 条，再只在该集合内将
未恢复事件置顶。API 严格排除证据键、路径、媒体、模型内容和内部异常。

Dashboard 和脚本继续使用现有 Basic Auth 与 `no-store`。页面立即读取并每 15 秒
刷新；失败保留原列表并显示“数据可能已过期”。五种证据状态均有固定中文显示，
未恢复事件有语义和视觉突出。本切片没有新增图片、视频或证据访问能力，也没有加入
家长确认、误报反馈或 Baby Care 写入。

功能提交为 `96513aa`。新鲜软件门禁为 Python `692 passed`、Node `73 passed`；
Python 编译与 `git diff --check` 通过，仅保留既有 Starlette/httpx 弃用警告。
实机 i9、家庭场景准确率、两台 Android 收件和 72 小时发布门仍须单独验收。

## Baby guardian R4 evidence retention checkpoint

2026-08-13，在 Dashboard 发布快照 `69e2d5b` 上建立独立分支
`codex/guardian-evidence-retention`。视觉 runtime 复用 centralized
`event_retention_days` 与 `event_quota_gb`，启动时立即清理，之后每 24 小时运行一次。
到期证据优先删除，超额时再按最旧顺序删除；打开事件、采集中证据和仍有待发送通知的
证据始终受保护。清理只删除受控截图/动画和符合条件的 evidence row，风险事件、介入与
通知历史继续保留，Dashboard 联查结果自然变为“无证据”。

文件遍历不跟随符号链接，不使用数据库证据键拼接任意路径，并将不认识的目录内容作为
失败处理。SQLite 在删除 evidence row 时重新验证资格。文件、数据库、日志、scheduler
或线程故障不会停止视觉 worker；日志只包含结果、数量和字节数，不包含事件 ID、路径、
摘要、异常或凭据。边界测试还发现并修复了 SQLite `julianday` 在一微秒年龄边界上的
舍入问题，最终时间比较改为 Python timezone-aware `datetime`。

独立审查随后复现了两个安全缺口：符号链接形式的 root/`visual-risk` 祖先可将旧版路径
删除引向配置目录之外；恢复事务与 recovery outbox 事务之间存在 eligibility 窗口。
`e3cd69c` 将遍历与删除改为 directory-fd + `O_NOFOLLOW`，并要求 recovery 通知已经
终态，再在一个 `BEGIN IMMEDIATE` 写锁中复核精确记录、执行受控文件回调和删除 row。
时钟、等待与 runtime thread 异常也统一为允许的结构化失败日志，不再产生额外裸码。

实现提交依次为 `c9f434f`、`6291eb2`、`a915589`、`718af9a` 与安全闭环 `e3cd69c`。
新鲜 focused 门禁为 `53 passed`；完整软件门禁为 Python `714 passed`、Node
`73 passed`，仅保留既有 Starlette/httpx 弃用警告。该结果不证明 i9 实际磁盘占用、
两台 Android 投递、真实家庭场景准确率或无人照护安全。两位家长确认与绑定操作者的
误报反馈不在 Guardian 内另建身份模型，留待 Baby Care 读取 Guardian 只读事件并自行
拥有身份/写状态的未来契约。

## Baby guardian supervised live acceptance checkpoint

2026-08-14，在 `codex/guardian-evidence-retention` 上新增独立的
`make alpha-guardian-test-live`。它不会改变无副作用的自动
`make alpha-guardian-test`：真实模式必须由交互终端启动，先精确确认现场没有真实
婴儿且有成人监督，再完成 Guardian readiness，随后最多发送一次明确标为“验收测试、
不是宝宝风险告警”的纯文字 ntfy 消息，并依次确认两台手机、已鉴权实时画面和事件列表。

通知 helper 只从 centralized 环境配置构造既有 Alpha notification gateway，不构造
完整 Dashboard runtime，因此不会初始化环境或事件 SQLite。标题保持 ASCII，topic/token
只进入 URL/Authorization，所有底层输出和异常被抑制。hook-only 测试模式不读取生产
runtime 配置、不执行网络/设备 I/O，只能输出 `guardian_live_test=SIMULATED`；任何拒绝、
EOF、readiness/通知失败或后续人工未确认都 fail closed，不能伪造实机 PASS。

功能提交为 `d862f2a` 与 `67db75d`。新鲜 focused 门禁为 `38 passed`，更宽 Guardian
门禁为 `126 passed`，完整门禁为 Python `739 passed`、Node `73 passed`；Python 编译、
全部跟踪 Shell 的语法/ASCII/LF、三个 Guardian Make dry-run、`git diff --check`、跟踪
runtime/媒体/SQLite 与敏感字面量扫描均通过，仅保留既有 Starlette/httpx 弃用警告。
这些软件证据不证明 i9 已安装服务、真实 Xiaomi 画面、两台 Android 实际收件、家庭
场景准确率、持续性能或无人照护安全。实机验收仍须在无真实婴儿、成人监督条件下完成。

### Installed Intel i9 and two-iPhone acceptance — 2026-08-15

在无真实婴儿、成人全程监督的条件下，安装于 Intel i9 的 Guardian 完成真实交互验收。
固定 readiness 门通过；命令只发送一条明确标注为验收测试、非宝宝风险告警的纯文字
ntfy 消息，两台 iPhone 分别确认收件。经过鉴权的实时画面和 Dashboard 中的 Guardian
事件列表均确认可见；事件列表为空是有效的已加载状态。最终固定结果为
`guardian_live_test=PASS`。

本次验收不记录 topic、token、私网地址、凭据、通知正文或家庭媒体。它证明该次运行中
Intel i9 服务就绪、双 iPhone 文字通知、鉴权实时查看和事件列表闭环可用；不证明真实
宝宝姿态识别准确率、持续性能、24/72 小时稳定性或无人照护安全。

## Guardian household synthetic scene acceptance checkpoint

2026-08-15，在 Intel i9 上完成监督式 `make alpha-guardian-scene-test`。固定七类场景
为空床、玩偶或静态道具、成人入镜、红外夜视、安全模拟镜头遮挡、蚊帐摆动和安全正常
翻身替代场景。每类完成 10 次操作员确认，聚合结果均为 `correct=10`、
`false_positive=0`、`missed=0`、`unavailable=0`，最终固定结果为
`guardian_scene_test=PASS`。

本地状态只保存闭合枚举、序号和时间，不包含画面、模型原文、床区坐标、地址、凭据或
自由文本。本结果是该次固定场景的人工观察记录，不是自动标注数据，不证明真实宝宝姿态
识别准确率、医疗监护、持续性能或无人照护安全。

## Guardian Intel i9 realtime performance checkpoint

2026-08-15，在已安装 Guardian 的 Intel i9 上将视觉 LaunchAgent 更新为
`ProcessType=Interactive` 并完成 10 分钟生产性能门禁。60 个固定间隔样本全部保持
5 FPS，`processing_p50_ms=100.836`、`processing_p95_ms=130.789`、
`processing_max_ms=201.529`，模型状态全程为 `available`，最终结果为
`performance=PASS mode=5fps`。

为定位先前的偶发尖峰，实时分析器新增超过 180ms 才触发、最多每 10 秒一条的固定脱敏
阶段耗时记录，不记录画面、事件、路径、设备身份或配置。该次门禁只出现一条慢帧记录：
JPEG 解码 4.416ms、视觉特征 9.333ms、语义模型 187.779ms、总计 201.529ms；尖峰来自
语义阶段，但未形成持续过载或降帧。新增功能的完整软件门禁为 Python `765 passed`，
仅保留既有 Starlette/httpx 弃用警告。

本检查点只证明该 10 分钟窗口内的 i9 生产性能，不等同于 24/72 小时稳定性、真实宝宝
识别准确率、医疗监护或无人照护保证。

## go2rtc health-aware startup recovery checkpoint

2026-08-15，i9 停止与恢复过程中出现两个 go2rtc 进程交叠：旧进程仍占用 loopback
监听端口时新进程启动，新进程绑定失败但保持存活，PID 文件随后指向这个无监听进程。
旧进程退出后，原启动脚本只以 `kill -0` 判断健康，因而持续跳过真正的恢复启动。

修复后的启动路径同时验证 loopback API、PID 存活、BSD `ps -ww` 完整命令，以及该
已验证 PID 对 API 监听端口的实际所有权。只有命令身份匹配但 API 不健康的进程才能
进入有界停止与单次替换；未知进程、缺失或陈旧 PID、以及不属于该 PID 的健康端口均
固定失败，且不会按端口选择或终止进程。功能提交为 `c75683f`，严格监听所有权闭环为
`1b1732d`。

新鲜软件门禁为 Alpha 部署测试 `26 passed`、Guardian/Alpha 联合部署测试
`54 passed`、完整 Python 套件 `772 passed`，Shell 语法、ASCII/LF、Make dry-run、
`git diff --check` 与跟踪差异敏感扫描通过，仅保留既有 Starlette/httpx 弃用警告。

随后由实际拥有服务的 `kandysmith` 会话执行运行检查：Xiaomi 源为 `PASS`，使用
`cs2+udp` 和 H.265，原始尺寸 `2560x1440`，Dashboard live 尺寸 `1280x720`，接收
字节非零。视觉 worker 为 5 FPS、实时指标与模型可用，Ollama 隧道和桥接正常，
Dashboard 画面持续更新。本文不记录私网地址、设备标识、凭据、topic 或家庭媒体。

该事件同时确认 macOS 账户边界：`chatgpt-agent` 中的 Codex 可能无法权威观察
`kandysmith` GUI 域中的监听和 launchd 服务。后续实机操作应从 `kandysmith` SSH
登录直接启动 Codex；不要通过全盘读取权限或无限制 sudo 绕过账户隔离。

## Project plan reconciliation checkpoint

2026-08-16，按仓库现场状态复核正式规格、计划和交接文档。环境软件与 Guardian
功能闭环保持已完成，不重新设计。当前未完成工作按依赖固定为：环境 E1–E5 实机门、
三浏览器高清门、正常照护且不得摆拍危险姿势的真实宝宝 Guardian 观察门、另行批准的
音频/哭声阶段、Tailscale Serve/ACL 私有远程访问，以及最终 72 小时发布门。

WS2021 旧 schema-v1 标定稿明确标为已被 2026-08-05 批准的 schema-v2 环境规格
取代。`docs/NEXT.md` 现在为每个阶段记录状态、前置条件、Codex/真人边界、验收、
验证和下一步；详细行为仍由各自正式规格和计划约束。本检查点只整理文档，没有启动
实机标定、24/72 小时运行、通知、设备操作或业务代码变更，也没有 push、merge 或
修改 `main`。

## WS2021 E1 private calibration checkpoint

2026-08-16，在拥有服务的 `kandysmith` 登录会话中完成一次鉴权 Dashboard
schema-v2 标定。只读验证确认标定模型有效、参考 JPEG 有效且两份文件均为私有权限；
本文不记录标定 ID、坐标、画面、温湿度值、路径、地址或凭据。Guardian 固定 readiness
同时全部通过。

该结果只关闭 E1 标定文件门，不证明读针准确率。标定后的首条环境记录引用了新标定，
但固定高分辨率 `source` 的 MJPEG burst 返回 `frame_source_unavailable`；独立
`alpha-source-check` 仍确认 H.265 source 健康。E2 必须先修复并验证这一受控帧源边界，
不能把不可用样本计入 30 组白天对照。

## WS2021 E2 frame-source prerequisite checkpoint

2026-08-16 在不输出家庭画面、标定内容或读数值的前提下，为 go2rtc 增加固定按需
`gauge` 派生流：2560×1440 MJPEG、2 FPS。环境受控帧源固定消费该流，仍以一个
连续连接取得五帧。运行配置通过现有 0600 原子备份边界迁移，未改动 Xiaomi source
参数。

定向软件测试为 73 passed；实机单帧与单连接五帧 burst 均 PASS，尺寸一致。新的
gauge worker 记录不再是 `frame_source_unavailable`，而是在后续几何门安全拒绝为
`roi_out_of_bounds`。因此帧源前置阻塞已关闭，但 E2 尚未开始计数；下一步必须在
不泄露私人坐标的前提下复核 E1 ROI 映射，不能降低质量门或把该样本计入 30 组。

2026-08-16 第二次私人标定复现两只表盘 `geometry_roi_out_of_bounds`，确认不是单个
点击误差。读针器现根据圆形刻度几何恢复非 16:9 仪表平面比例，并为固定 1.3 倍
圆搜索窗口增加有界 padding；40 个 gauge 测试通过。私人五帧探测随后通过两只
表盘 ROI 几何门及温度圆匹配，湿度圆匹配仍严格拒绝为 `calibration_invalid`。
E2 仍为零组，下一步只需重新标记湿度表盘，不得放宽圆心 5% 或半径 8% 门限。

## WS2021 automatic-localization contract checkpoint

2026-08-16，按已批准的环境规格开始 Task 15。新增 i9 本地定位边界：固定 640×640
letterbox、单一候选、固定置信度/NMS、最小原图宽度和竖直姿态门；缺失、歧义、越界、
过小、姿态或模型输出异常均使用稳定代码 fail closed。定位结果只迁移 schema-v2 几何，
读数仍完全由既有确定性 OpenCV 门禁负责。

新增测试使用合成 JPEG 和数值候选，不含家庭画面、私人坐标、模型权重或运行配置。
定向扩大门禁为 `53 passed`，Python 编译与 `git diff --check` 通过。本检查点只证明
定位/迁移软件契约，不证明真实 WS2021 定位率、读针准确率或家庭场景安全。下一步为
15.2 隐私安全裁剪采集；原始家庭全帧不得持久化。

2026-08-16，Task 15.2 完成隐私安全采集边界。全帧只在内存中提供给隐私候选检查，
持久化接口只接收裁剪后的 JPEG；成人或皮肤候选框与仪表框相交、隐私后端异常、低清晰
度、过暗/过亮、越界、重复或存储异常均使用闭合结果拒绝。裁剪与元数据采用摘要文件名、
0600 原子写入，目录固定为 0700；公开状态只有聚合计数，不返回路径或样本身份。

新增测试均使用合成画面。Task 15 定向门禁为 `17 passed`；扩大后的 monitoring/gauge
套件在允许绑定临时 loopback 测试端口的环境中为 `124 passed`，Python 编译和
`git diff --check` 通过。该证据不证明真实成人/皮肤检测召回率，也不证明真实仪表定位；
下一步为 15.3 确定性数据集划分和有界增强。

2026-08-16，Task 15.3 完成本地数据集构建。私有裁剪先按摘要稳定划分 train/val，再只对
train 执行固定种子的有界旋转、缩放、亮度和位置增强；val 不增强。所有训练图固定为
640×640，标签和清单只含相对路径及闭合字段。公共负样本必须提供 HTTPS 来源和许可
标识；被篡改的摘要、尺寸元数据或疑似全帧来源均 fail closed。命令行只输出状态和聚合
计数，不输出输入/输出路径或样本身份。

专项数据集门禁为 `12 passed`，WS2021/gauge 相关扩大门禁为 `62 passed`，Python
编译和 `git diff --check` 通过。测试全部使用合成图；这不证明真实数据分布、检测精度
或负样本覆盖率。下一步为 15.4 固定 YOLOX 提交的显式本地训练、ONNX 导出和固定
OpenVINO FP16 转换。
