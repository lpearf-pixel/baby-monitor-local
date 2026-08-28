# Voice Care 多护理动作 ASR Task 8 实机验收结论

**执行日期：** 2026-08-28
**分支：** `codex/xiaomi-camera-reply-lifecycle-review`
**验收前分支 HEAD：** `bb4f737783488b108f3428df24fe90ebf454dc1f`
**安装候选：** `528b31a45f521d3b11ad4882abac67732d1d06f7`
**结论：** 低风险动作保持 fail closed，但家庭实机召回未达到接受条件；不恢复
Camera Reply V3E，不扩张 Baby Care 合同。

## 1. 范围与前置条件

本轮只执行成人监督的 Feeding、换尿布和拍嗝低风险 listen-only 验收。药物候选因
generated gate 尚未完整通过且缺少独立高风险设计，未进入实机门。全程满足：

- Voice 为 `healthy / listen_only_idle`；
- `camera_reply_enabled=false`；
- Xiaomi source 为单一长期 producer；尾部 media diagnostic 为
  `configured_transport=auto`、`producer_count=1`、`producer_replaced=false`，source
  check 仍为 `cs2+udp`、H265、2560x1440 source / 1280x720 live；
- Voice diagnostic 前后均为 inactive、0 records、0 bytes；
- 未调用 Baby Care、签名、outbox 或护理写入；
- 没有保存或在状态文档中记录家庭音频、家庭转写、session ID 或私有路径。

`transport=auto` 未改变；`cs2+udp` 只是本轮实际协商结果，不是硬编码要求。

## 2. 固定聚合基线与尾部状态

验收前固定计数：

| 项目 | 基线 |
|---|---:|
| processed_count | 3 |
| listen_only_feeding_exact | 1 |
| listen_only_feeding_corrected | 0 |
| listen_only_diaper_exact | 0 |
| listen_only_burping_exact | 0 |
| listen_only_medication_candidate | 0 |
| listen_only_action_rejected | 1 |
| ignored_followups / ignored_far / ignored_near_start | 1 / 0 / 1 |
| output_failures | 2 |

尾部固定计数：

| 项目 | 尾部 | 本轮增量 |
|---|---:|---:|
| processed_count | 20 | 17 |
| listen_only_feeding_exact | 9 | 8 |
| listen_only_feeding_corrected | 0 | 0 |
| listen_only_diaper_exact | 2 | 2 |
| listen_only_burping_exact | 1 | 1 |
| listen_only_medication_candidate | 0 | 0 |
| listen_only_action_rejected | 3 | 2 |
| ignored_followups / ignored_far / ignored_near_start | 3 / 2 / 1 | 2 / 2 / 0 |
| output_failures | 2 | 0 |

## 3. 动作结果

### Feeding

- 经批准的正例尝试 11 次，8 次得到一次本地 i9 固定确认，3 次没有确认；
- 其中一个单句组合首次漏识别后，独立重测成功；
- 两阶段 wake/follow-up 路径有一次完整成功；
- 20 个负例覆盖无 wake、否定、停止、取消、疑问、相邻语义、普通陈述和跨动作，
  20/20 保持静默；
- 所有动作计数在负例矩阵中保持不变，观察到的 false accept 为 0。

结论：安全性边界通过，实机召回为 8/11，未达到完整接受条件。

### 换尿布

- 两个单句组合正例均未进入最终处理：0/2；
- 两个两阶段 exact 正例均得到一次本地 i9 固定确认：2/2；
- 相关无 wake、疑问、事后陈述和跨动作负例 4/4 静默；
- `listen_only_diaper_exact` 增量为 2，其他动作计数未串类。

结论：闭集动作分类有效，但单句组合入口召回不可靠，不接受为稳定实机能力。

### 拍嗝

- 两个单句组合正例均未进入最终处理：0/2；
- 两阶段 start 正例 1/1 成功；
- 两阶段 complete 正例 0/2，两次均在已成功 wake 后安全落入 `far` 拒绝；
- 相关无 wake、疑问、事后陈述和跨动作负例 4/4 静默；
- `listen_only_burping_exact` 增量为 1，没有串到 Feeding 或尿布。

结论：start 分类实机可达，complete 召回失败；整体不接受。

## 4. 根因边界与被推翻的假设

固定证据支持以下边界：

- 失败时 Voice 仍为 healthy，source 仍 PASS，`output_failures` 没有增加，因此不是本轮
  CoreAudio 输出故障、Xiaomi source 离线或 Camera Reply settlement；
- 多个失败样本增加了 utterance/VAD 活动但没有动作/响应增量，说明音频到达 VAD，失败
  位于后续 ASR、精确 wake 或单句组合解析入口；
- 拍嗝 complete 的两次失败均在成功 wake 后增加 `ignored_far` 和
  `listen_only_action_rejected`，把该子问题进一步定位到 follow-up ASR 与闭集文本距离边界；
- 两阶段尿布 2/2 和拍嗝 start 1/1 证明内部动作注册表不是全面不可达；
- 零 false accept 不等于召回通过，不能用安全拒绝掩盖实机漏识别。

本轮没有保存失败转写，因此不能诚实断言具体错字、漏字、分词或声学内容。下一修复必须
先用 synthetic/public regression 或另行批准的私有诊断取得证据，不能直接增加通用模糊
匹配、扩大 edit distance 或根据家庭听感猜测映射。

## 5. 模型与实现决策

- 保留当前 pinned Paraformer 和已通过软件门的 closed classifier；本轮没有安装、升级或
  替换模型；
- 保留 Feeding 仅有的 source-controlled 受限纠错，但本轮 corrected 增量为 0；
- 不把 household miss 直接加入纠错表；
- 不回滚安全边界，因为 20/20 主负例及动作相关负例均无 false accept；
- 不宣称 Tasks 1-7 的 generated/software PASS 等价于 Task 8 实机 PASS。

软件 benchmark 的 87 ms / 196 ms p50/p95 仍只属于 generated gate。本轮普通 memory-only
状态不保存逐 utterance latency，`last_latency_ms=none`，因此实机 p50/p95 和独立 RSS 均为
`NOT_RUN`，不复用旧软件数字冒充实机性能。

## 6. Camera Reply、隐私与独立链路

- 所有可听回复均来自 i9；Camera Reply 始终 false，未执行摄像头扬声器播放；
- 成人未观察到摄像头转动；PTZ 未调用；
- 视频 source 尾部仍 PASS；Voice diagnostic inactive；
- 无 household raw audio、转写或护理事实持久化；
- Baby Care write/outbox/signing 均未构造、未调用；
- Camera Reply V3E 的 movement、truncation、duplicate、timeout、EOF 和 lifecycle 门没有由
  本轮 ASR 结果替代，且因低风险动作门不干净而不恢复。

## 7. 保留、回滚与下一步

本轮没有修改业务代码、模型、运行配置或 go2rtc，没有创建需要回滚的运行时资产。保留
现有安全实现；Camera Reply 保持 false；此前私有诊断 bundle 的保留/删除仍是独立授权。

下一项产品切片是一个受限的 Task 8 recall follow-up：先为“组合 wake+动作未进入处理”与
“拍嗝 complete 在 armed 后落入 far”建立 synthetic/public 可失败回归和固定聚合诊断，
再决定是否需要另行批准短时私有诊断。不得先放宽识别规则。药物、Baby Care 写入、
Camera Reply V3E 和 full-care identity 继续保持独立。

## 8. Git 与发布状态

验收开始时本地分支 HEAD 为 `bb4f737`，相对远端 ahead 13，tracked worktree clean。
本 resolution 只记录 Task 8 聚合证据；push、PR、merge、stable/main 修改和 release 均未授权。

## 9. 组合 wake/action 软件 follow-up

后续 synthetic 重现确认，四个尿布/拍嗝单句组合的确定性失败位于 wake 边界，而不是动作
分类器：四个已批准 Gate B 命令缺少 punctuation-free allowlist 入口。最小修复只增加这四个
精确前缀；否定、疑问、多动作和未知后缀仍 fail closed。TDD 证据为 RED 8 failed / 4 passed，
修复后新门 12/12、affected Voice 161/161、完整 Voice 605/605 PASS。

同时重新运行 current Paraformer generated benchmark：低风险 18/18、负例 48/48、false
accept 0，故没有证据支持此时替换模型或为拍嗝 complete 猜测纠错。该软件 follow-up 尚未
部署时不能改变原 Task 8 recall FAIL 结论；下一节记录随后完成的受监督实机复验。

## 10. Installed combined-command revalidation

Installed candidate `44bd855` 通过 Voice-only restart 部署，没有重启 go2rtc、Dashboard 或
其他 worker。Voice 从零计数开始，四个组合命令依次产生 diaper exact +2、burping exact
+2，processed +4；reject、far 和 output failure 均无增量。成人确认四句均听到一次 i9
固定回复，摄像头无转动、无重复回复。尾部 Voice healthy，Xiaomi source PASS，配置仍为
`transport=auto`，实际协商为 `cs2+udp`。

因此组合单句入口从 recall FAIL 转为 4/4 supervised PASS。两阶段 `小小` 后再说拍嗝完成
的历史 `far` 路径没有在本轮重测，继续作为独立 recall follow-up；medication、Camera
Reply 与 Baby Care 写入状态不变。

## 11. Two-stage burping-complete diagnosis

使用已批准的本机私有诊断边界完成一次有效两阶段复现：exact wake 后 follow-up 固定为
`listen_only_followup_far`。诊断随后停止，Voice恢复memory-only且保持healthy，source
PASS。家庭音频、转写、私有字符内容、session ID和路径均未进入本报告、普通日志或Git。

current Paraformer 的generated孤立动作仍为3/3，不能把家庭结果转写为source-controlled
mapping。现有Whisper base/small运行包可导入，但两个immutable model artifact均校验失败，
因此没有绕过加载或切换生产模型。当前可用路径为已通过4/4的组合单句；两阶段改善需另立
ContextualParaformer、transducer hotword或有许可KWS的模型迁移设计与回滚门。

本轮新增两个retained私有session，分别为12和2个完整pair；diagnostic现为inactive。这些
内容不是训练数据，保持ignored/private，未经单独删除授权不得清理。
