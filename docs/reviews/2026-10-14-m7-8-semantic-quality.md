# M7.8 高频护理语义质量专项

## 范围

本轮冻结现有 C 模式为默认路径，仅增加 opt-in 的 `semantic_focus` prompt
variant；未修改 M6、Gateway、SSH、Guardian 或 Camera Reply。评测只使用合成文本，
不保存家庭语音、转写或护理数据。

## 基线与模型

- CI `38488256913`：`d0f8fc7`，success。
- Qwen2.5-Coder 7B：`qwen2.5-coder:7b-instruct`，Q4_K_M，digest
  `dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364`。
- Qwen3 4B：`qwen3:4b-instruct`，Q4_K_M，digest
  `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`。

## 开发集对照（56 条）

| 方案 | 意图 | 明确奶量 | 工具合法 | P50/P95(ms) |
|---|---:|---:|---:|---:|
| Qwen2.5 + C/optimized | 35/56 | 17/20 | 41/56 | 1136/1618 |
| Qwen3 + C/optimized | 27/56 | 10/20 | 42/56 | 1106/1303 |
| Qwen2.5 + semantic_focus | 41/56 | 16/20 | 16/56 | 710/1562 |
| Qwen3 + semantic_focus | 45/56 | 20/20 | 47/56 | 903/1135 |

`semantic_focus` 只增加明确的 intent/action 路由和安全澄清规则，保留完整
Schema、Tool Registry 和确认门禁。Qwen3 结果优于旧 prompt，但仍低于发布目标，
且工具合法率与端到端安全闭环尚不足，因此不替换默认 C。

## 固定与独立回归

- 固定 168 条：Qwen3 + `semantic_focus` 意图 144/168，明确奶量 60/60，
  工具合法 140/168，P50/P95 1273/1645ms；1 次 schema failure。
- 历史 24 条：意图 17/24，明确奶量 5/7，工具合法 19/24，P50/P95 1200/1514ms。
- 新独立合成 12 条（仅本次命令内生成，原文未持久化）：意图 9/12，
  明确奶量 3/4，工具合法 10/12；P50/P95 1267/1753ms，最大 5411ms。

失败仍集中在语义/工具路由及确认边界，不能据此宣称发布级准确率。未确认写入、
错误奶量写入和重复权威事件在现有合成 Gateway 测试中仍为 0；本轮未连接生产库。

## 软件门禁

- M7 定向：41 passed。
- 全 Python：2599 passed，1 skipped（既有 public visual corpus incomplete）。
- 编译（内存 compile，无 pyc 写入）、`git diff --check`：通过。

结论：`SOFTWARE_RELEASE_CANDIDATE=false`，Camera Reply=false，硬件验收仍挂起。
