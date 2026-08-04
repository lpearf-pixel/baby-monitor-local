# MJSXJ17CM 原生高清 Subtype 应用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供一个将实测推荐编号 `3` 安全应用到 Xiaomi source、完整验收并在失败时自动恢复的命令。

**Architecture:** `packages/monitoring/subtype_probe.py` 增加事务应用核心，复用现有配置变换、原子写入和高清健康检查。`tools/alpha_quality.py` 只负责参数、重启适配和脱敏输出；Make 固定 MJSXJ17CM 的实测编号与最低原生高清门槛。

**Tech Stack:** Python 3.11+、PyYAML、pytest、GNU/BSD Make、FastAPI/go2rtc 本地健康端点。

## Global Constraints

- PR #4 必须保持 Draft，直到 Intel i9 原生高清与持续运行门禁通过。
- 不提交或输出 Xiaomi URI、Token、UID、DID、MAC、私网地址或家庭画面。
- go2rtc 保持 loopback-only；禁止 Tailscale Funnel 和路由器端口转发。
- 不修改 microSD 录像、`live` 的 `1280×720@10 FPS` 配置或脚本权限。
- 所有实现遵循 RED → GREEN，失败、异常和中断都必须恢复原配置。

---

### Task 1: 事务式 subtype 应用核心

**Files:**
- Modify: `packages/monitoring/subtype_probe.py`
- Modify: `tests/monitoring/test_subtype_probe.py`

**Interfaces:**
- Consumes: `with_source_subtype(...)`, `_atomic_write(...)`, `HealthResult`
- Produces: `apply_subtype(config_path, backups_dir, subtype, minimum_dimensions, restart, health_check, now) -> ApplySummary`

- [x] **Step 1: 写成功与恢复路径的失败测试**

测试必须以字面 fixture 断言：`3` 成功且 `2560×1440` 时保留新配置；
`864×480`、非 `PASS`、健康检查异常或 `KeyboardInterrupt` 时恢复原始字节、
`0600` 权限并再次重启。

- [x] **Step 2: 运行 RED**

Run: `pytest -q tests/monitoring/test_subtype_probe.py`

Expected: collection fails because `apply_subtype`/`ApplySummary` do not exist.

- [x] **Step 3: 写最小事务实现**

实现只在完整门禁为 `PASS` 且源尺寸达到最低门槛时提交变更；其他路径统一从
原始字节恢复。备份使用 `go2rtc-quality-YYYYmmdd-HHMMSS.yaml`，以便现有
`rollback_latest` 发现。

- [x] **Step 4: 运行 GREEN 与恢复突变检查**

Run: `pytest -q tests/monitoring/test_subtype_probe.py`

Expected: all tests pass；删除恢复分支或尺寸门槛会让对应测试失败。

### Task 2: CLI、Make 与脱敏输出

**Files:**
- Modify: `tools/alpha_quality.py`
- Modify: `Makefile`
- Modify: `tests/monitoring/test_alpha_quality_cli.py`
- Modify: `tests/deploy/test_alpha_commands.py`

**Interfaces:**
- Produces: `tools/alpha_quality.py apply-subtype ... --subtype 3 --minimum-width 1920 --minimum-height 1080`
- Produces: `make alpha-subtype-apply`

- [x] **Step 1: 写 CLI/Make 的失败测试**

本地 HTTP 夹具必须验证成功持久化与低分辨率自动恢复；重启命令即使打印敏感
样例也不能污染 stdout/stderr。Make 干运行必须展示固定 `3` 和门槛，且不得
实际启动服务。

- [x] **Step 2: 运行 RED**

Run: `pytest -q tests/monitoring/test_alpha_quality_cli.py tests/deploy/test_alpha_commands.py`

Expected: failures because `apply-subtype` and `alpha-subtype-apply` are absent.

- [x] **Step 3: 写最小 CLI/Make 实现**

CLI 调用事务核心，输出 `result/applied_subtype/protocol/bytes_received/source_dimensions/live_dimensions/original_config_restored`，成功返回 `0`，恢复后的门禁失败返回 `2`。

- [x] **Step 4: 运行 GREEN**

Run: `pytest -q tests/monitoring/test_alpha_quality_cli.py tests/deploy/test_alpha_commands.py`

Expected: all tests pass and combined output contains no fixture secrets or private address.

### Task 3: 文档、全量门禁与发布

**Files:**
- Modify: `README.md`
- Modify: `docs/runbooks/ALPHA_QUICKSTART.md`
- Modify: `docs/superpowers/plans/2026-08-04-xiaomi-subtype-apply.md`

**Interfaces:**
- Produces: 可复制的 i9 更新、应用、信息与回滚命令

- [x] **Step 1: 更新操作文档**

记录探测结果 `3 → 2560×1440`、正式应用命令、预期脱敏输出和现有回滚命令；
明确 `4/5` 未被选择以及安全网络边界不变。

- [ ] **Step 2: 运行完整验证**

Run:

```bash
pytest -q
python -m compileall -q apps packages services tools
bash -n tools/*.sh
make -n alpha-subtype-apply
```

Expected: every command exits `0` and no command starts real services.

- [ ] **Step 3: 原子更新现有 Draft 分支**

重新读取 PR #4 HEAD；基于当前 HEAD 创建单一提交 `Apply verified Xiaomi native HD subtype`，只做 fast-forward 更新。PR 必须继续 `draft=true`。

- [ ] **Step 4: 等待 GitHub CI**

Expected: fresh workflow for the new HEAD finishes `SUCCESS` before any i9 command is issued.

- [ ] **Step 5: 执行 i9 实机门禁**

```bash
cd ~/dev/baby-monitor-local
make alpha-update
make alpha-subtype-apply
make alpha-quality-info
```

Expected: `source_dimensions=2560x1440`、`live_dimensions=1280x720`、`source_quality=3`，网页连续画面正常。
