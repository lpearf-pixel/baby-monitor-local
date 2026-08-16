# Baby Monitor Local 环境监测设计规格

**日期：** 2026-08-05

**状态：** 已由用户于 2026-08-05 书面批准

**范围：** WS2021 光学读表、环境读数契约、SQLite 历史、确定性告警、
Dashboard 与 ntfy；不包含任何设备控制

## 1. 目标

在现有小米 MJSXJ17CM 高清取流和鉴权 Dashboard 基础上，增加一条独立、
可替换、可降级的环境监测链路：

```text
WS2021 指针式温湿度计
  → 小米摄像头固定高分辨率表盘 ROI
  → i9 gauge worker 每 60 秒读取一次
  → EnvironmentReading 严格契约
  → SQLite 历史与确定性状态机
  → Dashboard 当前值、24 小时/7 天趋势和环境事件
  → ntfy 文字异常、不可读与恢复提醒
```

第一版的工程验收目标是：所有被系统发布为 `available` 的读数，温度误差不
超过 ±1℃，湿度误差不超过 ±5%RH。不能满足质量门时必须发布
`unavailable`，不得用上一次有效值、插值或单表盘结果冒充当前读数。

本系统只做家庭环境的辅助监测，不构成医疗建议或生命安全监护。

## 2. 与现有规格的关系和裁决

本规格细化并约束以下三份既有规格：

- `2026-08-04-baby-monitor-local-design.md` 保留总体硬件、阈值、microSD 和
  本地优先架构；其“通知包含缩略图”不适用于第三方 ntfy 环境通知，本规格的
  纯文字规则优先。
- `2026-08-04-ws2021-manual-calibration-design.md` 保留 Dashboard 一次性人工
  标定流程；矩形 ROI 升级为四角仪表面，同时保留外接矩形，才能进行真实透视
  校正。标定仍不负责自动读数、数据库或告警。
- `2026-08-04-qwen3-vl-local-review-design.md` 明确排除温湿度读数，本规格不向
  Qwen3-VL 发送表盘 ROI，也不依赖 M2、SSH 隧道或 Ollama。

现有 V1 实施计划中的 Task 8 仍写“交互式 CLI”，已被专项标定规格中的鉴权
Dashboard 向导取代。规格批准后生成的新实施计划必须修正该项，不实现第二套
CLI 标定流程。

规范命名如下：

- `visual-review worker`：只处理床区视觉复核；
- `gauge worker`：只处理环境采样、读针和读数发布；
- `gauge_roi`：只描述仪表区域；
- `bed_zone`、`privacy_masks`：只描述床区视觉链路。

这些配置不得复用同一个字段，也不得由一个 worker 的故障改变另一个 worker
的运行状态。

## 3. 方案选择

采用“独立环境源契约 + 独立 gauge worker + 共享受控视频源”的方案。

备选方案及不采用原因：

1. 把读表塞入 `visual-review worker`：代码较少，但会让 Qwen/M2 故障影响环境
   读取，也会混淆床区隐私遮罩和表盘 ROI，拒绝采用。
2. 第一版直接购买并以蓝牙/MQTT 数字传感器为主源：长期更适合自动控制，但
   当前没有确定硬件和协议，会延迟现有 WS2021 的可用闭环，暂不采用。
3. 选定方案：先定义稳定的 `EnvironmentReadingSource`，以
   `Ws2021GaugeSource` 实现；以后增加蓝牙、MQTT 或局域网数字传感器时替换
   输入适配器，不改历史、状态机、Dashboard 和通知。

## 4. 总体架构与隔离

```text
MJSXJ17CM source 2560×1440
  └─ go2rtc（i9 loopback，固定 `gauge` MJPEG 派生流）
       ├─ visual-review worker → 床区裁剪/隐私遮罩 → M2 Qwen3-VL
       └─ gauge worker → 固定 gauge_roi → 本地 OpenCV 读针
                              ↓
                    SQLite / event service
                              ↓
                    Dashboard / ntfy 文字通知
```

两个 worker 使用同一个受控 go2rtc 上游，但各自拥有独立进程、launchd 单元、
调度、健康状态和失败计数。受控帧源只允许代码内固定 profile，HTTP 客户端不能
提交流名、URL、设备编号或 FFmpeg 参数。所有访问 loopback 视频源的客户端均
显式禁用环境代理，防止本地帧因代理配置错误离开 i9。

资源守卫按以下优先级降级：

1. 延长或跳过视觉模型复核；
2. 降低视觉分析帧率；
3. 暂停非必要视觉证据导出；
4. 始终保留每分钟环境采样、摄像头断流检测、Dashboard 和通知。

Qwen 离线时环境读取继续；表盘不可读时视觉复核继续。任一 worker 崩溃都不得
重启 go2rtc、Dashboard 或另一个 worker。

## 5. 输入源抽象

环境业务层只依赖以下逻辑接口：

```python
class EnvironmentReadingSource(Protocol):
    @property
    def source_kind(self) -> EnvironmentSourceKind: ...

    def read(self, requested_at: datetime) -> EnvironmentReading: ...
```

第一版 `Ws2021GaugeSource` 依赖：

- `ControlledFrameSource`：从固定 `gauge` profile 获取受限高分辨率帧；
- `GaugeCalibrationStore`：只读取当前已验证标定；
- `Ws2021Reader`：执行质量检查、透视校正、读针和多帧聚合。

未来适配器可以是 `BluetoothEnvironmentSource`、`MqttEnvironmentSource` 或
`LanSensorEnvironmentSource`。它们必须输出相同严格契约，不得把协议字段泄漏
给状态机或 Dashboard。第一版只允许一个活动主源，不实现多源融合或自动切换。

视频帧源与环境读数源是两层接口：未来 UVC 摄像头只替换
`ControlledFrameSource`；未来数字温湿度传感器则直接替换
`EnvironmentReadingSource`。

## 6. 人工标定

标定继续复用现有 Dashboard 的 `2×/3×` 高清当前视野：

1. 用户把 WS2021 拖到清晰位置并冻结当前高清截图；
2. 按顺序标记仪表面四角，形成 `gauge_quadrilateral`；
3. 分别标记湿度和温度表盘的圆心、当前针尖及至少三个已知刻度；
4. 服务端把 CSS/视口坐标反算为原始 `source` 帧归一化坐标；
5. 显示透视校正后的叠加预览，用户确认后原子保存。

标定模型使用 `schema_version: 2`，并包含：

- 不可预测的 `calibration_id`；
- 创建时间、原始源宽高和方向；
- 标定时的 `zoom`、`center_x`、`center_y`；
- 原始源坐标中的四角仪表面和外接矩形；
- 两个表盘的圆心、针尖、半径和刻度点；
- 每个刻度的角度和值，以及展开后的有效角度区间；
- 只用于本地几何复核的参考图版本。

刻度映射使用按圆周展开后的分段线性插值，明确支持跨越 `0°/360°`；角度落在
已标定有效区间之外时返回不可用，不外推数值。

固定本地位置仍为：

```text
runtime/calibration/ws2021-v1.json
runtime/calibration/ws2021-reference.jpg
runtime/calibration/backups/
```

文件名保持兼容，JSON 内的 `schema_version` 和 `calibration_id` 承担版本语义。
保存使用同目录临时文件、`fsync` 和原子替换，最多保留三个旧版本。真实参考图
和标定 JSON 均已被 Git 忽略，不得进入提交、日志或通知。

下列情况使标定失效：

- 原始帧宽高或方向变化；
- 标定文件缺失、损坏或版本不支持；
- 当前表盘圆心相对标定位置偏移超过表盘直径的 5%；
- 当前表盘半径相对标定值偏差超过 8%；
- 四角透视变换退化、越界或无法稳定拟合。

失效时输出 `calibration_invalid`，要求重新标定，不能自动修改旧标定。

## 7. 采样调度与帧质量

`gauge worker` 使用单调时钟每 60 秒启动一次采样，不追赶因休眠或过载错过的
周期，不建立积压队列。每次采样：

- 从固定 `gauge` 高分辨率 MJPEG 流连续取得 5 帧；该按需派生流固定为
  2560×1440、2 FPS，不允许客户端选择流名或 FFmpeg 参数；
- 帧间隔目标为 500 毫秒，整个 burst 最长 8 秒；
- 一个 burst 复用同一个连续 producer/解码会话，不连续发起五个一次性 JPEG
  请求，避免再次触发已修复的 go2rtc producer 停止/重启竞态；
- 每帧字节、像素尺寸和解码上限沿用受控高清截图边界；
- 任一帧在进入算法时已超过 5 秒，标记为 `frame_stale`；
- 原始整帧和普通 ROI 只存在内存，不写盘。

每帧先执行统一质量门：JPEG 可解码、ROI 在界内、清晰度、亮度、过曝比例、
反光面积、遮挡比例、圆心和表盘半径匹配。质量门失败的帧不参与中位数，但保留
稳定错误码。

温度和湿度必须分别至少有 3 帧有效，且必须来自同一次 5 帧 burst。任何一只
表盘不满足条件时，整条 `EnvironmentReading` 为 `unavailable`。

## 8. 白天与夜间读针

### 8.1 通用步骤

1. 按四角仪表面进行透视校正，生成固定尺寸的规范化表盘图；
2. 用标定圆心和半径限制搜索范围；
3. 排除中心帽、数字文字和外圈刻度带；
4. 为两只表盘独立生成候选针角度和值；
5. 聚合 5 帧结果并输出一个严格读数。

### 8.2 白天路径

- 在 HSV/Lab 色彩空间做红针分割；
- 只接受起点接近圆心、长度位于标定半径合理区间的连通线段；
- 以圆心距离、径向一致性、红色纯度、长度和轮廓稳定性评分；
- 反光导致大面积高亮、红色污染或多根近似候选时拒绝猜测。

### 8.3 夜间路径

- 使用灰度归一化和局部对比度增强，不依赖红色；
- 在已标定圆心附近做径向线段检测；
- 排除固定外圈刻度带和不穿过中心邻域的线段；
- 使用方向、长度、边缘对称性和跨帧一致性选择候选；
- 全黑、红外反光、蚊帐网格、严重噪声或多候选不可区分时输出不可用。

系统根据 ROI 亮度、色度和红针可分性选择白天或夜间路径；允许在质量门内尝试
另一路径一次，但不得混合两个低置信度结果拼成有效读数。

透视校正画布必须恢复已标定仪表平面的纵横比。仅使用投影后的四条边长度不足以
恢复斜视矩形，因此实现以两只圆形表盘的中心和三个圆周刻度点为约束，在有界候选
比例内选择使校正后各表盘圆周半径离散度最小的矩形比例；输出面积取四边形投影
面积并等比限制在原始帧尺寸内。归一化点先按原始 source 宽高换算，再进入透视
矩阵；表盘边界、搜索窗口和圆检测则使用校正后画布宽高。禁止把仪表四边形强制
拉伸到摄像头 16:9 全帧尺寸，因为这会把圆形表盘变形并错误触发
`roi_out_of_bounds`。约束不足、最优解不唯一、退化边长或越界输出继续返回
`calibration_invalid`，不得放宽 ROI、置信度或圆匹配门限。
校正画布应按两只表盘的 1.3 倍半径搜索窗口增加恰好足够的有界 padding，再统一
等比缩放到原始帧尺寸上限；padding 只扩大可搜索画布，不改变 5% 圆心偏移、8%
半径误差或其他质量阈值。

### 8.4 多帧聚合与置信度

每只表盘对有效帧的数值取稳健中位数，并要求：

- 温度值的中位绝对偏差不超过 0.5℃；
- 湿度值的中位绝对偏差不超过 2.5%RH；
- 最终综合置信度不低于默认 0.75；
- 两只表盘都通过物理范围和标定角度范围检查。

最终综合置信度取两只表盘置信度的较低值。任何门限失败均不输出部分数值。
这些是项目默认值，可在严格配置中调整，但不得由 Dashboard 请求临时覆盖。

## 9. EnvironmentReading 严格契约

现有 `packages/contracts/events.py` 中的 `EnvironmentReading` 必须增强为：

```text
schema_version
reading_id
source_kind
captured_at
fresh_until
state: available | unavailable
temperature_c
humidity_rh
confidence
confidence_state: high | acceptable | low | unavailable
failure_reason
calibration_version
sample_count
valid_temperature_samples
valid_humidity_samples
```

对 `available`，`captured_at` 取本次 burst 中最后一张参与聚合的有效帧时间；
对有帧但不可读的结果，取最后一张成功解码帧的时间；完全未取得帧时取本次
调度的 `requested_at`，并固定使用 `frame_source_unavailable`。默认
`fresh_until = captured_at + 90 秒`。WS2021 记录中的 `calibration_version`
就是当前标定文件内的 `calibration_id`，Dashboard 也显示这个值。

验证规则：

- 所有时间必须带时区，`fresh_until` 必须晚于 `captured_at`；
- 默认新鲜期为 90 秒；
- `available` 必须同时包含温度和湿度，不允许只含一个值；
- `available` 不得含失败原因，且置信度必须达到配置门限；
- `unavailable` 不得含温度或湿度，必须包含枚举失败原因；
- WS2021 的所有记录必须包含 `calibration_version`；数字源可为空；
- 湿度限定 `0–100%RH`，温度限定 WS2021 标定范围 `-50–60℃`；
- 禁止额外字段和自由文本错误详情。

第一版失败原因使用闭合集合：

```text
calibration_missing
calibration_invalid
frame_source_unavailable
frame_stale
roi_out_of_bounds
too_dark
glare
occluded
needle_not_found
insufficient_valid_frames
inconsistent_frames
low_confidence
internal_error
```

Dashboard 的“当前读数”始终取最后一次采样结果。若该结果不可用或已过期，
当前值显示为不可用；可以另行显示“最近一次有效读数及其时间”，但不得把它
显示成当前值或用于推进告警/恢复计时。

## 10. SQLite 历史与查询

每个计划采样周期都追加一条记录，包括 `unavailable`。数据库至少包含：

- `environment_readings`：完整严格读数和来源元数据；
- `environment_incidents`：打开、升级、恢复和通知状态；
- `environment_state_snapshot`：状态机重启恢复所需的最小确定性状态。

读数按 `reading_id` 唯一，按 `captured_at` 建索引；写入使用事务和 WAL。保留期
沿用现有默认 365 天。清理只删除超过保留期的历史，不删除当前打开事件所引用
的读数。

趋势 API 使用有界查询：

- 24 小时：5 分钟桶，返回温湿度的最小值、中位数、最大值和可用率；
- 7 天：1 小时桶，返回相同统计；
- 不可用区间显示为空档，不使用前值填充；
- API 不接受任意 SQL、路径或无限时间范围。

一年每分钟一条记录对 SQLite 足够小，第一版不增加时序数据库或后台聚合服务。

## 11. 确定性环境状态机

普通范围默认值：

- 温度 `18–26℃`；
- 湿度 `35–60%RH`。

严重门限默认值：

- 温度低于 `15℃` 或高于 `30℃`；
- 湿度低于 `25%RH` 或高于 `75%RH`。

所有门限是可配置的项目默认值，不表述为医疗建议。配置校验必须保证严重低值
低于普通低值、严重高值高于普通高值。

状态机规则：

1. 任一普通范围超限持续至少 5 分钟，打开一个环境异常事件并通知一次；
2. 多个温湿度原因合并进同一打开事件，以原因码列表展示，避免通知轰炸；
3. 严重门限需要两个连续有效读数、跨度至少 60 秒，升级为紧急环境提醒；
4. 已打开事件出现严重读数时仍须下一次有效读数确认，不允许单帧升级；
5. 所有环境值回到普通范围并连续保持 5 分钟后恢复，只通知一次；
6. 连续 10 分钟不可读，打开独立的“环境读数不可用”事件并通知一次；
7. 不可读事件需要两个连续有效读数恢复，只通知一次；
8. 不可用样本不等于正常或异常，会中断尚未满足的 5 分钟连续计时；
9. 若环境异常已打开后读数不可用，异常保持打开但标记数据不可用，不能据此
   恢复或重复升级；
10. 同一事件同一级别不重复通知，原因变化只写审计；严重度升级和最终恢复各
    通知一次。

状态机以持久化快照恢复打开事件。进程重启后保留已打开/已通知状态，但未完成
的普通或恢复连续计时重新开始，避免跨进程停机间隔误触发。

共享健康检查器还会把“连续 10 分钟没有产生任何新读数记录”视为不可读；因此
即使 gauge worker 反复崩溃，也不会因为没有 `unavailable` 行而静默。launchd
仍负责独立重启 worker，健康检查器不尝试自行执行进程控制。

## 12. Dashboard

鉴权 Dashboard 增加独立环境卡片：

- 当前温度、湿度或明确的“不可用”；
- 最近采集时间、距今时长和是否新鲜；
- 数值置信度状态与不可用失败原因；
- 当前 `calibration_version` 和重新标定入口；
- 最近一次有效读数及时间，视觉上与当前值分开；
- 24 小时和 7 天温湿度趋势、普通范围带和数据空档；
- 当前及历史环境异常、严重升级、不可读和恢复事件。

图表使用仓库内本地代码，不从第三方 CDN 加载脚本。API 和页面沿用现有鉴权、
`Cache-Control: no-store` 和 Tailscale 私网访问边界。

## 13. ntfy 通知

第一版环境通知只发送：

- 事件类型和严重度；
- 当前温度、湿度或“读数不可用”；
- 读数采集时间；
- 持续时间和稳定原因码；
- 一个不含凭据、仍需 Dashboard 鉴权的 HTTPS 链接。

链接基址只能来自受信配置，必须使用 HTTPS 主机名；拒绝数字 RFC1918 地址、
loopback、查询参数中的凭据和本地文件路径。推荐使用 Tailscale Serve 的固定
HTTPS 名称。

第三方 ntfy 不得接收宝宝画面、表盘截图、视频、私网数字地址、Xiaomi URI、
本地绝对路径、标定文件或自由文本异常堆栈。若以后启用其他第三方通知通道，
必须复用同一脱敏负载。通知失败使用有界退避并记录安全错误码，不阻塞采样、
入库和本地事件状态。

## 14. 配置

新增环境配置进入现有严格 Pydantic 模型和 JSON Schema，保持
`extra="forbid"`：

```text
environment.enabled = true
environment.source_kind = ws2021_gauge
environment.interval_seconds = 60
environment.freshness_seconds = 90
environment.burst_frames = 5
environment.burst_interval_ms = 500
environment.minimum_confidence = 0.75
environment.unreadable_seconds = 600
environment.normal_sustained_seconds = 300
environment.recovery_sustained_seconds = 300
environment.critical_confirmations = 2
environment.critical_min_span_seconds = 60
environment.calibration_path = runtime/calibration/ws2021-v1.json
environment.policy.mode = monitor_only
environment.policy.required_independent_sources_for_control = 2
```

现有 `ThresholdSettings` 增加四个严重门限并校验嵌套顺序。采样周期、burst 帧数
和恢复时间允许通过本地配置调整，但生产默认值与本规格一致；Dashboard 不能
动态更改。

## 15. 未来控制安全接口

第一版只暴露只读 `EnvironmentSnapshotProvider.current()`，返回当前严格读数、
新鲜度、打开事件、策略版本和控制资格。对 WS2021 单一光学源，控制资格固定为
`ineligible`，原因至少包含 `optical_source_only` 和 `actuator_api_disabled`。

本次不创建执行器接口、设备发现、开关命令、控制队列或 HTTP 控制路由。未来
自动控制必须另写独立规格并同时满足：

- 数字传感器主源或两个独立来源一致；
- 读数可用、未过期且连续稳定；
- 迟滞、绝对上下限、最短启停时间、动作频率限制和故障锁定；
- 数据冲突、陈旧、离线或结果不可验证时停止自动控制并通知人工；
- 实体遥控、手动接管和一键禁用；
- 大模型不能决定设备开关；
- 控制命令、执行结果和人工覆盖全部审计。

## 16. 故障降级

- 标定缺失或失效：当前读数立即不可用，10 分钟后通知，不自动重标；
- 摄像头断流：记录 `frame_source_unavailable`，并由摄像头健康链路按自己的
  60 秒规则告警；环境链路避免重复发送摄像头断流文案；
- 表盘遮挡、反光、过暗或低置信度：只写不可用读数，不输出旧值；
- SQLite 临时繁忙：短时有界重试；仍失败时保留内存中的本次结果并报告 worker
  健康降级，不阻塞下一次调度；
- ntfy 离线：本地历史和事件继续，恢复后只补发仍打开事件的最新状态，不回放
  大量过期通知；
- 负载过高：优先降视觉频率，环境采样仍保持每分钟一次；
- gauge worker 崩溃：launchd 独立重启，Dashboard 显示数据陈旧，不把旧值
  标为当前。

## 17. 实现组件边界

- `packages/contracts/events.py`：增强 `EnvironmentReading` 和闭集枚举；
- `packages/contracts/settings.py`：环境源、采样、严重门限和只读策略配置；
- `services/stream/frame_source.py`：固定 profile 的受控高分辨率帧源；
- `services/gauge/calibration.py`：标定 schema v2、坐标反算和原子存储；
- `services/gauge/source.py`：`EnvironmentReadingSource` 与
  `Ws2021GaugeSource`；
- `services/gauge/reader.py`：日间/夜间读针和多帧聚合；
- `services/gauge/worker.py`：单调调度、无积压运行和健康状态；
- `services/events/environment_state.py`：确定性异常、严重、不可读和恢复状态机；
- `services/storage/environment.py`：SQLite 迁移、读写和趋势查询；
- `services/notifications/ntfy.py`：环境文字负载和脱敏校验；
- `apps/api/`：鉴权环境 API、标定向导和 Dashboard；
- `deploy/launchd/`：独立 gauge worker 单元；
- `tests/gauge/`、`tests/environment/`、`tests/storage/`、
  `tests/notifications/` 和受影响的前端测试。

共享模块必须保持单一职责。Gauge 算法不得导入 Ollama 客户端，视觉 worker
不得导入 WS2021 reader，FastAPI 请求处理器不得执行五帧读针。

## 18. TDD、定向测试和实机验收

规格批准后按 TDD 小步实现。每个小步先运行与改动直接相关的定向测试；环境
阶段集成完成后运行受影响集成测试，大版本前再运行完整 Python、Node、Schema、
编译、Shell、安全扫描和 `git diff --check` 门禁。

自动测试至少覆盖：

- `available` 必须同时含两个值，`unavailable` 禁止任何值；
- 标定四角、视口反算、跨 0° 刻度、原子保存和版本失配；
- 合成白天红针、夜间灰度针、反光、遮挡、过暗、多针和无针；
- 5 帧中位数、最少 3 帧、MAD、低置信度和陈旧帧；
- 每分钟无积压调度及 visual/gauge 独立故障；
- SQLite 重复 ID、事务、365 天清理和 24 小时/7 天空档趋势；
- 普通 5 分钟、严重两次确认、恢复 5 分钟、不可读 10 分钟、重启恢复、去重
  和单次恢复通知；
- ntfy 负载不含媒体、数字私网地址、凭据、路径或自由文本堆栈；
- Dashboard 当前值不回退到旧值，趋势不做前值填充；
- Qwen 离线不影响环境读取，表盘不可读不影响视觉复核；
- 无任何执行器 API 或控制命令可达。

i9 真实硬件验收：

1. 在 `2×/3×` 当前视野完成一次 WS2021 schema v2 标定；
2. 白天至少采集 30 组人工核对读数，所有发布为 `available` 的样本满足
   ±1℃、±5%RH；不满足者必须被拒绝为不可用；
3. 完全黑暗/红外、反光、短时遮挡和移动表盘分别验证；夜间达不到误差目标时
   必须稳定输出不可用，不虚报数值；
4. 连续运行 24 小时，60 秒调度无队列增长，24 小时趋势和空档正确；
5. 模拟普通超限、严重超限、恢复和连续 10 分钟不可读，通知各只发送一次；
6. 断开 M2/Ollama 后环境读取、入库和通知继续；
7. 制造 CPU 压力后视觉频率先下降，环境采样和断流检测保持；
8. 两台 Android 收到的 ntfy 仅含文字、读数、时间和鉴权链接；
9. Git 状态和提交内容不含真实家庭影像、标定照片、凭据、Token、私网地址或
   本地绝对路径。

## 19. 明确不做

- 不控制空调、加湿器、除湿器、风扇或智能插座；
- 不提供执行器 API、自动控制开关或 Dashboard 设备按钮；
- 不让 Qwen3-VL、任何大模型或单次光学读数决定设备动作；
- 不读取宝宝生命体征，不把阈值描述为医疗建议；
- 不把表盘图片发送到 M2、ntfy 或其他第三方；
- 不在第一版实现多源融合、蓝牙/MQTT 适配器或 UVC 摄像头；
- 不提交真实家庭画面、标定参考图、运行数据库、凭据或私网信息。

## 20. i9 本地 WS2021 自动定位

人工 schema-v2 标定继续定义两只表盘的刻度和值域，但不再把仪表位置永久固定在
原画面坐标。一个独立的 i9 轻量目标检测器只回答“WS2021 在哪里”，不得直接输出
温度、湿度、指针角度或安全状态。检测器输入是内存中的 2560×1440 `gauge` 帧，
固定使用 640×640 letterbox 推理；目标在原始画面最远验收位置的宽度不得小于
原图宽度的 1/10，letterbox 后目标宽度约 64 像素。

检测结果是闭集契约：一个归一化矩形、置信度和模型版本。只接受单一候选、置信度
不低于固定门限、纵向直立且完全位于画面内的结果。零候选、多个近似候选、模型
缺失、推理错误、框越界或姿态不符分别映射为稳定失败码，不泄漏模型输出或图像。
模型使用 OpenVINO 在 Intel i9 推理；M2、Ollama、网络和云服务不参与生产读表。

边界框只作为搜索窗口。OpenCV 必须在框内重新找到白色外壳四边形和符合固定布局
的两个圆形表盘；随后把已标定四边形、圆心、针尖和刻度点通过单应变换迁移到当前
画面。迁移后的几何仍执行现有 5% 圆心、8% 半径、质量、多帧和物理范围门。模型
成功不能绕过任何读针门；定位失败时不得回退到上一次位置或旧读数。

### 20.1 隐私采集与训练资料

采集只允许在宝宝不在画面时显式启动。完整帧仅驻留内存；持久化前必须裁成紧贴
WS2021 的受控区域。检测到人脸、人体或皮肤区域与候选裁剪相交时丢弃该帧，不保存
成人图像。重复、模糊、过暗、过曝和遮挡帧自动丢弃。训练负样本使用许可明确的
公开/合成背景，不保存家庭完整帧。

本机资料固定保存在 Git 忽略的 `runtime/training/ws2021/`，文件与目录模式均为
私有；内容、文件名、摘要和绝对路径不得进入日志、状态 API、通知或 Git。资料可
保留到夜间验收及最终 72 小时门完成，删除仍由用户决定。训练工具只输出计数、
闭集状态码和聚合指标。

### 20.2 数据、训练和发布门

真实资料目标为白天 60–100 个有效裁剪、夜间/红外 30–60 个有效裁剪及 30–50 个
许可明确的非家庭负样本。自动增强覆盖画面位置、目标宽度 1/10–1/3、亮度、轻微
平面旋转、缩放和有限透视，但不得合成明显侧倾或倒置为正样本。增强产物同样只在
忽略目录。

训练框架固定为 Apache-2.0 的 YOLOX 0.3.0 commit
`419778480ab6ec0590e5d3831b3afb3b46ab2aa3`，架构固定 `YOLOX-Tiny`，单类
`ws2021`，输入 640×640。训练与导出是显式离线命令，不属于 Alpha 启动。模型必须固定架构、输入尺寸、类别
顺序、归一化、输出解码和文件摘要；发布产物为本机忽略的 OpenVINO IR。候选模型
必须在隔离的保留集通过召回、误检、单候选和最小尺寸门，随后通过真实移动、白天、
红外、遮挡和成人经过的 fail-closed 验收。软件测试只使用合成或许可明确媒体，不
证明家庭场景准确率。
