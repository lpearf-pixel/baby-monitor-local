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

2026-08-16，Task 15.4a 完成显式 i9 本地训练/导出工具。固定训练环境使用 Torch
2.2.2、独立 venv 和精确 YOLOX commit
`419778480ab6ec0590e5d3831b3afb3b46ab2aa3`；上游源码保持未修改。由于该提交官方
trainer 将设备硬编码为 CUDA，项目使用同一 YOLOX-Tiny 模型、损失和优化器的固定
CPU 循环，并关闭 W&B、远程日志和训练期网络。数据集同时补齐 YOLOX 直接可读的
COCO train2017/val2017 标注。

固定提交实机模型构造为 5,032,866 参数，合成 640×640 单批次已完成 CPU 前向、有限
loss 和反向传播。软件相关门禁为 `66 passed`，Python 编译和 `git diff --check`
通过。真实私有裁剪尚未采集，因此没有训练、导出或批准任何生产权重；随机烟测权重不能
关闭 15.4b。下一项可自动执行工作是 15.5 worker 集成，真实模型工件随后依赖真人摆放
仪表完成私有采集。

2026-08-16，Task 15.5 与 15.6a 软件门完成。Gauge source 在每个五帧 burst 的第一帧
只执行一次固定 640×640 定位，随后从仪表外框四边形和双圆布局细化几何，以透视迁移
schema-v2 标定，并将同一结果用于整组五帧。模型摘要、XML/BIN 摘要、FP16、输入和
输出形状均在加载前验证；缺失、歧义、越界、布局或推理异常直接 unavailable，不保存
或复用上次位置。功能默认关闭，只有私有模型通过后才在本地 settings 启用。

新增短命令覆盖当前标定位置采集、模型定位采集、数据集构建、训练、导出和工件检查。
采集持久化前使用既有 i9 人体姿态/人脸模型及局部皮肤比例门，任何隐私后端异常同样
拒绝；命令只输出闭合聚合计数。相关门禁为 `115 passed`，Python 编译、六个 Make
dry-run 和 `git diff --check` 通过。下一步 15.6b 必须由真人先确认无宝宝入镜，再执行
首个 30 秒当前标定位置采集；本文不声称已采集家庭资料或训练真实权重。

2026-08-16，在用户明确确认无宝宝入镜后完成 Task 15.6b 白天位置 1/5 的当前
schema-v2 标定位置采集。私有忽略目录稳定保存 60 组裁剪 JPEG/元数据配对；目录权限
0700、文件权限 0600，配对、闭合字段和 SHA-256 一致性检查 PASS。未读取、展示或提交
家庭图像，也未输出文件名、摘要、坐标或绝对路径。

本次运行同时发现 `duration-seconds` 原实现按尝试次数而非真实墙钟计算，实际超过预期
30 秒。采集循环已改为单调时钟截止并新增回归测试；相关定向门禁 `11 passed`，Python
编译和 `git diff --check` 通过。位置 1 的 60 组不能代替位置多样性；下一步仍为真人将
仪表竖直移动到白天位置 2/5，再执行同一 30 秒隐私采集。

2026-08-16，位置 2 已就绪后，位置 1 数据的首轮模型暴露训练增强尺度错误：目标宽度
45%–80% 与批准的实机约 10%–35% 不符。增强改为 10%–35%，补充固定 20 轮的仅采集
种子训练入口，并修复上游 YOLOX 导出子进程缺少固定源码路径的问题。重建数据集为
train 86、val 17、negative 0；20 轮训练、OpenVINO FP16 导出及精确工件检查均完成。

该种子在位置 2 仍严格返回 `gauge_not_found`。连续帧预测未达到 0.75 生产门，较低
候选还出现越界或不满足尺寸/姿态；位置 1 私有裁剪的 SIFT/边缘模板匹配和全帧圆形搜索
也没有形成唯一可靠候选。因此未降低生产阈值、未保存猜测裁剪、未把种子声明为最终
模型。下一步需要一次本地位置 2 框标注，再继续 30 秒隐私采集和后续位置循环。

2026-08-17，WS2021 有效训练期间用户报告 Dashboard 实时影像消失。训练被优先停止，
有界诊断确认 Dashboard、gauge 和 visual launchd job 仍在，但 source 为 0 字节、
visual 指标 stale。`alpha-restart` 随后按设计拒绝 `go2rtc pid identity mismatch`；
只读身份核对确认 1984 监听者确属当前仓库 go2rtc，但运行时 PID 所有权记录缺失。

停止该已确认的孤立进程并以当前固定配置重新启动后，`make alpha-source-check` 返回
PASS：`cs2+udp`、H.265、2560×1440 source、1280×720 live；visual 指标恢复为
available、5 FPS。Ollama bridge 仍独立不可达，不影响此次视频恢复结论。操作手册
新增了 fail-closed 排查和安全接管步骤；未修改摄像头 URI、FFmpeg 参数、隐私门或
业务代码，也未记录地址、凭据、画面或绝对路径。

2026-08-17，用户批准音频/哭声第一阶段隐私边界：家庭音频仅在有界内存中处理，永不
持久化，只允许文字事件与聚合指标。新增正式设计及分阶段计划；A1 严格契约和集中设置
按 TDD 完成。新增闭合 observation/failure 状态、默认关闭的固定 mono 16 kHz PCM
边界、15 秒内存上限、5/10/30 秒时序设置与相对本地模型路径校验。定向契约门禁
`37 passed`，Python 编译与 `git diff --check` 通过。该证据不证明真实音轨可用或哭声
准确率；当前下一项为 A2 有界内存 PCM source，实机音频门仍由上游音轨阻塞。

同日，A2 有界内存 PCM source 按 TDD 完成。固定 loopback-only FFmpeg 命令只选择音轨，
带 5 秒读取超时并输出 mono 16 kHz s16le；启动失败、EOF、stale、解码异常和畸形半采样
只返回闭合失败码。frame-aligned ring 严格裁剪到 15 秒上限且没有持久化接口。音频 A1-A2
定向门禁 `23 passed`，Python 编译和 `git diff --check` 通过。测试仅使用生成字节与 fake
process，不证明真实 Xiaomi 音轨存在；下一项为 A3 响度和动态底噪。

合并远端依赖闭环证据：干净临时 Python 3.11 环境通过 71 项定向部署/API 测试、741 项
完整 Python 测试、73 项 Node 测试、`pip check`、编译、Shell、Make dry-run 与
`git diff --check`。修复为当前 Starlette TestClient 增加 `httpx2`，保留旧兼容依赖，
并让 `alpha-install` 安装验收 extras。该软件证据与后续 i9 实机证据并存，不倒退或替代
WS2021、Guardian 或音频阶段的最新状态。

同日，音频 A3 响度与动态底噪按 TDD 完成。生成的静音、变化底噪、音调和响声验证
s16le RMS/dBFS 有界计算；底噪只在 gate 关闭时按集中设置适应，响声不能抬高基线，
分类器前输出只允许 `quiet` 或 `sound`。定向门禁 `20 passed`；未读取、保存或提交任何
家庭音频。下一项为 A4 固定 ONNX 分类器边界，软件测试不能替代真实哭声准确率。

同日，音频 A4 固定 ONNX 分类器软件边界按 TDD 完成。模型必须位于项目本地相对路径，
SHA-256 在 runtime 创建前流式核对，符号链接逃逸、缺失、摘要不符、异常、非有限或错误
shape 输出均 fail closed。输入固定为一秒 mono 16 kHz float32 waveform；低于阈值仍为
`sound` 且不持久化分数。定向门禁 `22 passed`，仅使用合成模型字节和 fake runner。
生产模型、许可证与实机准确率仍未批准；A5 确定性状态机可继续。

同日完成 Xiaomi 实机音轨发现。固定生产 `source` 同时暴露 HEVC 视频与 Opus 音频，
新增 loopback-only `audio_analysis` 仅暴露 Opus；两秒音频成功解码为 mono 16 kHz PCM
后直接丢弃，未保存、播放或输出任何家庭音频。强制 Xiaomi TCP 握手失败，因此继续保持
现有自动/UDP 传输。实机还确认 launchd 后台上下文会发生 UDP timeout，而当前交互用户
会话可稳定建立音视频源；这通过了音轨存在性与短时解码门，不替代 A7、持续稳定性或
家庭哭声准确率验收。

同日，音频 A5 确定性状态机按 TDD 完成。连续 5 秒接受的哭声观察开启 normal，10 秒
升级 high；连续可用的非哭声输入按固定恢复窗关闭事件，30 秒内重复发作合并为一次 high
升级。`unavailable` 不推进正向推断或恢复，重复时间幂等，乱序/冲突时间拒绝且不改变
状态；重启只恢复已开启 normal/high，不恢复短候选计时。新增 9 项状态机测试，音频、
契约和部署扩大门禁共 `79 passed`，Python 编译与 `git diff --check` 通过。下一项为
A6 文字事件与通知 outbox 集成；本阶段未保存或读取家庭音频。

同日，音频 A6 文字事件与通知 outbox 集成按 TDD 完成。只有状态机接受的转换可生成
确定性、幂等的 `audio_cry_candidate` 事件；固定摘要、severity、置信度、规则版本和单个
闭合 transition 标量与通知队列在同一 SQLite 事务写入。队列保持因果顺序，重复转换不
重复创建事件或通知，接口不接受音频样本、路径、模型文字或媒体。EventStore schema
升级为 v4；音频、事件、契约和部署扩大门禁 `93 passed`，Python 编译与
`git diff --check` 通过。下一项为 A7 独立 worker、launchd 与无副作用软件门。

同日，音频 A7 独立 worker 与安装门完成。worker 组合固定 loopback 解码、动态响度门、
固定 OpenVINO/ONNX 分类边界、确定性状态机、原子事件 sink 和 mode-0600 闭合状态文件；
拥有独立 launchd job 与 `alpha-audio-status`/`alpha-audio-test`，音频失败不重启任何同级
服务。事件持久化失败会回滚状态并只发布 `internal_error`。自动音频门 `59 passed`，
完整 Python `879 passed`、前端 `73 passed`，编译、Shell、Make dry-run 与 diff 检查
通过。i9 安装后 job 在 `audio.enabled=false` 下退出 0 并保持停止，没有执行家庭音频分析、
生成事件或发送通知。A8 仍需批准的生产模型/许可证和真人监督场景。

同日，WS2021 collection-seed 训练闭环修复完成。Intel CPU loop 不再继承 YOLOX warmup
产生的零学习率，最佳 state 使用独立 clone，避免后续 epoch 覆盖；确定性非均匀背景和
64 个项目生成负样本替代单色 padding 偏差。修正后的 20-epoch bootstrap、OpenVINO
FP16 export 和精确工件检查均通过；WS2021/gauge 专项 `78 passed`，完整 Python 门的
`879 passed` 也包含这些改动。该结果只证明训练/导出链，不能替代实时定位、位置 2–5、
夜间/IR 或 E2 人工对照。

随后恢复的生产源完成一次无落盘实时定位诊断。20-epoch seed 从旧的无候选提升为 15 个
阈值候选、NMS 后 3 个，最高聚合置信度 0.862953；但三个候选均 `gauge_box_invalid`，
严格外框/双圆布局通过数为 0。候选布局验证因此前移到 ambiguity 判定之前：只有唯一
满足基本框与批准布局的候选才可返回，多候选或全失败继续 fail closed，相关扩大门禁
`71 passed`。再次使用 schema-v2 固定标定框采集时，11 帧全部被人体/人脸/皮肤隐私门
拒绝，accepted 0、持久化 0；没有绕过隐私门或降低 0.75 阈值。

2026-08-17，因 WS2021 已确认固定在画面右下角，新增固定 schema-v2 ROI 路径和连续帧
稳定器。自动定位开启时，固定 ROI 优先于 OpenVINO 检测器；同宽高比的 2560×1440 到
1280×720 缩放通过，宽高比漂移、无效几何和未稳定帧 fail closed。gauge/environment
软件回归 95 passed，模型工件检查和实时源检查均 PASS。该证据不替代真实读表、30 组
白天对照、夜间/红外/反光/遮挡/移动、M2/Ollama 离线、24 小时、三浏览器或 72 小时门。

2026-08-18，实时 5 帧 burst 中有 3 帧达到固定 ROI 稳定阈值；Task 5 的有界内存自适应
双圆几何已提交为 `c001507`，reader 专项 20 passed、完整 gauge 79 passed。同一 burst
仍全部以 `calibration_invalid` fail closed。诊断为 humidity 无 0.25R/12% 范围内候选，
temperature 最近圆心偏差约 0.393R（门限 0.25R）；不是可安全放宽的代码缺陷。
当前读表门仍未通过，不能把 OCR 接到生产链；下一步必须在当前视角重新执行 schema-v2
标定。

随后在不改变标定数据的前提下增加 calibrated-center pointer fallback，并在白天红色
指针掩码较弱时改用 grayscale temperature needle signal。gauge 专项为 `81 passed`；
实时 5 帧现可得到约 `29.3C / 59.5%RH`、置信度 `0.75` 的 available smoke reading。
该结果不降低置信度门，也不证明 E2 准确率或 OCR。用户已决定将 30 组白天人工对照
延后，主线下一项改为 E3 的夜间/红外反光/遮挡/表盘移动 fail-closed 验收。

E3 软件专项已复核：夜间灰度读针、无指针、过暗、反光、遮挡、超界移动和 burst 内
不一致移动共 `6 passed`。这些测试只证明 fail-closed 合同，不替代真实夜间/红外/反光
和物理移动实机验收。

主线继续执行 E4 软件独立性复核：WS2021 source、视觉 frame-health/worker、gauge
worker launchd、Ollama tunnel/visual worker 的离线与独立失败路径共 `64 passed`。
该结果不替代实际断开 M2/Ollama 后的 i9 实机验收。

随后 i9 readiness 检查 8 项均 PASS，`make alpha-guardian-test` 4 项均 PASS；gauge
和 visual launchd 当前 running。Ollama tunnel 当前虽被 launchd 保持 running，但最近
一次退出码为 `255`，因此不能宣称 E4 实机离线门通过；下一步需在不影响 gauge 的前提下
记录一次受控 M2/Ollama 断开与恢复。

后续一次现场检查发现 go2rtc、Dashboard 和 Ollama bridge 短暂不可用，但各 worker 仍由
launchd 独立保持；执行既有 `make alpha-start` 恢复后，readiness 8/8、`alpha-source-check`
恢复 PASS（H265，2560x1440 -> 1280x720），当前 5 帧 WS2021 实读 available，约
`29.38C / 60.00%RH`、置信度 `0.8333`。这证明可恢复性和独立 worker 行为，不替代受控
M2/Ollama 断开恢复门。

尝试受控卸载 `com.babymonitor.ollama-tunnel` 后，断开窗口内 gauge 捕获链也短暂不可用，
随后使用 `make alpha-start` 恢复；readiness 和 source-check 恢复 PASS，WS2021 读数恢复
available（约 `29.58C / 59.90%RH`、置信度 `0.8333`）。这证明恢复路径，但不能宣称
“断开期间 gauge 独立”已通过；下次需在真实 i9 终端中隔离 tunnel 进程，避免影响 go2rtc。

E5 短时前置检查：gauge 与 environment-watchdog launchd 均 running、各自 `runs=1` 且
无退出码；visual realtime 维持 5 FPS（P50 105.5ms、P95 121.7ms、max 129.2ms），
`alpha-source-check` PASS。Ollama bridge 仍 unreachable，因此 E4 先于 E5 长测继续保持
未完成，尚未启动 24 小时测试。

最新 tunnel 诊断窗口显示失败根因是配置的 M2 SSH 主机多次 timeout/host down，
不是 i9 gauge 或固定配置错误。tunnel launchd 仍按 KeepAlive 重试；该外部主机不可达
期间不再反复重启 Alpha，待 M2 SSH/Ollama 恢复后再执行 E4 断开/恢复门。

2026-08-18 进一步核对发现必须长期避免的转发方向错误：i9 launchd 固定使用 `-L`
（i9 `127.0.0.1:11435` → M2 `127.0.0.1:11434`），而现场已有的 M2→i9 SSH 登录
并不等价于该端口转发。旧 ssh 进程曾保持 launchd `running`/监听记录，但 `/api/tags`
实际为 `http=000`；因此 launchd 状态不能单独证明 bridge 健康。已停止失效旧监听并
释放 i9 11435。受控恢复可从 M2 重连 `-R 127.0.0.1:11435:127.0.0.1:11434`，再以
HTTP 200 和 `alpha-visual-status` 的 `reachable` 双重证据确认；恢复后应回到正式
i9→M2 `-L` 配置。该记录不证明 E4 真实断开/恢复门已通过，E4 仍待完成。

随后用户在实际 `kandysmith` i9 终端完成 E4 受控验证：短暂停止 M2→i9 反向 SSH
后，Ollama bridge 按预期 fail-closed，而摄像头、go2rtc、gauge、存储/状态链路继续
正常；恢复 SSH 后 i9 `127.0.0.1:11435/api/tags` 返回 HTTP 200。结合前置 `117 passed`
软件独立性门，E4 标记 PASS。下一阶段转入 E5 24 小时环境稳定性门；该证据仍不替代
24 小时持续运行、三浏览器高清验收或最终 72 小时发布门。

E5 于 2026-08-18 在实际 `kandysmith` i9 终端开始。权威基线：Dashboard health
`status=ok`，Dashboard/go2rtc/gauge/visual workers 均 running，visual 5 FPS、P95
约 `106.713ms`，`alpha-source-check` PASS（H.265，source `2560x1440`，live
`1280x720`，接收字节非零）。Ollama tunnel 当前可暂时断开；E4 已证明其不会停止
环境链路。24 小时窗口尚未完成，期间不得宣称 E5 PASS。

E5 结束检查由实际 i9 终端完成：过去 24 小时 `environment_readings` 共 1,414 条，
覆盖 `2026-08-18T04:16:35Z` 至 `2026-08-19T04:16:06Z`；最大相邻读数间隔为
`82.105s`。Dashboard health、go2rtc、gauge/visual worker 与两次 source-check
均正常，未发现调度积压或 worker 异常退出。按“无积压”而非“每次严格 60 秒”的
验收定义，E5 标记 PASS；82 秒间隔作为后续性能观察项保留，不降低任何 fail-closed
门槛。

随后用户完成 P1 三浏览器高清实机检查：M2 Chrome、M2 Safari 与 iPhone 浏览器均可
打开并查看实时画面。iPhone 排版尚未优化但不影响查看，因此 P1 标记 PASS；移动端
布局列为后续 UX 改进，不阻塞 Guardian 主线。下一阶段进入 P2 正常照护条件下的真实
Baby Guardian 观察门，必须有成人持续监督，不得摆拍危险姿势。

用户确认当前没有 Baby，P2 真实 Guardian 观察门暂缓，先推进 P3 音频/哭声阶段。
音频软件门 `make alpha-audio-test` 通过 `59 passed`；`audio_status=unavailable` 是
生产音频默认关闭的预期状态。A1–A7 已完成，A8 仍需批准的生产模型/许可证与监督场景；
任何家庭音频继续只允许有界内存处理，永不持久化，只保存文字事件和聚合指标。

随后由 `kandysmith` i9 实际终端确认反向映射已恢复：访问 i9 本地
`127.0.0.1:11435/api/tags` 返回 HTTP 200，M2 本机 Ollama 仍保持
`127.0.0.1:11434`。该证据证明 bridge 可用，但不替代 E4 受控断开、恢复及独立性
验收；反向 SSH 会话必须保持运行，后续仍应回到正式 i9→M2 `-L` 配置。

随后连续 3 次独立 5 帧 burst 均 available：温度约 `29.32C +/-0.01C`、湿度约
`59.46%RH +/-0.02`，每次置信度 `0.75`、温湿度各 5 个有效样本。该结果只证明短时
软件/源流稳定，不替代真人参考温湿度计的 30 组 E2 对照。

分层诊断显示透视校正本身成功；湿度圆的清晰度/圆检测失败，温度圆的 ROI 越界。该
结果说明当前 schema-v2 双圆几何与实时画面不一致，按 fail-closed 要求先重新标定，
不绕过几何门禁，也不提前接入 OCR。

2026-08-19 在文档面更新交接：新增 `docs/superpowers/plans/2026-08-19-voice-care-v1.md`，
用于将 Voice Care v1 Gate V0 拆分为可独立交付的小阶段（音频源可行性、独立探针、
OPUS 合成兼容、停止清理与服务隔离）。本阶段未执行额外代码变更或实机验证；
仅补齐计划体系与状态引用，确保 `docs/NEXT.md`、`docs/STATUS.md`、`SUMMARY.md`
的顺序与依赖保持一致：在 A8 真场景前先完成 Gate V0 前置可行性与离线隔离验证。

2026-08-20 完成 Voice Care v1 Gate V0。新增固定 loopback 的脱敏媒体/接收探针，
真实 Xiaomi source 为 HEVC+Opus，`audio_analysis` 为 Opus；入站 48 kHz 双声道由
固定 FFmpeg 边界归一化为 mono 16 kHz s16le。60 秒门解码 1,920,000 字节，10 分钟
门解码 19,200,000 字节，均立即丢弃且退出后无 `audio_analysis` ffmpeg 残留。
合成 Opus 软件门 `61 passed` 并完成一次真实内存 encode/decode PASS；既有音频门
`69 passed`；完整 Python `919 passed`、Dashboard Node `73 passed`。FFmpeg 8 的
RTSP 输入使用已实测支持的 `-timeout`，worker 在停止或异常
路径显式释放 decoder。前后 visual、gauge、environment-watchdog PID 不变，Dashboard
health 保持 OK，realtime visual 保持 5 FPS/available。该证据不批准生产 cry/ASR 模型、
说话人身份、家庭准确率或 Baby Care 写入；A8 仍等待模型/许可证与真人监督场景。
2026-08-20，反复无画面与 `Bootstrap failed: 5` 被拆成两个独立故障。进程证据显示
launchd 管理的 go2rtc 持有 1984/8554，而旧启动回退又创建第二个不能监听的 go2rtc，
PID 文件因此指向错误进程。macOS 启停现改为唯一用户级 launchd 所有者：已加载但 API
不健康时只 kickstart；bootstrap 失败直接闭合失败；不再直启回退、不按端口杀进程，且
API 只有在 launchd PID 的精确命令和监听所有权同时匹配时才被接受。非 macOS 路径保留
原精确 PID 身份契约。

TDD 回归先稳定重现 3 个错误，修复后生命周期测试 8 项、原启停测试 30 项通过；完整
Python 门为 927 项，前端 73 项、Shell/plist/Make/diff 检查
均通过。安装到 i9 后，完整停止/启动与第二次幂等启动无 sudo、无 I/O error、无身份
错误，PID 保持不变且精确进程数为 1。摄像头主机可达、防火墙允许当前二进制，停止
visual/gauge/audio 消费者后单独探测仍为 `SOURCE_OFFLINE`，日志只显示 CS2 UDP 超时。
因此软件所有权缺陷已关闭，但画面恢复仍要求摄像头本体重启后重新通过 source gate；
不得以 Dashboard 健康或进程运行替代真实字节、编码和尺寸证据。

同一切片随后增加 `make alpha-go2rtc-restart` 单组件入口。实机运行返回
`go2rtc_restart=PASS`，go2rtc PID 已变化，而 Dashboard、visual、gauge、audio PID
全部保持不变；再次 source check 仍为 `SOURCE_OFFLINE`。这证明恢复命令的服务隔离，
不证明摄像头源已恢复。

随后继续分离摄像头、路由与进程身份。已获系统许可的最小 CS2 探针能收到 24 字节
LAN-search 响应，而新编译的等价两阶段探针在第一阶段超时；摄像头地址、请求字节和
应用防火墙均一致。签名检查确认原 app 的 designated requirement 是随重建变化的
`cdhash`。安装器现生成固定 `Go2RTC.app`，以 bundle identifier
`com.babymonitor.go2rtc` 作为显式 designated requirement，并在签名后以相同 requirement
验证。launchd 与精确命令检查均使用 app 内 executable。

实机先通过 LaunchServices 完成稳定身份登记；随后 `alpha-source-check` 返回 PASS：
`cs2+udp`、H.265、source `2560x1440`、live `1280x720`、接收字节非零。恢复完整 Alpha
后 visual 为 5 FPS/available，gauge 与 Dashboard 正常，Ollama bridge reachable。
一次 `alpha-go2rtc-restart` 后同一源门再次 PASS。最后执行不重编译的 `ensure` 刷新
app 签名，再做 launchd-only restart，第三次源门仍 PASS，证明固定 requirement 跨安装
刷新保留。生产音频仍按批准设置 disabled；launchd 未运行且上次退出码 0 是预期，
不是本次恢复故障。以上证据不证明家庭场景准确率、WS2021 E2/E3 或最终 72 小时门。

提交前完整验证为：Python `931 passed`，Dashboard Node `73 passed`，相关 go2rtc/
launchd 文件 `50 passed`，新增 Guardian 安装身份门 `2 passed`，Python 编译、Shell
syntax、plist 解析、Make dry-run、
`git diff --check`、新增 diff 敏感字面量扫描和状态冲突扫描均 PASS。安装态
`make alpha-guardian-test` 的 repository/software/installation/service/media/isolation
共 19 个阶段全部 PASS，未发送真实通知、未生成风险事件、未写生产 evidence。

2026-08-20 批准 Voice Care v1 本地模型架构并完成实施计划拆分。Gate V1 固定使用
Silero VAD 打开最长 8 秒、500 ms pre-roll、800 ms 终止静音的内存 utterance；在 i9
上对官方 OpenAI Whisper `base`/`small` 做合成普通话门禁，且 ASR 结果必须以规范化的
精确 `小小` 开头；说话人候选为 SpeechBrain ECAPA，响应使用固定 macOS 系统语音。
家庭原始音频和普通 transcript 仍不得持久化。Baby Care 当前累计开发线经只读核对为
`codex/m4-birth-ready-operations`，规划时 head 为
`53997b9c24de75b4850b4e193ef89ff755be9913`，M0–M3 完成、M4 Task 3 待执行。
Voice Care 计划因此允许 Baby Local Tasks 1–3 与 Baby Care M4 并行，但 Baby Care
contract/pairing/write 分支只能从 M4 完成且 exact-head CI 通过的提交创建；两项目不得
互相直接写数据库，也不得借此修改或合并 `main`。

2026-08-21 完成 Voice Care Gate V1 Baby Local Task 1。提交序列从 `8f9044b` 到
`1cc1f51` 建立严格 disabled-by-default 设置、四项封闭模型注册表、canonical source/
runtime manifest、固定 ignored runtime 路径与原子安装边界。三轮定向复核最终关闭了
任意路径、伪造来源、错误通用 tar 处理以及不可转换 OpenAI `model.pt` 输入：Whisper
现固定到两个独立 Hugging Face Transformers revision，使用 manifest 校验后的完整本地
目录转换，并验证包含 `vocabulary.json` 的 faster-whisper 布局。控制端新鲜验证为
61 passed、Python compile 与 `git diff --check` PASS。没有下载、生成或启用真实模型；
真实 source manifest 记录、i9 CTranslate2 转换和准确率仍是后续明确门禁。下一项为
Task 2 的纯内存 VAD 与最长 8 秒 utterance collector。

2026-08-21 完成 Voice Care Gate V1 Baby Local Task 2。`ce13d83` 添加固定帧
16 kHz mono s16le VAD 边界与 bytearray-only collector，精确执行 500 ms pre-roll、
800 ms terminal silence 和 8 秒上限；模型异常、非有限/越界/错误 cardinality 与 malformed
frame 均 fail closed。独立复核发现原 zeroization 测试在 clear 后检查空数组而无效，
`d750f05` 用 clear 时快照证明 reset、close、validation-error 与 terminal-take 均先覆盖为
零再清空，同时返回的 immutable PCM copy 保持完整。控制端新鲜验证为 23 passed、Python
compile 与 `git diff --check` PASS。测试仅使用生成 PCM，不证明真实 Silero、家庭语音
准确率或生产 worker；Task 3 的本地 Whisper/exact-wake 门是下一项。

2026-08-21 完成 Voice Care Gate V1 Baby Local Task 3 软件切片。`4dc87cf` 添加只读
本地 base/small ASR、精确 `小小` 唤醒与生成/公开语料聚合门；`7ef10c2` 补齐固定 ignored
布局的无下载安装入口、六类 benchmark-only typed slots、近似唤醒和坏 WAV/symlink/
aggregate-only 覆盖；`8de7b7b` 将 CTranslate2 converter 固定到当前 Voice venv Python
同目录并对缺失、symlink、不可执行 fail closed。两轮独立复审最终 clean。控制端新鲜
验证为 90 focused、136 adjacent passed，Make dry-run、Python compile 与 diff check
PASS。真实 pinned 模型尚未物化，installed-i9 24/48 合成语料准确率与 p95 延迟门尚未
执行，因此 Task 3 总体仍在 Step 5，Voice Care 保持 disabled。

2026-08-21 完成 Voice Care Gate V1 Baby Local Task 3 installed-i9 门。`99eb8f7`
新增可重建的隔离 Whisper 转换环境、固定依赖、安装前 symlink 路径门和仓库自有
NumPy 转换适配器，避开 Intel macOS 上 CTranslate2 与转换期 PyTorch 的同进程冲突；
运行期不加载 PyTorch，也未把转换依赖放入生产 worker 启动路径。两个固定 revision
均从已验证本地 source manifest 转换并安装到 ignored runtime。最终四速率 72 条 macOS
生成普通话门中，`base` 为 24/24 exact wake、0/48 false wake、24/24 typed slots，p50
1,873 ms、p95 2,196 ms并被选中；`small` 虽为 24/24 wake/slots，但有 1/48 false wake，
p95 5,772 ms，按 fail-closed 拒绝。生成 WAV 仅存在于临时目录并立即丢弃，未使用或
持久化家庭音频。新鲜 focused 门为 114 passed，完整 Python 为 1,024 passed，转换器
安装/check、pip check、Python compile、三个 Make dry-run 与 `git diff --check` 均 PASS。
该证据只证明本机合成语音，不证明家庭成人、距离、噪声或说话人身份准确率；生产
Voice worker 仍 disabled。下一项 Voice Care 产品切片为 Baby Care-owned Task 4，但须
等待 Baby Care M4 的 verified exact head。

2026-08-23 完成 Voice Care Gate V1 Baby Local Task 6。`84e9a17` 从 Baby Care
合同提交 `bb1337226c1948695159d14199c9bb73cdaf115a` 逐字节 vendored schema 与合并
golden corpus，并固定 SHA-256；Python 合同拒绝非 canonical JSON、重复键、额外身份、
transcript/audio 字段及无时区时间。确定性 grammar 只接受批准的喂奶开始、更新、结束、
确认与取消短语；未知单位、自由文本、畸形中文数字与状态冲突均 fail closed。新鲜门禁为
19 focused、103 adjacent passed，compile/diff checks PASS；Baby Care 只读 verifier
返回 `CONTRACT_OK`。该证据不证明家庭成人说话人识别或真实交付，Voice worker 仍
disabled；下一项为 Task 7 本地说话人 enrollment 与 Keychain-backed hybrid identity。

2026-08-23 完成 Voice Care Gate V1 Baby Local Task 7 软件边界。`e850b8d` 新增不经
argv 的 macOS Security.framework generic-password 适配器、Keychain 保护的 32 字节
AES-GCM key、canonical mode-0600 加密 profile、3–5 条成人合成 enrollment 质量门以及
verified/uncertain/mismatch/not-enrolled 四种闭合状态。短、静、噪声、重叠、claim 冲突、
篡改、未知 schema、symlink 和删除路径均有合成回归；18 focused、121 adjacent、1,061
完整 Python 测试以及 compile/diff checks PASS。真实 Security.framework 仅做了不存在项的
只读探测，没有写入或删除用户 Keychain。原计划的 `cryptography==50.0.0` 在官方 PyPI
不存在，已修正为可安装的固定 `48.0.1`；另发现主 venv 既有 Transformers 转换依赖残留
导致独立 `pip check` 不一致，此项不属于生产 Voice runner，未通过删除包掩盖。Voice
Care 仍 disabled；ECAPA 安全转换/安装、真实成人 enrollment 与家庭准确率未验收。下一
软件切片为 Baby Local Task 9 signed delivery 与 bounded structured outbox。

2026-08-24 完成 Voice Care Gate V1 Baby Local Task 9 软件边界。`b8f0002` 新增
Keychain-backed Ed25519 设备身份、与 Baby Care 完全相同的 canonical 签名字节、一次性
pairing challenge 签名、严格封闭语义响应客户端，以及 mode-0600/AES-GCM 加密的有界
SQLite outbox。重复 request ID、断网、重启、密文篡改、过期临界点和 ambiguous delivery
均有 fail-closed 回归；过期或不明确状态只进入 reconciliation，queued 永不冒充 saved。
新鲜门禁为 27 focused、108 adjacent Voice Care、1,088 完整 Python 测试，compile/diff
checks PASS；同一固定签名向量在 Baby Care `9b4f150` 的 53 项合同测试通过。未写真实
Keychain、未访问生产 endpoint、未写 Baby Care、未使用家庭音频。Voice Care 仍
disabled；下一软件切片为 Task 10 fixed TTS、独立 worker 与部署门。

2026-08-24 完成 Voice Care Gate V1 Baby Local Task 10 软件边界并提交 `31e8332`。
固定八种 Baby Care 语义短句只通过 stdin 进入 macOS `say`，播放音量固定 0.35，采集在
播放前 duck、播放后守卫 0.5 秒，取消或输出失败只降级 Voice。内存流水线组合 ASR、精确
唤醒、成人声明、speaker state、封闭喂奶 grammar、Ed25519 签名、加密 outbox 与 Baby
Care response；状态不含 transcript、profile、分数、路径或配置。新鲜证据为 Voice 140、
frontend 73、Guardian-focused 133、完整 Python 1,106 passed，shell/plist/Make/compile/diff
checks PASS。隔离 worktree 的 `make alpha-guardian-test` 为 13 PASS / 6 FAIL：缺失该
worktree 自己的 `.local` go2rtc app、private runtime、installed launchd 和 realtime model，
不是软件回归；source 和 sibling services 通过。Voice 仍 disabled，真实 TTS/Keychain/
护理写入未执行；部署到真实 i9 checkout 后须重跑 installed 门。下一自动切片为 Task 11
cross-repository synthetic Gate V1。

2026-08-24 完成 Voice Care Task 11 本地跨项目合成 Gate V1。Baby Local `e4cd5d5`
新增 2 项组合验收：纯合成 PCM 经过 VAD、精确唤醒、ASR 结果、成人声明、speaker state、
canonical Ed25519 签名、mode-0600/AES-GCM outbox 与固定语义反馈；瓶喂、亲喂、取消、
身份不匹配均闭合，断网后只重试完全相同的加密签名字节，SQLite/status 不含 transcript、
音频或 profile ID。Baby Care `bca9b9e` 新增 Node 24 + disposable PostgreSQL 16 的 2 项
权威验收：Dad 通过认证租约 API 接手，瓶喂提交/重复交付/既有 revision 更正、亲喂提交、
取消、身份不匹配与提交失败均符合预期。合同 digest 5/5，Baby Local 完整 Python 1,108、
frontend 73 passed；Baby Care lint/typecheck/build PASS、完整 458 passed / 115 opt-in skipped、
真实 PostgreSQL 2/2。隔离 worktree installed Guardian 仍为 13 PASS / 6 FAIL，缺私有安装/
模型资产，未声明安装态通过。未使用家庭音频、真实 Keychain 或生产数据库；Voice disabled。
下一门为双分支推送与 exact-head CI，再在真实 i9 checkout 部署复验。

2026-08-24 Voice Care Gate V1 双分支已发布并通过 exact-head CI。Baby Local 首轮 run
`32679703106` 暴露两项 CI portability 问题：浅克隆使敏感 diff 门无法取得基线，旧测试
硬编码 `.venv-alpha/bin/python`；`c554334` 以完整 checkout history 和 `sys.executable`
修复，完整 Python 1,109 passed，run `32680519119` 全绿。Baby Care 首轮 run
`32679908753` 暴露 M5 restore sanitation 已正确返回 Voice lease/session 两项计数但旧
M4 期望遗漏；`53e69d4` 只补齐安全计数期望，operations 148 passed / 4 skipped，run
`32680603091` 的 static、unit、integration、build、production Compose 5/5 全绿。两次
失败均未降低验收标准；未创建 PR、未 merge、未修改 main。下一项仍是把接受的 Baby
Local head 部署到真实 i9 checkout 后重跑 installed Guardian 门；Voice 保持 disabled。

2026-08-24 完成 Voice Care Gate V1 实际 Intel i9 安装验收。Baby Local 最终发布 HEAD
`614ea69` 部署到保留私有 runtime 与模型的根 checkout；安装更新和受控重启后，Dashboard
健康、Xiaomi H265 source check PASS、visual worker 保持 5 FPS、Voice launchd 以
`voice_disabled` 正常退出。首次 `make alpha-guardian-test` 为 18 PASS / 1 FAIL，唯一失败
是 M2 Ollama bridge：旧临时映射已消失、受限 launchd job 被持久禁用且目标使用陈旧 DHCP
地址。将目标改为同一 M2 的稳定 Bonjour 身份前，先逐项确认新旧 SSH host key 3/3 完全
匹配；随后追加哈希 known-host 别名并重新启用用户 job。11435 `/api/version` 与 `/api/tags`
均返回 HTTP 200，最终同一 installed 门为 19 PASS / 0 FAIL。未改业务代码、未启用 Voice、
未保存家庭音频、未运行真实 TTS/enrollment/Baby Care 写入。下一门为本地 ECAPA 安装和
两名成人的私有监督 Gate V2。

2026-08-24 完成 Voice Care Gate V2 的本地 ECAPA 运行时切片。Intel i9 建立独立固定
版本 SpeechBrain 环境，显式获取并校验固定 ECAPA 工件，通过单一有界持久子进程接收
内存 PCM；模型加载不再修改不可变工件，输出显式做 L2 归一化。当前实机合成语音门
5/5 返回有限 192 维 embedding，p50 284 ms、p95 311 ms，且
`raw_audio_persisted=false`。新鲜软件门为 Python 1,156 passed、前端 73 passed；正式
安装目录的 Guardian 门仍为 19 PASS / 0 FAIL。隔离功能 worktree 的同一门为 13/19，
6 项仅因该 worktree 没有私有 launchd/视觉模型安装资产，不作为生产回归。Voice 继续
disabled；未使用家庭音频、未登记成人声纹、未访问 Baby Care 写接口、未设置身份阈值。
下一切片为另行批准的 replay/overlap 质量与 Dad/Mom 私有监督 enrollment/accuracy。

同日发布 Voice Care Gate V2 ECAPA 运行时实现。首轮远端 `37287b1` / run
`32699054840` 的 Linux Python 门为 1 failed / 1,155 passed：新测试错误依赖本地私有
`.venv-alpha` 路径，CI checkout 在进入产品代码前退出。`7dd0155` 改用当前测试解释器，
保持临时无 runtime 项目和原 fail-closed 断言；本地定向 9/9、部署命令 39/39 通过。
修正后的 exact-head run `32699249559` 全绿，包括 Python、前端、schema、编译、shell 与
go2rtc cross-build。未降低验收标准，未创建 PR、未 merge、未修改 main。

2026-08-24 将 Voice Care Gate V2 重新收敛为 ASR-first。新增最大 20 条、每条最多
8 秒的固定短句 AES-GCM 私有语料库，专用 key 只允许进入 i9 Keychain；官方 Silero
v6.2 ONNX 工件先经 manifest/digest 校验，再以固定 16 kHz/state/context 合同运行。
校准命令支持 Silero 分段、一次 6 句 batch、单句固定 8 秒存储和同一密文语料的
Whisper base/small 聚合评测，输出不含 transcript。真实 Xiaomi source PASS，独立 30 秒
采集连续取得 960,000 字节；监督 batch 的官方 Silero 结果为 0 spans，正确无写入。
随后固定 8 秒采集成功但 Keychain 发布返回 macOS OSStatus -25308（当前自动化上下文
不允许用户交互），因此无 corpus 文件、无专用 key。下一步必须从登录用户 Terminal
执行一次固定短句采集；Voice 保持 disabled，speaker/enrollment/Baby Care 写入继续阻塞。
本切片新鲜软件门为 Voice Care 209 passed、完整 Python 1,229 passed；Python compile、
Make dry-run 与 `git diff --check` 均通过。

2026-08-24 Voice Care Gate V2 ASR-first real-device checkpoint. Commit `de499b7` added
the signed `com.babymonitor.voice-keychain-helper` boundary and copied the existing
32-byte calibration key in memory from legacy v1 to helper-owned v2 without rewriting
the encrypted corpus or deleting v1. A one-shot user launchd probe ran twice with exit
0 and returned only `key_state=available`, `key_bytes=32`. Commit `f61e2ed` ran the
closed base/small x baseline/no-hotwords/care-hotwords/beam10 matrix on the same six
encrypted clips. No candidate passed: the best base care profiles were 5/6 exact, 6/6
wake, P95 2,246/2,145 ms and missed only public prompt ID `feeding_start_dad`; all small
candidates failed accuracy and latency. Commit `305232f` added aggregate Silero signal
diagnostics: its generated Mandarin control and five private prompts had one span,
while `negative_weather` had two; no gain was applied because private RMS was not 12 dB
below control. Fresh focused gates were 39 and 15 passed, and the final Voice suite was
233 passed. No raw audio, transcript, key, corpus path or Baby Care write was emitted.
Voice remains disabled with `asr_candidate_unavailable` and
`vad_candidate_unavailable`; Task 5D/enrollment require a separate approved ASR model/
runtime/license amendment and a passing unchanged Silero gate.

2026-08-25 完成批准的 Voice Care Gate V2 Paraformer Mandarin ASR 修订实现，业务提交
`4677fec`。固定 Apache-2.0 INT8 工件与完整五分布 hash lock 通过全新 staging venv 和
macOS 原子发布安装；实际运行用 `python -I`、单一非阻塞写读 deadline、子进程组结算和
child-private 已校验模型快照，严格要求恰好六段公开 prompt ID。新鲜软件门为 Voice
250/250、完整 Python 1,302/1,302，compile、Make dry-run、diff/privacy checks PASS；
独立复审无 Critical/Important。exact-head user-launchd 实机门对 6/6 加密 clips 可用，
p50 509 ms、p95 529 ms，但只有 5/6 exact、1/6 wake；唯一 exact mismatch 为公开 ID
`negative_weather`，aggregate edit distance 2。因此仍返回
`asr_candidate_unavailable`，Voice disabled；未输出 transcript、PCM、Keychain 值、
私有路径或写入 Baby Care。下一 Voice 切片是独立设计 punctuation-free wake/KWS 边界，
并干净重录公开 negative control；不得降低现有 ASR/VAD 门槛。

2026-08-25 完成 Voice Care Gate V2 Task 5F 的 deterministic punctuation-free wake
boundary，业务提交 `6e933a6`。新增固定护理词首只证明无标点 `小小` 的词边界；重复
唤醒词、未知/句中/偶然匹配继续 fail closed，识别文本不被改写且完整命令仍由原
closed parser 独立验收。
RED 捕获 9 个合法连续文本被拒绝，以及复审发现的内部重复 `小小` 和 `开始亲喂`
缺口；GREEN 为 wake 27/27、Voice 267/267、完整 Python 1,319/1,319。真实 user-launchd
exact-head 聚合门为 Paraformer 5/6 exact、6/6 wake、p50 506 ms、p95 540 ms，唯一
mismatch 仍是公开 ID `negative_weather`（edit distance 2）；Silero 同一 clip 仍为 2 spans，其余
5 条为 1 span。未输出 transcript/audio/key/private path，Voice 保持 disabled。下一步
只重录固定公开 `negative_weather` 提示，再原样复跑 ASR 和 VAD 门。

2026-08-25 完成 Voice Care Gate V2 Task 5D 安装态非交互预检。业务提交 `41da786`
增加 disabled-mode login-LaunchAgent 预检，只读取固定 Keychain helper 并验证固定
Paraformer/Silero 工件，不解码音频、不运行推理、不重启其他 worker。经用户明确批准，
`make alpha-voice-asr-recover` 删除一个旧 legacy pending request，返回
`state=cleared`；兼容恢复提交为 `aacefd9`。随后两个 Voice launchd label 均注册，
`make alpha-voice-preflight` 返回 PASS，Keychain、ASR artifact 和 Silero artifact
全部 available。没有删除加密语料、模型、Keychain 或护理记录。Voice 仍 disabled；
Task 5 总门仍需干净重录公开 `negative_weather` 并通过不变的 ASR/VAD 6/6 门。

2026-08-26 完成独立 Voice listen-only 软件与 installed-i9 readiness 检查点，实施
HEAD `aa28cf3`。该模式持续读取 Xiaomi `audio_analysis`，仅在内存中完成固定帧、Silero
VAD、Paraformer、精确 `小小` 唤醒与 8 秒单次跟进，并只通过 i9 扬声器播放两条固定
回复；未构造 Baby Care 写入、家庭身份、签名或 outbox，未持久化原始家庭音频或普通
transcript。新鲜 Voice 门 321/321，compile、shell、plist、Make dry-run 与 diff check
均 PASS。安装态 Voice-only launchd 最终为 `healthy / listen_only_idle`，FFmpeg 音频
子进程存在；同时 `alpha-source-check` PASS（CS2+UDP、H.265、2560x1440 到 1280x720、
接收字节非零）。重启后首次状态查询曾在解码器预热窗口返回
`voice_audio_unavailable`，随后由同一独立 Voice 进程自动恢复，未重启 Guardian。
之后完整执行 Voice-only 生命周期，得到 `voice_stop=PASS`、`voice_start=PASS`，服务
重新进入 `healthy / listen_only_idle`；后续 source check 仍 PASS。
真人 5 次唤醒、3 次两阶段命令、3 次静默超时、5 次非唤醒和无自触发仍待监督验收；
合成 TTS 不替代该门。分支未 push/merge，main 未修改。

同日继续真人交互时，单句 `小小` 两次进入 armed，组合唤醒加固定护理命令一次返回
`listen_only_acknowledged`，端到端状态延迟 5,277ms；这些结构化状态不包含 transcript。
随后连续请求在 36ms/118ms 内返回 `voice_model_unavailable`，进程核对确认 Voice worker
仍在而 Paraformer child 已退出，既有对象永久 closed。TDD 提交 `ce6dfb6` 增加单次有界
重建并对同一内存 PCM 重试一次；无效 PCM 和第二次失败仍 fail closed。聚焦 18/18、
Voice 322/322，纯合成静音的真实模型恢复门确认 child_count=2 且 replacement_open=true。
安装运行中又观察到 Voice worker PID 保持、Paraformer child PID 被替换后仍能识别
`小小` 并进入 armed，证明无需人工重启即可恢复。随后提交 `3e9673d` 修复 Voice start
误收旧健康状态：启动前固定 epoch，status 必须由本次启动之后写入；RED 2 项及畸形
epoch fail-closed 测试转 GREEN，相关 51/51、Voice 324/324。真实 Voice-only stop/start
再次 PASS，并返回新进程的 count=0 healthy idle。真人完整 5/3/3/5 矩阵仍未完成。

2026-08-26 完成 Voice listen-only 监督实机矩阵。真实跟进失败暴露 `/usr/bin/afplay`
结束后额外 0.5 秒 duck 会裁掉立即回答的“开始”；TDD 提交 `4590489` 仅为 listen-only
将 guard 设为 0，完整 Voice Care 默认保护保持不变。此前 `07eef64` 令 bounded empty
no-match 可继续服务下一请求而不退出模型，`15a2ff8` 将 start freshness 收紧为微秒级。
最终 Voice 门 325/325。真人实际通过至少 5 次独立 `小小` 唤醒、3 次两阶段命令、
3 次唤醒后静默 10 秒超时及 5 句不含唤醒词的控制；操作者确认成功对话的“我在，请说”
和“我听到了”均可听见。计数增量与人工发声严格一致，无额外自触发；最终非唤醒后
count 保持 5。Voice worker、Paraformer、FFmpeg PID 在最终矩阵中保持不变，Xiaomi
source check 仍 PASS，最近 30 分钟新增 wav/aiff/pcm/opus 文件为 0。该证据不证明任意
成人、任意噪声、全护理写入或无人照护安全；full-care Voice 继续 disabled。

同日批准 Voice Gate V3 Xiaomi Camera Reply 设计与实施计划。官方 go2rtc Xiaomi/Streams
手册及固定源码确认现有 MISS `cs2+udp` 路径具备 sendonly/双向音频结构，无需先切换
传输协议；固定 commit 的 `WritePacket` 存在把 header 再次复制到 payload 区的强烈静态
缺陷迹象，必须先以合成 Go 包验证 RED，再决定一行最小补丁。V3 排在 P4 软件检查点后、
P5 72 小时门前，且只允许两句现有固定回复。摄像头实机门通过前 i9 扬声器仍是生产
输出；摄像头发送开始或结果不确定后禁止二次 i9 回退。当前仅完成文档，没有修改协议/
Voice 业务代码、播放摄像头、保存家庭音频、push、merge 或修改 main。

2026-08-26 完成 P4 authenticated private remote access 软件检查点。业务提交
`a39340f`、`b2d0e88`、`f55d08c` 和 `a265312` 分别实现纯证据合同、只读有界 macOS
适配器、精确 `/dev/tty` 确认后的固定 Serve 配置接口，以及 Make/grants/runbook
工作流。全仓门首先发现 Guardian 测试 fixture 漏掉既有 `voice_preflight` 检查；没有
降低生产门禁，测试同步提交 `5dca783` 后 Guardian 部署测试 31/31、完整 Python
1,514/1,514。P4 门为 95 passed/1 个沙箱 Unix-socket fixture skip，邻接 API 123/123、
前端 73/73；Python compile、shell syntax、Make dry-run、diff 和逐项审查后的隐私扫描
均 PASS。该证据只证明 parser、redaction、固定 argv、Basic Auth 与 same-origin 软件
合同；没有安装/登录真实 Tailscale，没有合并私有 policy、应用 Serve 或运行两部
iPhone 蜂窝网络验收。P4 installed/device gate 仍 pending，下一软件切片为 Voice Gate V3。

2026-08-26 Voice Gate V3 installed-i9 验收在 V3E **fail closed**。Task 1–7
实现提交为 `26eea4d`、`47c42ba`、`1bcc8da`、`53e0231`、`ca2822c`、
`e548dfe` 和 `e358aaf`；真实 macOS 非 seekable TTY 修复为 `5768894`。
固定 go2rtc 构建、CS2+UDP H.265 source、60 秒 Opus V0、Voice listen-only 和
摄像头回复软件门均通过；成人明确听到一次 1 秒生成音，tone/post-health/marker
门全部通过。启用忽略态私有开关后的第一组真人交互出现卡住和摄像头异常转动，
本地聚合状态记录 4 次完成回复，随后固定日志窗口出现 CS2 UDP read timeout、
音频转码 EOF 和 `voice_audio_unavailable`。这违反零重复/自触发、零 stuck state
及 sibling-source 不回归要求，不能用单音通过替代 V3E。

处置结果：Voice-only job 先停止，私有 `camera_reply_enabled` 恢复为 `false`，
当前构建 acceptance marker 被置为不接受，`alpha-voice-camera-status` 返回
`CAMERA_REPLY_NOT_PROVEN`；随后仅恢复既有 i9 speaker 的 listen-only Voice，状态
重新为 healthy/idle，source check 再次 PASS（CS2+UDP、H.265、2560x1440、接收
字节非零）。当前 source 无反向音频 consumer 残留。修复后的聚焦软件证据为 Voice
406/406、camera reply 91/91、Python compile 和 diff check PASS。V3E 保持失败，
摄像头回复不得重新启用；P5 需要明确采用 i9-only release scope 后才可继续。

同日用户明确将 Tailscale/外网访问移到最后，当前不安装、不登录、不配置 Serve，也
不运行两部 iPhone 蜂窝验收。P4 软件合同和测试证据保留，但 installed/device Tasks
继续 unchecked；本地发布范围采用局域网 Dashboard 与 i9-only Voice，远程访问不再
阻塞其余本地功能或最终本地稳定性门。

同日恢复 Full-care Voice Gate V2。安装态非交互预检 PASS：Keychain、固定
Paraformer 和固定 Silero 工件均 available，listen-only worker 保持 healthy/idle。
正确的登录 LaunchAgent 聚合门仍为 Paraformer 5/6 exact、6/6 wake、p50 520 ms、
p95 568 ms，唯一 mismatch 为公开 prompt ID `negative_weather`。当前该 clip 约为
-41 dBFS 且 Silero 检出 0 spans；两次新的 10 秒倒计时录制窗口也均在 VAD 阶段以
0 spans fail closed，未发布新的有效 clip。未降低阈值、未开始 Dad/Mom enrollment、
未启用 full-care Voice、未写 Baby Care，也未保存自由语音。下一步需要真人在明确的
`capture_now` 窗口内只说一次固定公开句“今天天气不错”，随后原样复跑 ASR/VAD 6/6。

随后干净重录成功，Task 5 按不变门槛关闭：Paraformer 6/6 exact、6/6 wake、p50
587 ms、p95 661 ms、mismatch none、edit distance 0；Silero 对 generated control 与
六条 private prompt 均为 exactly one span。Source PASS，speaker environment ready，
真实 i9 generated ECAPA 5/5、192 dimensions、p50 386 ms、p95 433 ms，原始音频未
持久化。注册前发现 `tools/voice_enroll.py` 仍调用历史 Whisper base；规格 4.2.2 已
批准 Paraformer 为替代候选，因此 TDD 提交 `24b8906` 固定注册使用 Paraformer，并
在成功、失败和构建中断时关闭 ASR/ECAPA。聚焦 33/33、Voice 406/406、compile 与
diff check PASS。

Dad 实机注册尚未通过，也未创建 profile。多轮聊天驱动尝试暴露两个必须长期保留的
操作边界：Codex sandbox PTY 连接固定 loopback RTSP 时 FFmpeg exit 255 / reason
`operation_not_permitted`，不能作为真实 i9 音频证据；即使在真实 i9 用户上下文，工具
调用会在聊天提示送达后立即打开五秒窗口，成人往往尚未看到/读完一次性口令。一次
不输出 transcript 的 aggregate diagnostic 得到 exact=false、edit distance 17、length
delta +6，wake/challenge/digit 三项均 false，说明抓到的是另一时段语音而非近似口令。
原始 PCM 与识别文字均未持久化。下一步先实现本地固定 readiness/countdown；禁止跨
聊天 turn 等待已签发的 60 秒 challenge、禁止继续盲试、延长 TTL 或放宽 exact gate。

随后首个本地 15 秒倒计时实现完成，但真实 Dad 尝试仍在 challenge 阶段 fail closed：
它直到 `capture_now` 才新建解码器并读取固定五秒，摄像头/RTSP 建链与人工起说仍可能
占用有效窗口。未创建 profile，未持久化原始音频。严格 TDD 将该边界改为先打开并预热
固定音频源、在本地倒计时期间持续丢弃 PCM 追到 live edge，再由现有固定 Silero VAD
和 utterance collector 在最多 12 秒内返回一段完整内存话语。随机数字、60 秒 TTL、
exact match、Paraformer 与 ECAPA 门均未放宽。新鲜软件证据为 enrollment 14/14、Voice
406/406、compile 与 diff check PASS；真实 logged-in-i9 Dad/Mom enrollment 仍待完成。

同日完成 Voice 日常口令审查修复。审查提交 `dd88ff6` 在基线 `1ab5c99` 证明
`嘿，小小，我要喂奶了` 同时被 wake 和 intent 两个独立闭集拒绝；当前分支保留审查
文档于 `1c00899`。严格 RED/GREEN 业务提交 `e786d2e` 仅增加固定可选前导词 `嘿`、
精确 punctuation-free ASR 形式和精确 idle-state 别名 `我要喂奶了`。任意前导语、同音、
句中或重复 wake、近似命令和状态冲突继续 fail closed。用户金句端到端只返回一次
`listen_only_received` 并回到 idle，不构造 Baby Care 写入。新鲜证据为 focused
72/72、Voice 418/418、compile/diff/privacy PASS。首轮全仓门发现 4 个旧 synthetic
benchmark 用例仍把已批准前导词当负例；同步为仍拒绝的任意前导语后，benchmark
26/26、完整 Python 1634/1634 PASS。随后真实登录 i9 单句复验通过：金句只产生一次
可听确认，`processed_count` 从 0 增至 1 后回到 healthy/idle，source check 保持 PASS。
首轮回复失败被定位为 CoreAudio 输出会话阻塞：连系统 Ping 控制音也超时；重启
`coreaudiod` 后控制音和金句回复均恢复。完整过程记录于同目录 review-resolution 文档。

同日开始 Camera Reply 生命周期根因门。远端审查分支
`codex/xiaomi-camera-reply-lifecycle-review` 以 `4d479b8` 为父提交，审查文档提交为
`f610d7b`。在固定 go2rtc upstream commit 的临时纯合成 fixture 中，向容量 10 的
command channel 连续送入 11 个 speaker-start response 后，真实 worker 以
`cs2: pop buffer is full` 退出并使 `ReadPacket` 观察到共享媒体失败。五个 speaker
lifecycle RED 分别证明未消费 start response、接受重叠 start、stop 后仍写 channel 3、
首个写错误被吞及 20 轮积压 20 个 response；四个 Streams RED 证明 empty stop、stop
failure、natural end 和 cancel/natural race 都没有协议 settlement。因此根因结论为
`H1_H2_CONFIRMED`，H3 独立确认。全部证据无网络、无摄像头、无家庭音频或私有配置。
新的 lifecycle spec/plan 已形成草案；规格批准前不写生产补丁，不启用或安装 Camera
Reply，也不执行实机 probe。

2026-08-27 完成已批准 Camera Reply lifecycle 软件 Tasks 1–6，业务提交为
`e66302ef1ab448705dc05d03086d52bf69f0e124`。最终补丁保持固定 upstream
`b465651a94c1f637d566a8c660b4fad102b35153` 与 `cs2+udp`，实现有界 command
dispatcher、命令入队时间所有权、generation-owned speaker session、停止前禁写、首个
错误保持、1.5 秒有界且 exactly-once 的 Streams settlement，以及 Python start/stop
同 generation 完成证明。两轮独立复审提出的 8 项及最终 2 项 Important 均经
RED/GREEN 关闭，最终结论 0 Critical / 0 Important。Fresh 证据为精确补丁 apply、三组
Go focused 与三组 race PASS，repository focused 106/106、Voice 431/431、frontend
73/73、full Python 1648/1648、compile/Make dry-run/diff/privacy PASS。额外扩大运行的
upstream `internal/streams` 两项 source-registration 失败在未打补丁的同一固定提交原样
复现，不属于本次回归。全过程未访问摄像头、未播放或保存家庭音频、未安装 candidate、
未发布 marker。Camera Reply 继续 disabled；实机 D0–D4 仍需单独批准和成人监督。

同日经批准执行受监督实机门。D0 自动健康与人工观察通过；候选只重建、重启 go2rtc
单组件。首轮 D1 暴露有限媒体 EOF 误判与 active HTTP 快照含内部 playback producer
的解析缺口，分别经 RED/GREEN 修复并提交为 `20ca71c`、`8e684dd`。重新清零后 D1
实机通过：短音调可听、无转动、start/response/stop=1/1/1、closed、零 pending、零
residual、source PASS、Voice healthy。D2 前两次同样 COMPLETE；第三次（累计第 4 次）
人工仍可听且无转动，但软件返回 AMBIGUOUS。随后固定聚合显示连接已重建为 generation
0，日志记录 Xiaomi CS2 UDP 连续 10 秒无媒体后的 read timeout；source 与 Voice 随后
独立恢复。按停止线废弃 marker，保持 Camera Reply disabled，未执行 D3/D4、未重启
完整 Alpha。该残余问题不能在当前禁止切换 TCP/增加第二摄像头连接的规格内继续猜修。
随后发现失败报告虽显示 marker_current=false，旧 D1 marker 文件仍会保留。经明确删除
授权移除该精确文件，并以 RED/GREEN 修复 `59a8ab4`：probe 在任何摄像头访问前先安全
撤销旧 marker，控制终端不可用和后置健康检查失败均不再留下历史 READY。安装 checkout
固定门 106/106，状态为 NOT_PROVEN；source PASS、Voice healthy/listen_only，未播放音频。

同日批准并完成 transport-auto 诊断计划 Task 8 软件切片，业务提交为 `f153cbd`。
新增固定 macOS 预检接口和 CLI：只通过 `shell=False`、`/dev/null` stdin、10 秒上限及
1 MiB 合并输出上限运行固定命令；精确验证稳定 `Go2RTC.app` requirement、拒绝
`cdhash`、验证单一 launchd PID 及其 app/config 参数、验证该 PID 独占 loopback 1984
listener，并将 app-firewall 结果闭合为 available/blocked/unknown。初始 RED 为两个
missing-module collection error；fresh GREEN 为 62/62，compile、Make dry-run、
ASCII/privacy/diff 检查通过。本切片未执行安装态预检、未访问摄像头媒体、未播放、
未安装或重启服务；因此不声明 macOS 或实机 PASS。下一项为 Task 9 单一 producer 与
`transport=auto` 只读软件诊断。
