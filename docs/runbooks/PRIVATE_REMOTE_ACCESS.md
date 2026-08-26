# P4 私有远程访问操作手册

本流程只把经过 Dashboard Basic Auth 保护的页面发布到私有 tailnet HTTPS 443。
摄像头、go2rtc、SQLite、Ollama、Voice 和 Dashboard 的局域网 8080 均不直接发布。
P4 不改变 Guardian、Voice、米家或摄像头 microSD 录像。

## 1. 人工安装与策略准备

在 Intel i9 安装 **Official Tailscale Standalone** macOS 客户端，并在 Settings
中启用 **CLI integration**。两部家长 iPhone 安装官方客户端。登录、设备命名、
身份验证和管理后台操作必须由家长交互完成；仓库不接收登录凭据或复用密钥。

管理员以 `config/tailscale.grants.example.hujson` 为最小模板，把 `.invalid`
占位身份替换为私有后台中的实际家长身份。必须 **merge** 到现有策略，不能覆盖
无关规则。保存前先验证策略，并检查所有 **broader grant**；已有宽权限不会被
本例的窄规则自动收紧。i9 使用 `tag:baby-monitor`，该标签由管理员拥有。

不要把实际策略、身份、设备名、MagicDNS 名称、地址或私有 URL 写入 Git、Issue、
聊天或诊断输出。

## 2. 只读软件检查

先确认 Dashboard 本机健康、Basic Auth、Tailscale 登录、Serve/Funnel 冲突和
go2rtc 监听范围。以下命令不修改 Tailscale：

```bash
make alpha-remote-preflight
make alpha-remote-status
make alpha-remote-test
```

只分享 `remote_code` 和布尔字段，不分享原始 CLI JSON 或 URL。任何未知、超时、
未认证、Dashboard 不健康、非本机 go2rtc 监听、Funnel 或冲突都必须先单独解决。

## 3. 显式配置固定 Serve

确认管理后台策略已经验证且没有更宽规则后，在 i9 的交互终端运行：

```bash
make alpha-remote-configure
```

命令只接受 `/dev/tty` 中精确的大写 `YES`，并且只能应用仓库固定的 HTTPS 443 到
本机 Dashboard 路由。它不会安装或登录 Tailscale，不编辑 tailnet 策略，不接受
自定义端口、主机或目标。成功后再次只读检查：

```bash
make alpha-remote-status
```

`REMOTE_READY_SOFTWARE` 只证明 i9 本地软件边界成立，不代表手机实机已经通过。

## 4. 两部 iPhone 人工验收

每部 iPhone 分别关闭 Wi-Fi，连接 Tailscale，再通过私有 HTTPS 地址检查：错误或
缺失的 Dashboard Basic 凭据被拒绝；正确凭据能打开普通视频；一次 2x/3x HD
会话能够打开或按既有合同安全回退；直接访问 8080、1984、8554、8555 不可用。
关闭手机 Tailscale 后私有地址应不可用，同时米家、microSD 录像和 i9 本地 worker
不受影响。

验收记录只写聚合 PASS/FAIL，不记录截图、URL、地址、身份或凭据。两部手机都通过
后才能记录 `REMOTE_READY_DEVICE_GATE`。

## 5. 故障与回滚

配置或手机验收失败时先运行只读状态检查。不要重启整套 Alpha，也不要停止
Guardian、Voice、Dashboard 或 go2rtc。移除 P4 自有路由属于状态删除，必须先取得
**explicit approval** 并核对精确目标；本仓库故意不提供通用回滚 Make 目标。
不得使用全局重置、设备退出、公共发布或路由器端口映射作为修复手段。
