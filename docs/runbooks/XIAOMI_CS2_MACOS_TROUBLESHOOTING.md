# 小米摄像头 CS2 在 Intel macOS 上无画面：实机排查记录

> 实机日期：2026-08-04  
> 环境：Intel i9 Mac、macOS、go2rtc darwin/amd64、小米智能摄像机 2 云台版（MJSXJ17CM）  
> 结论状态：已验证原始 `source` 能生成非零 JPEG；最终验证样本为 864×480、19479 字节。

本文记录一次完整的跨层排查，供后续安装、升级和其他小米 CS2 摄像头接入时复用。

## 1. 最终结论

本次不是单一故障，而是三个问题叠加：

1. **米家共享账号限制**：摄像头在米家 App 中可以被共享账号查看，但 go2rtc 无法枚举或使用该共享设备；必须先用摄像头所有者账号接入。
2. **Intel macOS 上 Go/go2rtc 的 UDP 接收问题**：摄像头确实返回了 CS2 握手包，但原始 go2rtc 使用通配 UDP Socket 时未能在用户态收到；最终工作版本强制使用 `udp4`，并允许固定 go2rtc 二进制接收入站连接。
3. **错误地强制 `transport=tcp`**：该摄像头在第二阶段返回 `0x42`（UDP ready），而强制 TCP 时 go2rtc 只接受 `0x43`（TCP ready），导致握手持续重试。删除 `transport=tcp`、恢复自动选择后成功。

最终已验证的组合：

```text
摄像头账号：设备所有者账号
Go2rtc 基线：上游 PR #2222（commit b465651）
本地补丁：net.ListenUDP("udp", nil) → net.ListenUDP("udp4", nil)
Xiaomi transport：auto（URL 中不设置 transport）
macOS：固定路径二进制签名并加入应用防火墙允许列表
实际协议：cs2+udp
```

注意：PR #2222 单独使用仍未解决本机问题；成功版本包含 PR #2222 和本地 `udp4` 修改。两者是否都为该型号长期必需，尚未独立拆分验证，因此应以“已验证组合”管理，而不是把某一项描述为唯一修复。

## 2. 初始现象

Dashboard 页面可以登录，但没有视频。

Go2rtc 中已经存在：

```text
live
source
```

但实际表现为：

```text
/api/frame.jpeg?src=source
HTTP 200
Content-Length: 0
```

生成文件为空：

```text
/tmp/source-test.jpg: empty
0 /tmp/source-test.jpg
```

RTSP 测试返回：

```text
DESCRIBE failed: 404 Not Found
```

日志出现：

```text
streams: read udp [::]:<随机端口>: i/o timeout
```

`/api/streams` 虽然列出了 `source`，生产者却没有实际媒体状态：

```text
protocol=None
medias=None
bytes_recv=None
```

经验：**流名称存在只表示配置已注册，不表示摄像头已经连通。** 必须检查生产者协议、媒体轨道和接收字节数。

## 3. 账号层排查

实机对照结果：

- 摄像头所有者账号：go2rtc 可以列出 MJSXJ17CM；
- 米家共享账号：米家 App 可以看，但 go2rtc 无法查看。

因此接入顺序应为：

```text
先用所有者账号验证型号兼容性
→ 再处理账号隔离
```

不能把“米家 App 中能看共享设备”等同于“第三方接口能取得该设备的连接密钥”。

长期安全方案是让专用账号成为摄像头真正所有者，再分享回日常账号；在迁移所有权前，先使用现有所有者账号完成 Alpha 验证。

## 4. 网络层证据

摄像头 IP 可以 ping 通，但 ping 只能证明 ICMP 可达，不能证明 CS2 UDP 握手成功。

抓包命令：

```bash
sudo tcpdump -ni en0 -c 4 -XX "host <摄像头IP> and udp"
```

抓包明确看到：

```text
i9 → 摄像头:32108
payload: f1 30 00 00

摄像头 → i9 随机端口
payload: f1 41 00 14 ...
```

协议含义：

```text
0x30 = LAN search
0x41 = punch packet
```

这证明：

- 摄像头在线；
- 路由器没有阻断双向 UDP；
- 摄像头确实响应了 go2rtc；
- 超时发生在 Go/go2rtc 对返回包的接收或后续状态机，而不是普通网络不可达。

经验：当应用报 UDP timeout 时，必须同时看 tcpdump；**内核抓到包不代表目标进程的 Socket 已收到包。**

## 5. Python 与 Go 最小探针的关键对照

同一台 i9、同一个摄像头、同一个探测包：

Python UDP 探针成功：

```text
local=('0.0.0.0', <随机端口>)
remote=('<摄像头IP>', <随机端口>)
length=24
payload=f1410014...
```

最小 Go UDP 程序失败：

```text
read udp4 0.0.0.0:<随机端口>: i/o timeout
```

这个对照把范围从“小米协议或路由器”缩小到了：

```text
Go 二进制 / macOS 应用防火墙 / UDP Socket 行为
```

处理原则：

- 不使用 `go run` 的临时随机二进制做防火墙验证；
- 只使用安装器生成的固定 `Go2RTC.app`；
- 由安装器写入并验证固定 bundle identifier designated requirement；
- 将 app bundle（不是裸二进制）加入 macOS 应用防火墙允许列表；
- go2rtc 的 CS2 Socket 强制使用 `udp4`。

典型命令：

```bash
env -u GOROOT PATH="/usr/local/opt/go@1.24/bin:$PATH" \
  .venv-alpha/bin/python tools/go2rtc_build.py ensure

codesign --verify --deep --strict .local/Go2RTC.app
codesign -d -r- .local/Go2RTC.app

sudo /usr/libexec/ApplicationFirewall/socketfilterfw \
  --add "$PWD/.local/Go2RTC.app" || true

sudo /usr/libexec/ApplicationFirewall/socketfilterfw \
  --unblockapp "$PWD/.local/Go2RTC.app"
```

预期 requirement 是固定 identifier，不是 `cdhash`。不要手工重新签名裸
`.local/bin/go2rtc`，也不要为了排查而永久关闭整个系统防火墙。

## 6. CS2 两阶段握手定位

在 CS2 握手代码加入临时诊断后，第一阶段显示：

```text
b1=41 matched=true
accepted
```

说明摄像头的 punch 响应已经被程序接收。

随后摄像头不断返回：

```text
b1=42
```

但当 URL 强制设置：

```text
transport=tcp
```

程序输出：

```text
b1=42 matched=false
```

原因是：

- `0x42` 表示 UDP ready；
- `0x43` 表示 TCP ready；
- 强制 TCP 时，go2rtc 不接受摄像头返回的 `0x42`。

删除 URL 中的 `transport` 参数后，恢复自动模式：

```text
transport=auto
```

程序可以接受摄像头实际选择的 UDP 路径，随后成功获得视频关键帧。

经验：**`transport=tcp` 不是通用的“更稳定”选项。** 在 CS2 中，TCP/UDP 是摄像头握手协商结果；强制错误方向会直接阻断连接。

## 7. 版本对照结论

测试过：

```text
go2rtc v1.9.14：失败
go2rtc v1.9.13：失败
PR #2222：单独测试仍失败
PR #2222 + udp4 + 固定二进制防火墙放行 + transport auto：成功
```

因此不能把本次问题简单归为 v1.9.14 回归。

上游 PR #2222 修复了 CS2 地址解析和 IP 比较：

```go
addr.IP.Equal(c.addr.IP)
```

但本机还需要把：

```go
net.ListenUDP("udp", nil)
```

改为：

```go
net.ListenUDP("udp4", nil)
```

### 固定 Local Network 代码身份

macOS 的 Local Network 许可不能只依赖 app 目录名。默认 ad-hoc 签名的 designated
requirement 是 `cdhash`；二进制重建后哈希变化，系统可能把它视为新的网络身份并静默
丢弃 CS2 UDP。项目安装器因此使用固定 `Go2RTC.app`、固定 bundle identifier，并在
签名与验证时都要求：

```text
designated => identifier "com.babymonitor.go2rtc"
```

首次登记可通过 LaunchServices 启动 app，并在 macOS 提示时允许“本地网络”。此后
`ensure`、重建和 launchd 单组件重启必须保持相同 requirement。不要把裸二进制、临时
探针或每次变化的 `cdhash` 当成生产身份，也不要用放宽防火墙、修改摄像头 URI 或改为
公网暴露来绕过权限。

### 受监督的摄像头固定语音回复

摄像头回复默认关闭。先按以下顺序验证；不要跳过前后健康检查：

```bash
make alpha-source-check
make alpha-voice-listen-status
make alpha-go2rtc-info
make alpha-voice-camera-status
make alpha-voice-camera-probe
make alpha-source-check
make alpha-voice-listen-status
```

`alpha-voice-camera-probe` 是唯一会操作扬声器的入口。它要求成人在摄像头旁、要求
交互式 TTY，并只发送一秒生成音；它不录制家庭音频、不保留测试音，也不会自动启用
生产回复。听见测试音且确认来源后，终端必须精确输入 `YES`。不确定来源、重复播放或
任一后置健康检查失败都按失败处理。

启用还要求当前 go2rtc 提交、补丁和二进制完全匹配的有效本机验收标记，以及忽略的
`runtime/settings.yaml` 中 `voice_care.camera_reply_enabled: true`。设置后只运行：

```bash
make alpha-voice-listen-stop
make alpha-voice-listen-start
make alpha-voice-listen-status
make alpha-voice-camera-status
```

Voice 回滚时把该私有设置恢复为 `false`，再只停止和启动 Voice。不要为摄像头回复失败
重启整套 Alpha。若补丁版 go2rtc 本身导致 source 或入站音频失败，才使用现有的
`make alpha-go2rtc-rollback`，随后重新运行 source 与 Voice 健康检查。

## 8. Go 工具链附带问题

编译补丁版时曾出现：

```text
package crypto/fips140 is not in std
package crypto/mlkem is not in std
```

虽然 `go version` 显示 Go 1.24，实际 `GOROOT` 被旧配置污染：

```text
/usr/local/Cellar/go/1.13.4/libexec
/usr/local/go
```

来源包括：

```text
~/.bash_profile
Go 用户 GOENV 配置
```

经验：

- 不要手工固定 `GOROOT`；
- 只把目标 Go 的 `bin` 放到 PATH 前面；
- 不要把新版 Go 覆盖解压到旧 `/usr/local/go`；
- 编译异常时同时检查 `command -v go`、`go env GOROOT`、标准库目录。

健康状态应类似：

```text
command -v go
~/sdk/go1.24.13/bin/go

go env GOROOT
~/sdk/go1.24.13
```

## 9. 推荐的排查顺序

遇到“小米设备能添加但无画面”时，按以下顺序，不要直接调 Dashboard：

1. 确认使用设备所有者账号，不是共享账号；
2. 检查 `/api/streams` 中流名是否存在；
3. 检查生产者是否有 `protocol`、`medias`、`bytes_recv`；
4. 请求 `/api/frame.jpeg?src=source` 并检查 `Content-Length`；
5. 检查 go2rtc 日志是云认证错误、UDP timeout 还是媒体错误；
6. 使用 tcpdump 确认请求和摄像头回复；
7. 用 Python 与固定路径 Go 探针对照用户态 UDP 接收；
8. 检查 macOS 应用防火墙和固定二进制签名；
9. 查看 CS2 第二阶段返回的是 `0x42` 还是 `0x43`；
10. 只有 `source` 能稳定出图后，再排查 `live`、FFmpeg 和 Dashboard。

## 10. 安全与脱敏

不得提交或发送：

- 完整 `xiaomi://` URI；
- 小米账号 UID 和 Token；
- DID、MAC、家庭公网信息；
- `runtime/go2rtc.yaml`；
- 家庭监控画面；
- 包含密钥参数的 Xiaomi debug 日志。

可以安全分享：

- go2rtc 版本；
- `protocol`、`medias`、`bytes_recv`；
- 已脱敏错误类型；
- 抓包中的协议字节类型，例如 `f1 30`、`f1 41`、`f1 42`；
- JPEG 文件类型和字节数。

## 11. 后续工程化任务

当前成功依赖本地构建二进制，后续需要：

1. 固定上游源码提交和本地补丁；
2. 在安装器中自动构建或校验 Intel macOS 兼容二进制；
3. 安装时完成签名和防火墙提示；
4. 安装器不得覆盖有效的本地 Xiaomi Token；
5. 增加 `source` 实机健康检查；
6. go2rtc 更新时重新验证 CS2 UDP 行为；
7. 上游合并正式修复后，移除本地补丁并回归官方二进制。
