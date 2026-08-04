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

不需要修改任何仓库文件权限。

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
2. 登录米家账号；
3. 完成验证码；
4. 选择 MJSXJ17CM；
5. 将原始摄像头流命名为 `source`；
6. 返回 Dashboard 刷新。

本机配置应继续保持：

```yaml
api:
  listen: "127.0.0.1:1984"
rtsp:
  listen: "127.0.0.1:8554"
webrtc:
  listen: "127.0.0.1:8555"
streams:
  live: ffmpeg:source#video=mjpeg#width=960#height=540#fps=5
```

不要将 go2rtc 端口改成 `0.0.0.0`。

## 7. Android 通知

两台 Android 安装 ntfy，并订阅：

```bash
grep '^NTFY_TOPIC=' runtime/alpha.env
```

在 Dashboard 点击“发送测试通知”。

## 8. 后续外部访问

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

## 9. 录像和功能边界

全天录像仍由摄像头内的 256GB microSD 负责，写满后覆盖最早内容。

当前 Alpha 已提供：

- 局域网实时画面；
- 当前截图；
- 摄像头状态；
- 双 Android 测试通知；
- M2 SSH 维护方式。

声音、双向语音、云台和 microSD 回放暂时继续使用米家 App。

本系统不是呼吸、心率、血氧、窒息或医疗监护设备。

## 10. 已验证故障案例

Intel macOS 上遇到以下现象时：

```text
source 已配置但无画面
/api/frame.jpeg 返回 Content-Length: 0
日志出现 read udp [::] 或 read udp4 0.0.0.0 timeout
```

不要直接修改 Dashboard 或 FFmpeg。先阅读：

- [`XIAOMI_CS2_MACOS_TROUBLESHOOTING.md`](./XIAOMI_CS2_MACOS_TROUBLESHOOTING.md)

该记录包含米家共享账号限制、CS2 抓包、Python/Go UDP 对照、macOS 防火墙、`udp4` 补丁和 `transport=auto` 的完整实机证据。
