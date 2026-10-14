# M7.14 跨仓库契约与真实确认语义

日期：2026-10-14
基线：baby-monitor-local `4727e67d4ad78a97c1ad1f27101e41e3b73a1387`；baby-care
`cb9a86f3e4c83b637e331b30e0bbf8bdde938891`。

## 跨仓库契约

使用准确 baby-care Git checkout（保留 `.git`）、Node 24、pnpm 10.17.1，运行
`test/voice-care-consumer-contract.test.ts`：**1 file / 4 passed**。

此前失败的原因不是契约内容，而是执行器问题：归档目录没有 `.git`，随后
`node:24-bookworm-slim` 又缺少 `git`（`spawnSync git ENOENT`）。在临时容器内
安装测试所需 git 后，byte-identical artifact、source identity、symlink 和
untracked-artifact 四个场景全部通过。容器和临时 checkout 已清理，未改变源仓库。

## 真实 Ollama 确认语义探针

使用现有 `OllamaLanguageClient`、原有完整 Schema、相同安全边界，仅对合成短句
记录结构化字段（不保存原始模型文本）：

| 模型 | 8 条探针结果 |
|---|---|
| Qwen2.5-Coder + C | 4 条正常返回、3 条超时/不可用；“确认保存”被判为 `feeding_end` 但工具为 `confirm_feeding`；“取消刚才那条”意图被判为 `care_confirm` 但工具为 `cancel_feeding`；纠错确认同时产生纠错和确认候选 |
| Qwen3 + semantic_focus | 7 条正常返回、1 条不可用；“好了，结束吧”被判为取消但工具为结束；“对，确认”和无草稿确认只给确认意图、无工具；未保存和取消短句能进入取消意图 |

这些是模型候选层问题，不代表业务写入成功。确定性 Tool Registry/M6 状态机仍
拒绝无效工具组合、无草稿确认和过期确认；不自动确认、不生成权威摘要/签名/版本。
默认 C 模式未切换，也未引入新 Schema 或状态机。

## 门禁状态

- Node24/PG16 M7 相关集成：23/23（M7.13 新鲜隔离证据）。
- 跨仓库 consumer-contract：4/4（本轮）。
- M7/M6 确认链回归：63 passed（M7.13 新鲜证据）。
- CI `38540817143`：success。
- 真实模型完整任务：Qwen2.5 C 3/12、Qwen3 focus 6/12，权威保存均为 0。
- `SOFTWARE_RELEASE_CANDIDATE=false`，Camera Reply=false。

模型语义目标仍未达到发布门槛；不部署家庭环境。
