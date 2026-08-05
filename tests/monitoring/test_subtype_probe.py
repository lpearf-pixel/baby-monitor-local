from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from packages.monitoring.alpha_quality import HealthResult, QualityConfigError
from packages.monitoring.subtype_probe import apply_subtype, probe_subtypes


FIXED_NOW = datetime(2026, 8, 4, 16, 0, tzinfo=timezone.utc)


def runtime_config() -> dict[str, object]:
    return {
        "xiaomi": {"123": "V1:must-not-leak"},
        "streams": {
            "source": (
                "xiaomi://123:cn@192.0.2.10?did=456&subtype=hd"
                "&vendor_hint=keep"
            ),
            "live": "ffmpeg:source#video=mjpeg#width=1280#height=720#raw=-r 10",
        },
    }


def write_runtime(path: Path) -> str:
    content = yaml.safe_dump(runtime_config(), sort_keys=False)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return content


def test_probe_restores_original_after_success(tmp_path: Path) -> None:
    config = tmp_path / "go2rtc.yaml"
    original_text = write_runtime(config)
    seen_configs: list[str] = []
    health_results = iter(
        [
            HealthResult(
                "PASS",
                protocol="cs2+udp",
                bytes_received=2000,
                source_dimensions=(864, 480),
            ),
            HealthResult(
                "PASS",
                protocol="cs2+udp",
                bytes_received=4000,
                source_dimensions=(2560, 1440),
            ),
        ]
    )

    summary = probe_subtypes(
        config,
        tmp_path / "backups",
        (2, 3),
        lambda: seen_configs.append(config.read_text(encoding="utf-8")),
        lambda: next(health_results),
        FIXED_NOW,
    )

    assert config.read_text(encoding="utf-8") == original_text
    assert config.stat().st_mode & 0o777 == 0o600
    assert summary.recommended_subtype == 3
    assert [attempt.subtype for attempt in summary.attempts] == [2, 3]
    assert [attempt.source_dimensions for attempt in summary.attempts] == [
        (864, 480),
        (2560, 1440),
    ]
    assert len(seen_configs) == 3
    assert "subtype=2" in seen_configs[0]
    assert "subtype=3" in seen_configs[1]
    assert seen_configs[2] == original_text
    assert summary.backup.read_text(encoding="utf-8") == original_text
    assert summary.backup.stat().st_mode & 0o777 == 0o600


def test_probe_restores_original_when_health_check_raises(tmp_path: Path) -> None:
    config = tmp_path / "go2rtc.yaml"
    original_text = write_runtime(config)
    seen_configs: list[str] = []

    def fail() -> HealthResult:
        raise RuntimeError("probe failed")

    with pytest.raises(RuntimeError, match="probe failed"):
        probe_subtypes(
            config,
            tmp_path / "backups",
            (3,),
            lambda: seen_configs.append(config.read_text(encoding="utf-8")),
            fail,
            FIXED_NOW,
        )

    assert config.read_text(encoding="utf-8") == original_text
    assert seen_configs[-1] == original_text
    assert len(seen_configs) == 2


def test_probe_restores_original_when_interrupted(tmp_path: Path) -> None:
    config = tmp_path / "go2rtc.yaml"
    original_text = write_runtime(config)
    seen_configs: list[str] = []

    def interrupt() -> HealthResult:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        probe_subtypes(
            config,
            tmp_path / "backups",
            (3,),
            lambda: seen_configs.append(config.read_text(encoding="utf-8")),
            interrupt,
            FIXED_NOW,
        )

    assert config.read_text(encoding="utf-8") == original_text
    assert seen_configs[-1] == original_text


def test_probe_continues_after_unavailable_candidate(tmp_path: Path) -> None:
    config = tmp_path / "go2rtc.yaml"
    write_runtime(config)
    health_results = iter(
        [
            HealthResult("SOURCE_OFFLINE"),
            HealthResult(
                "PASS",
                protocol="cs2+udp",
                bytes_received=8000,
                source_dimensions=(2304, 1296),
            ),
        ]
    )

    summary = probe_subtypes(
        config,
        tmp_path / "backups",
        (4, 5),
        lambda: None,
        lambda: next(health_results),
        FIXED_NOW,
    )

    assert [attempt.code for attempt in summary.attempts] == [
        "SOURCE_OFFLINE",
        "PASS",
    ]
    assert summary.recommended_subtype == 5


@pytest.mark.parametrize("candidates", [(), (3, 3), (-1,), (6,)])
def test_probe_rejects_invalid_candidates_without_modifying_config(
    tmp_path: Path,
    candidates: tuple[int, ...],
) -> None:
    config = tmp_path / "go2rtc.yaml"
    original_text = write_runtime(config)
    restarts = 0

    def restart() -> None:
        nonlocal restarts
        restarts += 1

    with pytest.raises(QualityConfigError, match="INVALID_SUBTYPE_CANDIDATES"):
        probe_subtypes(
            config,
            tmp_path / "backups",
            candidates,
            restart,
            lambda: HealthResult("PASS"),
            FIXED_NOW,
        )

    assert config.read_text(encoding="utf-8") == original_text
    assert restarts == 0
    assert not (tmp_path / "backups").exists()


def test_apply_subtype_keeps_verified_native_hd_and_creates_rollback_backup(
    tmp_path: Path,
) -> None:
    config = tmp_path / "go2rtc.yaml"
    original_text = write_runtime(config)
    seen_configs: list[str] = []

    summary = apply_subtype(
        config,
        tmp_path / "backups",
        3,
        (1920, 1080),
        lambda: seen_configs.append(config.read_text(encoding="utf-8")),
        lambda: HealthResult(
            "PASS",
            protocol="cs2+udp",
            bytes_received=607,
            source_dimensions=(2560, 1440),
            live_dimensions=(1280, 720),
        ),
        FIXED_NOW,
    )

    applied = yaml.safe_load(config.read_text(encoding="utf-8"))
    source = applied["streams"]["source"]
    assert "subtype=3" in source
    assert "vendor_hint=keep" in source
    assert "transport=" not in source
    assert config.stat().st_mode & 0o777 == 0o600
    assert summary.applied_subtype == 3
    assert summary.health.code == "PASS"
    assert summary.original_config_restored is False
    assert len(seen_configs) == 1
    assert summary.backup.name == "go2rtc-quality-20260804-160000.yaml"
    assert summary.backup.read_text(encoding="utf-8") == original_text
    assert summary.backup.stat().st_mode & 0o777 == 0o600


def test_apply_subtype_restores_original_when_source_is_below_minimum(
    tmp_path: Path,
) -> None:
    config = tmp_path / "go2rtc.yaml"
    original_text = write_runtime(config)
    seen_configs: list[str] = []

    summary = apply_subtype(
        config,
        tmp_path / "backups",
        3,
        (1920, 1080),
        lambda: seen_configs.append(config.read_text(encoding="utf-8")),
        lambda: HealthResult(
            "PASS",
            protocol="cs2+udp",
            bytes_received=32000,
            source_dimensions=(864, 480),
            live_dimensions=(1280, 720),
        ),
        FIXED_NOW,
    )

    assert summary.health.code == "SOURCE_DIMENSIONS_TOO_LOW"
    assert summary.health.source_dimensions == (864, 480)
    assert summary.original_config_restored is True
    assert config.read_text(encoding="utf-8") == original_text
    assert config.stat().st_mode & 0o777 == 0o600
    assert "subtype=3" in seen_configs[0]
    assert seen_configs[-1] == original_text
    assert len(seen_configs) == 2


def test_apply_subtype_restores_original_when_full_health_gate_fails(
    tmp_path: Path,
) -> None:
    config = tmp_path / "go2rtc.yaml"
    original_text = write_runtime(config)
    seen_configs: list[str] = []

    summary = apply_subtype(
        config,
        tmp_path / "backups",
        3,
        (1920, 1080),
        lambda: seen_configs.append(config.read_text(encoding="utf-8")),
        lambda: HealthResult(
            "LIVE_MJPEG_EMPTY",
            protocol="cs2+udp",
            bytes_received=607,
            source_dimensions=(2560, 1440),
            live_dimensions=(1280, 720),
        ),
        FIXED_NOW,
    )

    assert summary.health.code == "LIVE_MJPEG_EMPTY"
    assert summary.original_config_restored is True
    assert config.read_text(encoding="utf-8") == original_text
    assert seen_configs[-1] == original_text


@pytest.mark.parametrize("failure", [RuntimeError("health failed"), KeyboardInterrupt()])
def test_apply_subtype_restores_original_when_health_gate_raises(
    tmp_path: Path,
    failure: BaseException,
) -> None:
    config = tmp_path / "go2rtc.yaml"
    original_text = write_runtime(config)
    seen_configs: list[str] = []

    def fail() -> HealthResult:
        raise failure

    with pytest.raises(type(failure)):
        apply_subtype(
            config,
            tmp_path / "backups",
            3,
            (1920, 1080),
            lambda: seen_configs.append(config.read_text(encoding="utf-8")),
            fail,
            FIXED_NOW,
        )

    assert config.read_text(encoding="utf-8") == original_text
    assert config.stat().st_mode & 0o777 == 0o600
    assert seen_configs[-1] == original_text
    assert len(seen_configs) == 2


@pytest.mark.parametrize(
    ("subtype", "minimum_dimensions"),
    [(6, (1920, 1080)), (3, (0, 1080)), (3, (1920, -1))],
)
def test_apply_subtype_rejects_invalid_input_without_modifying_config(
    tmp_path: Path,
    subtype: int,
    minimum_dimensions: tuple[int, int],
) -> None:
    config = tmp_path / "go2rtc.yaml"
    original_text = write_runtime(config)
    restarts = 0

    def restart() -> None:
        nonlocal restarts
        restarts += 1

    with pytest.raises(QualityConfigError):
        apply_subtype(
            config,
            tmp_path / "backups",
            subtype,
            minimum_dimensions,
            restart,
            lambda: HealthResult("PASS"),
            FIXED_NOW,
        )

    assert config.read_text(encoding="utf-8") == original_text
    assert restarts == 0
    assert not (tmp_path / "backups").exists()
