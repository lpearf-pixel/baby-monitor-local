# Intel macOS go2rtc 可重复构建设计

日期：2026-08-04  
关联：PR #4、Issue #7、`docs/runbooks/XIAOMI_CS2_MACOS_TROUBLESHOOTING.md`

## 1. 目标

把已在 Intel i9 Mac 和小米智能摄像机 2 云台版（MJSXJ17CM）上验证成功的 go2rtc 兼容方案固化到 Alpha 安装流程，使新机器执行：

```bash
make alpha-install
make alpha-start
```

即可得到可审计、可回滚、不会覆盖本地 Xiaomi 凭据的 go2rtc 运行环境。

本设计不把编译后二进制提交到 Git，也不把真实 Xiaomi 账号、Token、完整 `xiaomi://` URI、DID、MAC、局域网详情或家庭画面写入仓库、日志或 CI artifact。

## 2. 已验证基线

已验证组合：

```text
上游 go2rtc commit：b465651a94c1f637d566a8c660b4fad102b35153
上游来源：PR #2222
本地补丁：net.ListenUDP("udp", nil) → net.ListenUDP("udp4", nil)
Xiaomi transport：auto，不强制 transport=tcp
实际协议：cs2+udp
平台：darwin/amd64
```

实机门禁样本：

```text
JPEG：864×480
文件大小：19479 字节
```

PR #2222 单独不足以解决本机问题；当前以“固定 commit + udp4 补丁 + 固定路径签名/防火墙允许 + transport auto”作为整体受控组合。

## 3. 安装流程

`tools/install_alpha_macos.sh` 负责：

1. 验证平台为 Intel macOS；
2. 安装或检测 Python 3.11、FFmpeg；
3. 检测 Go 工具链；
4. 从固定 commit 获取 go2rtc 源码；
5. 校验实际 checkout SHA；
6. 校验并应用仓库内审计补丁；
7. 使用检测到的 Go 绝对路径本机编译；
8. 验证二进制架构、版本和补丁特征；
9. 计算并记录二进制 SHA256；
10. 备份当前 `.local/bin/go2rtc`；
11. 原子安装新二进制；
12. 执行 ad-hoc codesign；
13. 检查 macOS 应用防火墙，并尝试允许固定二进制路径；
14. 保留现有 `runtime/go2rtc.yaml` 与 `runtime/alpha.env`。

源码构建目录放在可清理的本地工作区，不进入 Git。失败时不得覆盖当前可用二进制。

## 4. Go 工具链策略

安装器优先使用 `command -v go` 返回的实际二进制，并要求版本至少为 Go 1.24。

验证项：

- `go version` 满足最低版本；
- `go env GOROOT` 目录存在；
- 标准库中存在构建所需目录；
- 当前 `GOROOT` 与实际 Go 二进制一致。

安装器不写入、不导出 `GOROOT`，也不自动修改用户的 `.zprofile`、`.bash_profile` 或 Go 用户环境文件。发现陈旧 `GOROOT` 时立即停止，并输出明确修复说明。

未安装或版本不足时，通过 Homebrew 安装或升级 Go；随后重新解析 Go 绝对路径并再次验证。

构建命令显式调用已验证的 Go 路径，避免 PATH 中旧版本污染。

## 5. 补丁管理

仓库新增可审计 patch 文件，内容只包含当前实机验证所需的 `udp4` 修改。

安装器保存并校验：

- 上游 commit SHA；
- patch 文件 SHA256；
- 补丁应用前的目标代码片段；
- 补丁应用后的目标代码片段。

若上游源码已变化、补丁无法干净应用或预期代码片段不存在，安装器必须失败，不得尝试模糊匹配或继续构建。

上游正式合并等效修复后，通过单独实机回归决定是否移除本地 patch。

## 6. 配置保护

安装、重建和回滚不得覆盖：

```text
runtime/go2rtc.yaml
runtime/alpha.env
runtime/logs/
runtime/pids/
```

脚本只读取必要的结构信息，不打印敏感值。

对 `source` 的检查只输出：

- 是否存在；
- 是否包含 `transport=tcp`；
- 是否能产生媒体轨道；
- 是否能生成非零 JPEG。

检测到 MJSXJ17CM 的 `source` 强制 `transport=tcp` 时，不静默修改配置；启动前健康检查返回明确错误并提示改回自动协商。

## 7. 二进制安装与回滚

新二进制先写入临时路径并完成全部验证，再原子替换 `.local/bin/go2rtc`。

现有二进制备份到：

```text
runtime/backups/go2rtc/<时间戳>-<版本>-<sha256>/go2rtc
```

同时记录元数据：

```text
upstream_commit
go_version
patch_sha256
binary_sha256
build_time
platform
```

新增命令：

```text
make alpha-go2rtc-info
make alpha-go2rtc-rebuild
make alpha-go2rtc-rollback
make alpha-source-check
```

`alpha-go2rtc-rollback` 恢复最近一个有效备份，恢复前先备份当前二进制，且不触碰运行配置。

## 8. macOS 签名与防火墙

安装后执行：

```bash
codesign --force --sign - .local/bin/go2rtc
```

应用防火墙策略：

- 只允许固定路径 `.local/bin/go2rtc`；
- 不关闭全局防火墙；
- 无 sudo 权限时保留已构建二进制，并输出一条明确的手工允许命令；
- 不把临时 `go run` 产物加入规则；
- 重新构建后因文件内容变化再次签名，并验证规则状态。

## 9. `source` 健康检查

`make alpha-source-check` 必须验证：

1. go2rtc API 可访问；
2. `source` 已配置；
3. producer 的 `protocol` 非空；
4. `medias` 中存在视频轨道；
5. `bytes_recv > 0`；
6. `/api/frame.jpeg?src=source` 返回非零内容；
7. 输出文件可识别为 JPEG。

结果分类：

```text
PASS
CONFIGURED_ONLY
TOKEN_OR_CLOUD_AUTH_FAILED
CS2_HANDSHAKE_TIMEOUT
NO_VIDEO_MEDIA
NO_BYTES_RECEIVED
EMPTY_SNAPSHOT
INVALID_SNAPSHOT
```

输出不得包含完整生产者 URL、UID、Token、DID 或局域网地址。

## 10. 测试策略

### 10.1 静态与单元测试

验证：

- 固定 commit 不可漂移；
- patch SHA 不可漂移；
- patch 只能命中预期代码；
- 安装器不会覆盖 runtime 配置；
- 旧二进制能够备份和恢复；
- 强制 TCP 能被识别；
- 健康检查能够脱敏分类。

### 10.2 构建测试

CI 至少执行：

- shell 语法检查；
- patch 可应用性检查；
- Go 构建入口检查；
- 生成元数据格式检查；
- 不包含真实凭据的安全扫描。

CI 不要求访问真实摄像头。

### 10.3 实机门禁

Intel i9 Mac 执行：

```bash
make alpha-go2rtc-rebuild
make alpha-restart
make alpha-source-check
```

通过标准：

- `source` 实际协议为 `cs2+udp`；
- 存在视频媒体轨道；
- 接收字节数大于零；
- JPEG 非零且有效；
- Dashboard 能显示画面；
- 重启后自动恢复。

## 11. 错误处理

任何失败都应保持上一版可用二进制：

- Go 环境错误：构建前停止；
- checkout SHA 不符：停止；
- patch 不匹配：停止；
- 编译失败：停止；
- 签名失败：不安装；
- 防火墙规则失败：保留已签名安装结果并提示手工处理；
- 实机健康检查失败：不自动回滚，明确报告原因，由 `alpha-go2rtc-rollback` 执行显式回滚。

## 12. 发布边界

本轮完成后：

- PR #4 继续保持 Draft；
- Issue #7 在安装器、回滚、健康检查和实机门禁全部完成后关闭；
- 不提交编译后二进制；
- 不宣称适用于全部 macOS 或全部小米摄像头；
- 明确标记为 MJSXJ17CM + Intel macOS 实机验证方案；
- 完成兼容层后继续 Alpha 原有功能：稳定实时画面、状态、截图、通知，以及后续安全外部访问。