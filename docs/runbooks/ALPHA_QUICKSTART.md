# 基础可用 Alpha：Intel i9 Mac 安装与远程操作

实际结构：

```text
MJSXJ17CM 摄像头
  ├─ 256GB microSD：全天循环录像
  └─ 局域网视频 → Intel i9 Mac：监控服务
                         ├─ M2 Mac：SSH 管理＋局域网网页查看
                         └─ Android：后续通过 Tailscale 外部查看
```

网络边界：

- Dashboard `8080` 默认允许可信局域网访问，并使用独立随机密码；
- go2rtc `1984/8554/8555` 始终只监听 i9 本机；
- M2 配置摄像头时通过 SSH 隧道访问 go2rtc；
- 路由器不得转发监控端口；
- 外部访问使用 Tailscale Serve HTTPS，不使用 Funnel。

## 1. 从 M2 登录 i9

```bash
ssh <i9用户名>@<i9局域网IP>
```

在 i9 上查看局域网地址：

```bash
route -n get default | awk '/interface:/{print $2}'
ipconfig getifaddr en0
ipconfig getifaddr en1
```

建议在路由器中给 i9 设置 DHCP 地址保留。

## 2. 第一次下载

以下命令在 i9 的 SSH 会话中执行：

```bash
mkdir -p ~/dev
cd ~/dev

git clone -b codex/basic-usable-alpha \
  https://github.com/lpearf-pixel/baby-monitor-local.git

cd baby-monitor-local
git config core.fileMode false
make alpha-install
make alpha-start
```

不需要修改任何仓库文件权限。新安装的 `live` 模板默认为 1280×720、10 FPS MJPEG。

## 3. 后续更新

```bash
cd ~/dev/baby-monitor-local
make alpha-update
make alpha-restart
```

`make alpha-update` 会自动：

1. 设置 `core.fileMode=false`；
2. 拉取远端；
3. 切换到 `codex/basic-usable-alpha`；
4. 使用 fast-forward 更新。

因此不要再单独修改脚本可执行位。

## 4. 常用命令

```bash
make alpha-install
make alpha-start
make alpha-stop
make alpha-restart
make alpha-status
make alpha-logs
make alpha-quality-info
make alpha-source-check
make alpha-subtype-probe
```

查看本地账号、密码和 ntfy 主题：

```bash
cat runtime/alpha.env
```

不要上传或粘贴该文件内容。局域网 Alpha 当前使用 HTTP Basic Auth，密码必须保持独立，不与其他账户复用。

## 5. 从 M2 访问 Dashboard

启动后，i9 会输出类似：

```text
Local Dashboard: http://127.0.0.1:8080
LAN Dashboard: http://192.168.x.x:8080
```

M2 浏览器打开：

```text
http://<i9局域网IP>:8080
```

M2 测试：

```bash
nc -vz <i9局域网IP> 8080
curl -v http://<i9局域网IP>:8080/healthz
```

i9 检查监听：

```bash
make alpha-status
lsof -nP -iTCP:8080 -sTCP:LISTEN
```

正确状态应为 `*:8080` 或 `0.0.0.0:8080`，不是仅 `127.0.0.1:8080`。

若 i9 弹出 macOS 防火墙提示，只允许当前 Python/uvicorn 接收入站连接，不要关闭整个防火墙。

## 6. 从 M2 配置小米摄像头

go2rtc 管理端口不直接开放到局域网。在 M2 新开终端，使用一行式命令：

```bash
ssh -L 1984:127.0.0.1:1984 <i9用户名>@<i9局域网IP>
```

只建立隧道、不打开远程 Shell 时可使用：

```bash
ssh -N -L 1984:127.0.0.1:1984 <i9用户名>@<i9局域网IP>
```

保持会话打开，然后 M2 浏览器访问：

```text
http://127.0.0.1:1984
```

操作：

1. 选择 **Add → Xiaomi**；
2. 登录摄像头真正的设备所有者账号；
3. 完成验证码；
4. 选择 MJSXJ17CM；
5. 将原始摄像头流命名为 `source`；
6. 返回 Dashboard 刷新。

本机非敏感结构应继续保持：

```yaml
api:
  listen: "127.0.0.1:1984"
rtsp:
  listen: "127.0.0.1:8554"
webrtc:
  listen: "127.0.0.1:8555"
streams:
  source: "本机生成的 Xiaomi 敏感地址，subtype=hd，传输自动协商"
  live: ffmpeg:source#video=mjpeg#width=1280#height=720#raw=-r 10
```

不要将 go2rtc 端口改成 `0.0.0.0`，也不要把完整 `xiaomi://` 地址贴到聊天、Issue 或公开仓库。

## 7. 将现有安装升级到高清预览

先更新分支，然后执行一次安全升级：

```bash
cd ~/dev/baby-monitor-local
make alpha-update
make alpha-quality-hd
```

`make alpha-quality-hd` 会依次：

1. 将当前配置备份到 `runtime/backups/`；
2. 把 `source` 的画质设置为 `subtype=hd`；
3. 删除错误遗留的 `transport=tcp`，恢复 `transport=auto`；
4. 将 `live` 设置为 1280×720、10 FPS MJPEG；
5. 重启服务；
6. 检查真实生产者协议、媒体轨道、接收字节、JPEG、MJPEG 和 Dashboard。

查看不含账号和设备信息的配置摘要：

```bash
make alpha-quality-info
```

预期接近：

```text
source_quality=hd
transport=auto
live_width=1280
live_height=720
live_fps=10
```

单独重跑健康检查：

```bash
make alpha-source-check
```

成功时会输出：

```text
result=PASS
protocol=cs2+udp
bytes_received=<大于0>
source_dimensions=<摄像头实际尺寸>
live_dimensions=1280x720
```

不要重新加入 `transport=tcp`。该型号实机返回 UDP ready；强制 TCP 会使 CS2 握手停在传输选择阶段。

### 安全探测 MJSXJ17CM 的原生清晰度编号

如果 `source_dimensions` 仍为 `864x480`，说明 `subtype=hd` 在当前 go2rtc 中只映射到了质量编号 `2`。执行：

```bash
make alpha-subtype-probe
```

命令会依次探测编号 `0` 至 `5`，期间会重启 Alpha 多次，网页画面预计中断约 2–5 分钟。每个候选只输出：

```text
subtype=<编号> result=<状态> protocol=<协议> bytes_received=<字节数> source_dimensions=<实际尺寸>
```

结束时输出 `recommended_subtype` 和 `original_config_restored=true`。无论探测成功、失败或按 `Ctrl+C` 中断，命令都会恢复探测前的完整配置、文件权限和服务；推荐编号不会被自动应用。

重启脚本的输出会被抑制，避免终端探测摘要包含局域网地址。不要发送 `runtime/go2rtc.yaml`、完整 Xiaomi URI、账号、Token、UID、DID、MAC 或任何画面，只共享上述派生结果。

## 8. 回滚高清升级

升级后画面异常、CPU 占用不合适或需要恢复现场时执行：

```bash
make alpha-quality-rollback
```

该命令恢复最近一次 `go2rtc-quality-*.yaml` 备份并重启，不修改 `runtime/alpha.env`。回滚后旧配置可能不是 1280×720，因此不要把高清尺寸检查结果作为回滚成功条件；使用米家和 Dashboard 确认基础画面即可。

## 9. Android 通知

两台 Android 安装 ntfy，并订阅：

```bash
grep '^NTFY_TOPIC=' runtime/alpha.env
```

在 Dashboard 点击“发送测试通知”。

## 10. 后续外部访问

外部访问由 Issue #5 跟踪。目标命令为：

```bash
tailscale serve --bg http://127.0.0.1:8080
tailscale serve status
```

禁止：

```bash
tailscale funnel 8080
```

也禁止路由器转发 `1984`、`8080`、`8554`、`8555`。

## 11. 视频和功能边界

当前高清模式是 1280×720、10 FPS MJPEG，用于先获得稳定、清晰、浏览器通用的监控画面。它不是 15–25 FPS 的低延迟实时视频；后续将单独迁移到 WebRTC/MSE。

全天录像仍由摄像头内的 256GB microSD 负责，写满后覆盖最早内容。

当前 Alpha 已提供：

- 局域网高清画面；
- 当前截图；
- 摄像头状态；
- 双 Android 测试通知；
- M2 SSH 维护方式。

声音、双向语音、云台和 microSD 回放暂时继续使用米家 App。

本系统不是呼吸、心率、血氧、窒息或医疗监护设备。

## 12. 已验证故障案例

Intel macOS 上遇到以下现象时：

```text
source 已配置但无画面
/api/frame.jpeg 返回 Content-Length: 0
日志出现 read udp [::] 或 read udp4 0.0.0.0 timeout
```

不要直接修改 Dashboard 或 FFmpeg。先阅读：

- [`XIAOMI_CS2_MACOS_TROUBLESHOOTING.md`](./XIAOMI_CS2_MACOS_TROUBLESHOOTING.md)

该记录包含米家共享账号限制、CS2 抓包、Python/Go UDP 对照、macOS 防火墙、`udp4` 补丁和 `transport=auto` 的完整实机证据。
