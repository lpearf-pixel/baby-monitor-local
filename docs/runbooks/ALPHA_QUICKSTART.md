# 基础可用 Alpha：Intel i9 Mac 安装与远程操作

本 Alpha 的实际使用结构是：

```text
MJSXJ17CM 摄像头
  ├─ 256GB microSD：全天循环录像
  └─ 局域网视频 → Intel i9 Mac：监控服务
                         ├─ M2 Mac：SSH 管理＋局域网网页查看
                         └─ Android：后续通过 Tailscale 外部查看
```

安全边界：

- 监控网页 `8080` 默认允许可信局域网访问，并有独立随机密码；
- go2rtc 的管理、RTSP 和 WebRTC 端口仍只监听 i9 本机；
- M2 配置小米摄像头时通过 SSH 隧道访问 go2rtc；
- 路由器不得转发任何监控端口；
- 外部访问使用 Tailscale Serve HTTPS，不使用 Funnel。

## 1. 在 M2 上通过 SSH 操作 i9

先确认 i9 的局域网 IP。可以在已经建立的 SSH 会话里执行：

```bash
route -n get default | awk '/interface:/{print $2}'
ipconfig getifaddr en0
ipconfig getifaddr en1
```

通常只有其中一个 `ipconfig` 命令会返回地址。建议在路由器中给 i9 建立 DHCP 地址保留，避免 IP 经常变化。

从 M2 登录 i9：

```bash
ssh <i9用户名>@<i9局域网IP>
```

## 2. 获取 Alpha 分支

以下命令在 i9 的 SSH 会话中执行：

```bash
mkdir -p ~/dev
cd ~/dev

git clone -b codex/basic-usable-alpha \
  https://github.com/lpearf-pixel/baby-monitor-local.git

cd baby-monitor-local
chmod +x tools/*.sh
```

已有项目目录时：

```bash
cd ~/dev/baby-monitor-local
git fetch origin
git switch codex/basic-usable-alpha
git pull --ff-only
chmod +x tools/*.sh
```

## 3. 在 i9 上安装

```bash
./tools/install_alpha_macos.sh
```

安装器会准备：

1. Python 3.11；
2. FFmpeg；
3. 固定版本的 Intel go2rtc；
4. `.venv-alpha`；
5. 独立随机网页密码；
6. 随机 ntfy 主题；
7. 被 Git 忽略的本地运行目录。

本地账号和密码保存在：

```bash
cat runtime/alpha.env
```

不要将这个文件、终端截图或其中内容上传到 GitHub。不要把这个随机密码替换成你其他账号正在使用的密码，因为局域网 Alpha 当前使用 HTTP Basic Auth。

## 4. 启动服务

在 i9 的 SSH 会话中执行：

```bash
./tools/start_alpha.sh
```

脚本会输出类似：

```text
Local Dashboard: http://127.0.0.1:8080
LAN Dashboard: http://192.168.x.x:8080
```

M2 可直接打开：

```text
http://<i9局域网IP>:8080
```

如果 M2 无法访问，先在 M2 测试：

```bash
nc -vz <i9局域网IP> 8080
curl -I http://<i9局域网IP>:8080/healthz
```

若 i9 弹出 macOS 防火墙提示，允许该 Python/uvicorn 进程接收入站连接。不要关闭整个系统防火墙。

停止服务：

```bash
./tools/stop_alpha.sh
```

## 5. 从 M2 配置小米摄像头

go2rtc 管理端口 `1984` 不对局域网直接开放。请在 M2 新开一个终端窗口：

```bash
ssh -L 1984:127.0.0.1:1984 <i9用户名>@<i9局域网IP>
```

保持这个 SSH 会话打开，然后在 M2 浏览器访问：

```text
http://127.0.0.1:1984
```

依次操作：

1. 选择 **Add → Xiaomi**；
2. 登录米家账号；
3. 完成验证码；
4. 选择 MJSXJ17CM；
5. 将原始摄像头流命名为 **`source`**；
6. 系统预置的 `live` 流会在有人观看时，将 H.265 按需转换为 `960×540 / 5 FPS` MJPEG；
7. 回到 M2 的 `http://<i9局域网IP>:8080` 刷新。

本地 `runtime/go2rtc.yaml` 应保留：

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

不要把 `1984`、`8554` 或 `8555` 改成 `0.0.0.0`。

## 6. 两台 Android 接收通知

两台 Android 都安装 ntfy，并订阅 `runtime/alpha.env` 中的 `NTFY_TOPIC`：

```bash
grep '^NTFY_TOPIC=' runtime/alpha.env
```

在监控网页点击 **发送测试通知**，两台手机都应收到通知。

Alpha 当前使用随机长主题降低公开 ntfy 主题被猜中的风险。后续版本迁移到自建 ntfy 或受 Token 保护的服务。

## 7. 外部访问计划：Tailscale Serve HTTPS

本阶段先完成 M2 局域网访问。需要外出查看时，在 i9、M2 和两台 Android 安装 Tailscale，并加入同一个 tailnet。

在 i9 上执行：

```bash
tailscale serve --bg http://127.0.0.1:8080
tailscale serve status
```

Tailscale 会提供仅 tailnet 成员可访问的 HTTPS 地址，并把请求代理到 i9 本机的 `127.0.0.1:8080`。使用 `--bg` 后，Serve 配置可在 Tailscale 重启后恢复。

禁止使用：

```bash
tailscale funnel 8080
```

禁止在路由器转发：

```text
1984
8080
8554
8555
```

后续远程访问阶段还会增加：

- tailnet ACL，只允许两位家长设备访问；
- Android 外网验收；
- Tailscale 断线与恢复告警；
- 外部访问审计；
- 自动启动和进程看门狗。

## 8. 录像

全天录像仍由摄像头内的 256GB microSD 负责，写满后覆盖最早内容。请在米家 App 中确认：

- microSD 已识别；
- 录像模式为全天录像；
- 可正常回放；
- 已启用循环覆盖。

Alpha 不在 Mac 上重复保存全天视频，避免长期高 CPU 和磁盘占用。

## 9. 当前能力边界

当前可用：

- M2 通过 SSH 管理 i9；
- M2 通过局域网访问密码保护网页；
- 实时 MJPEG 画面；
- 当前截图；
- 摄像头流在线状态；
- ntfy 双手机测试通知；
- microSD 独立循环录像；
- 外部 Tailscale 接入方案。

暂时继续使用米家 App：

- 实时声音；
- 双向语音；
- 云台控制；
- microSD 历史回放。

后续迭代：

- 温湿度表盘自动识别；
- 哭声、大声响和床区移动候选；
- 事件前后短片；
- launchd 自动启动；
- 树莓派 2 独立看门狗；
- 企业微信/微信辅助通知；
- 每日报告。

本系统只提供辅助查看和候选提醒，不是呼吸、心率、血氧、窒息或医疗监护设备。

## 10. 排障

在 i9 SSH 会话中查看日志：

```bash
tail -n 100 runtime/logs/go2rtc.log
tail -n 100 runtime/logs/api.log
```

查看监听端口：

```bash
lsof -nP -iTCP:8080 -sTCP:LISTEN
lsof -nP -iTCP:1984 -sTCP:LISTEN
```

预期：

```text
8080 → *:8080 或 0.0.0.0:8080
1984 → 127.0.0.1:1984
```

检查接口：

```bash
curl -fsS http://127.0.0.1:1984/api/streams
curl -fsS http://127.0.0.1:8080/healthz
```
