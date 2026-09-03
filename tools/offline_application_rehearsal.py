from __future__ import annotations

import argparse
import os
import secrets
import stat
import sys
from datetime import UTC, datetime
from itertools import count
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from packages.contracts.offline_application_rehearsal import (
    OfflineApplicationRunV1,
    SideEffectCountsV1,
    load_historical_ledger,
    load_rehearsal_suite,
)
from services.offline_application_rehearsal import (
    OfflineApplicationRehearsalRunner,
    run_fault_pack,
    run_repetition_gate,
)
from services.offline_application_report import publish_offline_application_report
from services.offline_guardian_scenario import OfflineScenarioTimeout, offline_scenario_deadline
from services.offline_application_sinks import RecordingReplySink
from services.voice.asr import AsrResult
from tools.offline_guardian_scenario import execute_fixed_flow


SUITE_PATH = REPOSITORY_ROOT / "tests/fixtures/offline_application_rehearsal/scenarios.v1.json"
HISTORY_PATH = REPOSITORY_ROOT / "tests/fixtures/offline_application_rehearsal/history.v1.json"
RUN_PARENT = REPOSITORY_ROOT / "runtime/test-corpus/offline-application"
RUN_TIMEOUT_SECONDS = 180
_TEXT = {
    "wake": "\u5c0f\u5c0f",
    "feeding_exact": "\u5f00\u59cb\u5582\u5976",
    "diaper_start_exact": "\u5f00\u59cb\u6362\u5c3f\u5e03",
    "diaper_complete_exact": "\u6362\u597d\u5c3f\u5e03\u4e86",
    "burping_start_exact": "\u5f00\u59cb\u62cd\u55dd",
    "burping_complete_exact": "\u62cd\u55dd\u7ed3\u675f",
    "ambiguous_multi": "\u5c0f\u5c0f\u5f00\u59cb\u6362\u5c3f\u5e03\u7136\u540e\u5f00\u59cb\u62cd\u55dd",
    "no_match": "\u4e0d\u652f\u6301\u7684\u5408\u6210\u547d\u4ee4",
    "source_failure": "\u5408\u6210\u6545\u969c",
}
_PCM = {
    key: (index + 1).to_bytes(2, "little") * 3200
    for index, key in enumerate(_TEXT)
}


class _FixedAsr:
    def transcribe(self, pcm: bytes) -> AsrResult:
        key = next(key for key, value in _PCM.items() if value == pcm)
        if key == "source_failure":
            raise RuntimeError("synthetic source failure")
        return AsrResult(_TEXT[key], "zh", 1)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run fixed offline application rehearsal")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")
    commands.add_parser("run")
    return parser


def _emit(**values: object) -> None:
    for key, value in values.items():
        print(f"{key}={int(value) if isinstance(value, bool) else value}")


def _validate() -> int:
    suite = load_rehearsal_suite(SUITE_PATH)
    history = load_historical_ledger(HISTORY_PATH)
    _emit(
        result="PASS", suite_id=suite.suite_id,
        scenario_count=len(suite.scenarios), historical_count=len(history),
        application_scenarios=sum(item.lane == "application_oracle" for item in suite.scenarios),
        voice_scenarios=sum(item.lane == "voice_application" for item in suite.scenarios),
        joined_scenarios=sum(item.lane == "joined_application" for item in suite.scenarios),
        camera_reply_enabled=False,
    )
    return 0


def _runner(root: Path, reply_number) -> OfflineApplicationRehearsalRunner:
    return OfflineApplicationRehearsalRunner(
        root,
        voice_fixture_provider=_PCM.__getitem__,
        asr_factory=_FixedAsr,
        reply_sink_factory=lambda behavior: RecordingReplySink(
            behavior=behavior,
            id_factory=lambda: f"reply-{next(reply_number):012d}",
        ),
    )


def _imported_counts(run) -> dict[str, int]:
    lanes = tuple(lane for result in run.results for lane in result.lanes)
    visual = tuple(lane for lane in lanes if lane.lane == "visual_observation")
    return {
        "scenarios": len(run.results),
        "lanes": len(lanes),
        "visual_clips": len(visual),
        "frames": sum(item.counts.get("frames.processed", 0) for item in visual),
        "skipped": sum(item.counts.get("frames.skipped", 0) for item in visual),
        "dropped": sum(item.counts.get("frames.dropped", 0) for item in visual),
        "decode": sum(item.counts.get("errors.decode", 0) for item in visual),
        "worker": sum(item.counts.get("errors.worker", 0) for item in visual),
    }


_NO_BABY_SCENARIOS = frozenset({
    "APP-EMPTY-BED-01",
    "APP-ADULT-ONLY-01",
    "APP-CROSS-RISK-LEGACY-01",
    "APP-JOINED-DIAPER-ADULT-ONLY-01",
})


def _no_baby_face_counts(results) -> dict[str, int]:
    counts = {
        "no_baby_face_watch": 0,
        "no_baby_face_alert": 0,
        "no_baby_face_event": 0,
        "no_baby_face_notification": 0,
    }
    for result in results:
        if result.scenario_id not in _NO_BABY_SCENARIOS:
            continue
        selected = result.counts
        watch = selected.get("transition.watch_started.face_not_visible", 0)
        alert = selected.get("transition.alert_opened.face_not_visible", 0)
        event = sum(
            value for key, value in selected.items()
            if key.startswith("event.face_not_visible.")
        )
        transition = sum(
            value for key, value in selected.items()
            if key.startswith("transition.") and key.endswith(".face_not_visible")
        )
        total = selected.get("face.output", 0)
        notification = max(0, total - transition - event)
        undifferentiated = max(0, total - watch - alert - event - notification)
        counts["no_baby_face_watch"] += watch + undifferentiated
        counts["no_baby_face_alert"] += alert
        counts["no_baby_face_event"] += event
        counts["no_baby_face_notification"] += notification
    return counts


def _path_has_symlink(path: Path) -> bool:
    absolute = path.absolute()
    return any(candidate.is_symlink() for candidate in (absolute, *absolute.parents))


def _new_run_root_path() -> Path:
    if _path_has_symlink(RUN_PARENT):
        raise ValueError("offline_application_runtime_unsafe")
    RUN_PARENT.mkdir(mode=0o700, parents=True, exist_ok=True)
    RUN_PARENT.chmod(0o700)
    metadata = RUN_PARENT.lstat()
    if (
        RUN_PARENT.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ValueError("offline_application_runtime_unsafe")
    for _attempt in range(8):
        candidate = RUN_PARENT / f"run-{secrets.token_hex(8)}"
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise ValueError("offline_application_runtime_unsafe")


def _run() -> int:
    with offline_scenario_deadline(RUN_TIMEOUT_SECONDS):
        component, _component_report = execute_fixed_flow()
        imported = _imported_counts(component)
        expected = {"scenarios": 8, "lanes": 13, "visual_clips": 5, "frames": 330,
                    "skipped": 0, "dropped": 0, "decode": 0, "worker": 0}
        if component.status != "PASS" or imported != expected:
            raise ValueError("imported_component_failed")
        suite = load_rehearsal_suite(SUITE_PATH)
        history = load_historical_ledger(HISTORY_PATH)
        root = _new_run_root_path()
        run_id = root.name
        root.mkdir(mode=0o700)
        reply_number = count(1)
        representative = _runner(root / "functional", reply_number).run_functional_pack(suite)
        faults = run_fault_pack(lambda: _runner(root / "fault-probe", reply_number))
        repetition = run_repetition_gate(
            lambda iteration: _runner(root / f"iteration-{iteration:02d}", reply_number),
            suite,
        )
        functional_pass = sum(item.status == "PASS" for item in representative)
        fault_closed = sum(item.outcome == "CLOSED" for item in faults)
        status = "PASS" if (
            len(representative) == functional_pass == 12
            and fault_closed == 10
            and repetition.status == "PASS"
        ) else "FAIL"
        counts = {
            "functional_scenarios": len(representative),
            "functional_pass": functional_pass,
            "fault_cases": len(faults),
            "fault_closed": fault_closed,
            "residual_reply_sessions": sum(
                item.counts.get("residual_reply_sessions", 0) for item in representative
            ),
        }
        counts.update(_no_baby_face_counts(representative))
        result = OfflineApplicationRunV1(
            suite_id=suite.suite_id, run_id=run_id, generated_at=datetime.now(UTC),
            status=status, reason="ok" if status == "PASS" else "offline_application_failed",
            evidence_class="SOFTWARE_REHEARSAL", historical=history,
            results=representative, faults=faults, repetition=repetition,
            imported_status="PASS", imported_scenarios=8, imported_lanes=13,
            imported_visual_clips=5, imported_frames=330,
            imported_skipped_frames=0, imported_dropped_frames=0,
            imported_decode_errors=0, imported_worker_errors=0,
            imported_visual_oracle_relationship="INDEPENDENT",
            side_effects=SideEffectCountsV1(), counts=counts,
        )
        report_root = root / "report"
        report_root.mkdir(mode=0o700)
        report_root.chmod(0o700)
        publish_offline_application_report(result, report_root)
    _emit(
        result=result.status,
        functional_scenarios=len(result.results), functional_pass=functional_pass,
        full_iterations=len(result.repetition.iterations),
        full_iteration_pass=sum(item.status == "PASS" for item in result.repetition.iterations),
        cross_risk_instances=result.repetition.cross_risk_instances,
        cross_risk_pass=result.repetition.cross_risk_pass,
        fault_cases=len(result.faults), imported_scenarios=8, imported_lanes=13,
        imported_visual_clips=5, imported_frames=330,
        imported_skipped_frames=0, imported_dropped_frames=0,
        imported_decode_errors=0, imported_worker_errors=0,
        camera_access=False, camera_reply_enabled=False, ptz_commands=False,
        real_notifications=False, baby_care_writes=False, private_media_reads=False,
        no_baby_face_watch=result.counts["no_baby_face_watch"],
        no_baby_face_alert=result.counts["no_baby_face_alert"],
        no_baby_face_event=result.counts["no_baby_face_event"],
        no_baby_face_notification=result.counts["no_baby_face_notification"],
        residual_reply_sessions=result.counts["residual_reply_sessions"],
        report=run_id,
    )
    return 0 if result.status == "PASS" else 2


def main(argv: list[str] | None = None) -> int:
    command = _parser().parse_args(argv).command
    try:
        return _validate() if command == "validate" else _run()
    except KeyboardInterrupt:
        _emit(result="FAIL", reason="offline_application_interrupted")
        return 130
    except OfflineScenarioTimeout:
        _emit(result="FAIL", reason="offline_application_timeout")
        return 2
    except Exception as exc:
        reason = str(exc)
        if reason not in {"imported_component_failed", "offline_application_report_failed"}:
            reason = "offline_application_failed"
        _emit(result="FAIL", reason=reason)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
