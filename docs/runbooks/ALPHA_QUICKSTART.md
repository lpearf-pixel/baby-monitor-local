# 基础可用 Alpha：Intel Mac 安装与使用

本 Alpha 让现有 MJSXJ17CM 摄像头和 Intel i9 Mac 先形成可日常试用的闭环：

- 小米摄像头继续向 256GB microSD 全天循环录像；
- Mac 通过 go2rtc 读取本地视频；
- 两位家长可通过密码保护网页查看实时画面和截图；
- 两台 Android 可通过 Tailscale 外网访问；
- 两台 Android 可订阅同一个 ntfy 主题并测试通知；
- go2rtc 和网页均只监听 Mac 本机地址，不开放路由器端口。

## 1. 获取 Alpha 分支

```bash
git clone -b codex/basic-usable-alpha \
  https://github.com/lpearf-pixel/baby-monitor-local.git
cd baby-monitor-local
chmod +x tools/*.sh
```

已有仓库时：

```bash
git fetch origin
git switch codex/basic-usable-alpha
git pull --ff-only
chmod +x tools/*.sh
```

## 2. 安装

```bash
./tools/install_alpha_macos.sh
```

安装器会：

1. 检查 Intel macOS；
2. 通过 Homebrew 准备 Python 3.11 和 FFmpeg；
3. 下载固定版本 go2rtc 1.9.14 Intel 二进制；
4. 创建 `.venv-alpha`；
5. 创建本地密码和随机 ntfy 主题；
6. 把所有私密运行文件放入被 Git 忽略的 `runtime/`。

查看本地账号、密码和 ntfy 主题：

```bash
cat runtime/alpha.env
```

不要把这个文件、终端截图或其中内容发到 GitHub。

## 3. 启动

```bash
./tools/start_alpha.sh
```

本机打开：

- 小米接入配置：`http://127.0.0.1:1984`
- 婴儿监控网页：`http://127.0.0.1:8080`

停止：

```bash
./tools/stop_alpha.sh
```

## 4. 接入小米摄像头

打开 `http://127.0.0.1:1984`：

1. 选择 **Add → Xiaomi**；
2. 登录米家账号；
3. 按提示完成短信、邮件验证码或验证码验证；
4. 选择 MJSXJ17CM 摄像头；
5. 将加入后的原始摄像头流名称设为 **`source`**；
6. 配置文件中预置的 **`live`** 会在有人观看时，把 `source` 按需转换为 `960×540 / 5 FPS` 的 MJPEG 预览；
7. 回到 `http://127.0.0.1:8080` 刷新状态。

小米账号信息由 go2rtc 保存在本机 `runtime/go2rtc.yaml`，该文件不会提交到 GitHub。

如果安装器运行后你手工改过 `runtime/go2rtc.yaml`，请确认其中仍有：

```yaml
streams:
  live: ffmpeg:source#video=mjpeg#width=960#height=540#fps=5
```

## 5. 两台 Android 接收通知

两台 Android 都安装 ntfy，并订阅 `runtime/alpha.env` 中的 `NTFY_TOPIC`。

然后在婴儿监控网页点击 **发送测试通知**。两台手机都应收到标题为 `Baby Monitor Local` 的高优先级通知。

公开 ntfy 服务依赖主题名保密，因此安装器生成较长的随机主题。后续可迁移到自建 ntfy 并配置 Token。

## 6. 外出安全查看

在 Mac 和两台 Android 上安装 Tailscale，并登录同一个 tailnet。Mac 执行：

```bash
tailscale serve --bg 8080
tailscale serve status
```

命令会显示一个仅 tailnet 成员可访问的 HTTPS 地址。两台 Android 使用该地址打开网页，再输入 `runtime/alpha.env` 中的网页账号和密码。

禁止执行：

```bash
tailscale funnel 8080
```

也不要在路由器上转发 `1984`、`8080`、`8554` 或 `8555`。

## 7. 录像

全天录像仍由摄像头内的 256GB microSD 负责，存满后覆盖最早内容。Alpha 网页不重复录制全天视频，因此不会长期占用 Mac 大量 CPU 和硬盘。

请在米家 App 中确认：

- microSD 已识别；
- 录像模式为全天录像；
- 能够正常回放；
- 存储满后启用循环覆盖。

## 8. 当前 Alpha 边界

当前已经可用：

- 密码保护的实时 MJPEG 画面；
- 当前截图；
- 摄像头流在线状态；
- ntfy 双手机测试通知；
- Tailscale 私有外网访问；
- 米家与 microSD 独立降级能力。

当前仍使用米家 App：

- 实时声音；
- 双向语音；
- 云台控制；
- microSD 历史回放。

后续迭代再接入：

- 温湿度表盘自动识别；
- 哭声、大声响和床区移动候选；
- 事件前后短片；
- 自动启动和进程看门狗；
- 微信辅助通知；
- 每日报告。

本系统只提供辅助查看和候选提醒，不是呼吸、心率、血氧、窒息或医疗监护设备。

## 9. 排障

查看日志：

```bash
tail -n 100 runtime/logs/go2rtc.log
tail -n 100 runtime/logs/api.log
```

查看进程：

```bash
cat runtime/pids/go2rtc.pid runtime/pids/api.pid
ps -p "$(cat runtime/pids/go2rtc.pid)" -o pid,etime,%cpu,%mem,command
ps -p "$(cat runtime/pids/api.pid)" -o pid,etime,%cpu,%mem,command
```

检查本地接口：

```bash
curl -fsS http://127.0.0.1:1984/api/streams
curl -fsS http://127.0.0.1:8080/healthz
```
