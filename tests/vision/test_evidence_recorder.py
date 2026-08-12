from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO, StringIO
import json
from pathlib import Path

from PIL import Image

from packages.contracts.vision import (
    RiskTransition,
    RiskTransitionKind,
    VisualRiskKind,
    VisualRiskState,
)
from services.storage.visual_risk import VisualRiskEventStore
from services.vision.evidence_files import GuardianEvidenceFiles
from services.vision.evidence_recorder import GuardianEvidenceRecorder
from services.vision.frame_policy import PreparedAnalysisFrame
from services.vision.frame_ring import AnalysisFrameRing


NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def frame(seconds: int) -> PreparedAnalysisFrame:
    output = BytesIO()
    color = ((seconds * 17) % 256, (seconds * 31) % 256, (seconds * 47) % 256)
    Image.new("RGB", (32, 18), color).save(output, format="JPEG", quality=80)
    return PreparedAnalysisFrame(
        jpeg=output.getvalue(),
        captured_at=NOW + timedelta(seconds=seconds),
        width=32,
        height=18,
        crop_box=(0, 0, 32, 18),
    )


def opened_transition() -> RiskTransition:
    return RiskTransition(
        transition_kind=RiskTransitionKind.ALERT_OPENED,
        risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
        previous_state=VisualRiskState.WATCH,
        current_state=VisualRiskState.ALERT,
        observed_at=NOW,
        confidence=0.88,
        notify=True,
    )


def setup_event(tmp_path: Path) -> tuple[VisualRiskEventStore, object]:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    event = store.open_event(
        event_id="event-face",
        risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
        opened_at=NOW,
        confidence=0.88,
        rule_version="visual-risk-v1",
    )
    return store, event


def decoded(stream: StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_start_saves_snapshot_and_only_preceding_ten_second_window(
    tmp_path: Path,
) -> None:
    store, event = setup_event(tmp_path)
    ring = AnalysisFrameRing()
    for seconds in (-12, -10, -8, -6, -4, -2, 0):
        ring.add(frame(seconds))
    stream = StringIO()
    recorder = GuardianEvidenceRecorder(
        store=store,
        files=GuardianEvidenceFiles(tmp_path / "guardian-evidence"),
        frame_window=ring.snapshot_window,
        stream=stream,
    )

    recorder.start(event, opened_transition())
    recorder.start(event, opened_transition())

    evidence = store.get_evidence("event-face")
    assert evidence is not None
    assert evidence.state == "collecting"
    assert evidence.frame_count == 6
    assert evidence.snapshot_key is not None
    snapshot = tmp_path / "guardian-evidence" / evidence.snapshot_key
    assert snapshot.is_file()
    assert [line["code"] for line in decoded(stream)] == [
        "guardian.evidence_started"
    ]


def test_observe_completes_at_thirty_seconds_with_bounded_animated_clip(
    tmp_path: Path,
) -> None:
    store, event = setup_event(tmp_path)
    ring = AnalysisFrameRing()
    for seconds in (-10, -8, -6, -4, -2, 0):
        ring.add(frame(seconds))
    stream = StringIO()
    recorder = GuardianEvidenceRecorder(
        store=store,
        files=GuardianEvidenceFiles(tmp_path / "guardian-evidence"),
        frame_window=ring.snapshot_window,
        stream=stream,
    )
    recorder.start(event, opened_transition())

    for seconds in range(1, 31):
        recorder.observe(frame(seconds))

    evidence = store.get_evidence("event-face")
    assert evidence is not None
    assert evidence.state == "ready"
    assert evidence.frame_count == 21
    assert evidence.clip_key is not None
    with Image.open(tmp_path / "guardian-evidence" / evidence.clip_key) as clip:
        assert clip.is_animated is True
        assert clip.n_frames == 21
    assert decoded(stream)[-1] == {
        "code": "guardian.evidence_ready",
        "component": "baby_guardian",
        "event_id": "event-face",
        "frame_count": 21,
        "observed_at": (NOW + timedelta(seconds=30)).isoformat(),
        "result": "completed",
        "schema_version": 1,
        "state": "ready",
    }


def test_missing_snapshot_frame_fails_without_raising(tmp_path: Path) -> None:
    store, event = setup_event(tmp_path)
    ring = AnalysisFrameRing()
    stream = StringIO()
    recorder = GuardianEvidenceRecorder(
        store=store,
        files=GuardianEvidenceFiles(tmp_path / "guardian-evidence"),
        frame_window=ring.snapshot_window,
        stream=stream,
    )

    recorder.start(event, opened_transition())

    evidence = store.get_evidence("event-face")
    assert evidence is not None
    assert evidence.state == "failed"
    assert evidence.failure_code == "snapshot_unavailable"
    assert decoded(stream)[-1]["result"] == "snapshot_unavailable"


class SensitiveFailingFiles:
    def write_snapshot(self, _event_id: str, _frame: object) -> str:
        raise OSError("token at /private/family/snapshot.jpg")

    def write_clip(self, _event_id: str, _frames: object) -> str:
        raise OSError("token at /private/family/clip.webp")


def test_media_failure_is_redacted_and_does_not_escape(tmp_path: Path) -> None:
    store, event = setup_event(tmp_path)
    ring = AnalysisFrameRing()
    ring.add(frame(0))
    stream = StringIO()
    recorder = GuardianEvidenceRecorder(
        store=store,
        files=SensitiveFailingFiles(),
        frame_window=ring.snapshot_window,
        stream=stream,
    )

    recorder.start(event, opened_transition())

    evidence = store.get_evidence("event-face")
    serialized = stream.getvalue()
    assert evidence is not None
    assert evidence.state == "failed"
    assert evidence.failure_code == "media_write_failed"
    assert "token" not in serialized
    assert "/private" not in serialized


def test_restart_and_close_interrupt_collecting_without_fabricating_clip(
    tmp_path: Path,
) -> None:
    store, event = setup_event(tmp_path)
    ring = AnalysisFrameRing()
    ring.add(frame(0))
    first_stream = StringIO()
    first = GuardianEvidenceRecorder(
        store=store,
        files=GuardianEvidenceFiles(tmp_path / "guardian-evidence"),
        frame_window=ring.snapshot_window,
        stream=first_stream,
    )
    first.start(event, opened_transition())

    restarted_stream = StringIO()
    restarted = GuardianEvidenceRecorder(
        store=store,
        files=GuardianEvidenceFiles(tmp_path / "guardian-evidence"),
        frame_window=ring.snapshot_window,
        stream=restarted_stream,
    )
    restarted.recover_interrupted(NOW + timedelta(seconds=5))
    restarted.close(NOW + timedelta(seconds=6))

    evidence = store.get_evidence("event-face")
    assert evidence is not None
    assert evidence.state == "interrupted"
    assert evidence.failure_code == "worker_restarted"
    assert evidence.clip_key is None
    assert [line["code"] for line in decoded(restarted_stream)] == [
        "guardian.evidence_interrupted"
    ]
