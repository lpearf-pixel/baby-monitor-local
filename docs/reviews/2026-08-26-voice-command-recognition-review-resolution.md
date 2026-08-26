# Voice 口令识别审查处理结果

日期：2026-08-26

审查来源：`docs/reviews/2026-08-26-voice-command-recognition-review.md`

审查远端提交：`dd88ff6`

当前分支审查文档提交：`1c00899`

业务修复提交：`e786d2e`

状态：软件修复和自动测试完成；真实 Intel i9 单句复验待执行

## 1. 复现结果

在审查基线 `1ab5c99` 上直接调用真实 `classify_wake()` 与
`parse_feeding_command()`，结果与审查文档一致：

| 输入 | wake | command | intent |
|---|---|---|---|
| `嘿，小小，我要喂奶了` | `not_wake` | 无 | 无 |
| `小小，我要喂奶了` | `wake_with_command` | `我要喂奶了` | 无 |
| `小小，开始喂奶` | `wake_with_command` | `开始喂奶` | `feeding_start` |
| `小小` | `standalone_wake` | 无 | 无 |
| `开始喂奶` | `not_wake` | 无 | 无 |

因此两个审查 finding 均成立：唤醒闭集拒绝固定前导词 `嘿`，intent 闭集缺少
`我要喂奶了`。音频源、Silero、Paraformer 和 ECAPA 不参与这两个失败分支。

## 2. 修复范围

`services/voice/wake.py` 现在显式解析唯一可选前导词 `嘿`，随后仍要求精确
`小小`。带标点的 `嘿，小小` 和本地 ASR 省略标点后的 `嘿小小` 使用同一闭集入口。
任意其他前导语、同音词、句中匹配、重复唤醒词、未知命令和非护理命令继续拒绝。

`services/voice/intent.py` 仅增加精确别名 `我要喂奶了`，并映射到既有
`feeding_start`、`mode=unknown`。该别名只在 idle 状态成立；其他状态返回
`state_conflict`，相似但未批准的表达仍返回 `intent_uncertain`。

Listen-only 对用户金句只产生一次 `listen_only_received`，结构化结果为
`listen_only_acknowledged`，随后回到 idle。该路径仍不构造 Baby Care client、签名、
outbox 或护理事实。

## 3. RED/GREEN 过程

1. wake RED：新增固定前导词金句后得到 2 failed / 35 passed；最小实现后
   37/37 passed。
2. intent RED：新增精确别名和非 idle 状态后得到 2 failed / 16 passed；增加一个
   start-mode 条目后 18/18 passed。
3. listen-only 端到端 RED：在审查基线上，用户金句实际返回
   `listen_only_ignored`；恢复两处最小实现后控制器 8/8 passed。
4. 标点缺失 RED：对本地 ASR 可能产生的 `嘿小小` / `嘿小小我要喂奶了` 得到
   2 failed / 37 passed；仅增加精确连接形式和精确 post-wake 词法项后
   wake 39/39 passed。
5. 首轮全仓门在 synthetic benchmark 暴露 4 failed / 1630 passed：该 fixture 仍把
   已批准的 `嘿，小小，我是爸爸` 当作 negative，因而正确的新语法被误计为 false
   wake。仅将该 synthetic negative 换成仍被拒绝的任意前导语后，benchmark 26/26、
   第二轮全仓 1634/1634 passed。

没有删除或放宽原有负例、模型阈值、VAD 门、声纹门或身份门。

## 4. 新鲜验证证据

```text
focused wake/intent/listen-only/runtime: 72 passed
synthetic Voice model benchmark: 26 passed
make alpha-voice-test: 418 passed
full Python repository: 1634 passed
python compileall services/voice: PASS
git diff --check: PASS
tracked diff private/runtime/media/credential scan: 0 matches
```

修改范围只有 wake、intent、三组相邻行为测试、一个 synthetic benchmark fixture、
Voice v1 规格和 listen-only 手册。
没有模型、家庭音频、transcript、凭据、私有路径、运行时数据库或生成配置进入 Git。

## 5. 仍未证明的事项

- 尚未在安装了 `e786d2e` 的真实登录 Intel i9 上说出用户金句并确认一次回复。
- 软件测试不证明摄像头收音、房间噪声、实际 ASR 文本或扬声器播放质量。
- Full-care Voice 仍 disabled；Dad/Mom 声纹注册、replay/overlap 和身份门仍未完成。
- Listen-only 仍只回复固定确认语，不写 Baby Care 护理记录。
- Camera Reply V3 仍失败关闭且保持 disabled；本修复未触碰该路径。

## 6. 下一步复验

Web 审查业务提交 `e786d2e` 和本文后，在真实登录 i9 上安装该精确 HEAD，启动
listen-only，并只说一次 `嘿，小小，我要喂奶了`。验收要求：只听到一次
`我听到了`，`processed_count` 只增加 1，最终仍 healthy/idle，source 不回归，且没有
新增原始音频文件或 Baby Care 记录。
