from __future__ import annotations

import inspect
import subprocess
import time
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
        "scenario_count=8\n"
        "lane_count=13\n"
        "visual_clip_count=5\n"
        "expected_frame_count=330\n"
        "public_source_count=3\n"
        "declared_source_bytes=25964039\n"
    )


def passing_run() -> OfflineScenarioRunV1:
    declarations = (
        ("SAFE-SLEEP-01", 65, True),
        ("FACE-OCCLUSION-01", 50, True),
        ("ADULT-INTERVENTION-01", 50, True),
        ("VOICE-FEEDING-01", None, False),
        ("PRONE-CANDIDATE-01", 100, True),
        ("OUTSIDE-CANDIDATE-01", 65, True),
        ("VOICE-DIAPER-01", None, False),
        ("VOICE-BURPING-01", None, False),
    )
    results = []
    for scenario_id, frames, paired in declarations:
        if frames is None:
            lanes = (
                ScenarioLaneResult(
                    lane="voice_generated",
                    status="PASS",
                    reason="ok",
                ),
            )
        else:
            lanes = (
                ScenarioLaneResult(
                    lane="visual_observation",
                    status="PASS",
                    reason="ok",
                    counts={"frames.processed": frames},
                ),
                ScenarioLaneResult(
                    lane="guardian_deterministic",
                    status="PASS",
                    reason="ok",
                ),
            )
        results.append(
            OfflineScenarioResultV1(
                scenario_id=scenario_id,
                status="PASS",
                reason="ok",
                lanes=lanes,
                visual_oracle_relationship="INDEPENDENT" if paired else None,
            )
        )
    return OfflineScenarioRunV1(
        suite_id="offline-guardian-v1",
        status="PASS",
        reason="ok",
        results=tuple(results),
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
        "scenario_count=8\n"
        "pass_count=8\n"
        "skip_count=0\n"
        "fail_count=0\n"
        "lane_count=13\n"
        "visual_clip_count=5\n"
        "frame_count=330\n"
        "public_source_count=3\n"
        "declared_source_bytes=25964039\n"
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


def test_run_deadline_covers_work_before_runner(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setattr(module(), "DEFAULT_RUN_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(module(), "_execute_fixed_flow", lambda: time.sleep(1))

    assert module().main(["run"]) == 2
    assert capsys.readouterr().out == (
        "result=FAIL\nreason=offline_scenario_timeout\n"
    )


def test_fixed_selection_is_exact_and_public() -> None:
    manifest = module().load_manifest(module().VISUAL_MANIFEST_PATH)
    suite = module().load_offline_scenario_suite(module().SCENARIO_SUITE_PATH)
    selected = module().validate_visual_scenario_bindings(suite, manifest)

    assert tuple(clip.clip_id for clip in selected) == (
        "DAY-01",
        "OCC-02",
        "NEG-03",
        "DAY-03",
        "OCC-03",
    )
    assert [clip.source_type.value for clip in selected] == [
        "PUBLIC_DATASET",
        "SYNTHETIC",
        "PUBLIC_DATASET",
        "PUBLIC_DATASET",
        "SYNTHETIC",
    ]
    assert selected[1].parent_clip_id == "DAY-02"
    assert selected[4].parent_clip_id == "DAY-01"


def test_fixed_selection_rejects_a_synthetic_parent() -> None:
    manifest = module().load_manifest(module().VISUAL_MANIFEST_PATH)
    suite = module().load_offline_scenario_suite(module().SCENARIO_SUITE_PATH)
    by_id = {clip.clip_id: clip for clip in manifest.clips}
    changed_occ03 = by_id["OCC-03"].model_copy(update={"parent_clip_id": "OCC-02"})
    changed_clips = tuple(
        changed_occ03 if clip.clip_id == "OCC-03" else clip
        for clip in manifest.clips
    )

    with pytest.raises(
        ValueError,
        match="^offline_scenario_visual_provenance_invalid$",
    ):
        module()._validate_fixed_suite(
            suite,
            manifest.model_copy(update={"clips": changed_clips}),
        )


def test_fixed_selection_rejects_parent_source_mismatch() -> None:
    manifest = module().load_manifest(module().VISUAL_MANIFEST_PATH)
    suite = module().load_offline_scenario_suite(module().SCENARIO_SUITE_PATH)
    by_id = {clip.clip_id: clip for clip in manifest.clips}
    changed_occ03 = by_id["OCC-03"].model_copy(
        update={"source_id": by_id["NEG-03"].source_id}
    )
    changed_clips = tuple(
        changed_occ03 if clip.clip_id == "OCC-03" else clip
        for clip in manifest.clips
    )

    with pytest.raises(
        ValueError,
        match="^offline_scenario_visual_provenance_invalid$",
    ):
        module()._validate_fixed_suite(
            suite,
            manifest.model_copy(update={"clips": changed_clips}),
        )


def test_validate_rejects_each_fixed_acceptance_drift(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    suite = module().load_offline_scenario_suite(module().SCENARIO_SUITE_PATH)
    manifest = module().load_manifest(module().VISUAL_MANIFEST_PATH)
    scenarios = list(suite.scenarios)
    by_id = {clip.clip_id: clip for clip in manifest.clips}

    wrong_identity = list(scenarios)
    wrong_identity[-1] = wrong_identity[-1].model_copy(
        update={"scenario_id": "VOICE-OTHER-01"}
    )
    wrong_lanes = list(scenarios)
    wrong_lanes[3] = wrong_lanes[3].model_copy(
        update={"required_lanes": ("voice_generated", "voice_generated")}
    )
    wrong_frames = list(scenarios)
    wrong_frames[0] = wrong_frames[0].model_copy(
        update={
            "visual": wrong_frames[0].visual.model_copy(
                update={"expected_frames_processed": 64}
            )
        }
    )
    wrong_visual = list(scenarios)
    wrong_visual[0] = wrong_visual[0].model_copy(
        update={"visual": wrong_visual[0].visual.model_copy(update={"clip_id": "DAY-02"})}
    )
    shared_source_clip = by_id["DAY-03"].model_copy(
        update={"source_id": by_id["DAY-01"].source_id}
    )
    wrong_sources_manifest = manifest.model_copy(
        update={
            "clips": tuple(
                shared_source_clip if clip.clip_id == "DAY-03" else clip
                for clip in manifest.clips
            )
        }
    )
    source_index = next(
        index
        for index, source in enumerate(manifest.sources)
        if source.source_id == "cdc-two-month-movement"
    )
    source = manifest.sources[source_index]
    assert source.expected_bytes is not None
    byte_source = source.model_copy(
        update={"expected_bytes": source.expected_bytes + 1}
    )
    wrong_sources = list(manifest.sources)
    wrong_sources[source_index] = byte_source
    wrong_bytes_manifest = manifest.model_copy(
        update={"sources": tuple(wrong_sources)}
    )
    cases = (
        (suite.model_copy(update={"scenarios": tuple(wrong_identity)}), manifest),
        (suite.model_copy(update={"scenarios": tuple(scenarios[:-1])}), manifest),
        (suite.model_copy(update={"scenarios": tuple(wrong_lanes)}), manifest),
        (suite.model_copy(update={"scenarios": tuple(wrong_frames)}), manifest),
        (suite.model_copy(update={"scenarios": tuple(wrong_visual)}), manifest),
        (suite, wrong_sources_manifest),
        (suite, wrong_bytes_manifest),
    )

    for changed_suite, changed_manifest in cases:
        monkeypatch.setattr(
            module(), "load_offline_scenario_suite", lambda _path, value=changed_suite: value
        )
        monkeypatch.setattr(
            module(), "load_manifest", lambda _path, value=changed_manifest: value
        )
        assert module().main(["validate"]) == 2
        assert capsys.readouterr().out == (
            "result=FAIL\nreason=offline_scenario_command_failed\n"
        )


def test_fixed_flow_rejects_invalid_binding_before_factories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suite = module().load_offline_scenario_suite(module().SCENARIO_SUITE_PATH)
    manifest = module().load_manifest(module().VISUAL_MANIFEST_PATH)
    first = suite.scenarios[0]
    changed = first.model_copy(
        update={
            "visual": first.visual.model_copy(update={"provenance": "GENERATED_VISUAL"})
        }
    )
    changed_suite = suite.model_copy(
        update={"scenarios": (changed, *suite.scenarios[1:])}
    )
    calls: list[str] = []

    class ForbiddenFactory:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            calls.append("downloader_or_preparer")
            raise AssertionError("factory reached")

    monkeypatch.setattr(module(), "load_offline_scenario_suite", lambda _path: changed_suite)
    monkeypatch.setattr(module(), "load_manifest", lambda _path: manifest)
    monkeypatch.setattr(module(), "CorpusDownloader", ForbiddenFactory)
    monkeypatch.setattr(module(), "CorpusPreparer", ForbiddenFactory)
    monkeypatch.setattr(
        module(),
        "_build_model_backend_quietly",
        lambda: calls.append("model"),
    )
    monkeypatch.setattr(
        module(),
        "_new_run_root_path",
        lambda: calls.append("runtime_root"),
    )

    with pytest.raises(
        ValueError,
        match="^offline_scenario_visual_provenance_invalid$",
    ):
        module()._execute_fixed_flow()

    assert calls == []


@pytest.mark.parametrize("drift", ["skip", "frames", "results", "lanes"])
def test_run_exits_nonzero_for_any_non_exact_aggregate(
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    run = passing_run()
    results = list(run.results)
    if drift == "skip":
        lanes = list(results[0].lanes)
        lanes[0] = lanes[0].model_copy(update={"status": "SKIP", "reason": "skipped"})
        results[0] = results[0].model_copy(
            update={"status": "SKIP", "reason": "skipped", "lanes": tuple(lanes)}
        )
        run = run.model_copy(update={"status": "SKIP", "reason": "skipped", "results": tuple(results)})
    elif drift == "frames":
        lanes = list(results[0].lanes)
        lanes[0] = lanes[0].model_copy(update={"counts": {"frames.processed": 64}})
        results[0] = results[0].model_copy(update={"lanes": tuple(lanes)})
        run = run.model_copy(update={"results": tuple(results)})
    elif drift == "results":
        run = run.model_copy(update={"results": tuple(results[:-1])})
    else:
        results[0] = results[0].model_copy(
            update={"lanes": (results[0].lanes[0],), "visual_oracle_relationship": None}
        )
        run = run.model_copy(update={"results": tuple(results)})

    monkeypatch.setattr(
        module(),
        "_execute_fixed_flow",
        lambda: (run, "run-opaque/report"),
    )

    assert module().main(["run"]) == 2
    output = capsys.readouterr().out
    assert output.startswith("result=FAIL\n")


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
