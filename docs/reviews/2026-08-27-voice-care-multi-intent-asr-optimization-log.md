# Voice Care 多护理动作 ASR 优化过程与复盘日志

日期：2026-08-27

状态：设计与实施计划已写入；代码、模型、安装和实机工作均未开始

基线分支：`codex/xiaomi-camera-reply-lifecycle-review`

基线远端 HEAD：`4f599225f908d8052006353a9dafec03eed40fdf`

设计：
`docs/superpowers/specs/2026-08-27-voice-care-multi-intent-asr-optimization-design.md`

计划：
`docs/superpowers/plans/2026-08-27-voice-care-multi-intent-asr-optimization.md`

## 1. 用途和更新规则

本文件是 append-oriented 优化日志，不是乐观状态摘要。后续 Codex 每完成一个
RED/GREEN、模型比较、软件 gate、安装前置或成人监督小门，都必须在这里增加一条带 exact
HEAD、真实命令和真实结果的记录。

只允许记录：

- source-controlled synthetic/public fixture ID；
- 固定 action/reason；
- 样本、正确、拒绝、误接受、timeout 和失败数量；
- p50/p95/RSS 等聚合性能；
- branch、commit、diff scope、许可和公开模型/资产 digest；
- Camera Reply flag、单 producer 和 Baby Care 写入边界。

禁止记录：

- 家庭 PCM、音频文件、完整或局部 transcript；
- 纠错前后真实文本、字符差异或逐 utterance 距离；
- 药名、剂量、家庭成员私有身份、家庭地址/网络/路径；
- Xiaomi URI、token、session、设备密钥或其他 credential；
- 为了让结果好看而删除的失败或沿用的历史测试数字。

一条记录没有 fresh 命令/证据时，状态必须是 `NOT_RUN` 或 `UNVERIFIED`，不能写 PASS。

## 2. 初始能力基线

| 能力 | 2026-08-27 基线 | 证据等级 |
|---|---|---|
| 精确 wake | 已有软件与受控实机成功证据 | 已验证，但不代表所有环境准确率 |
| Xiaomi 视频/拾音 | 单 producer、视频及 60 秒 Opus 有历史实机 PASS | 历史实机；本轮未重跑 |
| Camera Reply lifecycle | 最近聚合 `34/34/34/34`、closed、零 residual/failure | 已验证生命周期；生产 flag=false |
| `开始喂奶` follow-up | 5 次中 1 次确认、4 次拒绝 | 成人监督聚合证据 |
| 4 次拒绝分类 | near-start=4、near-reply-echo=0、far=0 | 已验证固定桶；无 transcript |
| Feeding 闭集 | `feeding_start/update/end`、confirm/cancel | 代码与测试已有 |
| 换尿布 | ASR 可能转写，业务闭集未实现 | 未支持 |
| 拍嗝 | ASR 可能转写，业务闭集未实现 | 未支持 |
| 喂药 | 现有 Feeding parser 明确不支持 | 未支持；高风险 |
| Baby Care 非 Feeding 合同 | 不存在 | 未定义，禁止本仓库单方面发明 |

当前生产 ASR 为 sherpa-onnx `1.13.6` 的
`sherpa-onnx-paraformer-zh-2023-09-14`，16 kHz、`greedy_search`。既有 Gate V2
记录的当前候选延迟约 p50 587 ms、p95 661 ms；该数字是历史基线，任何后续比较都必须
重新运行后才能写 fresh 结果。

## 3. 根因假设账本

| ID | 假设 | 当前状态 | 证据/下一判定 |
|---|---|---|---|
| H1 | follow-up 没有被摄像头拾取 | 已推翻为完整原因 | VAD、utterance 和 speech-frame 有活动；失败仍形成 utterance |
| H2 | Camera Reply 尾部完全截掉 follow-up | 已推翻为完整原因 | tail replay 有 frames，且普通 live follow-up 也曾成功 |
| H3 | 固定回复 echo 消耗 armed turn | 已推翻为完整原因 | exact echo quarantine 后失败仍有 reply-echo=0 |
| H4 | Paraformer 输出接近 start，但闭集拒绝 | 当前首要证据支持 | 4/4 rejected follow-up 均为 near-start 桶 |
| H5 | 四次错误全部是同音替换 | 未验证 | 无真实 transcript；只能先做 synthetic/public HR A/B |
| H6 | KWS 可补足短命令召回且保持安全 | 技术候选，未验证 | 必须和 ASR guard 双信号；模型许可需先闭合 |
| H7 | ContextualParaformer 必须替换现模型 | 未证明且延后 | 先验证受限纠错；模型迁移需独立规格和性能门 |

## 4. 已批准设计决策

| ID | 决策 | 理由 | 回滚 |
|---|---|---|---|
| D1 | exact-first，纠错只在 armed follow-up 且 exact failed 后运行 | 保持 wake/idle/full-care fail closed | 删除/关闭纠错，恢复 exact-only |
| D2 | 初始纠错只有 source-controlled 显式映射 | 无真实 transcript，不能推导通用距离规则 | 移除单个映射 |
| D3 | 禁止 edit-distance、形状规则和跨动作纠错 | `断奶/泡奶/热奶/喂药` 可与喂奶短语相近 | exact-only |
| D4 | Feeding 先修；尿布和拍嗝后续只做 listen-only | 当前外部合同仅 Feeding V1 | 关闭非 Feeding registry entries |
| D5 | 喂药仅 high-risk candidate，不纠错、不播保存确认、不写入 | 药名/剂量/单位/给药结果不能由短 ASR 自动确定 | 完全禁用 medication candidate |
| D6 | 其他动作逐项小规格，不开放式分类 | 避免未知输入被“最接近动作”吸收 | 未注册即拒绝 |
| D7 | HomophoneReplacer 只离线 A/B | 全局后处理可能影响否定/wake | 不装入 production runner |
| D8 | KWS 只作第二信号且先解决许可 | 关键词也可出现在否定/疑问中 | 不打包模型、不启用 sidecar |
| D9 | FunASR ContextualParaformer 延后 | 属于模型/依赖迁移，不是最小修复 | 保留当前 pinned Paraformer |
| D10 | Camera Reply 保持 false，识别门与播放门分开 | 一条链路成功不能代证另一条 | i9 输出或聚合状态隔离验收 |

## 5. 优化记录

### R0 — 精确 HEAD、代码边界和上游方案复核

- 日期：2026-08-27
- exact HEAD：`4f599225f908d8052006353a9dafec03eed40fdf`
- checkout：detached inspection worktree，开始时干净
- 授权：只读调查和 docs-only 写入；无代码、commit、push、PR、安装或实机权限
- 代码结论：`services/voice/intent.py` 与 `VoiceCareIntentV1` 只覆盖 Feeding；
  listen-only 通过多个 synthetic Feeding state 判断命令是否闭合
- 实机证据结论：当前 first failing layer 为 near-start ASR/normalization；Camera Reply
  lifecycle 在失败窗口保持 clean closed
- 上游结论：当前 Paraformer 无直接 hotword flag；同版本有 HomophoneReplacer；
  sherpa KWS 可作 armed second signal；FunASR ContextualParaformer 是后续模型级候选
- 选择：D1–D10
- 新鲜测试：`NOT_RUN`，本记录没有把历史 pass 数冒充本轮结果
- 摄像头/家庭音频：未访问
- Camera Reply：未启用，目标状态仍为 false
- Baby Care：未调用、未写入
- 代码改动：无
- 文档改动：新增设计、计划和本日志；AGENTS、SUMMARY、STATUS、CHECKPOINT、NEXT 已
  增加一致的读取入口和当前状态
- docs-only 验证：tracked/untracked whitespace check PASS；设计/计划 placeholder scan
  为 0；远端同名分支仍为精确 `4f599225`
- 当前决定：先完成文档审查和 docs-only 验证，再等待用户授权代码 Task 1

## 6. 后续实验记录格式

### R1 — 多动作闭集 RED corpus

- 日期：2026-08-27
- branch / exact HEAD：`codex/xiaomi-camera-reply-lifecycle-review` /
  `09555342726e4d22b7a5b4b66f6ee9cf483ea29e`
- dirty/unrelated state：开始时存在两份旧的未提交 start-shape WIP；因其通用编辑距离与新
  批准规格冲突，先通过受控补丁恢复到 HEAD 行为，再建立新 RED；无其他 dirty 文件
- authority：software-only；允许本地聚焦提交和最终同名分支 push
- hypothesis：H4；当前需要显式动作接口和 source-controlled Feeding 映射，而不是通用
  相似度接受
- files changed：新增 `tests/voice/test_care_action.py`、
  `tests/voice/test_asr_correction.py`，扩展 `tests/voice/test_listen_only.py`，并更新本日志和
  计划状态
- RED command/result：使用共享项目 Python 3.11 venv 执行计划的三个测试文件；exit 2，
  collection 产生 2 errors，首个失败为 `services.voice.care_action` 不存在，第二个为
  `services.voice.asr_correction` 不存在
- GREEN command/result：NOT_RUN；Task 1 只建立 RED corpus
- focused/full command/result：RED 前基线 `tests/voice/test_intent.py` 与
  `tests/voice/test_listen_only.py` 为 33 passed；full NOT_RUN
- corpus：source-controlled synthetic text fixtures，license=`GENERATED`；无 PCM、无家庭
  transcript
- positives/accepted/rejected：7 exact action cases、1 reviewed correction case；RED 阶段
  accepted=NOT_RUN
- negatives/false accepts：9 exact-action rejection cases、20 correction rejection cases和
  controller idle/unsafe controls；RED 阶段 false accepts=NOT_RUN
- latency p50/p95/RSS：NOT_RUN；未调用 ASR 模型
- privacy scan：测试只含批准的 synthetic fixed phrases；diff gate 将在 GREEN 后执行
- Camera Reply flag/lifecycle：未读取或修改；目标保持 false；未播放
- Baby Care write/outbox/signing：未构造、未调用
- evidence proves：新接口缺失时 corpus 会失败，且失败发生在预期模块边界
- evidence does not prove：实现正确、真实 ASR 召回、家庭环境或实机准确率
- decision：keep；进入 Task 2 最小闭集注册表
- next single action：实现 `services/voice/care_action.py` 并跑 Task 2 focused GREEN

### R2 — 闭集动作注册表 GREEN

- 日期：2026-08-27
- branch / exact HEAD：`codex/xiaomi-camera-reply-lifecycle-review` / `c72b076`
- dirty/unrelated state：Task 1 已聚焦提交；本 slice 仅新增注册表并修正 synthetic 问号
  对抗 fixture
- authority：software-only；未安装或访问模型
- hypothesis：H4；现有 Feeding parser 可原样委托，非 Feeding 只需固定内部注册表
- files changed：新增 `services/voice/care_action.py`，修改
  `tests/voice/test_care_action.py`、本计划和日志
- RED command/result：`tests/voice/test_care_action.py` exit 2，1 collection error，固定原因
  为 `services.voice.care_action` 不存在
- GREEN command/result：`tests/voice/test_care_action.py tests/voice/test_intent.py`，
  41 passed，exit 0
- focused/full command/result：focused 41 passed；full NOT_RUN
- corpus：source-controlled synthetic exact/negative phrases，license=`GENERATED`
- positives/accepted/rejected：10 punctuation/space-normalized or exact positives全部 accepted
- negatives/false accepts：12 unknown/multi-domain/question/bounded negatives全部 rejected，
  false accepts=0
- latency p50/p95/RSS：NOT_RUN；未调用 ASR
- privacy scan：无 PCM、transcript、私有地址或 credential；最终 Task 7 统一复核
- Camera Reply flag/lifecycle：未读取或修改；目标保持 false；未播放
- Baby Care write/outbox/signing：注册表不导入、不构造、不调用
- evidence proves：内部闭集可分类 Feeding、尿布、拍嗝和 medication candidate；高风险
  类型不能设置 positive acknowledgement
- evidence does not prove：controller 已接线、真实 ASR 输出或实机召回
- decision：keep；只作为 listen-only 内部层
- next single action：实现 armed-only source-controlled correction 并跑 Task 3 focused GREEN

### R3 — Armed 显式 Feeding 纠错 GREEN

- 日期：2026-08-27
- branch / exact HEAD：`codex/xiaomi-camera-reply-lifecycle-review` / `eceeefb`
- dirty/unrelated state：Task 2 已聚焦提交；本 slice 只新增 correction 模块和相邻测试
- authority：software-only；不安装模型、不读取家庭输入
- hypothesis：H4；一个审查过的 source-controlled mapping 可安全补足 synthetic near-start，
  无需通用 edit distance
- files changed：新增 `services/voice/asr_correction.py`，修改
  `tests/voice/test_asr_correction.py`、计划和本日志
- RED command/result：模块级 RED 已在 R1 记录；post-validation 独立 RED 为 1 failed，
  实际错误是 stale mapping 可把 medication canonical 直接返回
- GREEN command/result：`tests/voice/test_asr_correction.py tests/voice/test_care_action.py`，
  51 passed，exit 0
- focused/full command/result：focused 51 passed；full NOT_RUN
- corpus：1 个 approved synthetic mapping 和 source-controlled adversarial strings，
  license=`GENERATED`
- positives/accepted/rejected：approved mappings=1，positive accepted=1
- negatives/false accepts：26 个显式安全/近邻/跨动作及 exact classifier controls通过，
  false accepts=0
- latency p50/p95/RSS：NOT_RUN；未调用 ASR
- privacy scan：只含 synthetic fixed phrases；模块不返回距离、概率或输入文本字段
- Camera Reply flag/lifecycle：未读取或修改；目标保持 false；未播放
- Baby Care write/outbox/signing：未导入、未构造、未调用
- evidence proves：只有 `开始为奶` 的显式映射可纠正；未知一字符近邻、否定、停止、
  取消、疑问、语义邻居、跨动作和 medication 均拒绝；canonical 必须重新通过低风险 Feeding
  exact classifier
- evidence does not prove：该 synthetic confusion 就是家庭实机四次 transcript，或真实召回
  已改善
- decision：keep；mapping 数固定为 1，不采用通用 fuzzy 算法
- next single action：按 exact-first 顺序接入 armed listen-only controller

### R4 — Listen-only 多动作接线 GREEN

- 日期：2026-08-27
- branch / exact HEAD：`codex/xiaomi-camera-reply-lifecycle-review` / `d30da28`
- dirty/unrelated state：Task 3 已聚焦提交；本 slice 只改 controller、相邻测试、计划和日志
- authority：software-only；未启用或播放 Camera Reply
- hypothesis：H4；exact-first + armed-only explicit correction 能保持 reply echo、replay和
  timeout 现有边界
- files changed：`services/voice/listen_only.py`、`tests/voice/test_listen_only.py`、
  计划和本日志
- RED command/result：Task 4 focused 初跑 8 failed / 135 passed；首败为 exact diaper
  command 被旧 Feeding-only controller 返回 `listen_only_followup_far`
- GREEN command/result：Task 4 四文件 focused 为 142 passed，exit 0
- focused/full command/result：listen-only/runtime/TTS/Camera Reply 142 passed；full NOT_RUN
- corpus：source-controlled synthetic exact/corrected/negative strings，license=`GENERATED`
- positives/accepted/rejected：4 diaper/burping exact follow-ups、1 corrected Feeding、2
  medication candidates和1 one-utterance exact action均达到固定预期
- negatives/false accepts：idle action和 unsafe question保持静默；现有 echo、replay、timeout、
  cancellation和Camera Reply回归全部通过；false accepts=0
- latency p50/p95/RSS：NOT_RUN；controller fake ASR 软件测试
- privacy scan：outcome 只含固定 reason/response/phase，无 command/transcript 字段
- Camera Reply flag/lifecycle：生产开关未读取或修改，保持 false；Camera Reply 测试通过，
  未执行实机播放
- Baby Care write/outbox/signing：controller 未导入、未构造、未调用
- evidence proves：exact low-risk 只确认一次并回 idle；correction 只在 armed exact miss 后运行；
  medication 只返回 silent high-risk candidate；one-utterance 不运行 correction
- evidence does not prove：真实 Paraformer 召回、家庭声学条件或 Baby Care 写入
- decision：keep；进入 aggregate-only counter slice
- next single action：为每个 terminal action 增加固定有界计数，且不暴露 transcript

### R5 — Aggregate-only 动作证据 GREEN

- 日期：2026-08-27
- branch / exact HEAD：`codex/xiaomi-camera-reply-lifecycle-review` / `957c300`
- dirty/unrelated state：Task 4 已聚焦提交；本 slice 仅改 outcome 固定元数据、Voice 状态
  allowlist、worker计数、CLI和相邻测试
- authority：software-only；未读取 runtime status 或家庭输入
- hypothesis：H4；固定 action code/match kind 足以复盘误识别，无需持久化 transcript
- files changed：`services/voice/listen_only.py`、`services/voice/listen_only_runtime.py`、
  `services/voice/worker.py`、`tools/voice_status.py`、三份相邻测试、计划和本日志
- RED command/result：Task 5 focused 初跑 10 failed / 23 passed；首败为 status writer
  fail closed 拒绝尚未加入 allowlist 的新 counters
- GREEN command/result：controller/worker/runtime/status CLI focused 56 passed，exit 0
- focused/full command/result：Task 5 exact三文件 33 passed；扩展 controller 后 56 passed；
  full NOT_RUN
- corpus：fake fixed `ListenOnlyOutcome` 和 synthetic action codes，license=`GENERATED`
- positives/accepted/rejected：feeding exact/corrected、diaper、burping、medication 各自产生
  唯一固定 counter；未带 action metadata 的既有 outcome 保持零
- negatives/false accepts：armed invalid outcome只增加 `listen_only_action_rejected`；未知
  status字段继续拒绝；false accepts=0
- latency p50/p95/RSS：NOT_RUN；无模型调用
- privacy scan：`git diff --check` PASS；批准敏感模式扫描无 true positive
- Camera Reply flag/lifecycle：未读取或修改，保持 false；未播放
- Baby Care write/outbox/signing：未构造、未调用；status schema不含外部 intent
- evidence proves：状态只能记录6个新固定非负有界整数；corrected Feeding不被双计为 exact；
  不含 command、corrected text、距离、置信度或 medication slots
- evidence does not prove：真实 ASR 准确率、延迟、RSS或实机动作门
- decision：keep；进入 generated/public aggregate benchmark
- next single action：先为 manifest和evaluator写 RED，再实现无 transcript benchmark

### R6 — Generated Paraformer 动作 benchmark

- 日期：2026-08-28
- branch / exact HEAD：`codex/xiaomi-camera-reply-lifecycle-review` / `0fb90cb`
- dirty/unrelated state：Task 5 已聚焦提交；本 slice 只新增 benchmark tool/test、计划和
  本日志
- authority：software-only；允许 macOS Tingting 生成临时测试音频；禁止播放和家庭采集
- hypothesis：H4；当前 Paraformer加闭集层可覆盖低风险动作，药物高风险短句必须独立
  通过 exact gate
- files changed：新增 `tools/voice_action_benchmark.py`、
  `tests/tools/test_voice_action_benchmark.py`，修改计划和本日志
- RED command/result：初始 module RED 为 1 collection error；首轮 GREEN 尝试为
  2 failed / 10 passed，分别捕获损坏 WAV 的未封装 EOF 和 false accept 被误计入
  exact matches；per-action 聚合独立 RED 为 1 failed
- GREEN command/result：benchmark tests 12 passed，exit 0
- focused/full command/result：benchmark unit 12 passed；真实 generated candidate
  `gate_passed=false`；full repository 尚未运行
- corpus：Tingting generated-only、24 positives / 48 adversarial negatives、四个固定 rate、
  license=`GENERATED`；临时 WAV 在退出时删除
- positives/accepted/rejected：总计21/24正确；Feeding 4/4、diaper start/complete 8/8、
  burping start/complete 6/6、medication start 3/3、medication complete 0/3；后三条被拒绝
- negatives/false accepts：48/48 rejected，false accepts=0
- latency p50/p95/RSS：87 ms / 196 ms / NOT_RUN（子进程没有可信的独立RSS边界）
- privacy scan：CLI JSON只含固定action code与聚合计数；无fixture ID、路径、PCM或
  transcript；临时目录自动清理
- Camera Reply flag/lifecycle：未读取或修改；保持 false；没有播放
- Baby Care write/outbox/signing：未构造、未调用；medication 只在内存成为 high-risk
  candidate
- evidence proves：当前本地 Paraformer在该generated corpus上低风险18/18、medication
  start 3/3、全部负例48/48；medication complete exact gate未通过
- evidence does not prove：家庭声学准确率、真实成人召回、公开模型许可或medication完成
  命令可发布
- disproved/environment note：沙箱内 macOS `say` 可成功返回空WAV；真实登录用户上下文
  单条格式门为16kHz/mono/16-bit且帧数为正，故generated benchmark必须使用该上下文
- decision：keep current Paraformer用于Feeding/diaper/burping软件层；不放宽 medication、
  不安装KWS/HR/FunASR；medication complete保持fail closed并延后独立高风险设计
- next single action：运行Task 7完整软件、编译、diff和隐私门并同步真实状态

每条新记录使用一个连续编号 `R1`、`R2`……，并完整写出以下字段：

```text
### R<number> — <固定短标题>

- 日期：YYYY-MM-DD
- branch / exact HEAD：...
- dirty/unrelated state：...
- authority：software-only / install-approved / supervised-device-approved
- hypothesis：H<number>
- files changed：...
- RED command/result：...
- GREEN command/result：...
- focused/full command/result：...
- corpus：synthetic/public fixture IDs and license only
- positives/accepted/rejected：aggregate integers
- negatives/false accepts：aggregate integers
- latency p50/p95/RSS：fresh aggregate or NOT_RUN
- privacy scan：PASS/FAIL with bounded reason
- Camera Reply flag/lifecycle：fixed state only
- Baby Care write/outbox/signing：not constructed / not called / separately proven
- evidence proves：...
- evidence does not prove：...
- decision：keep / revise / rollback / defer
- next single action：...
```

上述格式中的省略号只说明字段结构；实际追加记录不得保留空字段或 `TBD/TODO`。无法
运行的项目写 `NOT_RUN: <固定、脱敏原因>`。

## 7. 复盘门

| Checkpoint | 触发条件 | 当前状态 | 必须回答的问题 |
|---|---|---|---|
| P0 设计复盘 | 方案、计划和入口文档完成 | 完成 | 范围保持为识别而非写入；风险分级和回滚已写入 |
| P1 Feeding 软件复盘 | Gate A focused/full software 结束 | 完成 | generated Feeding 4/4，低风险合计18/18，false accept 0；保留当前模型 |
| P2 Feeding 实机复盘 | 10 正例/20 负例监督门结束 | 未授权 | 实机是否真正改善；哪条证据可/不可外推 |
| P3 尿布/拍嗝复盘 | Gate B 每个动作独立结束 | 软件完成/实机未授权 | generated 14/14，未互相串类且不推断护理结果 |
| P4 喂药安全复盘 | Gate C 软件/监督门结束 | 软件阻塞 | start 3/3，complete 0/3且安全拒绝；未确认或外部写入 |
| P5 模型决策复盘 | HR/KWS/Contextual 候选被评估或否决 | 当前模型保留 | 低风险保留Paraformer；高风险候选待独立设计/许可 |
| P6 最终复盘 | 所有获批动作门结束 | 未开始 | 最终保留方案、删除方案、遗留风险、下一合同 |

任何 false accept 都立即触发额外复盘，不等待当前 gate 完成。复盘必须保留失败，不能
只记录最终 GREEN。

## 8. 最终 resolution 要求

完成实施与监督门后，新建：

`docs/reviews/2026-08-27-voice-care-multi-intent-asr-optimization-resolution.md`

resolution 必须包含：

1. 基线与最终 exact head；
2. 最小复现；
3. 根因和被推翻假设；
4. 每个动作独立的正例、负例和 false-accept 结果；
5. current Paraformer、受限纠错及任何上游候选的对比；
6. p50/p95/RSS 与启动/故障隔离；
7. privacy scan 和家庭输入 memory-only 证据；
8. Camera Reply、Xiaomi producer、Baby Care 写入的独立状态；
9. 保留、回滚和删除的代码/资产；
10. 未验证风险和下一次实机/合同 gate；
11. commit、push、PR、merge 的真实状态。

## 9. 当前唯一下一步

软件 Tasks 1–7 已完成，获批的 Task 8 低风险实机门也已执行，但因召回不足而未接受。
当前唯一下一步是 synthetic/public-first 诊断组合 wake/action 入口和 armed 拍嗝 complete
的 `far` 拒绝。Camera Reply 保持 false；medication complete 在 generated gate 为 0/3，
必须先有独立高风险设计，不得放宽纠错、安装未批准模型或无人值守采集家庭音频。

### R7 — 完整软件与文档门

- 日期：2026-08-28
- branch / exact HEAD：`codex/xiaomi-camera-reply-lifecycle-review` / `df7b762`
- dirty/unrelated state：Tasks 1–6均已聚焦提交；Task 7开始时tracked worktree clean
- authority：software-only；本轮允许本地测试、文档检查点、聚焦提交和当前分支push
- hypothesis：H4；closed registry、受限纠错和聚合状态可通过全软件门且不扩张外部合同
- files changed：Tasks 1–6的16个批准业务/测试/计划文件，加本轮6个权威状态文档
- RED command/result：沿用R1–R6逐slice真实RED；Task 7不新增行为代码
- GREEN command/result：Task 7聚焦10文件247 passed；完整Voice 524 passed
- focused/full command/result：聚焦247/247、Voice 524/524、完整Python 1829/1829
- corpus：source-controlled synthetic strings和Tingting generated-only临时WAV，license=`GENERATED`
- positives/accepted/rejected：低风险18/18；medication start 3/3；medication complete 0/3并拒绝
- negatives/false accepts：48/48 rejected；false accepts=0
- latency p50/p95/RSS：87 ms / 196 ms / NOT_RUN（无可信独立RSS边界）
- privacy scan：compileall、diff-check和批准敏感模式扫描PASS；无家庭音频、转写或私有路径
- Camera Reply flag/lifecycle：保持false；未读取、启用、播放或重启实机服务
- Baby Care write/outbox/signing：not constructed / not called / unchanged
- evidence proves：closed软件合同、聚合状态、低风险generated召回和零generated误接收
- evidence does not prove：家庭声学、成人/儿童实机召回、夜间/远场、Camera Reply或护理写入
- decision：keep低风险实现；defer medication complete；Task 8等待成人单独批准
- next single action：成人返回后只运行Task 8低风险监督门；药物先做独立高风险设计

### R8 — 私有 Voice 诊断软件门

- 日期：2026-08-28
- branch / exact HEAD：`codex/xiaomi-camera-reply-lifecycle-review` / `fb7b17bd7ccae49f3d1ca50104045d49f329925e`
- dirty/unrelated state：业务提交后tracked worktree clean；随后仅本计划与本日志待文档检查点提交
- authority：software-only；未授权本轮录音、摄像头播放、push、merge或家庭内容读取
- hypothesis：H4；诊断旁路可在不改变识别结果和Camera Reply状态的条件下安全保留聚合证据
- files changed：7个批准的Voice诊断业务/测试文件；无go2rtc、小米协议、Baby Care或模型改动
- RED command/result：最终review wave明确观察15个边界回归失败，覆盖writer settlement、取消、父目录/临时文件竞态、rollback、FD所有权、lifecycle残留和重复pending容量
- GREEN command/result：最终affected review set 88/88；独立复审0 Critical、0 Important
- focused/full command/result：诊断focused 194/194、Voice 587/587、完整Python 1892/1892
- corpus：仅source-controlled synthetic metadata与生成PCM；未访问家庭音频或私有diagnostic内容
- positives/accepted/rejected：NOT_RUN（本轮是存储、生命周期和隐私软件门，不是识别准确率门）
- negatives/false accepts：NOT_RUN（未进行家庭或generated ASR benchmark）
- latency p50/p95/RSS：NOT_RUN（本轮不建立识别性能结论）
- privacy scan：PASS；compileall、Make dry-run、diff-check、tracked-scope与敏感模式扫描通过；唯一模式命中为代码变量`token_bytes`，不是凭据
- Camera Reply flag/lifecycle：未读取或修改运行时flag；未启用、播放、重启go2rtc或接触实机
- Baby Care write/outbox/signing：not constructed / not called / unchanged
- evidence proves：严格私有残留不会被误删、不会冒充complete、会占用序号，且status/stop/expired-start生命周期可恢复；未知或重复残留fail closed
- evidence does not prove：家庭语音采集、真实转写质量、持续监听稳定性、摄像头扬声器可听性或护理记录写入
- decision：keep Task 6软件实现；defer supervised local diagnostic to Task 7
- next single action：成人在场时执行一次Task 7监督本地诊断；先检查模式和状态，再短时采集，完成后显式stop

### R9 — Task 8 低风险成人监督实机门

- 日期：2026-08-28
- branch / exact pre-doc HEAD：`codex/xiaomi-camera-reply-lifecycle-review` / `bb4f737`
- installed candidate：`528b31a`
- authority：成人监督 Feeding、尿布和拍嗝；不含药物、Camera Reply、Baby Care 写入或私有诊断
- preflight：Voice healthy/listen-only；Camera Reply=false；source PASS；diagnostic inactive；transport=auto、producer_count=1、producer_replaced=false
- positives/accepted：Feeding 8/11；diaper single-sentence 0/2、two-stage 2/2；burping single-sentence 0/2、two-stage start 1/1、complete 0/2
- negatives/false accepts：共享20/20静默；动作相关负例静默；false accepts=0
- fixed deltas：feeding exact +8、diaper exact +2、burping exact +1、action rejected +2、ignored far +2、output failures +0
- latency p50/p95/RSS：NOT_RUN；普通 memory-only 状态不保存逐 utterance latency，禁止复用 generated 数字
- privacy：diagnostic前后inactive/0 records/0 bytes；未保存或记录家庭音频、转写、session ID或私有路径
- Camera Reply / movement：false；未播放摄像头扬声器；成人未观察到转动
- Baby Care：write/outbox/signing均未构造或调用
- evidence proves：closed safety boundary、零观察误接受、两阶段尿布与拍嗝start分类可达
- evidence does not prove：稳定家庭召回、儿童/远场/夜间、拍嗝complete、Camera Reply或护理写入
- decision：keep fail-closed implementation；Task 8 recall FAIL；Camera Reply V3E不恢复
- next single action：synthetic/public-first诊断组合wake/action入口与armed burping-complete far；不先放宽规则

### R10 — Task 8 组合 wake/action 入口软件修复

- 日期：2026-08-28
- authority：已批准的 bounded software fix；不含部署、实机播放、私有诊断、push或merge
- hypothesis：尿布/拍嗝单句组合漏识别来自 punctuation-free wake allowlist 缺项
- RED：新增四个组合正例在 wake/controller 层共 8 failed；否定、疑问、多动作和未知后缀 4 passed
- GREEN：只增加四个已批准 Gate B 精确前缀；新门 12/12、affected Voice 161/161、完整 Voice 605/605
- generated benchmark：current Paraformer 低风险 18/18、负例 48/48、false accepts 0；模型不变
- privacy/scope：仅 synthetic 字符串；无家庭音频/转写、Baby Care、Camera Reply、go2rtc或运行配置改动
- evidence proves：组合 wake/action 的确定性软件入口缺口已关闭且反例继续 fail closed
- evidence does not prove：installed i9 实机召回或 armed burping-complete `far` 已解决
- next single action：短监督复验四个组合命令；拍嗝 complete 保持独立诊断
