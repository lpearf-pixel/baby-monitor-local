# Voice ASR `near_start` 问题 Web 设计交接

日期：2026-08-27

状态：根因层已收敛；暂停业务修复，等待 Web 端设计裁决

当前开发分支：`codex/xiaomi-camera-reply-lifecycle-review`

证据检查点：`902c692`（V3E `near_start` 实机证据）

## 1. 本次问题

在已唤醒的两阶段 Voice 交互中，成人说固定后续命令：

```text
开始喂奶
```

连续五次监督测试只有一次得到确认回复。其余四次没有回复。

这不是 2026-08-26 审查已经修复的 `嘿，小小` 前导词和
`我要喂奶了` 固定语法问题。旧问题属于 wake/intent 闭集缺项；本次问题发生在
摄像头音频已经进入 Voice、VAD 已经形成 utterance 之后。

## 2. 已确认的证据

以下结论来自固定聚合状态，不依赖家庭原始音频或完整 transcript：

- 小米摄像头音频已进入 i9，Opus 接收和 PCM/VAD 链路可工作。
- VAD 检测到了后续语音和 utterance。
- Task 17 的尾部内存缓冲已经捕获并回放后续音频帧。
- Camera Reply speaker lifecycle 保持 clean closed；最近一组为
  `started/written/stopped/settled = 34/34/34/34`。
- 失败样本没有落入“完全无关”或“摄像头回复回声”分类。
- 五次后续命令中，一次人工观察成功，四次被固定分类为 `near_start`：
  `ignored_near_start=4`、`ignored_near_reply_echo=0`、`ignored_far=0`。
- 因此当前首要故障层是 Paraformer ASR 输出或其闭集命令归一化：输出接近
  `开始喂奶`，但没有达到现有精确命令门。

隐私边界禁止持久化家庭原始音频和完整错误 transcript。因此不能声称四次分别识别成了
哪些具体文字；现有证据只支持固定的 `near_start` 距离桶。

## 3. 已排除或暂不支持的解释

- **不是摄像头完全没有拾音：** VAD speech/utterance 和输入计数均有进展。
- **不是尾部音频全部被 Camera Reply 截断：** 内存 replay frames 有进展；失败仍进入
  ASR 后的 `near_start` 分类。
- **不是固定回复回声被误当命令：** 本轮失败的 `near_reply_echo` 为零。
- **不是扬声器 settlement 失败：** speaker generation 闭合，未见 pending/residual。
- **没有证据支持降低 VAD 阈值：** 当前失败已越过 VAD 层。
- **没有证据支持重新训练 WS2021 或视觉模型：** 与本问题无关。

## 4. 当前 ASR 实现边界

生产链路为：

```text
Xiaomi Opus
  -> memory-only PCM
  -> Silero VAD
  -> sherpa-onnx Paraformer
  -> exact closed command parser
  -> fixed TTS response
```

当前固定运行条件：

- `sherpa-onnx 1.13.6`
- `sherpa-onnx-paraformer-zh-2023-09-14`
- 16 kHz 输入
- `greedy_search`
- Intel i9 Mac 本地离线运行

本地实际安装版本的 `OfflineRecognizer.from_paraformer()` 没有 hotword 参数。官方
`non_streaming_server.py` 示例同样只给 transducer 路径传入
`hotwords_file/hotwords_score`；Paraformer 路径没有这些参数：

- <https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/non_streaming_server.py>

因此不能在不更换识别路径或模型接口的情况下，声称当前 Paraformer 已经获得热词偏置。

## 5. GitHub 上可供 Web 端比较的成熟方向

### 5.1 FunASR Paraformer 热词定制

FunASR 官方 Paraformer 实现明确包含 Hotword customization：

- <https://github.com/modelscope/FunASR/blob/main/funasr/models/paraformer/model.py>

该方向最接近“仍做中文完整 ASR，但提高固定护理命令权重”。采用前必须单独验证：

- Intel x86_64 macOS 的离线安装和固定依赖；
- 模型来源、许可证、digest 和离线独立性；
- 冷/热延迟、常驻内存和 worker 隔离；
- `开始喂奶`、否定句、停止句、疑问句和普通成人对话的真实混淆矩阵；
- 模型不可用时 Voice fail closed，且不能影响视频、Dashboard 或其他 worker。

### 5.2 sherpa-onnx 开放词表 KWS

sherpa-onnx 官方提供无需为每个词重新训练的开放词表关键词识别，并允许用关键词文件
定义中文短语：

- <https://github.com/k2-fsa/sherpa/blob/master/docs/source/onnx/kws/index.rst>
- <https://github.com/k2-fsa/sherpa/blob/master/docs/source/onnx/kws/pretrained_models/index.rst>

该方向适合 `小小` 等唤醒词，或数量很少的严格固定关键词。它不自动等同于完整护理语句
理解。设计必须避免仅因检测到“喂奶”就接受以下语句：

```text
不要喂奶
停止喂奶
取消开始喂奶
开始喂奶吗
```

如果采用 KWS，建议只将它作为 wake/候选提示，最终仍由带否定和状态约束的闭集语法
确认命令。

### 5.3 当前模型后的受限命令纠错

本地存在一份尚未提交、尚未完成全门验证的试验性修改，目标是：

- 只在 `小小` 已经唤醒的有界 follow-up 窗口内运行；
- 只接受以 `开始` 开头、以 `奶` 结尾并接近 `开始喂奶` 的肯定形态；
- 显式拒绝否定、停止、结束、取消、未发生和疑问形式；
- 不做 idle 状态的通用模糊匹配；
- 不改变 ASR/VAD 阈值，不写 Baby Care。

试验性正向/对抗子集目前为 21 项通过，但这不是完整 Voice gate，也不是已交付行为。
Web 端应明确决定继续、修改或放弃该方向，不能把当前 worktree 当作完成实现。

## 6. 当前 Git/WIP 状态

开发 worktree：

```text
branch: codex/xiaomi-camera-reply-lifecycle-review
HEAD: 902c692
remote relation: ahead 30
```

存在两个未提交业务文件：

```text
services/voice/listen_only.py
tests/voice/test_listen_only.py
```

它们属于上述受限纠错试验，不应随本文档提交，也不得被 Web 端误认为已安装。

当前安装目录仍是 detached `73c88bf`，不含该试验性纠错。安装目录中既有未跟踪文件
`Interactive` 和 `test.sh` 必须继续保留，除非用户另行批准其归属或删除。

Camera Reply 私有启用标志最近保持 false；不要为了 ASR 设计重新启用实机播放。

## 7. Web 端需要裁决的设计问题

1. 短期是否完成严格受限的 post-ASR 命令纠错，先处理当前 `near_start` 实机失败。
2. 中期是否用 FunASR 热词 Paraformer 替换或补充现有 sherpa Paraformer。
3. 是否增加独立 KWS；若增加，它只负责 wake、候选命令，还是最终命令确认。
4. 是否采用以下分层结构：

   ```text
   KWS wake
     -> bounded armed command window
     -> hotword-biased ASR
     -> negation/stop/question guard
     -> closed care intent
   ```

5. 如何区分低风险“回应我听到了”和未来高风险“写护理事实”。后者必须继续经过
   Baby Care 身份、状态、签名和用户纠正边界，Guardian 不得直接写库。
6. 是否批准仅保存固定聚合诊断：目标 command ID、距离桶、否定词命中、VAD span 数、
   KWS/ASR 时延和固定结果码；不得保存家庭音频或完整 transcript。

## 8. 建议的验收矩阵

设计至少应要求 30 组成人监督语音，不用宝宝参与：

- 多距离、正常环境噪声和 Camera Reply 后立即说话；
- `开始喂奶` 肯定命令达到批准的召回门；
- `不要喂奶`、`停止喂奶`、`结束喂奶`、`取消开始喂奶`、`未开始喂奶`、
  `开始喂奶吗` 必须全部静默、fail closed；
- 未唤醒时说护理命令必须静默；
- 普通成人对话不得触发；
- 一次命令最多一次回复，无重复、无卡死、无摄像头移动；
- 超时后恢复 idle，下一次必须重新用关键字唤醒；
- 原始音频只存在于有界内存，测试结束后无家庭音频文件；
- Camera Reply、视频、音频接收、ASR 和护理写入四个状态分别记录，不能相互代证。

## 9. 当前禁止事项

在 Web 设计批准前：

- 不继续修改 ASR、纠错器、模型或阈值；
- 不安装新模型或依赖；
- 不执行新的实机播放；
- 不把近似命令自动升级为护理写入；
- 不持久化家庭原始音频或完整 transcript；
- 不启用 Camera Reply；
- 不合并或修改 `main/stable`。

## 10. 给 Web 端的最短读取指令

```text
读取 AGENTS.md、SUMMARY.md、docs/STATUS.md、docs/NEXT.md，以及
docs/reviews/2026-08-27-voice-asr-near-start-design-handoff.md。

基于已确认的 near_start ASR 根因，对比：现有 sherpa Paraformer + 受限纠错、
FunASR Paraformer 热词、sherpa-onnx 开放词表 KWS 三种方向。只输出设计与验收计划，
不要修改代码、安装模型或执行实机播放。必须保留否定/停止/疑问 fail-closed、
memory-only 家庭音频、Camera Reply disabled 和 Baby Care 写入隔离。
```
