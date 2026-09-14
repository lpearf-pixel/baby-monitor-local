# 给 i9 Codex 的只读预检提示词

日期：2026-09-14。先执行下面的提示词并返回脱敏结果，再完善同日无宝宝全景方案。
这次任务是本地代码、安装和已有运行状态的检查，不要求用户立即说话或摆放场景。

---

你在用户实际使用的 Intel i9 Mac 上接管 baby-monitor-local。
请先阅读当前分支 AGENTS.md、SUMMARY.md、docs/STATUS.md、docs/CHECKPOINT.md、
docs/NEXT.md，以及：

- docs/superpowers/plans/2026-09-14-no-baby-panoramic-acceptance.md
- docs/superpowers/plans/2026-08-30-baby-monitor-ordered-delivery.md
- docs/superpowers/plans/2026-08-27-voice-care-multi-intent-asr-optimization.md

目标：给规划会话提供真实 i9 就绪信息，判断无宝宝大盘/单句语音/空场景验收如何执行。
不要直接开始全景矩阵。用户报告没有宝宝，但远端规划助手没有看过摄像头；
你也不能把运行健康或模型输出当成人工确认无宝宝。场景来源标 OWNER_REPORTED。
不要求上传截图、录像、音频或家庭转写。

## 任务顺序

1. 只读核对本地仓库归属、分支、HEAD、upstream、ahead/behind、dirty 状态和最近提交。
   检查远端当前分支，允许 fetch，但不 checkout/pull/merge/rebase/reset/clean。
   比较已安装代码与工作区代码；不能以工作区 HEAD 冒充 launchd 实际运行版本。
   如果计划文件还未同步，不覆盖本地改动；通过只读读取远端文档继续。
   已配置的凭据可用于正常读取，不打印 remote 中可能存在的凭据，不读取历史聊天 Token。

2. 确认实际登录用户上下文、i9 架构、当前解释器/Node、既有虚拟环境和服务入口。
   不打印用户名称、home、局域网地址、连接字符串、环境变量或私有设置内容。
   沙箱或非 GUI 登录上下文阻塞时写 BLOCKED_CONTEXT，不请求降低系统安全设置。

3. 阅读当前 Makefile 和它调用的脚本，核实以下入口是否只读及输出是否脱敏：
   alpha-status、alpha-visual-status、alpha-voice-status、alpha-voice-listen-status、
   alpha-voice-camera-status。只执行确认无写入/无新媒体采样的 status 子集。
   不盲目执行 alpha-source-check 或 alpha-guardian-test：它们可能有主动探测；
   先列出实际副作用和是否可在下一阶段使用。
   禁止 start/stop/restart/install/update、PTZ、speaker probe、录音诊断、
   private capture、数据库写入、通知测试和第二条 Xiaomi 连接。
   不改变服务、模型、阈值、床区、Camera Reply 或 listen-only 模式。

4. 从已有状态文件或已鉴权的本地只读健康接口做三次有界观察：
   起始、约 15 秒、约 30 秒；每次等待不超过 15 秒。
   只读取已经存在的状态与聚合计数，不创建新的 RTSP/摄像头/麦克风会话。
   观察状态时间是否推进、计数是否回退、producer/worker 是否稳定。
   不为了让 disabled 或 unavailable 变绿而启动服务。
   若没有安全的状态接口，写 NOT_OBSERVABLE 并给出缺少的证据。

5. 只读核对 Dashboard 四 Tab/本地资产是否确实存在于安装版本，
   以及 overview/alerts/analytics/system 实际路由、鉴权方式和只读属性。
   路由以源码为准，不猜 API，不复制 Token 到命令或报告。
   已有安全会话可用时只查询本地接口，过滤掉家庭标识、正文和地址后汇总。
   若页面包含家庭视频，不能截图/下载/交给远端视觉工具；本轮不主动打开媒体。
   物理 iPhone/可听回复/场景肉眼确认均记 NOT_RUN，不拿 HTTP 200 代替体验通过。

6. 仅在现有读取层能安全取得数据时，汇总本次之前的未恢复警报数量：
   face / outside / prone / adult / environment，并区分历史数据与观察期间新变化。
   说明床区是否配置且通过现有验证，不输出坐标、布局或校准文件。
   缺数据为 null + 原因，不填 0。
   不解析原始模型文字，不直接修改 SQLite，不删除或恢复旧警报。
   检查 resolution_cause 是否仍无数据库字段；若是，继续为 null。

7. 核对当前闭合口令和负例夹具。给出下一阶段 30 次合并单句正例与 20 次共用负例
   的固定试次清单及对应 action/family；全部来自公开仓库规则/合成测试，
   不是家庭识别转写。喂奶 10 次；换尿布开始/完成、拍嗝开始/完成各 5 次。
   无唤醒、否定、取消、疑问/近义非指令、多动作冲突各 4 次；
   每类覆盖三种动作族。合法其他动作应正确路由，不误设为静默负例。
   只准备清单，不发声、不采样、不运行 ASR 实机矩阵。
   如某个例子不能从当前代码/测试证明预期，标 NEEDS_REVIEW，不能自行放宽解析。

8. 不重跑完整软件套件、不新增测试代码。按真实结果提出同日方案需要改动的具体条目，
   尤其是安装版本、可观察字段、API 名称、旧警报处理、输出可用性和本地就绪流程。
   只报告结论，不擅自实施修复或重新设计模块。

## 返回格式

先给结论 READY_FOR_SUPERVISED_SUBSET / BLOCKED / PARTIAL。
READY 只表示可进入有人准备好的下一步，不是任何实机准确率 PASS。

返回一个简洁 Markdown 报告，使用下列键；不可观测值为 null，配固定原因：

| 字段 | 结果 |
|---|---|
| repository_match / branch / local_head / remote_head | |
| dirty / ahead / behind / installed_head_verified | |
| installed_head / code_asset_match | |
| execution_context / python / node | |
| dashboard / visual / environment / voice | |
| voice_mode / camera_reply_enabled | |
| source_status_fresh / video_progress / audio_progress | |
| producer_count / producer_stable / worker_stable | |
| existing_status_sample_count / observation_seconds | |
| scene_source | OWNER_REPORTED |
| baby_absence_visually_verified_by_agent | false |
| bed_zone_valid / usable_visual_observations | |
| i9_speaker_audibility | NOT_RUN |
| iphone_visual_check | NOT_RUN |
| existing_open_alert_counts / new_alert_count_deltas | |
| action_counters_available / resolution_cause_available | |
| safe_readonly_entrypoints | |
| blocked_items / missing_evidence | |

再附：
- 执行过的脱敏命令/入口、返回码、只读属性；不要贴未经清洗的终端日志。
- 30 正例/20 负例的预定义清单，可用范围编号压缩重复试次。
- 建议修改方案的条目：当前规定、现场证据、建议调整、是否需后续人参与。
- 实际副作用盘点：服务/配置改动、新媒体会话、家庭媒体持久化、通知测试、
  Baby Care 写入是否为零；被动观察到的现有服务自然活动单独列出，不能混称零副作用。

在既有忽略且私有的运行目录保存脱敏报告，并把可分享的 Markdown 结果返回给用户，
供规划会话读取。若没有适当忽略目录，直接返回清洗后的报告，不创建新家庭制品。
本轮不 commit/push/PR，不更改 main/stable。用户会把结果交回规划会话完善方案。
