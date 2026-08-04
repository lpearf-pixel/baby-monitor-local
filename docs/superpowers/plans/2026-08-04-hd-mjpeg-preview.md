# Alpha HD MJPEG Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing Alpha preview to Xiaomi HD input and a stable 1280×720 MJPEG stream at 10 FPS, with safe backup, rollback, non-sensitive status output, and real-device health checks.

**Architecture:** Put all YAML and Xiaomi URL manipulation in a focused Python module, expose a small command-line wrapper for apply/info/rollback/check, and connect it to stable Make targets. Existing runtime credentials stay in `runtime/go2rtc.yaml`; commands only emit derived non-sensitive state and write through an atomic temporary file after creating a timestamped backup.

**Tech Stack:** Python 3.11, PyYAML 6, standard-library `urllib`, `urllib.request`, `pathlib`, `argparse`, pytest, Bash/Make, go2rtc HTTP API, FFmpeg-backed MJPEG.

## Global Constraints

- Target platform remains Intel macOS (`darwin/amd64`) with MJSXJ17CM real-device validation.
- `source` must use `subtype=hd` and automatic transport negotiation; `transport=tcp` must be removed.
- `live` must be exactly `ffmpeg:source#video=mjpeg#width=1280#height=720#raw=-r 10`.
- Never print or commit a complete `xiaomi://` URI, Xiaomi token, UID, DID, MAC, local IP, or family image.
- Existing `runtime/go2rtc.yaml` and `runtime/alpha.env` must never be overwritten by installation or repository update.
- Quality upgrade backups live under `runtime/backups/` and remain ignored by Git.
- PR #4 remains Draft; this plan does not merge PR #3 or PR #4.

---

## File Structure

- Create `packages/monitoring/alpha_quality.py`: pure config transforms, safe inspection, atomic write, backup selection, JPEG dimension parser, and go2rtc health evaluation.
- Create `tools/alpha_quality.py`: CLI subcommands `apply-hd`, `info`, `rollback`, and `check`.
- Create `tests/monitoring/test_alpha_quality.py`: unit tests for URL preservation, idempotence, secrecy, backups, rollback, JPEG parsing, and health classifications.
- Modify `Makefile`: expose `alpha-quality-hd`, `alpha-quality-info`, `alpha-quality-rollback`, and `alpha-source-check`.
- Modify `config/go2rtc.alpha.yaml`: new-install default `live` profile becomes 1280×720 at 10 FPS.
- Modify `tools/install_alpha_macos.sh`: installation copy and user-facing text describe 1280×720 / 10 FPS without touching existing runtime config.
- Modify `docs/runbooks/ALPHA_QUICKSTART.md`: document upgrade, inspection, rollback, and verification commands.
- Modify `tests/deploy/test_alpha_commands.py`: static command and template contract checks.

---

### Task 1: Pure HD Configuration Transform

**Files:**
- Create: `packages/monitoring/__init__.py`
- Create: `packages/monitoring/alpha_quality.py`
- Test: `tests/monitoring/test_alpha_quality.py`

**Interfaces:**
- Produces: `LIVE_HD = "ffmpeg:source#video=mjpeg#width=1280#height=720#raw=-r 10"`
- Produces: `QualityInfo(source_quality: str, transport: str, live_width: int, live_height: int, live_fps: int)`
- Produces: `upgrade_to_hd(config: dict[str, object]) -> dict[str, object]`
- Produces: `inspect_quality(config: dict[str, object]) -> QualityInfo`
- Consumes: standard Python mappings and Xiaomi stream URL strings only.

- [ ] **Step 1: Write failing transform tests**

```python
from copy import deepcopy

from packages.monitoring.alpha_quality import LIVE_HD, inspect_quality, upgrade_to_hd


def test_upgrade_to_hd_preserves_unknown_xiaomi_parameters() -> None:
    original = {
        "xiaomi": {"123": "V1:secret"},
        "streams": {
            "source": (
                "xiaomi://123:cn@192.0.2.10?did=456&model=example.camera"
                "&subtype=sd&transport=tcp&channel=1&vendor_hint=keep"
            ),
            "live": "ffmpeg:source#video=mjpeg#width=960#height=540#fps=5",
        },
    }

    upgraded = upgrade_to_hd(deepcopy(original))
    source = upgraded["streams"]["source"]

    assert "subtype=hd" in source
    assert "transport=" not in source
    assert "channel=1" in source
    assert "vendor_hint=keep" in source
    assert upgraded["streams"]["live"] == LIVE_HD
    assert upgraded["xiaomi"] == original["xiaomi"]


def test_upgrade_is_idempotent() -> None:
    config = {
        "streams": {
            "source": "xiaomi://123:cn@192.0.2.10?did=456&model=example.camera",
            "live": LIVE_HD,
        }
    }

    assert upgrade_to_hd(upgrade_to_hd(deepcopy(config))) == upgrade_to_hd(
        deepcopy(config)
    )


def test_inspect_quality_returns_only_derived_values() -> None:
    config = upgrade_to_hd(
        {
            "streams": {
                "source": "xiaomi://123:cn@192.0.2.10?did=456&model=example.camera",
                "live": "old",
            }
        }
    )

    info = inspect_quality(config)

    assert info.source_quality == "hd"
    assert info.transport == "auto"
    assert (info.live_width, info.live_height, info.live_fps) == (1280, 720, 10)
    assert "192.0.2.10" not in repr(info)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest tests/monitoring/test_alpha_quality.py -v
```

Expected: collection fails because `packages.monitoring.alpha_quality` does not exist.

- [ ] **Step 3: Implement minimal pure transform**

```python
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

LIVE_HD = "ffmpeg:source#video=mjpeg#width=1280#height=720#raw=-r 10"


class QualityConfigError(ValueError):
    pass


@dataclass(frozen=True)
class QualityInfo:
    source_quality: str
    transport: str
    live_width: int
    live_height: int
    live_fps: int


def _streams(config: dict[str, Any]) -> dict[str, Any]:
    streams = config.get("streams")
    if not isinstance(streams, dict):
        raise QualityConfigError("SOURCE_NOT_CONFIGURED")
    return streams


def upgrade_to_hd(config: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(config)
    streams = _streams(result)
    source = streams.get("source")
    if not isinstance(source, str) or not source.startswith("xiaomi://"):
        raise QualityConfigError("SOURCE_NOT_CONFIGURED")

    parsed = urlsplit(source)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in {"subtype", "transport"}
    ]
    query.append(("subtype", "hd"))
    streams["source"] = urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )
    streams["live"] = LIVE_HD
    return result


def inspect_quality(config: dict[str, Any]) -> QualityInfo:
    streams = _streams(config)
    source = streams.get("source")
    live = streams.get("live")
    if not isinstance(source, str) or not isinstance(live, str):
        raise QualityConfigError("SOURCE_NOT_CONFIGURED")

    source_query = dict(parse_qsl(urlsplit(source).query, keep_blank_values=True))
    return QualityInfo(
        source_quality=source_query.get("subtype", "default"),
        transport=source_query.get("transport", "auto"),
        live_width=1280 if "#width=1280" in live else 0,
        live_height=720 if "#height=720" in live else 0,
        live_fps=10 if "#raw=-r 10" in live else 0,
    )
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
pytest tests/monitoring/test_alpha_quality.py -v
```

Expected: all transform tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/monitoring tests/monitoring/test_alpha_quality.py
git commit -m "feat: add safe HD quality transform"
```

---

### Task 2: Atomic Apply, Backup, Info, and Rollback CLI

**Files:**
- Modify: `packages/monitoring/alpha_quality.py`
- Create: `tools/alpha_quality.py`
- Modify: `tests/monitoring/test_alpha_quality.py`

**Interfaces:**
- Produces: `apply_hd(config_path: Path, backups_dir: Path, now: datetime) -> Path`
- Produces: `rollback_latest(config_path: Path, backups_dir: Path) -> Path`
- Produces CLI exit code `0` on success and `2` on `QualityConfigError`.
- Consumes: `upgrade_to_hd()` and `inspect_quality()` from Task 1.

- [ ] **Step 1: Write failing backup and secrecy tests**

```python
from datetime import datetime, timezone
from pathlib import Path

import yaml

from packages.monitoring.alpha_quality import apply_hd, rollback_latest


def test_apply_hd_creates_backup_and_preserves_file_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "go2rtc.yaml"
    backups = tmp_path / "backups"
    original = {
        "xiaomi": {"123": "V1:do-not-print"},
        "streams": {
            "source": "xiaomi://123:cn@192.0.2.10?did=456&model=example.camera",
            "live": "old",
        },
    }
    config_path.write_text(yaml.safe_dump(original), encoding="utf-8")
    config_path.chmod(0o600)

    backup = apply_hd(
        config_path,
        backups,
        datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc),
    )

    assert backup.exists()
    assert yaml.safe_load(backup.read_text(encoding="utf-8")) == original
    assert config_path.stat().st_mode & 0o777 == 0o600


def test_rollback_restores_latest_quality_backup(tmp_path: Path) -> None:
    config_path = tmp_path / "go2rtc.yaml"
    backups = tmp_path / "backups"
    backups.mkdir()
    older = backups / "go2rtc-quality-20260804-120000.yaml"
    latest = backups / "go2rtc-quality-20260804-130000.yaml"
    older.write_text("streams: {live: older}\n", encoding="utf-8")
    latest.write_text("streams: {live: latest}\n", encoding="utf-8")
    config_path.write_text("streams: {live: current}\n", encoding="utf-8")

    restored = rollback_latest(config_path, backups)

    assert restored == latest
    assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["streams"]["live"] == "latest"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest tests/monitoring/test_alpha_quality.py -v
```

Expected: import failures for `apply_hd` and `rollback_latest`.

- [ ] **Step 3: Implement atomic file operations**

Implementation requirements:

```python
def apply_hd(config_path: Path, backups_dir: Path, now: datetime) -> Path:
    if not config_path.is_file():
        raise QualityConfigError("SOURCE_NOT_CONFIGURED")
    original_text = config_path.read_text(encoding="utf-8")
    original = yaml.safe_load(original_text) or {}
    updated = upgrade_to_hd(original)
    backups_dir.mkdir(parents=True, exist_ok=True)
    backup = backups_dir / f"go2rtc-quality-{now.strftime('%Y%m%d-%H%M%S')}.yaml"
    backup.write_text(original_text, encoding="utf-8")
    mode = stat.S_IMODE(config_path.stat().st_mode)
    temporary = config_path.with_suffix(".yaml.tmp")
    temporary.write_text(
        yaml.safe_dump(updated, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    temporary.chmod(mode)
    yaml.safe_load(temporary.read_text(encoding="utf-8"))
    temporary.replace(config_path)
    return backup
```

`rollback_latest()` must sort only `go2rtc-quality-*.yaml`, restore through a temporary file, preserve mode, and raise `NO_QUALITY_BACKUP` when none exists.

- [ ] **Step 4: Implement CLI without secret output**

`tools/alpha_quality.py` must:

```python
parser.add_subparsers(dest="command", required=True)
# apply-hd --config runtime/go2rtc.yaml --backups runtime/backups
# info --config runtime/go2rtc.yaml
# rollback --config runtime/go2rtc.yaml --backups runtime/backups
# check --base-url http://127.0.0.1:1984 --dashboard-url http://127.0.0.1:8080
```

`info` output must be exactly derived fields:

```text
source_quality=hd
transport=auto
live_width=1280
live_height=720
live_fps=10
```

Do not catch exceptions by printing the original URL or YAML object.

- [ ] **Step 5: Run unit tests and CLI smoke tests**

Run:

```bash
pytest tests/monitoring/test_alpha_quality.py -v
python tools/alpha_quality.py --help
```

Expected: tests pass and help lists all four subcommands.

- [ ] **Step 6: Commit**

```bash
git add packages/monitoring/alpha_quality.py tools/alpha_quality.py tests/monitoring/test_alpha_quality.py
git commit -m "feat: add HD quality apply and rollback commands"
```

---

### Task 3: Real Media Health Classification

**Files:**
- Modify: `packages/monitoring/alpha_quality.py`
- Modify: `tools/alpha_quality.py`
- Modify: `tests/monitoring/test_alpha_quality.py`

**Interfaces:**
- Produces: `HealthResult(code: str, protocol: str, bytes_received: int, source_dimensions: tuple[int, int] | None, live_dimensions: tuple[int, int] | None)`
- Produces: `check_hd_health(base_url: str, dashboard_url: str, opener: Callable[..., ContextManager[HTTPResponse]]) -> HealthResult`
- Produces: `jpeg_dimensions(payload: bytes) -> tuple[int, int]`.

- [ ] **Step 1: Write failing JPEG and health tests**

```python
from io import BytesIO


def jpeg_1280x720() -> bytes:
    return bytes.fromhex("FFD8FFC000110802D0050003011100021100031100FFD9")


def test_jpeg_dimensions_reads_sof0() -> None:
    assert jpeg_dimensions(jpeg_1280x720()) == (1280, 720)


def test_health_rejects_configured_only_source(fake_http) -> None:
    fake_http.json("/api/streams", {"source": {"producers": [{"url": "redacted"}]}})

    result = check_hd_health(
        "http://127.0.0.1:1984",
        "http://127.0.0.1:8080",
        fake_http.open,
    )

    assert result.code == "SOURCE_OFFLINE"
    assert "redacted" not in repr(result)


def test_health_accepts_real_hd_media(fake_http) -> None:
    fake_http.json(
        "/api/streams",
        {
            "source": {
                "producers": [
                    {
                        "protocol": "cs2+udp",
                        "medias": ["video, recvonly, H265"],
                        "bytes_recv": 50000,
                    }
                ]
            }
        },
    )
    fake_http.bytes("/api/frame.jpeg?src=source", jpeg_1280x720())
    fake_http.bytes("/api/frame.jpeg?src=live", jpeg_1280x720())
    fake_http.bytes("/api/stream.mjpeg?src=live", b"--frame\r\nJPEG")
    fake_http.json("/healthz", {"status": "ok"})

    result = check_hd_health(
        "http://127.0.0.1:1984",
        "http://127.0.0.1:8080",
        fake_http.open,
    )

    assert result.code == "PASS"
    assert result.protocol == "cs2+udp"
    assert result.live_dimensions == (1280, 720)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest tests/monitoring/test_alpha_quality.py -v
```

Expected: missing health interfaces.

- [ ] **Step 3: Implement health checker**

Required evaluation order:

1. Missing `source` → `SOURCE_NOT_CONFIGURED`.
2. No producer with non-empty protocol → `SOURCE_OFFLINE`.
3. No producer media containing `video` → `SOURCE_NO_VIDEO`.
4. Sum of producer `bytes_recv`/`bytes_received` not positive → `SOURCE_OFFLINE`.
5. Empty or invalid source JPEG → `SOURCE_OFFLINE`.
6. Empty live JPEG → `LIVE_EMPTY_FRAME`.
7. Live JPEG not 1280×720 → `LIVE_WRONG_DIMENSIONS`.
8. MJPEG sample empty → `LIVE_MJPEG_EMPTY`.
9. Dashboard health not `{"status":"ok"}` → `DASHBOARD_OFFLINE`.
10. Otherwise → `PASS`.

Only keep protocol, aggregate byte count, and image dimensions in `HealthResult`; discard producer URL and all Xiaomi identifiers immediately.

- [ ] **Step 4: Add CLI check output**

Successful output:

```text
result=PASS
protocol=cs2+udp
bytes_received=50000
source_dimensions=1280x720
live_dimensions=1280x720
```

Failure output must include `result=<CODE>` and exit code `2` without secrets.

- [ ] **Step 5: Run focused tests**

```bash
pytest tests/monitoring/test_alpha_quality.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add packages/monitoring/alpha_quality.py tools/alpha_quality.py tests/monitoring/test_alpha_quality.py
git commit -m "feat: verify HD source and MJPEG health"
```

---

### Task 4: Stable Make Commands and New-Install Defaults

**Files:**
- Modify: `Makefile`
- Modify: `config/go2rtc.alpha.yaml`
- Modify: `tools/install_alpha_macos.sh`
- Modify: `tests/deploy/test_alpha_commands.py`

**Interfaces:**
- Consumes CLI from Tasks 2–3.
- Produces user commands `make alpha-quality-hd`, `make alpha-quality-info`, `make alpha-quality-rollback`, `make alpha-source-check`.

- [ ] **Step 1: Write failing static command tests**

```python
def test_makefile_exposes_quality_commands() -> None:
    content = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "alpha-quality-hd:" in content
    assert "alpha-quality-info:" in content
    assert "alpha-quality-rollback:" in content
    assert "alpha-source-check:" in content
    assert "python tools/alpha_quality.py apply-hd" in content


def test_default_live_profile_is_hd_ten_fps() -> None:
    content = (ROOT / "config/go2rtc.alpha.yaml").read_text(encoding="utf-8")
    assert "#width=1280#height=720#raw=-r 10" in content
    assert "#fps=5" not in content
```

- [ ] **Step 2: Run tests and verify RED**

```bash
pytest tests/deploy/test_alpha_commands.py -v
```

Expected: quality command and default profile assertions fail.

- [ ] **Step 3: Add Make targets**

```make
alpha-quality-hd:
	@$(PYTHON) tools/alpha_quality.py apply-hd --config runtime/go2rtc.yaml --backups runtime/backups
	@$(MAKE) alpha-restart
	@$(MAKE) alpha-source-check

alpha-quality-info:
	@$(PYTHON) tools/alpha_quality.py info --config runtime/go2rtc.yaml

alpha-quality-rollback:
	@$(PYTHON) tools/alpha_quality.py rollback --config runtime/go2rtc.yaml --backups runtime/backups
	@$(MAKE) alpha-restart

alpha-source-check:
	@$(PYTHON) tools/alpha_quality.py check --base-url http://127.0.0.1:1984 --dashboard-url http://127.0.0.1:$${BABY_MONITOR_PORT:-8080}
```

Define `PYTHON := ./.venv-alpha/bin/python` once near the top and include the new targets in `.PHONY` and `help`.

- [ ] **Step 4: Update template and installer text**

Use exactly:

```yaml
live: ffmpeg:source#video=mjpeg#width=1280#height=720#raw=-r 10
```

Installer text must say `1280x720 MJPEG at 10 FPS` and must retain the existing guard that copies the template only when `runtime/go2rtc.yaml` does not exist.

- [ ] **Step 5: Run static tests and shell syntax checks**

```bash
pytest tests/deploy/test_alpha_commands.py -v
bash -n tools/*.sh
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add Makefile config/go2rtc.alpha.yaml tools/install_alpha_macos.sh tests/deploy/test_alpha_commands.py
git commit -m "feat: expose stable HD preview commands"
```

---

### Task 5: Runbook and Full Verification

**Files:**
- Modify: `docs/runbooks/ALPHA_QUICKSTART.md`
- Modify: `README.md`
- Modify: PR #4 description after fresh CI and real-device evidence.

**Interfaces:**
- Consumes all commands delivered by Tasks 1–4.
- Produces repeatable user upgrade and rollback instructions.

- [ ] **Step 1: Update runbook commands**

Document:

```bash
make alpha-update
make alpha-quality-hd
make alpha-quality-info
make alpha-source-check
```

Rollback:

```bash
make alpha-quality-rollback
```

State explicitly that HD preview is 1280×720 / 10 FPS MJPEG, not 20–25 FPS low-latency WebRTC, and that `transport=tcp` must not be reintroduced.

- [ ] **Step 2: Run complete local test suite**

```bash
python -m pip install -e ".[dev]"
pytest -v
python -m json.tool config/settings.schema.json >/dev/null
python -m compileall -q apps packages services tools
bash -n tools/*.sh
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 3: Push branch and verify GitHub Actions**

```bash
git push origin codex/basic-usable-alpha
```

Expected: PR #4 CI completes successfully; keep PR Draft.

- [ ] **Step 4: Perform Intel i9 real-device gate**

On the i9 Mac after pulling the branch:

```bash
make alpha-quality-hd
make alpha-quality-info
make alpha-source-check
```

Expected safe output:

```text
source_quality=hd
transport=auto
live_width=1280
live_height=720
live_fps=10
result=PASS
protocol=cs2+udp
live_dimensions=1280x720
```

Then open `http://192.168.2.141:8080`, confirm visibly smoother preview, and observe CPU/memory for at least ten minutes. Do not upload screenshots containing family video.

- [ ] **Step 5: Update PR #4 without merging**

Replace the stale `960×540 / 5 FPS` statement with `1280×720 / 10 FPS`, add the CI SHA and real-device result, and keep the PR Draft until the wider Alpha acceptance gates are complete.

- [ ] **Step 6: Commit documentation**

```bash
git add README.md docs/runbooks/ALPHA_QUICKSTART.md
git commit -m "docs: document HD Alpha preview workflow"
git push origin codex/basic-usable-alpha
```

---

## Plan Self-Review

- Spec coverage: source HD, transport auto, 1280×720 / 10 FPS live stream, backup, atomic write, rollback, safe info, health classification, template, Make commands, docs, CI, and i9 gate are all assigned to tasks.
- Placeholder scan: no TBD, TODO, “similar to”, or unspecified error-handling steps remain.
- Interface consistency: Task 1 defines the transforms used by Task 2; Task 2 defines the CLI used by Task 4; Task 3 extends the same module and CLI; Task 5 consumes only commands defined in Task 4.
