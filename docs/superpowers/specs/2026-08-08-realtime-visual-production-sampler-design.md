# R3/R3.5 实时视觉生产采样器设计

**日期：** 2026-08-08

**状态：** 已实现；已定位 launchd 调度瓶颈，待 i9 应用修复并复验

**阶段：** R3/R3.5 i9 实机性能门

**上位规格：** `2026-08-07-realtime-visual-production-metrics-design.md`

## 1. 目标与范围

新增一个仓库自带、只读且脱敏的生产采样器，默认连续运行 600 秒、每 10 秒读取一次
`runtime/status/realtime-visual.json`。采样器只消费现有严格聚合契约，不读取画面、
候选类型、检测结果、床区、日志或网络配置，也不暂停或重启视觉 worker。

采样结果用于判定 R3/R3.5 的 5/3/1 FPS 生产性能门。它不修改 worker、模型、自动
降载阈值、候选规则、风险状态机或通知路径，也不能替代后续家庭场景准确率验收。

## 2. 接口与数据流

新增 `tools/realtime_visual_performance.py`，复用
`services.vision.realtime_status.read_realtime_visual_status` 的 schema、陈旧和有限数值
校验。新增 `make alpha-visual-performance`，使用仓库虚拟环境执行默认 10 分钟采样。

每次有效采样只保留以下内存字段：

- `realtime_fps`；
- `processing_p50_ms`；
- `processing_p95_ms`；
- `processing_max_ms`；
- `realtime_model_state`。

`written_at_unix` 只参与现有陈旧校验，不输出。运行结束后只输出固定键值报告：有效
样本数、5/3/1 FPS 计数、采样窗口 P50 的 nearest-rank 中位值、观察到的最差滚动
P95、全窗口最大处理时间、模型状态和最终 `performance=PASS|FAIL`。报告不包含绝对
路径、时间戳、异常文本、画面或家庭场景数据。

## 3. 判定规则

采样器 fail closed，规则按以下顺序判定：

1. 任一读取发生 unavailable、stale、invalid 或其他异常，立即输出稳定失败原因并
   非零退出；不得打印底层异常。
2. 任一有效快照的模型状态为 `degraded`，最终失败。
3. 任一快照进入 1 FPS，最终失败。
4. 5 FPS 通过要求全部有效样本均为 5 FPS，且所有快照中最差的滚动 P95 不超过
   `180ms`。
5. 3 FPS 通过允许记录 5→3 自动降档，但要求最后连续 60 秒的样本均为 3 FPS，
   所有 3 FPS 快照中最差的滚动 P95 不超过 `300ms`，且全程没有 1 FPS。
6. 不满足上述任一通过路径时，以稳定原因失败。不得通过平均值、删除慢样本或修改
   既有门限使结果通过。

采样窗口 P50 定义为各快照 `processing_p50_ms` 的 nearest-rank 中位值；报告 P95
定义为所有有效快照 `processing_p95_ms` 的最大值；报告 max 定义为所有快照
`processing_max_ms` 的最大值。这样报告明确是对滚动聚合快照的保守汇总，不伪装成
无法从现有状态文件重建的逐帧 10 分钟分位数。

## 4. 参数与运行约束

生产命令固定使用 600 秒与 10 秒间隔。Python CLI 可以注入持续时间、采样间隔、
睡眠和读取函数，供自动化测试在不等待 10 分钟、不接触 runtime 的情况下验证；
Make 入口不暴露缩短生产门的快捷参数。

采样过程不创建文件或数据库记录。用户需要保留证据时，只复制最终固定报告；报告
本身仍不得进入包含家庭身份或本地网络信息的内容。

## 5. 错误处理与退出码

- 通过：退出 `0`，最后一行输出 `performance=PASS mode=5fps` 或
  `performance=PASS mode=3fps`。
- 性能或稳定性不通过：退出非零，最后一行输出
  `performance=FAIL reason=<stable_code>`。
- 允许的稳定原因包括 `metrics_unavailable`、`metrics_stale`、`metrics_invalid`、
  `metrics_read_failed`、`model_degraded`、`one_fps_observed`、
  `five_fps_budget_exceeded`、`three_fps_unstable` 和
  `three_fps_budget_exceeded`。

中断采样时不吞掉终端中断，不生成部分 PASS，也不改变视觉服务状态。

## 6. TDD 与验收

自动化测试先失败，再以最小实现通过，至少证明：

1. 全 5 FPS 且最差 P95≤180 ms 时通过；任一最差 P95 超限时失败；
2. 5→3 且最后连续 60 秒稳定、3 FPS 最差 P95≤300 ms 时通过；
3. 3 FPS 尾窗不足、出现 1 FPS 或模型 degraded 时失败；
4. unavailable、stale、invalid 和意外读取失败只输出稳定脱敏原因；
5. FPS 分布、P50 中位值、最差滚动 P95 和最大值计算正确；
6. CLI 不输出状态路径、异常文本或未列入白名单的字段；
7. Makefile 提供固定的 `alpha-visual-performance` 生产入口。

focused 门禁包括采样器单元测试、部署命令测试、Python 编译、`make -n`、
`git diff --check` 和敏感信息扫描。首次真实 10 分钟运行只在 i9 上执行；本地自动化
通过仍不能宣称实机性能门或家庭场景门通过。

## 7. i9 生产失败、根因对照与调度修复

2026-08-09，i9 的完整 600 秒生产采样得到 60 个有效样本，全部处于 1 FPS；窗口
P50 为 `398.432ms`，最差滚动 P95 和最大值均为 `488.741ms`，模型状态始终为
`available`，最终以 `one_fps_observed` 失败。隔离分阶段诊断的 analyzer 总耗时
P95 为 `88.657ms`，整机同时保有大量空闲 CPU 且没有 swap，因此没有通过放宽门限、
屏蔽模型或降低分析质量处理该失败。

保留同一代码、配置、模型、连续真实帧和指标口径，仅把 worker 从已注册的
`ProcessType=Background` launchd job 改为当前终端前台运行。该对照达到 5 FPS，
且 P95 不超过 `180ms`；当时恢复正式 `Background` job 后又降至 1 FPS、P50 约
400ms。这份证据说明 launchd 调度与退化高度相关，并排除了 analyzer 持续慢、
模型不可用和连续帧缺失作为当次唯一解释，但尚不能证明 `Background` 是单独且
确定性的根因。

随后 i9 在仍安装 `ProcessType=Background` 的条件下重启同一 worker，并短时达到
5 FPS、P95 `153.117ms`；保持同一 PID `92126` 运行后，控制器目标档位降至
3 FPS，窗口 P95 达 `256.935ms`、最大值达 `325.313ms`。这里
`realtime_fps=3` 是负载控制器选择的目标档位，不是摄像头输入吞吐；超过
`180ms` 的长尾会触发降档并清零连续 60 秒的升档恢复计时。因此当前准确结论是：
Background 调度仍是候选因素，但重启热态、系统调度、取帧/循环计时之外的长尾也
必须通过同机实验继续区分。

正式修复把且只把 `com.babymonitor.visual` 的 `ProcessType` 改为 `Interactive`。
`make alpha-visual-launchd-update` 在替换前渲染并校验 plist，要求旧 job 已注册，
保留 `com.babymonitor.visual.plist.r3-background.bak` 且不覆盖既有备份。首次 i9
执行暴露出 `bootout` 返回后 launchd 仍处于 `inactive → removing` 的状态转换
竞态：候选立即 bootstrap 失败，文件回滚成功，但旧 job 的立即 bootstrap 也失败，
最终报告 `rollback_failed` 并离线；稍后手工 bootstrap 成功。

修复后的单 job 更新按
`bootout → 有界等待未注册 → 原子替换 → 有界 bootstrap → kickstart → print`
执行。等待和注册均以一秒间隔、最多 30 次观察为界；候选失败后的回滚复用相同状态
原语。固定输出不包含路径、launchd 原始错误、运行配置或家庭数据，并区分
`stop_timeout`、`activation_bootstrap_timeout`、
`activation_kickstart_failed`、`activation_verify_failed` 以及对应 rollback
阶段。gauge、environment watchdog、Ollama tunnel、Dashboard、分析器、负载
控制器和性能门限均不变。

软件回归和模拟 launchd 故障只能证明更新/回滚契约，不能证明 i9 已安装配置。
i9 应用修复后先确认 plist 确为 `Interactive` 且 visual job 已注册，再以同一 PID
连续观察 3 分钟，确认 5 FPS 且 P95≤`180ms`；服务恢复和短窗指标稳定后，才重新
运行完整 10 分钟 `make alpha-visual-performance` 关闭本性能门。若 Interactive
仍出现相同 5→3 FPS 退化，则否定“ProcessType 足以修复”的假设，转查取帧等待、
循环节拍和主机调度的同步证据。
