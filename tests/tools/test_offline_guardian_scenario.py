from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

import pytest

from packages.contracts.offline_guardian_scenario import (
    OfflineScenarioResultV1,
    OfflineScenarioRunV1,
    ScenarioLaneResult,
)


ROOT = Path(__file__).resolve().parents[2]


def module():
    from tools import offline_guardian_scenario

    return offline_guardian_scenario


@pytest.mark.parametrize("option", ["--url", "--path", "--model", "--port"])
def test_cli_has_only_fixed_validate_and_run_surface(option: str) -> None:
    with pytest.raises(SystemExit):
        module().parser().parse_args(["run", option, "value"])


def test_validate_checks_tracked_suite_and_visual_clip_references(capsys) -> None:
    assert module().main(["validate"]) == 0

    assert capsys.readouterr().out == (
        "result=PASS\n"
        "suite_id=offline-guardian-v1\n"
        "scenario_count=4\n"
        "visual_clip_count=3\n"
    )


def passing_run() -> OfflineScenarioRunV1:
    return OfflineScenarioRunV1(
        suite_id="offline-guardian-v1",
        status="PASS",
        reason="ok",
        results=(
            OfflineScenarioResultV1(
                scenario_id="SAFE-SLEEP-01",
                status="PASS",
                reason="ok",
                lanes=(
                    ScenarioLaneResult(
                        lane="visual_observation",
                        status="PASS",
                        reason="ok",
                        counts={"frames.processed": 10},
                    ),
                ),
            ),
        ),
    )


def test_run_prints_only_bounded_aggregate_and_relative_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        module(),
        "_execute_fixed_flow",
        lambda: (passing_run(), "run-opaque/report"),
    )

    assert module().main(["run"]) == 0

    output = capsys.readouterr().out
    assert output == (
        "result=PASS\n"
        "reason=ok\n"
        "scenario_count=1\n"
        "pass_count=1\n"
        "skip_count=0\n"
        "fail_count=0\n"
        "lane_count=1\n"
        "report=run-opaque/report\n"
    )
    assert str(ROOT) not in output
    assert "http" not in output.lower()


def test_underlying_failure_is_redacted(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(
        module(),
        "_execute_fixed_flow",
        lambda: (_ for _ in ()).throw(RuntimeError("private household token")),
    )

    assert module().main(["run"]) == 2
    assert capsys.readouterr().out == (
        "result=FAIL\nreason=offline_scenario_command_failed\n"
    )


def test_fixed_selection_is_exact_and_public() -> None:
    manifest = module().load_manifest(module().VISUAL_MANIFEST_PATH)
    selected = module()._selected_visual_clips(manifest)

    assert tuple(clip.clip_id for clip in selected) == ("DAY-01", "OCC-02", "NEG-03")
    assert [clip.source_type.value for clip in selected] == [
        "PUBLIC_DATASET",
        "SYNTHETIC",
        "PUBLIC_DATASET",
    ]
    assert selected[1].parent_clip_id == "DAY-02"


def test_cli_source_does_not_initialize_production_clients() -> None:
    source = inspect.getsource(module())

    for prohibited in (
        "go2rtc",
        "Xiaomi",
        "VoiceIntentOutbox",
        "VoiceCareClient",
        "CameraReply",
        "NotificationDispatcher",
        "Ollama",
    ):
        assert prohibited not in source


@pytest.mark.parametrize(
    ("target", "command"),
    [
        ("alpha-offline-scenario-validate", "validate"),
        ("alpha-offline-scenario-run", "run"),
    ],
)
def test_make_targets_are_fixed(target: str, command: str) -> None:
    completed = subprocess.run(
        ("make", "-n", target),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == (
        f"./.venv-alpha/bin/python tools/offline_guardian_scenario.py {command}"
    )
