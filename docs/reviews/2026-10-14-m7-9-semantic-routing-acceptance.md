# M7.9 语义泛化、工具路由与确认安全验收

## 冻结参数

- HEAD：`e4c6a324365672175c0edbe8b7994bdd119e852e`
- CI：`38492116973`，success
- 模型：`qwen3:4b-instruct`，Q4_K_M，digest `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`
- Prompt：opt-in `semantic_focus`；现有 full LanguageCandidate Schema
- 推理：temperature 0、非流式、`think=false`、`keep_alive=5m`、12 秒超时
- 默认生产路径：Qwen2.5-Coder + C，未改变

## 168 条固定集路由分层

28 个工具不合法/不符合预期案例中，27 个在 Tool Registry 校验阶段拒绝，1 个在
模型 Schema 输出阶段失败；full C 路径无中间适配器，没有证据表明是适配器丢字段。

| 阶段 | 数量 |
|---|---:|
| 正确完成 | 103 |
| Tool Registry 拒绝 | 27 |
| 模型意图错误 | 4 |
| 正确拒绝 | 33 |
| Schema 输出失败 | 1 |

ASR 扰动含 15 次工具拒绝，fault/确认类含 9 次工具拒绝和 1 次意图错；混合喂养含
2 次意图错和 1 次工具拒绝。查询、负面和歧义样本均未生成写入工具；确认/取消类有
4 次意图不匹配，但未进入持久化执行。

## 新独立 200 条合成集

样本按 start、母乳、配方奶、混合、纠错、结束、确认、取消、查询、歧义十个分层生成；
每条含自身期望奶量，原文未写入仓库或日志。

- 意图：152/200（76%）
- 明确奶量：65/80（81.25%）
- 工具合法：154/200（77%）
- 95% Wilson 区间：意图 69.63%–81.39%，明确奶量 71.34%–88.29%，工具合法 70.69%–82.29%
- 正确拒绝：8；Schema failure：2；工具/参数拒绝：44；意图错误：22；奶量错误：12
- P50/P95/max：1038/1601/1715ms
- 未连接生产数据库；未发现负面/歧义自动写入

先前一次 200 条试跑因生成器错误复用了 expected amount，已废弃，不计入结果。

## 结论

独立集远低于 95% 意图和 99% 明确奶量目标，不能进入软件发布候选。保持 C 默认、
`SOFTWARE_RELEASE_CANDIDATE=false`、Camera Reply=false；不新增 Minimal Schema、不修改
M6/Gateway、不启用家庭部署。
