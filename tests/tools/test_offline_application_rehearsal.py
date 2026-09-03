from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def _component_run(*, status: str = "PASS", face_output: int = 0):
    results = []
    for index in range(8):
        lanes = []
        if index < 5:
            lanes.extend((
                SimpleNamespace(
                    lane="visual_observation",
                    counts={
                        "frames.processed": 66,
                        "frames.skipped": 0,
                        "frames.dropped": 0,
                        "errors.decode": 0,
                        "errors.worker": 0,
                    },
                ),
                SimpleNamespace(lane="guardian_deterministic", counts={}),
            ))
        else:
            lanes.append(SimpleNamespace(lane="voice", counts={}))
        results.append(SimpleNamespace(lanes=tuple(lanes)))
    return SimpleNamespace(status=status, results=tuple(results), face_output=face_output)


def test_validate_reports_exact_tracked_cardinalities(capsys) -> None:
    from tools import offline_application_rehearsal as tool

    assert tool.main(["validate"]) == 0
    output = capsys.readouterr().out
    for line in (
        "result=PASS", "scenario_count=12", "historical_count=3",
        "application_scenarios=6", "voice_scenarios=3", "joined_scenarios=3",
    ):
        assert line in output


def test_tool_source_does_not_import_real_adapters() -> None:
    source = (Path(__file__).parents[2] / "tools/offline_application_rehearsal.py").read_text()
    for forbidden in (
        "services.voice.camera_reply", "xiaomi", "go2rtc", "services.camera.ptz", "notification_dispatch",
        "services.baby", "private_visual",
    ):
        assert forbidden not in source.lower()


def test_make_targets_are_fixed_and_discoverable() -> None:
    makefile = (Path(__file__).parents[2] / "Makefile").read_text()
    assert "alpha-offline-application-validate:" in makefile
    assert "alpha-offline-application-run:" in makefile
    assert "tools/offline_application_rehearsal.py validate" in makefile
    assert "tools/offline_application_rehearsal.py run" in makefile


def test_run_imports_component_once_and_emits_closed_summary(
    monkeypatch, tmp_path: Path, capsys,
) -> None:
    from tools import offline_application_rehearsal as tool

    calls = []
    monkeypatch.setattr(tool, "RUN_PARENT", tmp_path / "runs")
    monkeypatch.setattr(
        tool, "execute_fixed_flow",
        lambda: (calls.append("component") or _component_run(), "ignored/report"),
    )

    assert tool.main(["run"]) == 0
    assert calls == ["component"]
    output = capsys.readouterr().out
    for line in (
        "result=PASS", "functional_scenarios=12", "functional_pass=12",
        "full_iterations=10", "full_iteration_pass=10",
        "cross_risk_instances=50", "cross_risk_pass=50", "fault_cases=10",
        "imported_scenarios=8", "imported_lanes=13",
        "imported_visual_clips=5", "imported_frames=330",
        "imported_skipped_frames=0", "imported_dropped_frames=0",
        "imported_decode_errors=0", "imported_worker_errors=0",
        "camera_access=0", "camera_reply_enabled=0", "ptz_commands=0",
        "real_notifications=0", "baby_care_writes=0", "private_media_reads=0",
        "no_baby_face_watch=0", "no_baby_face_alert=0",
        "no_baby_face_event=0", "no_baby_face_notification=0",
        "residual_reply_sessions=0",
    ):
        assert line in output
    assert str(tmp_path) not in output


def test_run_refuses_an_invalid_imported_component(monkeypatch, capsys) -> None:
    from tools import offline_application_rehearsal as tool

    calls = []
    monkeypatch.setattr(
        tool, "execute_fixed_flow",
        lambda: (calls.append("component") or _component_run(status="FAIL"), "ignored/report"),
    )

    assert tool.main(["run"]) == 2
    assert calls == ["component"]
    assert capsys.readouterr().out == "result=FAIL\nreason=imported_component_failed\n"


def test_no_baby_face_counts_are_derived_not_hard_coded() -> None:
    from tools import offline_application_rehearsal as tool

    results = (
        SimpleNamespace(
            scenario_id="APP-EMPTY-BED-01",
            counts={"face.output": 1},
        ),
    )

    assert sum(tool._no_baby_face_counts(results).values()) == 1
