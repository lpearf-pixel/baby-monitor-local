from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

from packages.contracts.offline_guardian_scenario import (
    OfflineGuardianScenarioV1,
    load_offline_scenario_suite,
)
from services.vision.corpus_manifest import load_manifest
from services.vision.realtime_models import RealtimeModelError, RealtimeModelSignals


FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures/offline_guardian_scenarios/scenarios.v1.json"
)
VISUAL_MANIFEST = Path(__file__).parents[1] / "fixtures/visual_corpus/manifest.json"


def scenario(identifier: str) -> OfflineGuardianScenarioV1:
    suite = load_offline_scenario_suite(FIXTURE)
    return next(item for item in suite.scenarios if item.scenario_id == identifier)


def private_root(tmp_path: Path) -> Path:
    root = tmp_path / "scenario"
    root.mkdir(mode=0o700)
    return root


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        (
            "SAFE-SLEEP-01",
            {
                "dashboard.event": 0,
                "dashboard.open": 0,
            },
        ),
        (
            "FACE-OCCLUSION-01",
            {
                "transition.watch_started.face_not_visible": 1,
                "transition.alert_opened.face_not_visible": 1,
                "transition.recovered.face_not_visible": 1,
                "event.face_not_visible.recovered": 1,
                "dashboard.event": 1,
                "dashboard.open": 0,
            },
        ),
        (
            "ADULT-INTERVENTION-01",
            {
                "transition.watch_started.face_not_visible": 1,
                "transition.alert_opened.face_not_visible": 1,
                "transition.adult_intervention.none": 1,
                "event.face_not_visible.open": 1,
                "dashboard.event": 1,
                "dashboard.open": 1,
            },
        ),
    ],
)
def test_guardian_lane_runs_current_rules_and_dashboard_projection(
    tmp_path: Path,
    identifier: str,
    expected: dict[str, int],
) -> None:
    from services.offline_guardian_scenario import run_guardian_lane

    root = private_root(tmp_path)
    result = run_guardian_lane(scenario(identifier), root)

    assert result.lane == "guardian_deterministic"
    assert result.status == "PASS"
    assert result.reason == "ok"
    assert result.counts == expected
    database = root / "guardian-events.sqlite3"
    assert database.is_file()
    assert stat.S_IMODE(database.stat().st_mode) == 0o600


def test_guardian_lane_rejects_existing_store_without_reading_it(
    tmp_path: Path,
) -> None:
    from services.offline_guardian_scenario import run_guardian_lane

    root = private_root(tmp_path)
    database = root / "guardian-events.sqlite3"
    database.write_bytes(b"private-existing-state")
    database.chmod(0o600)

    result = run_guardian_lane(scenario("SAFE-SLEEP-01"), root)

    assert result.status == "FAIL"
    assert result.reason == "guardian_store_not_empty"
    assert database.read_bytes() == b"private-existing-state"


def test_guardian_lane_rejects_symlink_runtime_root(tmp_path: Path) -> None:
    from services.offline_guardian_scenario import run_guardian_lane

    actual = private_root(tmp_path)
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)

    result = run_guardian_lane(scenario("SAFE-SLEEP-01"), linked)

    assert result.status == "FAIL"
    assert result.reason == "offline_scenario_runtime_unsafe"
    assert list(actual.iterdir()) == []


def test_guardian_lane_reports_expectation_mismatch_without_changing_rules(
    tmp_path: Path,
) -> None:
    from services.offline_guardian_scenario import run_guardian_lane

    value = scenario("SAFE-SLEEP-01")
    guardian = value.guardian.model_copy(
        update={"dashboard_event_count": 1},
    )
    changed = value.model_copy(update={"guardian": guardian})

    result = run_guardian_lane(changed, private_root(tmp_path))

    assert result.status == "FAIL"
    assert result.reason == "scenario_guardian_mismatch"
    assert result.counts["dashboard.event"] == 0


class AvailableVisualBackend:
    def infer(self, _bgr: object) -> RealtimeModelSignals:
        return RealtimeModelSignals(
            face_boxes=((0.4, 0.3, 0.2, 0.2),),
            pose_centers=((0.5, 0.5),),
        )


class DegradedVisualBackend:
    def infer(self, _bgr: object) -> RealtimeModelSignals:
        raise RealtimeModelError("private model detail")


def generated_video(path: Path) -> None:
    completed = subprocess.run(
        (
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=10",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            "-f",
            "matroska",
            str(path),
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0


def test_visual_lane_replays_real_file_through_current_worker(tmp_path: Path) -> None:
    from services.offline_guardian_scenario import run_visual_lane

    media = tmp_path / "public-fixture.mkv"
    generated_video(media)

    result = run_visual_lane(
        scenario("SAFE-SLEEP-01"),
        load_manifest(VISUAL_MANIFEST),
        lambda _clip, _profile: media,
        AvailableVisualBackend(),
    )

    assert result.lane == "visual_observation"
    assert result.status == "PASS"
    assert result.reason == "ok"
    assert result.counts["frames.total"] == 10
    assert result.counts["frames.processed"] >= 1
    assert result.counts["errors.decode"] == 0
    assert result.counts["errors.worker"] == 0
    assert result.metrics_ms["pipeline.p95"] >= 0
    assert result.metrics_ms["model.p95"] >= 0
    assert not (tmp_path / "guardian-events.sqlite3").exists()
    assert not hasattr(result, "frame_observations")


def test_visual_lane_rejects_unknown_clip_before_resolving_media() -> None:
    from services.offline_guardian_scenario import run_visual_lane

    value = scenario("SAFE-SLEEP-01")
    changed = value.model_copy(
        update={"visual": value.visual.model_copy(update={"clip_id": "DAY-99"})},
    )
    called: list[object] = []

    result = run_visual_lane(
        changed,
        load_manifest(VISUAL_MANIFEST),
        lambda *_args: called.append("resolver"),
        AvailableVisualBackend(),
    )

    assert result.status == "FAIL"
    assert result.reason == "offline_scenario_clip_missing"
    assert called == []


@pytest.mark.parametrize(
    ("backend", "reason"),
    [
        (None, "visual_corpus_model_unavailable"),
        (DegradedVisualBackend(), "visual_corpus_model_degraded"),
    ],
)
def test_visual_lane_fails_closed_for_required_model_state(
    tmp_path: Path,
    backend: object | None,
    reason: str,
) -> None:
    from services.offline_guardian_scenario import run_visual_lane

    media = tmp_path / "public-fixture.mkv"
    generated_video(media)

    result = run_visual_lane(
        scenario("SAFE-SLEEP-01"),
        load_manifest(VISUAL_MANIFEST),
        lambda _clip, _profile: media,
        backend,
    )

    assert result.status == "FAIL"
    assert result.reason == reason


def test_visual_lane_reports_missing_prepared_artifact_without_path(
    tmp_path: Path,
) -> None:
    from services.offline_guardian_scenario import run_visual_lane

    result = run_visual_lane(
        scenario("SAFE-SLEEP-01"),
        load_manifest(VISUAL_MANIFEST),
        lambda _clip, _profile: tmp_path / "private-household-name.mkv",
        AvailableVisualBackend(),
    )

    assert result.status == "FAIL"
    assert result.reason == "visual_corpus_input_invalid"
    assert "private-household-name" not in repr(result)
