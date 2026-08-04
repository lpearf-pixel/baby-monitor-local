# Alpha 高清 MJPEG 预览设计

日期：2026-08-04  
关联：PR #4、Issue #7、`docs/runbooks/XIAOMI_CS2_MACOS_TROUBLESHOOTING.md`

## 1. 目标

在不迁移 Dashboard 播放协议、不引入 WebRTC/MSE 的前提下，将当前 Alpha 预览从低负载模式升级为稳定高清模式：

```text
摄像头 source：HD
Dashboard live：1280×720 MJPEG
目标帧率：10 FPS
```

本轮只解决清晰度和流畅度，不加入音频、双向语音、云台控制或公网暴露。后续真正的 15–25 FPS 实时视频仍通过独立的 WebRTC/MSE 任务完成。

## 2. 已知约束

1. 小米摄像头所有者账号已经能够通过兼容版 go2rtc 建立 `cs2+udp` 媒体连接。
2. Xiaomi URL 必须保持传输协商为自动，不得重新加入 `transport=tcp`。
3. `runtime/go2rtc.yaml` 包含敏感 Token 和设备参数，升级脚本不得打印完整 `xiaomi://` URI。
4. Dashboard 当前消费 `live` 流，并通过 `/api/stream.mjpeg?src=live` 代理到浏览器。
5. MJPEG 会增加 Intel i9 的 CPU 和局域网带宽，因此本轮上限固定为 1280×720、10 FPS，不直接提升到 1080p 或 20–25 FPS。

## 3. 最终配置

### 3.1 原始摄像头流

升级命令只修改 `source` URL 的画质参数：

```text
subtype=hd
```

处理规则：

- 保留账号、地区、IP、DID、model 和其他未知参数；
- 删除既有的 `subtype` 后追加唯一的 `subtype=hd`；
- 删除错误遗留的 `transport=tcp`，保持 transport 自动协商；
- 不将完整 URL 输出到终端或日志。

### 3.2 Dashboard 预览流

`live` 固定为：

```yaml
live: ffmpeg:source#video=mjpeg#width=1280#height=720#raw=-r 10
```

依据 go2rtc 的 FFmpeg 参数规则：

- `width`、`height` 用于转码缩放；
- `raw` 用于传入额外 FFmpeg 参数；
- `-r 10` 限制输出帧率为 10 FPS；
- 不继续使用当前模板中未被 go2rtc 解析器定义的 `#fps=5`。

## 4. 用户操作入口

新增 Makefile 命令：

```text
make alpha-quality-hd
make alpha-quality-info
make alpha-quality-rollback
```

### `alpha-quality-hd`

1. 检查 `runtime/go2rtc.yaml` 是否存在；
2. 检查 `streams.source` 是否存在；
3. 创建不含敏感内容的时间戳备份；
4. 安全更新 `source` 的查询参数；
5. 更新 `live` 为 1280×720、10 FPS；
6. 验证 YAML 可重新读取；
7. 重启 Alpha；
8. 执行高清健康检查。

### `alpha-quality-info`

只输出非敏感状态：

```text
source_quality=hd
g2rtc_transport=auto
live_width=1280
live_height=720
live_fps=10
```

不输出账号、Token、DID、IP、model 或完整 URL。

### `alpha-quality-rollback`

恢复最近一次由高清升级命令生成的配置备份，重启服务，并重新执行基础健康检查。

## 5. 健康检查

高清升级成功必须同时满足：

1. `source` 的 producer `protocol` 非空；
2. `source` 的 `medias` 包含视频；
3. `source` 的 `bytes_recv > 0`；
4. `source` 单帧 JPEG 非零且文件类型有效；
5. `live` 单帧 JPEG 非零；
6. `live` 单帧尺寸为 1280×720；
7. `/api/stream.mjpeg?src=live` 在限定时间内产生非零数据；
8. Dashboard `/healthz` 正常。

健康检查失败时不删除备份，并输出分层错误：

```text
SOURCE_NOT_CONFIGURED
SOURCE_OFFLINE
SOURCE_NO_VIDEO
LIVE_EMPTY_FRAME
LIVE_WRONG_DIMENSIONS
LIVE_MJPEG_EMPTY
DASHBOARD_OFFLINE
```

## 6. 配置保护与回滚

- 写入前备份到 `runtime/backups/go2rtc-quality-<timestamp>.yaml`；
- 使用临时文件写入并原子替换；
- 文件权限继承或恢复为仅当前用户可读写；
- `runtime/alpha.env` 不参与修改；
- Xiaomi Token 不进入测试输出、Git、Issue 或 CI artifact；
- 高清检查失败时提示执行 `make alpha-quality-rollback`，不静默覆盖现场证据。

## 7. 仓库默认值

`config/go2rtc.alpha.yaml` 的新安装默认预览改为 1280×720、10 FPS，但模板仍不包含真实 `source`。

安装器在已存在 `runtime/go2rtc.yaml` 时继续保持“不覆盖用户配置”的原则。现有机器通过 `make alpha-quality-hd` 显式升级。

## 8. 测试策略

### 静态和单元测试

- 模板不再包含 `#fps=5`；
- 模板包含 1280×720 和 `#raw=-r 10`；
- URL 更新保留未知参数；
- 重复执行高清命令不会产生重复 `subtype`；
- 强制 TCP 参数会被移除；
- 命令输出不得包含 `xiaomi://`、Token、UID、DID 或 IP；
- 缺少 `source` 时拒绝修改。

### 实机门禁

Intel i9 Mac 执行：

```bash
make alpha-quality-hd
make alpha-quality-info
make alpha-source-check
```

然后验证：

```text
source：真实媒体在线
live：1280×720 JPEG
MJPEG：连续非零输出
Dashboard：浏览器可见，主观流畅度明显高于原 5 FPS 模式
```

## 9. 发布边界

- 本轮保持 PR #4 为 Draft；
- 不将 MJPEG 10 FPS 描述为真正低延迟实时视频；
- 不把高清升级与 go2rtc 兼容构建绑成不可拆分脚本；
- 兼容版构建完成后继续执行此前功能路线：Dashboard 稳定化、通知、Tailscale 私有外部访问，再进入 WebRTC/MSE 和音频能力。
