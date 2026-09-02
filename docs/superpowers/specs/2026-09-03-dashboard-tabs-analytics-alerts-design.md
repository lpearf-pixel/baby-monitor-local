# Baby Monitor Local 紧凑式 Dashboard、警报与数据分析设计

**日期：** 2026-09-03

**状态：** 已由 owner 于 2026-09-03 确认精确文本；允许编写实施计划

**工作分支：** `codex/dashboard-tabs-analytics-alerts`

**基线：** `origin/codex/visual-regression-corpus@cabd4cf10e35a4aa9877a9b3c9a1e8692818948d`

## 1. 问题与目标

现有 Alpha Dashboard 把实时画面、截图、通知测试、原始系统状态、Guardian
事件、环境当前值、趋势、事件和标定入口堆在一个长页面中。它已经具备基础功能，
但存在三个产品问题：

1. 手机夜间查看时需要上下滚动，实时画面、当前风险和系统维护入口混在一起；
2. Guardian、环境和系统故障没有统一的注意力优先级，用户必须分别检查；
3. 已保存的环境读数、Guardian 生命周期、成人介入和通知状态没有形成稳定的
   分析视图，后续增加更长周期分析会继续挤压单页。

本切片把 Dashboard 调整为紧凑的四 Tab 信息架构，并新增只读聚合边界：

- 默认进入“监控总览”，一屏看到实时画面、最高优先级警报和关键读数；
- “警报中心”统一显示已确认 Guardian 事件、环境事件和当前系统故障；
- “数据分析”先提供 `24h`、`7d` 两个有界窗口，并为后续 `30d`、`90d`
  或 Baby Care 只读汇总保留版本化接口；
- “系统状态”集中健康信息和现有维护入口，不让维护控件占用主监控页面；
- 桌面和 iPhone 小屏都保持紧凑、清晰、可键盘操作且不误导数据新鲜度。

本系统仍是本地辅助监控，不是医疗设备，不替代成人直接照护，也不得被描述为
可以无人值守。

## 2. 方案选择

考虑过三种信息架构：

1. **四个顶部 Tab：总览 / 警报 / 数据 / 系统。** 实时监控、异常处理、趋势
   复盘和维护边界清晰；顶部 Tab 在桌面和手机上都稳定。采用此方案。
2. **三个 Tab，系统状态放抽屉。** 页面更少，但摄像头、环境链路或通知故障
   容易被隐藏，也不利于现场排查，不采用。
3. **桌面左侧栏。** 宽屏信息密度高，但 iPhone 需要二级抽屉，夜间单手操作更
   复杂，不采用。

选定方案不引入 SPA 框架、构建链或外部 CDN。继续使用 FastAPI、原生 JavaScript
和本地受保护静态资源，避免为了四个页面增加与现有 Alpha 不相称的运行依赖。

## 3. 范围与非目标

### 3.1 本切片包含

- 鉴权后的四 Tab Dashboard 壳、紧凑样式和响应式布局；
- 全局当前警报条与各 Tab 的未恢复数量；
- Guardian、环境和系统当前异常的只读规范化投影；
- 环境 `24h` 五分钟桶和 `7d` 一小时桶趋势；
- Guardian 已确认事件构成、恢复时长、成人介入、当前保留证据状态和通知投递
  统计；
- 当前值、最近有效值、数据生成时间和过期状态的明确区分；
- 既有截图、数码变焦、全屏、测试通知和温湿度计标定入口的重新编排；
- 旧 API 与环境事件深链接的兼容；
- 后端闭合模型、前端呈现、鉴权、隐私、过期和响应式回归测试。

### 3.2 本切片明确不包含

- 修改 Guardian 候选、确认、恢复、去重、通知或跨风险状态机；
- 修改环境阈值、采样、标定算法、状态机或通知判定；
- 调整视觉模型、提示词、置信度、帧率或 Camera Reply 生命周期；
- 新数据库、数据库迁移、写入型分析表、后台聚合任务或任意 SQL 查询；
- 家长确认、误报反馈、事件编辑或任何 Baby Care 写入；
- 图片、音频、视频证据查看器、下载或导出；
- 任意日期范围、`30d`/`90d` UI、同比环比、预测或模型生成结论；
- PTZ 启用、设备控制或自动控制空调、加湿器、风扇和插座；
- 修改 `main`、`stable/xiaomi-alpha`，或未经单独批准的推送、PR、合并和发布。

## 4. 页面信息架构

### 4.1 共享壳

共享壳固定包含：

- 产品名和本地监控状态；
- `总览`、`警报`、`数据`、`系统` 四个 Tab；
- 有未恢复确定性异常时出现的全局警报条；
- 每个响应最后成功生成时间以及必要的“数据可能已过期”提示。

Tab 切换只改变当前面板，不重新创建实时画面节点，不触发 go2rtc producer
切换，也不修改已选择的 `1x`、`2x`、`3x` 或全屏状态。实时画面即使暂时被
隐藏也保持现有生命周期；返回总览不能因为 Tab 切换创建第二条 HD 会话。

URL hash 保存当前 Tab：

```text
#tab=overview
#tab=alerts
#tab=analytics
#tab=system
```

刷新页面可以恢复合法 Tab。未知值回退到 `overview`，不得变成服务端路径或查询
参数。

### 4.2 监控总览

总览是默认页，桌面使用“实时画面 + 右侧关键状态”两栏，小屏降为单栏。首屏顺序：

1. 全局警报条；
2. 实时画面及现有数码变焦、全屏能力；
3. 环境当前读数或明确的不可用状态；
4. Guardian 未恢复已确认风险数和今日恢复数；
5. 摄像头、Guardian 查询、环境读取、通知队列等关键链路摘要；
6. 最近确定性动态。

“今日恢复”按 `AppSettings.app.timezone` 的本地自然日计算，响应时间本身仍使用
带时区 UTC。未加载设置时沿用项目默认 `Asia/Shanghai`，不能改成浏览器各自推断的
自然日，否则两台手机可能得到不同计数。

环境当前读数不可用或超过 `fresh_until` 时，主值显示“不可用”。最近一次有效
温湿度可以在独立次级行显示，并必须包含时间，不能复用当前值颜色、字号或文案。

“最近动态”首期只来自已确认 Guardian 事件、环境事件和当前系统异常。当前代码
没有稳定候选投影，因此不能从内部状态、模型 prose 或日志拼出候选动态。

### 4.3 警报中心

警报中心把三类记录规范化为同一列表：

- `guardian`：只接受确定性状态机已经打开或恢复的 Guardian 事件；
- `environment`：范围或不可读环境事件；
- `system`：当前查询得到的有界组件故障或数据过期状态。

列表默认按以下顺序显示：

1. 未恢复项优先；
2. 优先级 `critical`、`warning`、`info`；
3. `updated_at` 倒序；
4. 稳定 `alert_id` 倒序作为最终确定性排序。

返回所有当前未恢复项，再以最新已恢复项补足最多 100 条。Guardian 当前最多三种
打开风险，环境当前最多两个打开事件，系统组件集合也是闭合的，因此未恢复项不会
形成无界结果。页面提供“全部 / Guardian / 环境 / 系统”和“进行中 / 已恢复”
客户端筛选，不把筛选值传成 SQL 或路径。

环境通知的既有 `/incidents/{incident_id}` 继续重定向到
`/#environment-incident=<id>`。新 Dashboard 解析此旧 hash 时必须自动进入警报
Tab、定位并高亮精确事件；非法 ID 继续返回 404。新链接可以使用
`#tab=alerts&alert=<id>`，但不得删除旧格式支持。

### 4.4 数据分析

数据 Tab 首期只有 `24h` 和 `7d`。第一次进入 Tab 或切换窗口时加载；它不随
总览的 15 秒周期重复查询。页面提供手动刷新，并显示分析窗口和生成时间。

布局包含：

- 四个核心指标：环境数据可用率、已确认 Guardian 事件数、恢复时长中位数、
  成人介入次数；
- 温度和湿度最小值/中位数/最大值趋势，显式保留数据空档；
- Guardian 风险类型构成；
- 当前保留证据状态分布、通知投递结果和环境事件构成；
- 无数据、查询失败和数据过期的独立状态。

图表使用本地 Canvas 或内联受控 SVG，不加载外部图表库、字体、图标或分析脚本。
每张图同时提供文字摘要或可访问表格，颜色不是唯一信息载体。

### 4.5 系统状态

系统 Tab 只展示有权威来源的组件：摄像头/实时画面、Guardian 事件查询、环境
当前值、温湿度计标定、通知队列，以及已经存在稳定状态提供者的视觉或 Voice
组件。没有稳定提供者时显示 `unavailable`，不得根据页面能打开就推断 worker
健康。

Camera Reply 在本切片保持 `false`。页面可以明确显示“关闭”，不能提供启用
按钮。PTZ 继续显示为禁用或从主界面隐藏，不能因为重新布局而启用真实移动。

现有“刷新状态”“发送测试通知”“打开当前截图”“标定温湿度计”移动到合理位置，
其服务端行为和安全边界保持不变。新分析接口自身全部是 GET、只读操作。

## 5. 警报语义与优先级

Dashboard 只呈现确定性状态，不重新判定风险。统一优先级如下：

| 优先级 | 条件 | 页面语义 |
|---|---|---|
| `critical` | 任一未恢复 Guardian 高风险；未恢复且 `severity=critical` 的环境范围事件 | 红色、全局警报条置顶 |
| `warning` | 普通环境范围事件、环境不可读/过期、摄像头或只读查询组件不可用 | 黄色、需要检查 |
| `info` | 已恢复事件、成人介入审计、正常维护信息 | 灰蓝色，不伪装成当前危险 |

规则约束：

- 模型观察、watch、候选或语义冲突永远不能映射为红色已确认警报；
- “没有 baby”不能由 Dashboard 推断成遮脸；本切片只消费状态机最终事件；
- 成人介入是审计信息，除非关联的确定性风险仍打开，否则不单独升级为红色；
- 多个未恢复项同时存在时，全局警报条显示最高优先级、最早打开项和其余数量；
- 点击警报条进入警报中心并聚焦该项；
- 没有未恢复项时隐藏警报条，顶部仅保留简短健康状态；
- `resolution_cause` 在规范化模型中预留
  `explicit_safe | subject_outside | null`。当前上游没有该字段时为 `null`；以后
  合并跨风险修正后可以呈现准确恢复原因，但本分支不修改状态机或存储语义。

系统异常首期是当前快照，不伪造历史恢复记录。如果以后需要系统故障历史，必须
另行设计持久化健康事件，不能从浏览器轮询缺口反推。

## 6. 数据分析口径

所有服务端时间继续使用带时区 UTC；浏览器使用 `Intl.DateTimeFormat` 和当前
设备时区显示。窗口采用半开区间 `[started_at, ended_at)`，`ended_at` 是本次
查询固定的一个 `now`，同一响应内所有统计共用该边界。

| 指标 | 精确口径 | 无分母时 |
|---|---|---|
| 环境数据可用率 | `sum(available_count) / sum(sample_count)`，不是桶可用率的简单平均 | `null`，显示“无数据” |
| 已确认 Guardian 事件 | `opened_at` 落入窗口的确定性事件数 | `0` |
| Guardian 风险构成 | 上述事件按闭合 `risk_kind` 分组 | 每类 `0` |
| 已恢复事件 | `recovered_at` 落入窗口的事件数 | `0` |
| 恢复时长中位数 | 上述已恢复事件的 `recovered_at - opened_at` 中位数 | `null` |
| 成人介入 | `visual_interventions.observed_at` 落入窗口的唯一记录数 | `0` |
| 当前保留证据就绪率 | 窗口内打开事件中，当前仍有 evidence 行且状态为 `ready` 的数量 / 当前仍有 evidence 行的数量 | `null` |
| 缺失证据数 | 窗口内打开事件中当前没有 evidence 行的数量 | `0` |
| 通知成功率 | `updated_at` 落入窗口的终态通知中，`delivered / (delivered + rejected)` | `null` |
| 待发送通知 | 查询时当前 `state=pending` 的数量，另列而不进入成功率分母 | `0` |
| 环境事件构成 | `opened_at` 落入窗口，按 `range/unreadable` 和严重级别分组 | 每类 `0` |

证据文件和 evidence 行受既有保留策略影响，因此“当前保留证据就绪率”不是永久
历史质量率。页面必须同时显示保留记录分母和缺失证据数，不能把清理后的缺失记录
算成采集失败。通知成功率也必须显示终态分母；没有终态通知时是“无数据”，不是
`100%`。

环境趋势继续复用既有口径：

| 窗口 | 桶宽 | 桶字段 |
|---|---:|---|
| `24h` | 300 秒 | 样本数、可用数、可用率、温湿度 min/median/max |
| `7d` | 3600 秒 | 同上 |

不可用桶中的温湿度保持 `null`，图表断线并显示空档，禁止前值填充、插值或用
最近有效值补齐。

环境原始读数既有默认保留期为 365 天，因此未来可增加有界 `30d`、`90d` 日桶，
而不改变页面信息架构。本切片只定义 `schema_version=1` 和两个窗口；增加新窗口
需要显式扩展闭合枚举和测试，不能开放任意日期或任意 SQL。如果实际查询性能不足，
日聚合表和迁移必须另行批准，不能偷偷加入首期。

## 7. 后端与 API 架构

### 7.1 单一注入边界

`AlphaRuntime` 只增加一个可选的 Dashboard 数据提供者，而不是让路由分别知道
多个数据库和状态文件：

```python
class AlphaDashboard(Protocol):
    def overview(self, now: datetime) -> DashboardOverviewV1: ...
    def alerts(self, now: datetime) -> DashboardAlertListV1: ...
    def analytics(
        self, window: DashboardWindow, now: datetime
    ) -> DashboardAnalyticsV1: ...
    def system(self, now: datetime) -> DashboardSystemV1: ...
```

具体实现组合既有 Guardian 查询、环境 Dashboard 服务、摄像头网关和闭合健康
提供者。路由只接收已验证模型，不接收数据库路径、流名、设备 ID、模型 ID 或
配置对象。

Guardian 分析和通知统计需要访问 `events.sqlite3` 时，使用独立只读查询服务：

- SQLite URI 固定 `mode=ro`；
- 打开后执行 `PRAGMA query_only = ON`；
- 查询有固定窗口、固定字段和固定上限；
- 数据库不存在、锁定、schema 不匹配或行验证失败时返回稳定不可用码；
- 不执行 `CREATE`、迁移、清理、修复或任何写操作；
- 异常类型、SQL、文件路径和原始行不进入 HTTP 响应或日志。

环境趋势可复用已经注入的 `AlphaEnvironment.trend()`。新增 Dashboard 聚合层不得
再次构造会自动迁移的 `EnvironmentStore`。

### 7.2 新接口

全部接口继续要求现有 HTTP Basic 鉴权并返回 `Cache-Control: no-store`：

```text
GET /api/dashboard/overview
GET /api/dashboard/alerts
GET /api/dashboard/analytics/24h
GET /api/dashboard/analytics/7d
GET /api/dashboard/system
GET /assets/dashboard.css
GET /assets/dashboard-shell.js
GET /assets/dashboard-analytics.js
```

闭合响应模型统一包含 `schema_version=1` 和 `generated_at`。主要模型为：

- `DashboardOverviewV1`：最高注意项、未恢复数量、环境当前/最近有效投影、关键
  组件和最多 10 条最近确定性动态；
- `DashboardAlertListV1`：最多 100 条统一警报；
- `DashboardAnalyticsV1`：窗口边界、环境桶、Guardian/环境/证据/通知统计；
- `DashboardSystemV1`：闭合组件 ID、`healthy | degraded | unavailable | disabled`
  状态、稳定 detail code 和最后更新时间。

统一警报项只允许以下公开字段：

```text
alert_id
source: guardian | environment | system
kind: 闭合枚举
state: open | recovered
priority: critical | warning | info
opened_at
updated_at
recovered_at
reason_codes: 闭合枚举数组
adult_intervention_count: int | null
evidence_state: collecting | ready | failed | interrupted | unavailable | null
notification_state: pending | delivered | rejected | mixed | unavailable | null
resolution_cause: explicit_safe | subject_outside | null
```

标题、说明和本地化文案由前端根据闭合代码映射，服务端不返回模型 prose、原始
异常或自由文本。事件 ID 可以用于本地深链接，但不能暴露 evidence key、媒体路径、
数据库路径、通知 topic、私网地址或凭据。

### 7.3 兼容接口

现有接口继续保留：

```text
/api/guardian/events
/api/environment/current
/api/environment/trends/{24h|7d}
/api/environment/incidents
/api/gauge-calibration
/api/status
/live.mjpeg
/snapshot.jpeg
/api/test-notification
```

已有前端测试依赖的响应语义不能被新页面无意改变。新 Dashboard 不再把
`/api/status` 的 JSON 原样放入 `<pre>`；新系统投影只显示稳定代码。如果顺便
发现 `/api/status` 会把底层异常文本暴露给客户端，修复必须保留健康响应兼容并加
独立回归测试，不能用 UI 隐藏代替服务端封闭。

## 8. 前端模块与状态管理

HTML 继续由鉴权根页面返回，但样式迁移到本地受保护的 `dashboard.css`，避免
继续扩大 `_DASHBOARD` 内联字符串。推荐职责边界：

- `dashboard-shell.js`：Tab、hash、刷新调度、全局警报、过期状态和共享请求代次；
- `dashboard-analytics.js`：窗口切换、统计呈现和本地图表；
- `guardian-events.js`：保留 Guardian 闭合状态文案，可提取为纯 presenter；
- `environment-dashboard.js`：保留当前/最近有效、趋势空档和环境事件 presenter；
- `dashboard-viewer.js`、`hd-player.js`、`gauge-calibration.js`：沿用现有生命周期
  和安全边界，只有挂载位置发生必要变化。

不得把多个模块对同一端点的轮询叠加。共享调度器拥有刷新：

- 页面加载立即取总览、警报和系统；
- 总览、警报、系统每 15 秒刷新一次；
- 同一资源上一请求未结束时不并发第二次；
- 较旧请求晚返回时按代次丢弃，不能覆盖新结果；
- 分析数据只在首次激活、切换窗口或手动刷新时请求；
- 页面进入 BFCache、隐藏和恢复时沿用既有媒体生命周期，并恢复一个而非多个定时器。

刷新失败时保留最后一次成功结果，同时显示“数据可能已过期”、最后成功时间和
稳定错误码。第一次请求就失败则显示独立 unavailable 状态。任何失败都不能把
旧值改写成“刚刚更新”或清空正在显示的高优先级未恢复警报。

所有服务端字符串使用 `textContent` 或显式属性赋值，不拼接不可信 HTML。实际
实现使用本地 CSS、文字或仓库内审计过的 SVG，不依赖交互草图宿主提供的图标库。

## 9. 响应式与可访问性

- 支持最窄 320 CSS 像素，不出现页面级横向滚动；
- 桌面总览为两栏，约 720 像素以下降为单栏；
- 顶部四 Tab 保持一行等宽，文字不依赖图标；
- 可点击目标至少 44×44 CSS 像素；
- 使用 `tablist`、`tab`、`tabpanel`、`aria-selected`、`aria-controls` 和 roving
  `tabindex`；
- 左右方向键切换相邻 Tab，Home/End 到首尾；点击和键盘都同步 hash；
- 警报刷新使用 `aria-live=polite`，不能每 15 秒重复播报未变化内容；
- 红、黄、绿之外必须同时使用文字、状态词和结构；
- 支持 `prefers-reduced-motion`，不增加持续闪烁、呼吸灯或自动滚动；
- 夜间深色界面保持正文、次级文字、焦点环和警报颜色对比度；
- 图表有标题、摘要和无 Canvas 时的文字回退。

## 10. 鉴权、隐私与失败关闭

- 根页面、新静态资源和所有新 API 均先鉴权再调用服务；
- 所有页面、脚本、样式和 JSON 使用 `Cache-Control: no-store`；
- Dashboard 不返回或持久化家庭图片、音频、视频、转写、模型 prose、证据 key、
  本地路径、数据库内容、私网地址、设备标识、凭据或通知 topic；
- 图表只使用规范化数值、计数、闭合状态和带时区时间；
- 缺服务、数据库异常、验证错误和组件超时映射为稳定公开码；
- 部分数据源失败时其他卡片继续工作，并逐项标记 unavailable，不伪造全局健康；
- 新查询层不接触摄像头帧，不启动 worker，不发送通知，不写事件或分析结果；
- 新 UI 不增加任何设备控制能力。

## 11. 与其他 Codex 分支的合并约束

本分支从当时最新的 `codex/visual-regression-corpus@cabd4cf` 建立。该基线已经
包含现有 Guardian 事件 Dashboard、环境 Dashboard、Camera Reply 设计链和离线
应用演练文档，但若其他 Codex 分支以后前进，不能假设提交祖先关系等于功能已经
完全合并。

为降低后续冲突：

- 新查询模型、聚合服务、CSS、shell 和分析脚本优先放新增文件；
- `apps/api/alpha.py` 只做一个 provider 注入、固定路由和最小 HTML 壳调整；
- 不格式化或重排与本功能无关的 Python、JavaScript 和文档；
- 不修改视觉、Voice、Camera Reply、环境状态机和存储写路径；
- 兼容未来可选 `resolution_cause`，但不依赖尚未合入的跨风险修正；
- 每个实施提交保持单一意图，便于 cherry-pick、range-diff 和冲突定位；
- 在任何实际合并前重新 `fetch`，核对 `merge-base`、双方独有提交和
  `git merge-tree` 结果；
- 未经 owner 明确批准，不 rebase、merge、push、创建 PR 或修改目标分支。

全局 `SUMMARY.md`、`docs/STATUS.md`、`docs/CHECKPOINT.md` 和 `docs/NEXT.md` 是
高冲突文件。设计阶段不改变当前主线优先级；在本分支实现形成可验证检查点或进入
实际集成时，再基于目标分支最新内容做一次窄幅对账，不提前复制旧快照。

## 12. 验收与测试

### 12.1 后端

- 每个新响应模型 `extra=forbid`、时间带时区、窗口闭合；
- 鉴权失败发生在 provider/数据库调用之前；
- 所有成功和失败响应不缓存；
- 只读 SQLite 连接、缺库、锁库、schema 不匹配和无效行全部失败关闭；
- 统一警报只包含确认事件，候选/watch/模型 prose 不能进入；
- 多项警报的优先级、未恢复置顶、数量和最终排序确定；
- 最近 100 条边界不会挤掉当前未恢复项；
- 环境加权可用率、半开窗口、零分母 `null`、恢复中位数和介入去重准确；
- evidence 行清理后单列缺失数，不伪装成 evidence failure；
- 通知 pending 不进入终态成功率分母；
- 新接口没有数据库写入、迁移、通知或摄像头副作用；
- 旧 API 与环境 incident redirect 保持兼容。

### 12.2 前端

- 默认总览，四 Tab 点击和键盘切换正确，hash 刷新恢复；
- 旧 `#environment-incident=` 深链接自动进入警报并定位事件；
- 切换 Tab 不重建 live/HD 媒体节点，不增加 HD 会话或重复定时器；
- 总览/警报/系统立即加载并每 15 秒刷新，分析只按激活或操作加载；
- 并发请求和乱序响应被有界处理；
- 首次失败显示 unavailable，后续失败保留旧数据并显示 stale；
- 环境 current 不回退到 last-valid，图表空档保持空档；
- 候选不显示为红色确认警报；
- ARIA 状态、焦点、触控尺寸、reduced motion 和 320/390 像素布局有回归覆盖；
- 页面不依赖 CDN、网络字体或外部图表脚本。

### 12.3 计划中的验证命令

实施计划必须给出实际新增测试文件名，至少运行：

```bash
python -m pytest -q <focused-dashboard-test-paths>
node --test tests/frontend/*.test.mjs
python -m pytest -q
python -m compileall apps/api services
git diff --check
```

最终还要扫描 tracked diff，确认没有凭据、私网地址、家庭媒体、SQLite、runtime
状态或生成设置。软件测试证明的是 Dashboard 契约、聚合口径和交互回归，不证明
真实摄像头准确率、婴儿安全、通知到达、iPhone 网络质量或无人值守能力。

## 13. 任务契约

| 字段 | 本切片约束 |
|---|---|
| Current state | `codex/dashboard-tabs-analytics-alerts`，基线 `cabd4cf`；建分支时工作区干净；前端基线 73/73 通过，当前 Codex Python 环境缺少 `pytest`，全量 Python 基线未实际运行 |
| Goal | 鉴权 Dashboard 以四 Tab 紧凑显示实时总览、统一警报、`24h/7d` 分析和系统状态 |
| Allowed scope | Dashboard HTML/CSS/原生 JS、只读 provider/query/API、测试和本设计/后续计划文档 |
| Prohibited | 风险/环境/Voice/Camera Reply 判定，数据库写入迁移，PTZ/设备控制，家庭媒体，受保护分支和未批准远端操作 |
| Done | 本规格第 12 节回归通过，旧接口兼容，移动端/键盘/过期/隐私语义满足验收 |
| Verify | 聚焦 Python、全部 frontend、全量 Python、compileall、diff 和敏感内容扫描 |
| Delivery | 规格先独立本地提交；精确文本复核后才写实施计划；实施使用小提交；push/PR/merge 均需 owner 另行批准 |
