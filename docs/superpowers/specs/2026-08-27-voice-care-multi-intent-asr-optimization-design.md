# Voice Care 多护理动作 ASR 优化设计

**日期：** 2026-08-27

**状态：** 用户已批准将优化方案写入项目；实现尚未开始。本设计只授权后续
Codex 按配套计划开展 synthetic/public-media 软件工作，不授权安装新模型、执行家庭
摄像头播放、启用 Camera Reply、写入 Baby Care、提交、push、创建 PR 或修改
`main/stable`。

**基线：** `codex/xiaomi-camera-reply-lifecycle-review` @
`4f599225f908d8052006353a9dafec03eed40fdf`

**前置证据：**
`docs/reviews/2026-08-27-voice-asr-near-start-design-handoff.md`

**配套计划：**
`docs/superpowers/plans/2026-08-27-voice-care-multi-intent-asr-optimization.md`

**过程与复盘日志：**
`docs/reviews/2026-08-27-voice-care-multi-intent-asr-optimization-log.md`

## 1. 目标

把当前只面向 Feeding V1 的 Voice listen-only 识别边界整理成一个可逐项扩展、
fail-closed、可测试和可复盘的护理动作识别层。

第一优先级仍是修复已经复现的 `开始喂奶` near-start 拒绝。框架随后分阶段支持：

1. 喂奶；
2. 换尿布；
3. 拍嗝；
4. 喂药候选；
5. 经单独小规格批准的其他护理动作。

“识别动作”与“保存护理事实”必须保持为两个不同能力。listen-only 可以确认自己识别到
一个闭集命令，但不得创建、更新、结束或确认 Baby Care 记录。除 Feeding V1 外，当前
Baby Care Voice 合同没有尿布、拍嗝或药物 intent；本设计不得在本仓库单方面发明外部
合同或把内部候选伪装成已保存事实。

## 2. 当前事实基线

### 2.1 已确认的最新故障层

在五次成人监督的两阶段 follow-up 中，`开始喂奶` 只有一次得到确认；四次被拒绝。
固定聚合证据为：

- `ignored_near_start=4`；
- `ignored_near_reply_echo=0`；
- `ignored_far=0`；
- Camera Reply lifecycle 为 `34/34/34/34`；
- speaker closed，且无 write、stop、pending 或 residual failure；
- Xiaomi 拾音、Opus、PCM、VAD、utterance 和 tail replay 均有活动证据。

因此当前首个失败层是 Paraformer 输出后的文本/闭集解析边界，不是摄像头未拾音、
整段 follow-up 被截断、固定回复 echo、speaker settlement、视频或共享 producer。

由于隐私边界不持久化家庭 transcript，现有证据不能说明四次近似文本分别是同音字、
漏字、插字还是词序变化。任何具体错误文本都必须标注为 synthetic/public fixture，不能
冒充实机原文。

### 2.2 当前真正支持的动作

`services/voice/intent.py` 是 Feeding 专用闭集解析器，当前外部合同只有：

- `feeding_start`；
- `feeding_update`；
- `feeding_end`；
- `care_confirm`；
- `care_cancel`。

`services/voice/listen_only.py` 复用该 Feeding 解析器，只判断语法是否闭合并播放固定
`我听到了。`，不会使用解析结果写护理记录。

当前状态如下：

| 动作 | ASR 可能转写 | 闭集解析 | Listen-only 确认 | Baby Care 合同/写入 |
|---|---:|---:|---:|---:|
| 喂奶 | 是 | 已有，但 near-start 实机不稳定 | 已有 | Feeding V1 已定义，Full-care 仍受门禁保护 |
| 换尿布 | 是 | 未实现 | 未实现 | 未定义 |
| 拍嗝 | 是 | 未实现 | 未实现 | 未定义 |
| 喂药 | 是 | 明确拒绝/未实现 | 未实现 | 未定义；必须高风险人工确认 |
| 其他动作 | 可能 | 未实现 | 未实现 | 未定义 |

底层 ASR 能输出中文不等于系统已经识别了护理动作。只有通过动作词表、状态、否定与
问题保护、风险策略和验收门的输入，才能称为已识别。

## 3. 设计决策

采用“闭集动作注册表 + 动作域内受限纠错 + 风险策略”的方案。当前生产 Paraformer
继续作为唯一 ASR，不立即更换模型，也不盲目升级 sherpa-onnx。

```text
one long-lived Xiaomi producer
  -> audio_analysis Opus
  -> mono 16 kHz PCM
  -> Silero VAD / bounded utterance
  -> pinned Paraformer
  -> punctuation/space normalization only
  -> exact closed action classifier
  -> if armed and exact failed: action-scoped guarded correction
  -> exact classifier again
  -> risk policy
  -> listen-only acknowledgement or high-risk candidate
  -> aggregate-only status; discard/zeroize PCM and text
```

不采用开放式 LLM/embedding 意图判断，不采用通用模糊匹配，不让 KWS 单独触发护理
意图。语义模型以后可以作为离线候选分析器，但不能直接控制 Camera Reply、写 Baby Care
或绕过闭集解析器。

## 4. 动作风险分级和发布顺序

### Gate A — Feeding near-start

只解决现有 `开始喂奶` follow-up 被识别成近似文本的问题。该 gate 不增加外部 intent，
不改变 Feeding V1 状态机和 Baby Care 合同。

允许的首批精确 Feeding start 仍来自现有解析器，例如：

- `开始喂奶`；
- `我要开始喂奶`；
- `我要喂奶了`；
- `开始喂配方奶`；
- `开始喂母乳`；
- `开始亲喂`。

纠错只覆盖经审查的 synthetic/public 混淆映射；例如已有测试 fixture
`开始为奶 -> 开始喂奶`。它不是实机 transcript 证据，也不能推导出一个通用
edit-distance 规则。

### Gate B — 换尿布和拍嗝

这两个动作先作为低风险 listen-only 识别类别，不产生外部护理 intent。初始闭集只覆盖
明确的动作句，不推断宝宝状态或完成质量：

- 换尿布：`开始换尿布`、`换好尿布了`；
- 拍嗝：`开始拍嗝`、`拍嗝结束`。

这些命令只表示成人说出了动作，不表示系统观察到尿布湿/便、宝宝已经打嗝或动作达到
护理效果。尿布类型、排便情况、发生时间和拍嗝结果属于后续结构化合同，不在本 gate
推断。

### Gate C — 喂药候选

药物属于高风险护理信息。初始闭集可以识别 `开始喂药`、`喂药完成` 为
`medication_candidate`，但必须满足：

- 不进行近似纠错；
- 不复用低风险 `我听到了` 作为“记录成功”证明；
- 不构造、签名、排队或发送 Baby Care intent；
- 不推断药名、剂量、单位、给药途径或是否已经服下；
- 只有后续单独设计的药名、剂量、单位、照护人和明确二次确认闭环通过后，才可讨论
  护理记录写入；
- 医嘱、剂量建议和用药决策不属于 Voice 系统能力。

本 gate 的成功结果只能是内存中的高风险候选和固定聚合计数。用户可见确认方式需要
单独批准的交互设计；在此之前宁可静默 fail closed，也不能播放容易被理解成“已给药或
已记录”的确认语。

### Gate D — 其他护理动作

睡觉、醒来、洗澡、测温、吸奶等动作不进入首轮实现。动作注册表必须允许以后逐项扩展，
但每个新动作都需要：

1. 明确的业务语义和风险等级；
2. 精确正例与最容易混淆的负例；
3. 状态约束和一条 utterance 只匹配一个动作的规则；
4. 独立 synthetic/public 软件门；
5. 如需写入，Baby Care 先发布相应版本化合同；
6. 单独成人监督实机验收。

“其他动作”不是开放词表入口，不能使用相似度最高的类别兜底。

## 5. 内部接口边界

新增的内部动作识别接口只供 listen-only 使用，不能直接替换现有
`parse_feeding_command()` 或 `VoiceCareIntentV1`。

建议内部结果包含：

- 固定 `action_code`；
- 固定 `risk`；
- `exact|corrected|high_risk_candidate|rejected`；
- 是否允许固定 listen-only acknowledgement；
- transcript-free 固定 reason。

结果对象只在一次 utterance 的内存生命周期内存在。状态文件只能接收固定 reason 和
有界整数计数，不能接收原始文本、纠错前后文本、编辑距离、字符、概率或 PCM 摘要。

现有 Feeding full-care 路径继续调用 `parse_feeding_command()` 和版本化合同。新内部动作
注册表不得被 `services/voice/worker.py` 的 Care 模式自动调用；未来跨产品写入需要新的
Baby Care 规格、schema、签名 fixture、幂等和人工确认门。

## 6. 受限纠错合同

纠错只能在以下条件全部成立时运行：

1. controller 已因一个精确 wake 进入 armed follow-up；
2. 当前 utterance 的精确闭集解析已经失败；
3. 输入长度、字符集和归一化边界有效；
4. 只尝试一个明确动作域的 source-controlled 映射；
5. 输入不包含该 start 动作的否定、停止、取消或疑问形态；
6. 输入不同时包含两个护理动作域；
7. 纠错结果再次通过精确闭集解析；
8. 一次 utterance 最多产生一个结果并立即回到 idle。

严格禁止：

- `edit_distance <= N` 直接接受；
- `startswith("开始")` / `endswith("奶")` 一类形状兜底；
- 把未知字替换为最接近的护理名词；
- 跨动作纠错，例如把 `开始喂药`、`开始换尿布` 或 `开始拍嗝` 映射到
  `开始喂奶`；
- idle 状态近似 wake 或近似护理命令触发；
- 对喂药候选做近似纠错；
- 把 KWS 命中当作最终意图；
- 记录纠错前后的家庭 transcript。

start 纠错至少必须拒绝以下族：

- 否定：`不要开始喂奶`、`不喂奶`、`还没开始喂奶`；
- 停止/取消：`停止喂奶`、`结束喂奶`、`取消开始喂奶`；
- 疑问：`开始喂奶吗`、`要不要开始喂奶`、`是不是开始喂奶`；
- 相邻语义：`开始断奶`、`开始泡奶`、`开始热奶`；
- 其他动作：`开始喂药`、`开始换尿布`、`开始拍嗝`；
- 普通陈述：`宝宝刚才喝了奶`、`刚换过尿布`；
- 无 wake/armed 上下文的任何近似短语。

本设计只在 armed listen-only 内放宽
`docs/superpowers/specs/2026-08-25-voice-listen-only-design.md` 中对 phrase repair 的
绝对禁止；wake、full-care、身份、签名、Baby Care 写入和其他状态仍保持原禁止边界。

## 7. GitHub 上游方案决策

### 7.1 当前 Paraformer 直接 hotword — 不采用

当前固定 `sherpa-onnx 1.13.6` 的 Paraformer offline recognizer 只支持
`greedy_search`，其 Python `from_paraformer()` 没有模型级 hotword/contextual
biasing 参数。不能通过增加一个配置项声称已经启用热词。

参考：

- https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.6/sherpa-onnx/csrc/offline-recognizer-paraformer-impl.h
- https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.6/sherpa-onnx/python/sherpa_onnx/offline_recognizer.py

### 7.2 HomophoneReplacer — 仅离线 A/B

同一 sherpa-onnx 版本支持 `hr_dict_dir`、`hr_rule_fsts` 和 `hr_lexicon`，且
Paraformer decode 后会应用 HomophoneReplacer。它可用于确认“同音替换是否足以解决
Feeding near-start”，但不是声学热词增强。

风险包括：

- 全局替换影响 wake、否定、疑问和普通对话；
- 需要新的 lexicon/FST 资产、digest、许可和 artifact contract；
- 无法解决漏字、插字或语序错误；
- 当前不知道四次实机近似结果是否都是同音问题。

因此只允许在 synthetic/public 离线 evaluator 中比较，不允许直接接入生产 runner。

参考：

- https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.6/c-api-examples/sense-voice-with-hr-c-api.c

### 7.3 sherpa-onnx KWS — 有条件的中期候选

官方 Keyword Spotter 支持关键词文件、每词 score 和 threshold。它可以在 armed 窗口为
完整护理短语提供第二信号，并复用 sherpa 运行体系。

KWS 不能成为最终意图：`不要开始喂奶` 仍可能命中 `开始喂奶`。只有“KWS 命中 + ASR
通过否定/停止/取消/疑问保护 + 单一动作域”才可产生低风险候选。

当前公开中文 KWS 权重的可再分发许可仍需在打包前确认；许可未闭合时只能做获得单独
批准的本地评估，不能加入模型 manifest 或发布包。

参考：

- https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.6/sherpa-onnx/python/sherpa_onnx/keyword_spotter.py
- https://github.com/k2-fsa/sherpa/blob/master/docs/source/onnx/kws/index.rst
- https://github.com/k2-fsa/sherpa-onnx/issues/3760
- https://github.com/k2-fsa/sherpa-onnx/issues/3802

### 7.4 FunASR ContextualParaformer — 延后模型迁移评估

FunASR 官方 `ContextualParaformer` 和 ONNX runtime 示例支持 decoder hotword。
这是模型级方案，但意味着新模型、依赖、模型许可、digest、Intel macOS 延迟/RSS、worker
隔离和回滚验证。只有受限纠错与获许可 KWS 仍不能满足门禁时，才为其建立独立模型
迁移规格；本设计不授权安装或替换当前 Paraformer。

参考：

- https://github.com/modelscope/FunASR/blob/main/funasr/models/contextual_paraformer/model.py
- https://github.com/modelscope/FunASR/blob/main/runtime/python/onnxruntime/demo_contextual_paraformer.py
- https://github.com/modelscope/FunASR/blob/main/model_zoo/modelscope_models.md
- https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE

## 8. 隐私、日志和诊断

家庭 PCM、原始音频、完整/局部 transcript、字符差异、药名、剂量和自由文本均保持
memory-only，并在 utterance 结束、失败、超时、取消、进程关闭或新 playback 时清理。

允许持久化的只有：

- 固定版本号和 exact Git head；
- fixed reason；
- 每个动作 gate 的有界整数计数；
- exact/corrected/high-risk-candidate/rejected 聚合计数；
- p50/p95 延迟、样本总数和 pass/fail；
- synthetic/public fixture ID；
- 模型/规则资产的公开名称、许可和 digest。

禁止把家庭 transcript 为了“方便调试”临时写入普通日志。若无法区分混淆类型，先通过
synthetic/public corpus 和聚合分类缩小，再由成人在受控本机界面即时观察；观察内容不
进入 Git、聊天或状态文件。

## 9. 验收矩阵

### 9.1 软件门

每个动作 gate 都必须按 RED -> 最小 GREEN -> focused -> Voice gate 顺序执行。至少覆盖：

| 类别 | 必须证明 |
|---|---|
| 精确正例 | 每个批准词组只确认一次并回 idle |
| synthetic 近似正例 | 只有 source-controlled 映射可纠正 |
| 否定/停止/取消/疑问 | 误接受为 0 |
| 跨动作 | 误映射为 0 |
| 无 wake/超时 | 误触发为 0 |
| reply echo/replay | 不消费真实 armed follow-up |
| 多动作同句 | fail closed |
| medication | 不纠错、不确认保存、不构造外部 intent |
| 隐私 | 无 PCM/transcript/private path 进入 diff、log 或 status |
| 性能 | 与当前 Paraformer 基线分别记录 p50/p95/RSS，不隐藏退化 |

任何负例误接受都阻止进入实机 gate。正例召回不足可以继续优化，但不能通过降低负例门
换取通过。

### 9.2 成人监督 i9 门

实机阶段必须单独批准，并按以下顺序隔离变量：

1. Camera Reply 继续 false，使用已接受的 i9 输出或只读聚合状态验证 ASR；
2. Feeding 先做至少 10 次正例和 20 次覆盖否定、问题、相邻语义、无 wake 的负例；
3. Feeding clean 后，分别测试换尿布和拍嗝，每个动作独立清零计数；
4. Medication 只验证 high-risk candidate，不播放“已记录”确认，不写护理事实；
5. 只有多动作识别层单独通过，才返回 Camera Reply V3E 组合矩阵；
6. Camera Reply 成功不能代替 ASR 成功，ASR 成功也不能代替 Camera Reply、身份或写入成功。

出现任一误接受、重复确认、摄像头转动、截断、producer replacement、timeout、EOF、
残留 sender 或状态不一致，立即停止该 run，保持 Camera Reply false，记录聚合证据并回滚
到前一已知精确解析配置。

## 10. 过程记录和复盘

后续 Codex 每完成一个 RED/GREEN slice、模型 A/B、安装前置或实机小门，必须追加
`docs/reviews/2026-08-27-voice-care-multi-intent-asr-optimization-log.md`，记录：

- exact branch/HEAD 和工作区状态；
- 假设、预期首个失败层和实际证据；
- 使用的 synthetic/public corpus 及许可；
- 运行命令、真实 pass/fail 数和延迟；
- 误接受数；
- 哪些结论被证明、被推翻或仍未验证；
- 是否改动模型、规则、状态机或外部合同；
- 回滚状态、Camera Reply flag 和 Baby Care 写入边界；
- 下一步唯一动作。

Feeding gate、每个新增动作 gate、任何 false accept、模型候选否决和最终实机 gate 后都要
复盘。最终必须新建：

`docs/reviews/2026-08-27-voice-care-multi-intent-asr-optimization-resolution.md`

resolution 必须对比基线与最终：召回、误接受、延迟、资源、隐私、实机结果、保留/删除
方案、回滚和剩余风险。没有新鲜测试或实机证据时必须写“未验证”，不能沿用历史数字。

## 11. 回滚和发布边界

- 默认回滚是移除/关闭动作域纠错，恢复 exact-only listen-only parser；
- Camera Reply 保持 false，直到单独的 V3E 组合门通过；
- Full-care Voice、Dad/Mom enrollment、replay/overlap、签名、outbox 和 Baby Care 写入
  不因本设计自动解锁；
- 不改变 `transport=auto`、单一长期 Xiaomi producer、固定 go2rtc patch 或 PTZ 禁用；
- 不把 HomophoneReplacer、KWS、FunASR 模型资产加入仓库，除非许可、digest、性能和
  回滚规格另行批准；
- 不 push、PR、merge、tag 或修改 `main/stable`，除非用户单独明确批准。

## 12. 完成标准

本设计只有在以下条件全部满足时才可称为完成：

1. Feeding near-start 在软件和成人监督样本中达到批准的正例门，负例误接受为 0；
2. 换尿布和拍嗝分别通过独立 closed-corpus 门，不依赖 Feeding 模糊规则；
3. Medication 只产生 high-risk candidate，无纠错、无写入、无误导性确认；
4. current Paraformer 的延迟和资源退化有真实数字；
5. 所有家庭输入仍 memory-only；
6. 完整 Voice 软件门和 privacy scan 通过；
7. review log 完整，resolution 明确保留/否决的上游方案；
8. `SUMMARY.md`、`docs/STATUS.md`、`docs/CHECKPOINT.md`、`docs/NEXT.md` 与真实状态一致；
9. 任何实机结论都由单独监督证据支持；
10. 远端操作仍遵守用户单独授权。

## 13. 给后续 Codex 的读取入口

```text
读取 AGENTS.md、SUMMARY.md、docs/STATUS.md、docs/CHECKPOINT.md、docs/NEXT.md，随后完整读取：

1. docs/reviews/2026-08-27-voice-asr-near-start-design-handoff.md
2. docs/superpowers/specs/2026-08-27-voice-care-multi-intent-asr-optimization-design.md
3. docs/superpowers/plans/2026-08-27-voice-care-multi-intent-asr-optimization.md
4. docs/reviews/2026-08-27-voice-care-multi-intent-asr-optimization-log.md

从计划第一个未完成 checkbox 继续。先确认 exact branch/HEAD 和 dirty state；先 RED，
再做最小 GREEN。不得启用 Camera Reply、安装新模型、持久化家庭音频/transcript、写
Baby Care、修改 main/stable、提交或 push，除非获得对应的单独明确授权。每个 slice
结束必须更新 review log，并用真实命令和结果复盘。
```
