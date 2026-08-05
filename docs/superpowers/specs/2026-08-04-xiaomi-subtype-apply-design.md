# MJSXJ17CM 原生高清 Subtype 应用设计

## 状态与目标

Intel i9 实机安全探测已经确认 `subtype=3` 可通过 `cs2+udp` 提供
`2560×1440` 源画面。现有 `subtype=hd` 实际落到编号 `2`，只能得到
`864×480`，再由 FFmpeg 放大到 `1280×720`，因此需要一个独立、可回滚的
正式应用操作。

## 方案选择

采用事务式应用，而不是手工编辑配置或让探测命令自动采用推荐值：

1. 读取并验证现有 `runtime/go2rtc.yaml`；
2. 保留未知 Xiaomi 查询参数，将 `subtype` 精确设为 `3`，删除强制
   `transport=tcp` 以继续自动协商；
3. 以原文件字节和权限创建兼容现有回滚命令的 `go2rtc-quality-*` 备份；
4. 原子写入、重启 Alpha，并运行完整高清门禁；
5. 只有源尺寸至少为 `1920×1080`，且实时流、MJPEG 与 Dashboard 都通过时
   才保留新配置；
6. 健康检查失败、异常或中断时恢复原文件字节和权限并重启旧服务。

未采用的方案：手工编辑容易暴露 Xiaomi URI 或破坏未知参数；探测后自动采用
会把一次观察操作变成持久变更；只检查尺寸会漏掉连续 MJPEG 或 Dashboard
故障。

## 接口与输出

新增命令：

```bash
make alpha-subtype-apply
```

该 Make 目标固定使用本机已验证的编号 `3`。成功时只输出：

```text
result=PASS
applied_subtype=3
protocol=cs2+udp
bytes_received=<大于0>
source_dimensions=2560x1440
live_dimensions=1280x720
original_config_restored=false
```

门禁未通过时输出稳定结果码与 `original_config_restored=true`，返回非零状态。
不得输出 Xiaomi URI、Token、UID、DID、MAC、账号、私网地址、重启脚本日志或
家庭画面。

## 回滚与安全边界

成功应用后的备份继续由现有命令恢复：

```bash
make alpha-quality-rollback
```

本变更不修改 microSD 录像、FFmpeg 输出尺寸、Basic Auth、监听地址或外部访问
策略。go2rtc 继续仅监听 loopback；永不使用 Tailscale Funnel，永不配置
路由器端口转发。

## 验证

单元测试覆盖成功保留、低分辨率恢复、健康失败恢复、异常恢复、`Ctrl+C`
恢复、权限保持和参数保留。CLI 集成测试使用本地 HTTP 夹具验证输出脱敏、
退出码和真实配置副作用。完整仓库测试、Python 编译、Shell 语法与 GitHub CI
通过后，才允许在 i9 执行一次正式应用门禁。
