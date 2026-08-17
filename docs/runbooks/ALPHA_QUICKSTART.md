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
make alpha-install
make alpha-restart
```

`make alpha-update` 会自动：

1. 设置 `core.fileMode=false`；
2. 拉取远端；
3. 切换到 `codex/basic-usable-alpha`；
4. 使用 fast-forward 更新。

`make alpha-install` 会复用现有 `.venv-alpha` 和本机运行配置，安装/更新仓库
声明的 Python 依赖，并从固定 commit 构建带 `udp4` 与 `hvc1` 两个审计补丁的
Intel macOS go2rtc。首次构建会安装或检查 Go，耗时可能比普通 Python 更新长；
现有 Xiaomi URI 和 `runtime/alpha.env` 不会被覆盖。

因此不要再单独修改脚本可执行位。

## 4. 常用命令

```bash
make alpha-install
make alpha-start
make alpha-stop
make alpha-restart
make alpha-status
make alpha-visual-status
make alpha-logs
make alpha-quality-info
make alpha-source-check
make alpha-go2rtc-info
make alpha-subtype-probe
make alpha-subtype-apply
make alpha-guardian-scene-test
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
  source_compat: ffmpeg:source#video=h264#hardware=videotoolbox#width=2560#height=1440#bitrate=6M
```

不要将 go2rtc 端口改成 `0.0.0.0`，也不要把完整 `xiaomi://` 地址贴到聊天、Issue 或公开仓库。

## 7. 将现有安装升级到高清预览

先更新分支，然后执行一次安全升级：

```bash
cd ~/dev/baby-monitor-local
make alpha-update
make alpha-install
make alpha-quality-hd
```

`make alpha-quality-hd` 会依次：

1. 将当前配置备份到 `runtime/backups/`；
2. 把 `source` 的画质设置为 `subtype=hd`；
3. 删除错误遗留的 `transport=tcp`，恢复 `transport=auto`；
4. 将 `live` 设置为 1280×720、10 FPS MJPEG；
5. 加入固定的 `source_compat` VideoToolbox 1440p H.264 配置；该流只在 compat
   消费者存在时运行，不随服务永久启动；
6. 重启服务；
7. 检查真实生产者协议、媒体轨道、接收字节、JPEG、MJPEG 和 Dashboard。

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
compat_profile=videotoolbox-1440p-6M
```

单独重跑健康检查：

```bash
make alpha-source-check
```

成功时会输出：

```text
result=PASS
protocol=cs2+udp
source_codec=H265
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

MJSXJ17CM 的 Intel i9 实机结果为：编号 `0–2` 提供 `864×480`，编号
`3–5` 报告 `2560×1440`，探测器推荐 `3`。多个候选同为最高分辨率时，探测器
选择扫描顺序中编号最低的 `3`；短连接启动阶段的瞬时接收字节不能用于比较
清晰度或长期稳定性，因此不据此选择 `4/5`。

应用原生高清：

```bash
make alpha-subtype-apply
make alpha-quality-info
```

应用命令会先创建兼容现有回滚流程的质量备份，再设置 `subtype=3`、重启并
验证完整实时链路。只有源尺寸至少达到 `1920×1080` 且实时流、连续 MJPEG、
Dashboard 全部通过时才保留配置。成功时输出接近：

```text
result=PASS
applied_subtype=3
protocol=cs2+udp
bytes_received=<大于0>
source_dimensions=2560x1440
live_dimensions=1280x720
original_config_restored=false
```

任何门禁失败、异常或中断都会恢复应用前的完整配置和权限。不要手工复制或
编辑完整 Xiaomi URI。

## 8. 回滚高清升级

升级后画面异常、CPU 占用不合适或需要恢复现场时执行：

```bash
make alpha-quality-rollback
```

该命令恢复最近一次 `go2rtc-quality-*.yaml` 备份并重启，不修改 `runtime/alpha.env`。回滚后旧配置可能不是 1280×720，因此不要把高清尺寸检查结果作为回滚成功条件；使用米家和 Dashboard 确认基础画面即可。

## 9. 配置 WS2021 环境监测

安装程序会保留已有运行配置，并在首次安装时创建：

```text
runtime/settings.yaml
runtime/launchd/com.babymonitor.gauge.plist
runtime/launchd/com.babymonitor.environment-watchdog.plist
```

两者都只留在 i9 本机。`make alpha-start` 会把 gauge worker 作为独立 PID
启动；`make alpha-stop` 只向各自 PID 发送停止信号，不会让 gauge worker
停止 API、go2rtc 或后续 visual-review worker。查看非敏感运行状态：

```bash
make alpha-status
make alpha-logs
```

先打开鉴权 Dashboard，切换到能看清完整表盘的 `2×` 或 `3×` 视野，然后点击
“标定温湿度计”。按向导依次标记仪表面四角、湿度盘和温度盘的圆心、针尖及
刻度值。保存会生成私有参考 JPEG 和 schema v2 JSON；不要把这些文件复制到
仓库、Issue、聊天或 PR。标定缺失或失效时系统显示 `unavailable`，不会用旧
读数冒充当前值。

默认每 60 秒在同一连续解码会话中采集 5 帧。Dashboard 显示当前值、采集
时间、新鲜度、置信状态、失败原因、标定版本、24 小时/7 天趋势和环境事件。
普通范围与严重门限是项目可配置默认值，不是医疗建议。

要让环境事件通知链接可点击，先启用 Tailscale Serve，然后只把其鉴权 HTTPS
DNS URL 写到本机 `runtime/alpha.env`：

```text
BABY_MONITOR_DASHBOARD_URL=https://<本机tailnet名称>
```

不要写入账号、密码、Token、数字私网地址或 URL 查询参数。留空时本地读取、
历史、状态机和 Dashboard 继续运行，但环境事件 ntfy 发送保持禁用。安装程序
会把不含凭据的 plist 同步到个人 LaunchAgents；`make alpha-start` 注册独立的
gauge 和缺记录 watchdog job，登录和异常退出后由 launchd 恢复。watchdog 不
读取画面，只检查共享 SQLite 是否持续缺少新记录，因此 gauge 在配置、导入或
启动阶段反复失败也能形成十分钟不可读事件。`make alpha-stop` 只卸载这两个
环境 job，不停止同级 API 或 go2rtc。`environment.enabled=false` 时进程成功
退出且 `SuccessfulExit=false` 的 KeepAlive 条件不会重启它们。非 macOS 测试
环境才使用独立 PID 回退，两种启动方式不会同时运行。

环境监测当前固定为只读。Qwen/M2 离线不影响每分钟读表；表盘不可读也不影响
视觉复核。系统没有空调、加湿器、除湿器、风扇或智能插座执行器 API。

## 10. 配置 M2 本地 Qwen3-VL 复核

固定模型为：

```text
qwen3-vl:8b-instruct-q4_K_M
```

M2 上的 Ollama 必须继续只监听默认 `127.0.0.1:11434`。不要设置
`OLLAMA_HOST=0.0.0.0:11434`，不要配置路由器端口转发或 Tailscale Funnel。
`ollama ps` 在没有正在执行的请求时为空是正常现象；视觉 worker 发出请求后
模型自动加载，并在空闲五分钟后允许 Ollama 释放内存。

在 i9 创建只用于该隧道的密钥，不复用日常 SSH 密钥：

```bash
ssh-keygen -t ed25519 -f "$HOME/.ssh/baby-monitor-m2" \
  -C baby-monitor-ollama-tunnel
chmod 600 "$HOME/.ssh/baby-monitor-m2"
```

把 `.pub` 公钥加入 M2 上专用 SSH 账户的 `~/.ssh/authorized_keys`，并在同一行
公钥前加以下限制：

```text
restrict,port-forwarding,permitopen="127.0.0.1:11434"
```

这允许唯一目标端口转发，但不授予交互式 Shell、PTY、agent/X11 转发。M2 专用
账户关闭密码登录。首次连接前，在 M2 本机查看 SSH host key 指纹，并在 i9
首次接受 host key 时人工核对；不要未经核对直接导入 `ssh-keyscan` 结果。

在 i9 生成本地 launchd 隧道配置：

```bash
cd ~/dev/baby-monitor-local
./.venv-alpha/bin/python tools/configure_ollama_tunnel.py \
  --target '<专用账户>@<M2私网IPv4或.local主机名>' \
  --identity "$HOME/.ssh/baby-monitor-m2"
```

配置器只接受 RFC1918 私网 IPv4 或 `.local` 主机名，只接受当前用户拥有、位于
`~/.ssh/` 且权限为 `400/600` 的普通文件。生成的隧道固定为：

```text
i9 127.0.0.1:11435 → SSH → M2 127.0.0.1:11434
```

`runtime/settings.yaml` 中 `visual.enabled` 默认是 `false`。必须在 i9 本地填写
真实、归一化的 `bed_zone`，可选填写 `privacy_masks`，再改为 `true`；不要把该
床区配置、截图或画面发到聊天、Issue 或 PR。没有床区时进程固定返回
`VISUAL_BED_ZONE_REQUIRED`，不会把全房间画面送给模型。

完成本地床区配置后：

```bash
make alpha-restart
make alpha-visual-status
```

预期看到 visual worker 与 tunnel 为 `running`、Ollama bridge 为 `reachable`。
状态命令不会显示 M2 地址、SSH 参数、模型原始输出或图片。R3 只建立本地复核和
确定性风险候选；当前仍没有事件截图/视频、ntfy 风险通知或 Dashboard 人工反馈，
这些属于 R4。它也不是医疗监护，不能替代成人持续照护。

## 11. iPhone 通知

两台 iPhone 安装 ntfy，并订阅：

```bash
grep '^NTFY_TOPIC=' runtime/alpha.env
```

在 Dashboard 点击“发送测试通知”。

环境异常通知只发送文字、读数、采集时间、稳定原因码和鉴权链接，不上传宝宝
画面、表盘截图、私网地址或本地路径。

## 12. Guardian 家庭合成场景验收

只能在无真实婴儿参与危险或模拟风险姿势、且有成人全程监督时运行：

```bash
make alpha-guardian-scene-test
```

命令固定检查空床、玩偶或静态道具、成人入镜、红外夜视、安全模拟镜头遮挡、
蚊帐摆动和安全正常翻身替代场景，每类需要 10 次。每次只输入
`correct`、`false_positive`、`missed` 或 `unavailable`。中断后可以重新运行并
继续未完成试次。

结果只写入被 Git 忽略的本地 `runtime/` 状态，不保存画面、模型原文、地址、
凭据或床区坐标，不发送 ntfy，也不写生产事件或证据数据库。该门禁仅证明本次
固定场景表现，不是医疗准确率或无人照护证明。

## 13. 后续外部访问

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

## 14. 视频和功能边界

1× 模式继续使用 1280×720、10 FPS MJPEG；2×/3× 会按需申请绑定 profile 的
一次性票据，通过 Dashboard 的同源 WebSocket 中继连接仅限本机的 go2rtc。
浏览器支持 HEVC MSE 时请求 `native`，直接解码 2560×1440 H.265 原码；不支持
或首帧前失败时，最多自动切换一次 `compat`，由固定 `source_compat` 启动
VideoToolbox 1440p H.264 硬编码。多个 compat 客户端共享一个 producer，最后
一个消费者离开后停止，且不允许软件编码回退。go2rtc 仍不暴露到局域网。
本阶段只启用视频 MSE，不包含 WebRTC/MSE 自动协商、实时音频或双向语音。

全天录像仍由摄像头内的 256GB microSD 负责，写满后覆盖最早内容。

当前 Alpha 已提供：

- 1× 轻量 MJPEG 与 2×/3× 原生 1440p 清晰变焦；
- 全屏、1×/2×/3× 数码变焦、鼠标拖动和 Android 单指拖动；
- 当前截图；
- 摄像头状态；
- 双 Android 测试通知；
- M2 SSH 维护方式。

使用查看器顶部的 `1×`、`2×`、`3×` 切换画面；进入 2×/3× 后状态依次为
`HD_LOADING`、`HD_ACTIVE`。放大后可拖动画面。点击“全屏”或双击当前
MJPEG/HD 画面进入全屏，按 `Esc` 退出并恢复 1× 居中。目标画面首帧成功前
旧画面不会消失；`HD_CODEC_UNSUPPORTED`、`HD_TRANSCODE_UNAVAILABLE`、
`HD_UPSTREAM_FAILED`、`HD_TIMEOUT`、`HD_UNSUPPORTED` 或 `HD_BUSY` 均保留
可用 MJPEG，浏览器不会在后台无限重试。

### 清晰变焦实机验收

更新并重启后，在 M2 Chrome/Safari 与 Android Chrome 逐项确认：

1. 1× 连续显示 1280×720 MJPEG；2×/3× 能看到比旧 720p 像素放大更多的
   2560×1440 原生细节。
2. 1×→2×/3× 正常切换约 1–2 秒，期间不黑屏；2×→3× 不再次显示
   `HD_LOADING`，也不创建第二个高清连接。
3. 回到 1× 或按 `Esc` 退出全屏后，MJPEG 先恢复，再释放 HD；反复切换、拖动
   和全屏时画面持续可见。
4. 关闭一次 HD WebSocket 或让浏览器拒绝 MSE 后，页面显示稳定回退码并保留
   MJPEG；重新尝试必须先选 1×，再选 2×/3×。
5. go2rtc 的 `1984/8554/8555` 仍只监听 `127.0.0.1`；稳定 1× 没有 MSE
   消费者。native 模式没有 HD 编码器；compat 模式恰有一个共享的
   `h264_videotoolbox` 编码器，最后一个 compat 页面回到 1× 后停止。
6. 方向键仍显示 `PTZ_DISABLED`，不会向摄像头发送电机指令。

只在 i9 本机或 SSH 隧道后的 go2rtc 页面观察消费者，不要粘贴原始
`/api/streams` 输出；该输出可能包含 Xiaomi URI。检查 FFmpeg 数量时也不要
粘贴完整进程参数，只记录数量和是否存在视频编码。

以下命令只打印 `source/live/source_compat` 的生产者、消费者数量和 FFmpeg
编码器数量，
不会打印流 URL、设备字段或进程命令行。分别在稳定 1×、稳定 2×、稳定 3×
执行并记录数字：

```bash
curl -fsS http://127.0.0.1:1984/api/streams | \
  ./.venv-alpha/bin/python -c '
import json, sys
streams = json.load(sys.stdin)
for name in ("source", "live", "source_compat"):
    stream = streams.get(name, {}) if isinstance(streams, dict) else {}
    print("{}_producer_count={}".format(name, len(stream.get("producers", []))))
    print("{}_consumer_count={}".format(name, len(stream.get("consumers", []))))
'
printf 'compat_encoder_count='
{ pgrep -f '[f]fmpeg.*h264_videotoolbox' || true; } | wc -l | tr -d ' '
printf '\n'
```

稳定 2× 与 3× 的数量必须相同。native 时 `compat_encoder_count=0`；compat
时 `compat_encoder_count=1`，同 profile 的多个页面仍为 1；最后一个 compat
页面回到 1× 后必须恢复为 0。若本机同时运行其他 FFmpeg 任务，只判断上述
VideoToolbox 特征计数，不要停止无关进程。

先确认补丁构建与源流，再记录浏览器结果：

```bash
make alpha-go2rtc-info
make alpha-source-check
```

每个浏览器在页面显示 `HD_ACTIVE` 后，从状态元素的非敏感 profile 标记记录
`active_profile=native` 或 `active_profile=compat`。把三端结果汇总为：

```text
m2_chrome_active_profile=native/compat/FAIL
m2_safari_active_profile=native/compat/FAIL
android_chrome_active_profile=native/compat/FAIL
native_detail_2x_3x=PASS/FAIL
handoff_seconds=实际秒数
no_black_frame=PASS/FAIL
zoom_2_to_3_reuse=PASS/FAIL
fallback_mjpeg=PASS/FAIL
compat_encoder_count=实际数量
compat_encoder_stops=PASS/FAIL
ptz_status=PTZ_DISABLED
```

方向键代表物理摄像头点按步进，但当前真实 MJSXJ17CM 控制适配器仍默认
禁用。点击时预期显示 `PTZ_DISABLED`，且不会向设备发送未经验证的电机
指令。只有精确协议 fixture 通过自动化测试，并完成一次受控“左一步→右一步
回位”实机门禁后，才会开放真实四向控制。当前物理云台、声音、双向语音和
microSD 回放继续使用米家 App。

稳定 PTZ 状态码：

- `PTZ_OK`：单步命令已接受；
- `PTZ_BUSY`：已有命令执行或仍在最短间隔内；
- `PTZ_DISABLED`：真实设备适配器未启用；
- `PTZ_TIMEOUT`：受控请求超时；
- `PTZ_UNAVAILABLE`：设备适配器或响应不可用。

本系统不是呼吸、心率、血氧、窒息或医疗监护设备。

## 15. 已验证故障案例

### Dashboard 仍在线但实时影像消失

2026-08-17 已验证过一种独立故障：Dashboard、gauge 和 visual launchd job 仍显示
运行，但 go2rtc 源为 0 字节，visual 指标随之变为 `stale`。先停止占满 CPU 的本地
WS2021 训练，再运行：

```bash
make alpha-source-check
make alpha-status
```

若第一条返回 `SOURCE_OFFLINE`，不要修改 Dashboard、摄像头 URI、FFmpeg 参数或
质量门。先执行现有幂等恢复：

```bash
make alpha-restart
```

若恢复命令返回 `go2rtc pid identity mismatch`，说明 1984 监听进程与
`runtime/pids/go2rtc.pid` 的所有权记录不一致。启动脚本会 fail closed，避免停止
无关进程。不要直接删除 PID 文件，也不要凭 PID 猜测后强杀。先在 i9 本机核对：

```bash
lsof -nP -iTCP:1984 -sTCP:LISTEN
ps -ww -p <PID> -o command=
```

只有命令精确属于当前仓库的 `.local/bin/go2rtc`，且参数是当前仓库的
`runtime/go2rtc.yaml` 时，才停止该已确认的孤立进程并重新启动：

```bash
kill <PID>
make alpha-start
```

不要把 `alpha-start` 输出的局域网地址或任何完整命令路径粘贴到聊天、Issue 或 PR。
恢复后必须重新验证：

```bash
make alpha-source-check
make alpha-visual-status
```

本次恢复证据为：`SOURCE PASS`、`cs2+udp`、H.265、2560×1440 source、
1280×720 live，以及 visual 指标恢复为 `available`、5 FPS。该结果证明本地摄像头
源和分析画面恢复，不证明 M2/Ollama 可用；Ollama bridge 可独立保持不可用。

根因不是 Dashboard 页面代码，也不是 WS2021 模型。它是一个已确认属于本项目、
但失去 PID 所有权记录的 go2rtc 监听进程；安全启动脚本因此拒绝接管。恢复过程中
不得降低源检查、隐私或 fail-closed 门限。

Intel macOS 上遇到以下现象时：

```text
source 已配置但无画面
/api/frame.jpeg 返回 Content-Length: 0
日志出现 read udp [::] 或 read udp4 0.0.0.0 timeout
```

不要直接修改 Dashboard 或 FFmpeg。先阅读：

- [`XIAOMI_CS2_MACOS_TROUBLESHOOTING.md`](./XIAOMI_CS2_MACOS_TROUBLESHOOTING.md)

该记录包含米家共享账号限制、CS2 抓包、Python/Go UDP 对照、macOS 防火墙、`udp4` 补丁和 `transport=auto` 的完整实机证据。
