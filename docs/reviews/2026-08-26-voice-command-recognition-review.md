# Voice 口令识别审查与修复任务书

日期：2026-08-26

审查基线：`codex/voice-care-v1-gate-v1` @ `1ab5c996c55a446d149d45edcb48642a2857ff3b`

状态：根因已确认，等待本地 Codex 按本文执行 RED/GREEN 修复

范围：只处理日常 Voice 口令的唤醒和喂奶开始语法；不处理模型训练、声纹阈值或 Baby Care 启用

## 1. 审查结论

用户最初要求的口令：

```text
嘿，小小，我要喂奶了
```

在当前代码中无法进入护理意图。失败由两个相互独立的闭集规则共同造成：

1. `嘿，小小` 被唤醒层明确判定为非唤醒；当前只允许规范化后以精确 `小小` 开头。
2. 即使去掉 `嘿`，`我要喂奶了` 也不在喂奶开始语法中；当前只接受
   `我要开始喂奶`、`开始喂奶` 等固定表达。

这不是单纯的摄像头音频、VAD 或 ASR 故障。ASR 即使正确输出用户原句，后续规则层仍会
静默返回 `listen_only_ignored`，操作者看到的现象就是“口令没有识别”。

## 2. 可重复证据

使用审查基线中的真实 `classify_wake()` 与 `parse_feeding_command()` 得到：

| 输入 | 唤醒结果 | 解析出的命令 | 护理意图 |
|---|---|---|---|
| `嘿，小小，我要喂奶了` | `not_wake` | 无 | 无 |
| `小小，我要喂奶了` | `wake_with_command` | `我要喂奶了` | 无 |
| `小小，开始喂奶` | `wake_with_command` | `开始喂奶` | `feeding_start` |
| `小小` | `standalone_wake` | 无 | 等待后续命令 |
| `开始喂奶` | `not_wake` | 无 | 无 |

对应代码证据：

- `services/voice/wake.py:8,41-71`：唯一 `WAKE_PREFIX = "小小"`。
- `tests/voice/test_wake.py:38-49`：把 `嘿，小小，我是爸爸` 明确列入拒绝用例。
- `services/voice/intent.py:162-168`：`start_modes` 缺少 `我要喂奶了`。
- `services/voice/listen_only.py:65-78,153-176`：只有唤醒和闭集命令同时通过才会回应。
- `docs/superpowers/specs/2026-08-19-voice-care-v1-design.md:464`：产品示例仍是
  `小小，我要喂奶了`，与实现不一致。
- `docs/runbooks/VOICE_LISTEN_ONLY.md:31-37`：当前运行手册仅描述两阶段
  `小小` → `开始喂奶`。

## 3. 根因

根因不是模型精度，而是规格、单层测试和端到端行为没有使用同一个金标准口令：

- wake 测试只证明能从 `小小，我要喂奶了` 提取命令，没有继续验证该命令能被
  `parse_feeding_command()` 接受；
- intent 测试只覆盖 `我要开始喂奶`，没有覆盖规格示例 `我要喂奶了`；
- `嘿，小小` 的用户原始交互要求在后续“精确唤醒”收敛中被改为拒绝项，但没有明确
  记录这是一次产品行为变更，也没有让用户原始口令进入兼容测试；
- 缺少一条从 ASR 文本到 `ListenOnlyController` 最终回应的用户金句回归测试。

## 4. 当前产品边界

修复时必须保留以下事实：

- 当前已验收的是 `listen_only`：识别后只说固定的“我听到了”，不会写入 Baby Care。
- full-care Voice 仍然 disabled；Dad/Mom 真实声纹注册、replay/overlap 和身份门未完成。
- 最新 `1ab5c99` 只修复了声纹注册的采集时序；真实 Dad 注册尚未在该实现上通过。
- 本次口令兼容修复不得借机启用 full-care、写护理记录或绕过身份验证。

## 5. 批准的最小修复目标

### 5.1 唤醒兼容

同时支持以下两个**精确**入口：

```text
小小
嘿，小小
```

`嘿` 只能作为固定、可审计的可选前导词，不能演变成模糊匹配。继续拒绝：

- `晓晓` 等同音或近音写法；
- 句中偶然出现的 `小小`；
- `小小鸟`、`小小心一点`；
- 重复唤醒词；
- 任意未批准前导语；
- 未知命令和非护理命令。

不要通过全局字符串替换、删除任意前缀或降低 ASR/VAD 阈值实现兼容。应在 wake
语法边界显式解析精确可选前导词，并继续由下游闭集 intent parser 决定命令是否合法。

### 5.2 喂奶开始别名

在 `idle` 状态下，将以下用户原句映射为现有 `feeding_start`、`mode=unknown`：

```text
我要喂奶了
```

保留现有 `我要开始喂奶` 和 `开始喂奶`。不要扩展到任意相似句、模型纠错或自由文本。

### 5.3 端到端目标

以下单句在 listen-only 模式必须只回应一次并返回 idle：

```text
嘿，小小，我要喂奶了
```

预期结构化结果：

```text
reason=listen_only_acknowledged
response_code=listen_only_received
phase=idle
```

listen-only 仍不得创建 Baby Care intent、签名、outbox 或护理事实。

## 6. 允许修改范围

优先只修改：

```text
services/voice/wake.py
services/voice/intent.py
tests/voice/test_wake.py
tests/voice/test_intent.py
tests/voice/test_listen_only.py
docs/superpowers/specs/2026-08-19-voice-care-v1-design.md
docs/runbooks/VOICE_LISTEN_ONLY.md
```

只有在现有测试组织确实要求时，才可最小修改相邻 Voice 测试或状态文档。

禁止修改：

- Silero、Paraformer、ECAPA 模型、工件或阈值；
- 录音、音频持久化和隐私边界；
- Voice 配对、签名、Keychain、身份或 Baby Care API；
- camera reply、Guardian、gauge、Dashboard 或远程访问；
- `main`、`stable/xiaomi-alpha` 或任何无关功能。

## 7. 本地 Codex 的严格 TDD 顺序

### Step 1：先写用户金句 RED

在 `tests/voice/test_wake.py` 增加：

- `嘿，小小，我要喂奶了` 必须分类为 `wake_with_command`；
- command 必须精确为 `我要喂奶了`；
- `嘿，小小` 必须分类为 `standalone_wake`；
- 新增固定负例，证明任意前导语、同音词、句中匹配和重复唤醒仍被拒绝。

运行并记录预期 RED：

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_wake.py
```

### Step 2：写 intent RED

在 `tests/voice/test_intent.py` 增加：

- `idle` + `我要喂奶了` → `feeding_start`、`mode=unknown`；
- 非 idle 状态仍返回 `state_conflict`；
- 未批准的相似句仍返回 `intent_uncertain`。

运行并记录预期 RED：

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_intent.py
```

### Step 3：写控制器端到端 RED

在 `tests/voice/test_listen_only.py` 增加真实用户金句：

```text
嘿，小小，我要喂奶了
```

断言仅一次 `listen_only_received`、`processed_count` 语义不重复、最终 phase 为 idle，
并证明原有两阶段 `小小` → `开始喂奶` 不回归。

### Step 4：最小 GREEN

只在 wake 和 intent 的闭集规则中增加上述两个精确兼容项。不要改模型、阈值、采集时序
或身份逻辑。每完成一个最小改动，都重跑产生 RED 的同一命令。

### Step 5：回归和文档一致性

更新规格和运行手册，使用户口令、精确边界和 listen-only 不落库行为一致。随后运行：

```bash
.venv-alpha/bin/python -m pytest -q \
  tests/voice/test_wake.py \
  tests/voice/test_intent.py \
  tests/voice/test_listen_only.py \
  tests/voice/test_listen_only_runtime.py
make alpha-voice-test
.venv-alpha/bin/python -m compileall -q services/voice
git diff --check
```

不要通过删除负例、放宽安全断言或跳过失败测试获得绿色结果。

## 8. 完成标准

只有同时满足以下条件才算完成：

- 用户原句 `嘿，小小，我要喂奶了` 的 wake、intent 和 listen-only 端到端测试通过；
- `小小，我要喂奶了`、`小小，开始喂奶` 和两阶段交互继续通过；
- 同音词、句中匹配、重复 wake、未知命令和非护理命令继续 fail closed；
- listen-only 只回应，不产生 Baby Care 写入；
- full-care Voice 仍 disabled；
- focused Voice 回归、`make alpha-voice-test`、compile 和 `git diff --check` 全部通过；
- 最终 diff 不含模型、家庭音频、transcript、凭据、私有路径或运行时数据；
- `STATUS`/`SUMMARY` 仅在行为和验证结果真实变化后按项目规则更新；
- 未经明确批准不 push、不建 PR、不 merge、不修改 `main`。

## 9. 实机复验（代码通过后）

实机步骤必须由登录 Intel i9 图形用户执行，Codex 一次只提示一个操作：

1. 确认安装的是修复后的精确 HEAD，并启动 listen-only。
2. 单句说 `嘿，小小，我要喂奶了`。
3. 确认只听到一次“我听到了”。
4. 检查 bounded status：`processed_count` 只增加 1，reason 为
   `listen_only_acknowledged`，服务仍 healthy。
5. 确认没有新增 wav/aiff/pcm/opus 文件，没有 Baby Care 记录，没有 sibling worker
   重启或 source 回归。

该实机复验只证明口令兼容和本地回应，不证明声纹身份、护理写入或无人照护安全。

## 10. 声纹注册口令是另一条问题链

如果操作者所说的“无法识别口令”指 `make alpha-voice-enroll-dad` 显示的随机数字口令，
不要用本修复掩盖它。应保留 `1ab5c99` 的 source warm-up、15 秒 drain 和 Silero-bounded
capture，先依据固定输出区分：

```text
failure_stage=capture
failure_stage=asr
failure_stage=challenge
```

只允许回传固定 stage 和 aggregate 指标；不得输出识别文本、PCM、家庭音频、Keychain
信息或本地私有路径。最新采集修复尚缺一轮真实 Dad/Mom 验收，它不能由软件测试替代。

## 11. 给本地 Codex 的最短指令

```text
读取 AGENTS.md、SUMMARY.md、docs/STATUS.md、docs/NEXT.md，以及
docs/reviews/2026-08-26-voice-command-recognition-review.md。

按审查文件修复日常 Voice 口令兼容问题。严格执行其中的 RED/GREEN 顺序，只修改允许范围，
保留全部 fail-closed、隐私和身份边界。完成 focused 与 alpha-voice-test、compile、
git diff --check 后更新必要状态文档并汇报。不要 push、PR、merge 或修改 main。
```
