from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest


def valid_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "written_at_unix": 90.0,
        "realtime_fps": 3,
        "sample_count": 7,
        "processing_p50_ms": 101.125,
        "processing_p95_ms": 202.251,
        "processing_max_ms": 303.376,
        "realtime_model_state": "available",
    }


def write_payload(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def run_cli(path: Path, capsys: pytest.CaptureFixture[str]):
    from tools import realtime_visual_status

    exit_code = realtime_visual_status.main(
        ["--path", str(path)],
        wall_clock=lambda: 100.0,
    )
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_cli_prints_available_metrics_in_fixed_order(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "realtime-visual.json"
    write_payload(path, valid_payload())

    exit_code, stdout, stderr = run_cli(path, capsys)

    assert exit_code == 0
    assert stdout.splitlines() == [
        "realtime_metrics=available",
        "realtime_fps=3",
        "sample_count=7",
        "processing_p50_ms=101.125",
        "processing_p95_ms=202.251",
        "processing_max_ms=303.376",
        "realtime_model_state=available",
    ]
    assert stderr == ""


def test_cli_reports_missing_file_without_path_or_exception(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "private-household-status.json"

    exit_code, stdout, stderr = run_cli(path, capsys)

    assert exit_code == 2
    assert stdout == "realtime_metrics=unavailable\n"
    assert stderr == ""
    assert str(path) not in stdout


def test_cli_reports_stale_file_without_payload_details(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "private-household-status.json"
    payload = valid_payload()
    payload["written_at_unix"] = 84.999
    write_payload(path, payload)

    exit_code, stdout, stderr = run_cli(path, capsys)

    assert exit_code == 3
    assert stdout == "realtime_metrics=stale\n"
    assert stderr == ""
    assert str(path) not in stdout
    assert "84.999" not in stdout


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {**valid_payload(), "extra_private_field": "secret"},
        {key: value for key, value in valid_payload().items() if key != "sample_count"},
        {**valid_payload(), "schema_version": 2},
        {**valid_payload(), "written_at_unix": True},
        {**valid_payload(), "realtime_fps": True},
        {**valid_payload(), "sample_count": 0},
        {**valid_payload(), "processing_p50_ms": float("nan")},
        {**valid_payload(), "processing_p95_ms": "202.251"},
        {
            **valid_payload(),
            "processing_p50_ms": 250.0,
            "processing_p95_ms": 200.0,
        },
        {**valid_payload(), "realtime_model_state": "disabled"},
    ],
)
def test_cli_reports_invalid_state_without_path_or_exception(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    payload: object,
) -> None:
    path = tmp_path / "private-household-status.json"
    write_payload(path, payload)

    exit_code, stdout, stderr = run_cli(path, capsys)

    assert exit_code == 4
    assert stdout == "realtime_metrics=invalid\n"
    assert stderr == ""
    assert str(path) not in stdout
    assert "secret" not in stdout


def test_cli_reports_malformed_json_without_parser_details(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "private-household-status.json"
    path.write_text('{"schema_version":', encoding="utf-8")

    exit_code, stdout, stderr = run_cli(path, capsys)

    assert exit_code == 4
    assert stdout == "realtime_metrics=invalid\n"
    assert stderr == ""
    assert str(path) not in stdout


def test_cli_rejects_duplicate_json_object_keys(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "private-household-status.json"
    path.write_text(
        """{"schema_version":1,"schema_version":1,"written_at_unix":90.0,"realtime_fps":3,"sample_count":7,"processing_p50_ms":101.125,"processing_p95_ms":202.251,"processing_max_ms":303.376,"realtime_model_state":"available"}""",
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(path, capsys)

    assert exit_code == 4
    assert stdout == "realtime_metrics=invalid\n"
    assert stderr == ""


def test_make_status_calls_metrics_reader_only_for_running_worker(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).resolve().parents[2]
    fake_python = tmp_path / "fake-python"
    marker = tmp_path / "metrics-reader-called"
    fake_python.write_text(
        "#!/bin/sh\nprintf 'called\\n' > \"$METRICS_MARKER\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o700)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uname = fake_bin / "uname"
    fake_uname.write_text("#!/bin/sh\necho Linux\n", encoding="ascii")
    fake_uname.chmod(0o700)
    environment = {
        **os.environ,
        "METRICS_MARKER": str(marker),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }

    offline = subprocess.run(
        [
            "make",
            "-f",
            str(repository / "Makefile"),
            "alpha-visual-status",
            f"PYTHON={fake_python}",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert offline.returncode == 0
    assert not marker.exists()

    pid_dir = tmp_path / "runtime/pids"
    pid_dir.mkdir(parents=True)
    (pid_dir / "visual.pid").write_text(str(os.getpid()), encoding="utf-8")
    online = subprocess.run(
        [
            "make",
            "-f",
            str(repository / "Makefile"),
            "alpha-visual-status",
            f"PYTHON={fake_python}",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert online.returncode == 0
    assert marker.read_text(encoding="utf-8") == "called\n"


def test_make_status_preserves_legacy_checks_before_metrics_failure(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).resolve().parents[2]
    fake_python = tmp_path / "stale-metrics"
    fake_python.write_text(
        "#!/bin/sh\nprintf 'realtime_metrics=stale\\n'\nexit 3\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o700)
    pid_dir = tmp_path / "runtime/pids"
    pid_dir.mkdir(parents=True)
    (pid_dir / "visual.pid").write_text(str(os.getpid()), encoding="utf-8")

    completed = subprocess.run(
        [
            "make",
            "-f",
            str(repository / "Makefile"),
            "alpha-visual-status",
            f"PYTHON={fake_python}",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "realtime_metrics=stale" in completed.stdout
    assert "Ollama tunnel:" in completed.stdout
    assert "Ollama bridge:" in completed.stdout
