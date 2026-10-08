# Dashboard 最近宝宝观察状态最小只读投影

## 目标

在正常 VisualReview 完成链路上提供一个默认更新、鉴权、只读的“最近一次观察”状态。
它只表达最近一次语义观察的可见性和新鲜度，不替代 Guardian 风险判定，不接入
SemanticObservationSession 诊断统计，也不代表宝宝安全或持续实时跟踪。

## 合法状态合同

状态文件为 `runtime/status/visual-observation.json`，0600、原子写入、无媒体/模型原文。

| state | baby_visibility | freshness | reason_code | 时间字段 |
|---|---|---|---|---|
| `available` | visible/partial/not_visible/uncertain | fresh | none | capture + completion 必须存在 |
| `stale` | 上一次成功枚举值 | stale | review_expired | capture + completion 必须存在 |
| `no_result` | null | unknown | no_review_yet | 两个时间均为 null |
| `failed` | null | unknown | review_failed/review_timeout | 两个时间均为 null |
| `worker_restarted` | null | unknown | worker_restarted | 两个时间均为 null |

输入帧时间取四帧中最新一帧的 `captured_at`；完成时间取 scheduler observer 收到结果的
时间。过期阈值为常规 10 秒间隔加 20 秒复核超时，即 30 秒。失败、超时和重启不会沿用
旧结果作为当前有效结果；迟到结果不能覆盖新 worker generation。

## 接线与边界

共享 producer → frame policy/ring → scheduler → reviewer → completion observer → 原子状态文件。
状态 observer 与诊断 observer 通过非阻塞 fan-out 分离；状态写入失败不得阻断 Guardian。
Dashboard 新增 `/api/dashboard/visual-observation`，继续使用 Basic Auth、`no-store` 和
闭合字段。页面复用现有 15 秒 Dashboard 刷新调度器，不增加独立定时器；该卡片请求失败
只局部显示不可用或过期。

UI 文案统一使用“最近一次观察”，不使用“持续跟踪”“宝宝安全”。`not_visible` 只在新鲜、
成功的 VisualReview 结果中显示，不能由警报数量、pose_count 或诊断报告推导。

## 非目标

- 不展示 SemanticObservationSession 的请求/延迟/bridge 统计；
- 不改变 Guardian 风险、恢复、通知或事件存储；
- 不访问摄像头、麦克风、扬声器、PTZ 或 WS2021；
- 不进行真实家庭观察或准确率验收。
