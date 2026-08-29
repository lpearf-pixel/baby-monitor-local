from __future__ import annotations

import importlib
import json
import os
import stat
import subprocess
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.vision.private_visual_overlay import PrivateMediaFacts
from packages.contracts.private_visual_overlay import (
    LocalOverlayReadiness,
    PrivateOverlayDescriptor,
)
from packages.contracts.visual_corpus import CorpusReadiness, ScenarioId
from services.vision.private_visual_overlay import PrivateOverlayValidation


ASSET_ID = "plc-0123456789abcdef0123456789abcdef"
SECOND_ASSET_ID = "plc-fedcba9876543210fedcba9876543210"
MEDIA = b"generated-private-video-only"


def tool():
    return importlib.import_module("tools.private_visual_corpus")


def ready_preflight(**overrides: object):
    module = tool()
    value = module.CapturePreflight(
        camera_reply_enabled=False,
        speaker_state="closed",
        pending_command_responses=0,
        residual_sender_count=0,
        configured_transport="auto",
        producer_count=1,
        negotiated_protocol="cs2+udp",
        producer_generation=7,
        consumer_count=3,
        video_media_ready=True,
        producer_replaced=False,
    )
    return replace(value, **overrides)


def generated_probe(path: Path) -> PrivateMediaFacts:
    import hashlib

    payload = path.read_bytes()
    return PrivateMediaFacts(
        bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        video_streams=1,
        audio_streams=0,
        subtitle_streams=0,
        data_streams=0,
        duration_ms=25_000,
        codec="hevc",
        width=2560,
        height=1440,
        fps=10.0,
    )


def generated_runner(argv: tuple[str, ...], _timeout: float) -> None:
    Path(argv[-1]).write_bytes(MEDIA)


def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


def test_parser_exposes_only_closed_private_operations() -> None:
    parser = tool().parser()

    assert parser.parse_args(["validate"]).command == "validate"
    assert parser.parse_args(["capture-preflight"]).command == "capture-preflight"
    assert parser.parse_args(["capture", "--duration", "20"]).duration == 20
    assert parser.parse_args(["capture", "--duration", "25"]).duration == 25
    assert parser.parse_args(["capture", "--duration", "30"]).duration == 30
    assert (
        parser.parse_args(
            ["review-prepare", "--private-asset-id", ASSET_ID]
        ).private_asset_id
        == ASSET_ID
    )
    assert (
        parser.parse_args(
            ["review-status", "--private-asset-id", ASSET_ID]
        ).private_asset_id
        == ASSET_ID
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["capture", "--duration", "10"],
        ["capture", "--duration", "60"],
        ["capture", "--duration", "20", "--source", "source"],
        ["capture", "--duration", "20", "--destination", "asset.mkv"],
        ["capture", "--duration", "20", "--host", "localhost"],
        ["capture", "--duration", "20", "--port", "8554"],
        ["capture", "--duration", "20", "--camera-id", "camera"],
        ["capture", "--duration", "20", "--codec", "hevc"],
        ["capture", "--duration", "20", "--ffmpeg-arg", "-y"],
        ["baseline"],
        ["compare"],
        ["promote"],
    ],
)
def test_parser_rejects_caller_controlled_media_and_baseline_inputs(
    arguments: list[str],
) -> None:
    with pytest.raises(SystemExit):
        tool().parser().parse_args(arguments)


def test_parser_never_echoes_rejected_private_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = "SENSITIVE_MARKER"

    with pytest.raises(SystemExit):
        tool().parser().parse_args(
            ["capture", "--duration", "20", "--destination", marker]
        )

    assert marker not in capsys.readouterr().err


@pytest.mark.parametrize(
    "override",
    [
        {"camera_reply_enabled": True},
        {"camera_reply_enabled": None},
        {"speaker_state": "active"},
        {"pending_command_responses": 1},
        {"residual_sender_count": 1},
        {"configured_transport": "udp"},
        {"producer_count": 0},
        {"producer_count": 2},
        {"negotiated_protocol": "unavailable"},
        {"video_media_ready": False},
        {"producer_replaced": True},
    ],
)
def test_preflight_fails_closed_before_runtime_write(
    tmp_path: Path,
    override: dict[str, object],
) -> None:
    module = tool()
    root = repository(tmp_path)

    with pytest.raises(
        module.PrivateVisualCorpusError,
        match="^private_overlay_capture_precondition_failed$",
    ):
        module.capture_private_asset(
            root,
            25,
            preflight=ready_preflight(**override),
            postflight=lambda: ready_preflight(),
            runner=generated_runner,
            probe=generated_probe,
            asset_id_factory=lambda: ASSET_ID,
        )

    assert list(root.iterdir()) == []


def test_capture_uses_fixed_video_only_loopback_command_and_private_layout(
    tmp_path: Path,
) -> None:
    module = tool()
    root = repository(tmp_path)
    observed: list[tuple[str, ...]] = []

    def runner(argv: tuple[str, ...], _timeout: float) -> None:
        observed.append(argv)
        Path(argv[-1]).write_bytes(MEDIA)

    result = module.capture_private_asset(
        root,
        25,
        preflight=ready_preflight(),
        postflight=lambda: ready_preflight(),
        runner=runner,
        probe=generated_probe,
        asset_id_factory=lambda: ASSET_ID,
    )

    assert result.private_asset_id == ASSET_ID
    assert result.bytes == len(MEDIA)
    assert result.duration_ms == 25_000
    assert result.codec == "hevc"
    assert result.width == 2560
    assert result.height == 1440
    assert result.fps == 10.0
    assert result.video_streams == 1
    assert result.audio_streams == 0
    assert result.subtitle_streams == 0
    assert result.data_streams == 0
    assert len(observed) == 1
    argv = observed[0]
    assert argv.count("rtsp://127.0.0.1:8554/source") == 1
    assert ("-map", "0:v:0") == argv[argv.index("-map") : argv.index("-map") + 2]
    assert "-an" in argv
    assert "-sn" in argv
    assert "-dn" in argv
    assert ("-c:v", "copy") == argv[argv.index("-c:v") : argv.index("-c:v") + 2]
    assert ("-f", "matroska") == argv[argv.index("-f") : argv.index("-f") + 2]

    overlay = root / "runtime/test-corpus/visual/private-overlay"
    for directory in (
        overlay,
        overlay / "assets",
        overlay / "review-frames",
        overlay / "results",
        overlay / "temp",
    ):
        assert stat.S_IMODE(directory.lstat().st_mode) == 0o700
    index = overlay / "index.json"
    assert stat.S_IMODE(index.lstat().st_mode) == 0o600
    mapping = json.loads(index.read_text(encoding="utf-8"))
    assert mapping == {
        "schema_version": 1,
        "assets": [
            {"private_asset_id": ASSET_ID, "basename": f"{ASSET_ID}.mkv"}
        ],
    }
    media = overlay / "assets" / f"{ASSET_ID}.mkv"
    assert media.read_bytes() == MEDIA
    assert stat.S_IMODE(media.lstat().st_mode) == 0o600
    assert not list((overlay / "temp").glob("*.tmp"))


def test_capture_success_runs_real_fake_ffmpeg_and_ffprobe_executables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = tool()
    root = repository(tmp_path)
    argv_log = tmp_path / "argv.log"
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys\n"
        "pathlib.Path(os.environ['PRIVATE_TEST_ARGV']).write_text('\\n'.join(sys.argv[1:]), encoding='utf-8')\n"
        "pathlib.Path(sys.argv[-1]).write_bytes(b'generated-private-video-only')\n",
        encoding="ascii",
    )
    ffmpeg.chmod(0o755)
    ffprobe = tmp_path / "ffprobe"
    ffprobe.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "print(json.dumps({'streams':[{'codec_type':'video','codec_name':'hevc','width':2560,'height':1440,'avg_frame_rate':'10/1'}],'format':{'duration':'25.000'}}))\n",
        encoding="ascii",
    )
    ffprobe.chmod(0o755)
    monkeypatch.setattr(module, "FFMPEG_EXECUTABLE", str(ffmpeg))
    monkeypatch.setattr(module, "FFPROBE_EXECUTABLE", str(ffprobe))
    monkeypatch.setenv("PRIVATE_TEST_ARGV", str(argv_log))

    result = module.capture_private_asset(
        root,
        25,
        preflight=ready_preflight(),
        postflight=lambda: ready_preflight(),
        asset_id_factory=lambda: ASSET_ID,
    )

    assert result.private_asset_id == ASSET_ID
    arguments = argv_log.read_text(encoding="utf-8").splitlines()
    assert "rtsp://127.0.0.1:8554/source" in arguments
    assert "-an" in arguments


def test_probe_supports_validator_held_descriptor_without_following_a_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = tool()
    media = tmp_path / "held-media.mkv"
    media.write_bytes(MEDIA)
    media.chmod(0o600)
    ffprobe = tmp_path / "ffprobe"
    ffprobe.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "print(json.dumps({'streams':[{'codec_type':'video','codec_name':'hevc','width':2560,'height':1440,'avg_frame_rate':'10/1'}],'format':{'duration':'25.000'}}))\n",
        encoding="ascii",
    )
    ffprobe.chmod(0o755)
    monkeypatch.setattr(module, "FFPROBE_EXECUTABLE", str(ffprobe))
    descriptor = os.open(media, os.O_RDONLY)
    try:
        facts = module.probe_private_media(Path(f"/dev/fd/{descriptor}"))
    finally:
        os.close(descriptor)

    assert facts.bytes == len(MEDIA)
    assert facts.video_streams == 1
    assert facts.audio_streams == 0


def test_capture_rejects_concurrent_second_writer(tmp_path: Path) -> None:
    module = tool()
    root = repository(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    first_error: list[BaseException] = []

    def blocking_runner(argv: tuple[str, ...], _timeout: float) -> None:
        Path(argv[-1]).write_bytes(MEDIA)
        entered.set()
        assert release.wait(timeout=5)

    def first_capture() -> None:
        try:
            module.capture_private_asset(
                root,
                25,
                preflight=ready_preflight(),
                postflight=lambda: ready_preflight(),
                runner=blocking_runner,
                probe=generated_probe,
                asset_id_factory=lambda: ASSET_ID,
            )
        except BaseException as exc:  # pragma: no cover - asserted after join
            first_error.append(exc)

    thread = threading.Thread(target=first_capture)
    thread.start()
    assert entered.wait(timeout=5)
    second_called = False

    def second_runner(_argv: tuple[str, ...], _timeout: float) -> None:
        nonlocal second_called
        second_called = True

    try:
        with pytest.raises(
            module.PrivateVisualCorpusError,
            match="^private_overlay_capture_precondition_failed$",
        ):
            module.capture_private_asset(
                root,
                25,
                preflight=ready_preflight(),
                postflight=lambda: ready_preflight(),
                runner=second_runner,
                probe=generated_probe,
                asset_id_factory=lambda: SECOND_ASSET_ID,
            )
    finally:
        release.set()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert first_error == []
    assert second_called is False


@pytest.mark.parametrize("failure", [TimeoutError(), KeyboardInterrupt()])
def test_capture_failure_leaves_no_accepted_mapping(
    tmp_path: Path,
    failure: BaseException,
) -> None:
    module = tool()
    root = repository(tmp_path)

    def failing_runner(_argv: tuple[str, ...], _timeout: float) -> None:
        raise failure

    expected = KeyboardInterrupt if isinstance(failure, KeyboardInterrupt) else module.PrivateVisualCorpusError
    with pytest.raises(expected):
        module.capture_private_asset(
            root,
            25,
            preflight=ready_preflight(),
            postflight=lambda: ready_preflight(),
            runner=failing_runner,
            probe=generated_probe,
            asset_id_factory=lambda: ASSET_ID,
        )

    overlay = root / "runtime/test-corpus/visual/private-overlay"
    assert not (overlay / "index.json").exists()
    assert not list((overlay / "assets").iterdir())
    assert not list((overlay / "temp").glob("*.tmp"))


def test_postflight_replacement_rejects_before_publication(tmp_path: Path) -> None:
    module = tool()
    root = repository(tmp_path)

    with pytest.raises(
        module.PrivateVisualCorpusError,
        match="^private_overlay_capture_precondition_failed$",
    ):
        module.capture_private_asset(
            root,
            25,
            preflight=ready_preflight(),
            postflight=lambda: ready_preflight(
                producer_generation=8,
                producer_replaced=True,
            ),
            runner=generated_runner,
            probe=generated_probe,
            asset_id_factory=lambda: ASSET_ID,
        )

    overlay = root / "runtime/test-corpus/visual/private-overlay"
    assert not (overlay / "index.json").exists()
    assert not list((overlay / "assets").iterdir())


def test_capture_rejects_audio_probe_without_publishing_mapping(tmp_path: Path) -> None:
    module = tool()
    root = repository(tmp_path)

    with pytest.raises(
        module.PrivateVisualCorpusError,
        match="^private_overlay_audio_present$",
    ):
        module.capture_private_asset(
            root,
            25,
            preflight=ready_preflight(),
            postflight=lambda: ready_preflight(),
            runner=generated_runner,
            probe=lambda path: replace(generated_probe(path), audio_streams=1),
            asset_id_factory=lambda: ASSET_ID,
        )

    overlay = root / "runtime/test-corpus/visual/private-overlay"
    assert not (overlay / "index.json").exists()
    assert not list((overlay / "assets").iterdir())


def test_capture_does_not_chmod_or_delete_hardlinked_lock(
    tmp_path: Path,
) -> None:
    module = tool()
    root = repository(tmp_path)
    overlay = module._prepare_overlay_layout(root)
    outside = tmp_path / "outside-lock"
    outside.write_bytes(b"owner-data")
    outside.chmod(0o644)
    os.link(outside, overlay / "temp" / "capture.lock")

    with pytest.raises(
        module.PrivateVisualCorpusError,
        match="^private_overlay_capture_precondition_failed$",
    ):
        module.capture_private_asset(
            root,
            25,
            preflight=ready_preflight(),
            postflight=lambda: ready_preflight(),
            runner=generated_runner,
            probe=generated_probe,
            asset_id_factory=lambda: ASSET_ID,
        )

    assert outside.read_bytes() == b"owner-data"
    assert stat.S_IMODE(outside.lstat().st_mode) == 0o644
    assert outside.lstat().st_nlink == 2


def test_publication_settlement_failure_removes_owned_unmapped_final(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = tool()
    root = repository(tmp_path)
    calls = 0

    def failing_fsync(_path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("generated fsync failure")

    monkeypatch.setattr(module, "_fsync_directory", failing_fsync)

    with pytest.raises(
        module.PrivateVisualCorpusError,
        match="^private_overlay_identity_mismatch$",
    ):
        module.capture_private_asset(
            root,
            25,
            preflight=ready_preflight(),
            postflight=lambda: ready_preflight(),
            runner=generated_runner,
            probe=generated_probe,
            asset_id_factory=lambda: ASSET_ID,
        )

    overlay = root / "runtime/test-corpus/visual/private-overlay"
    assert not (overlay / "index.json").exists()
    assert not list((overlay / "assets").iterdir())


def test_index_settlement_failure_rolls_back_new_mapping_and_final(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = tool()
    root = repository(tmp_path)
    calls = 0

    def fail_after_index_replace(_path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("generated index settlement failure")

    monkeypatch.setattr(module, "_fsync_directory", fail_after_index_replace)

    with pytest.raises(
        module.PrivateVisualCorpusError,
        match="^private_overlay_mapping_invalid$",
    ):
        module.capture_private_asset(
            root,
            25,
            preflight=ready_preflight(),
            postflight=lambda: ready_preflight(),
            runner=generated_runner,
            probe=generated_probe,
            asset_id_factory=lambda: ASSET_ID,
        )

    overlay = root / "runtime/test-corpus/visual/private-overlay"
    assert not (overlay / "index.json").exists()
    assert not list((overlay / "assets").iterdir())


def test_real_ffmpeg_timeout_is_settled_without_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = tool()
    root = repository(tmp_path)
    ffmpeg = tmp_path / "ffmpeg-timeout"
    ffmpeg.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys, time\n"
        "pathlib.Path(sys.argv[-1]).write_bytes(b'partial')\n"
        "time.sleep(5)\n",
        encoding="ascii",
    )
    ffmpeg.chmod(0o755)
    monkeypatch.setattr(module, "FFMPEG_EXECUTABLE", str(ffmpeg))
    real_runner = module._run_ffmpeg
    monkeypatch.setattr(
        module,
        "_run_ffmpeg",
        lambda argv, _timeout: real_runner(argv, 0.05),
    )

    with pytest.raises(
        module.PrivateVisualCorpusError,
        match="^private_overlay_capture_precondition_failed$",
    ):
        module.capture_private_asset(
            root,
            25,
            preflight=ready_preflight(),
            postflight=lambda: ready_preflight(),
            probe=generated_probe,
            asset_id_factory=lambda: ASSET_ID,
        )

    overlay = root / "runtime/test-corpus/visual/private-overlay"
    assert not (overlay / "index.json").exists()
    assert not list((overlay / "assets").iterdir())
    assert not list((overlay / "temp").glob("*.tmp"))


def test_existing_asset_identity_is_not_replaced(tmp_path: Path) -> None:
    module = tool()
    root = repository(tmp_path)
    first = module.capture_private_asset(
        root,
        25,
        preflight=ready_preflight(),
        postflight=lambda: ready_preflight(),
        runner=generated_runner,
        probe=generated_probe,
        asset_id_factory=lambda: ASSET_ID,
    )
    overlay = root / "runtime/test-corpus/visual/private-overlay"
    media = overlay / "assets" / f"{ASSET_ID}.mkv"
    original = media.read_bytes()
    called = False

    def replacement_runner(_argv: tuple[str, ...], _timeout: float) -> None:
        nonlocal called
        called = True

    with pytest.raises(
        module.PrivateVisualCorpusError,
        match="^private_overlay_duplicate_clip$",
    ):
        module.capture_private_asset(
            root,
            25,
            preflight=ready_preflight(),
            postflight=lambda: ready_preflight(),
            runner=replacement_runner,
            probe=generated_probe,
            asset_id_factory=lambda: ASSET_ID,
        )

    assert first.private_asset_id == ASSET_ID
    assert media.read_bytes() == original
    assert called is False
    assert len(json.loads((overlay / "index.json").read_text())["assets"]) == 1


def test_validate_and_review_prepare_do_not_create_missing_private_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = tool()
    root = repository(tmp_path)
    monkeypatch.setattr(module, "REPOSITORY_ROOT", root)
    monkeypatch.setattr(
        module,
        "load_manifest",
        lambda _path: SimpleNamespace(readiness=CorpusReadiness.PARTIAL),
    )

    assert module.main(["validate"]) == 2
    validate_output = capsys.readouterr().out
    assert "result=FAIL" in validate_output
    assert "public_readiness=PARTIAL" in validate_output
    assert "local_readiness=LOCAL_UNAVAILABLE" in validate_output
    assert "reason=private_overlay_unavailable" in validate_output
    assert list(root.iterdir()) == []

    assert module.main(
        ["review-prepare", "--private-asset-id", ASSET_ID]
    ) == 2
    review_output = capsys.readouterr().out
    assert "result=FAIL" in review_output
    assert "reason=private_overlay_review_incomplete" in review_output
    assert list(root.iterdir()) == []


def test_capture_cli_prints_only_bounded_aggregate_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = tool()
    root = repository(tmp_path)
    monkeypatch.setattr(module, "REPOSITORY_ROOT", root)
    monkeypatch.setattr(module, "_collect_capture_preflight", lambda _root: ready_preflight())
    monkeypatch.setattr(module, "_asset_id", lambda: ASSET_ID)
    monkeypatch.setattr(module, "_run_ffmpeg", generated_runner)
    monkeypatch.setattr(module, "probe_private_media", generated_probe)

    assert module.main(["capture", "--duration", "25"]) == 0
    output = capsys.readouterr().out
    assert output.splitlines() == [
        "result=PASS",
        "operation=capture",
        f"private_asset_id={ASSET_ID}",
        f"bytes={len(MEDIA)}",
        f"sha256={__import__('hashlib').sha256(MEDIA).hexdigest()}",
        "duration_ms=25000",
        "codec=hevc",
        "width=2560",
        "height=1440",
        "fps=10.0",
        "video_streams=1",
        "audio_streams=0",
        "subtitle_streams=0",
        "data_streams=0",
    ]
    assert str(root) not in output
    assert "source" not in output


def test_capture_preflight_command_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = tool()
    root = repository(tmp_path)
    monkeypatch.setattr(module, "REPOSITORY_ROOT", root)
    monkeypatch.setattr(module, "_collect_capture_preflight", lambda _root: ready_preflight())

    assert module.main(["capture-preflight"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "result=PASS",
        "operation=capture-preflight",
        "reason=ok",
    ]
    assert list(root.iterdir()) == []


def test_review_prepare_extracts_half_second_samples_and_explicit_ends(
    tmp_path: Path,
) -> None:
    module = tool()
    root = repository(tmp_path)
    module.capture_private_asset(
        root,
        25,
        preflight=ready_preflight(),
        postflight=lambda: ready_preflight(),
        runner=generated_runner,
        probe=generated_probe,
        asset_id_factory=lambda: ASSET_ID,
    )
    observed: list[tuple[str, ...]] = []

    def frame_runner(argv: tuple[str, ...], _timeout: float) -> None:
        observed.append(argv)
        output = Path(argv[-1])
        if "%06d" in output.name:
            for sequence in range(1, 51):
                frame = output.with_name(
                    output.name.replace("%06d", f"{sequence:06d}")
                )
                frame.write_bytes(b"generated-frame")
        else:
            output.write_bytes(b"generated-frame")

    result = module.prepare_review_material(
        root,
        ASSET_ID,
        runner=frame_runner,
        probe=generated_probe,
    )

    assert result.private_asset_id == ASSET_ID
    assert result.sha256 == __import__("hashlib").sha256(MEDIA).hexdigest()
    assert result.sample_interval_ms == 500
    assert result.sample_frame_count == 50
    assert result.first_frame_present is True
    assert result.last_frame_present is True
    assert len(observed) == 3
    assert "fps=2" in observed[0]
    start = observed[1].index("-ss")
    assert ("-ss", "0") == observed[1][start : start + 2]
    assert "-sseof" in observed[2]
    review = root / "runtime/test-corpus/visual/private-overlay/review-frames" / ASSET_ID
    assert stat.S_IMODE(review.lstat().st_mode) == 0o700
    for entry in review.iterdir():
        assert stat.S_IMODE(entry.lstat().st_mode) == 0o600


def test_review_prepare_failure_publishes_no_review_directory(tmp_path: Path) -> None:
    module = tool()
    root = repository(tmp_path)
    module.capture_private_asset(
        root,
        25,
        preflight=ready_preflight(),
        postflight=lambda: ready_preflight(),
        runner=generated_runner,
        probe=generated_probe,
        asset_id_factory=lambda: ASSET_ID,
    )

    with pytest.raises(module.PrivateVisualCorpusError):
        module.prepare_review_material(
            root,
            ASSET_ID,
            runner=lambda _argv, _timeout: (_ for _ in ()).throw(TimeoutError()),
            probe=generated_probe,
        )

    review_root = root / "runtime/test-corpus/visual/private-overlay/review-frames"
    assert not (review_root / ASSET_ID).exists()


def test_review_prepare_rejects_unexpected_frame_inventory(tmp_path: Path) -> None:
    module = tool()
    root = repository(tmp_path)
    module.capture_private_asset(
        root,
        25,
        preflight=ready_preflight(),
        postflight=lambda: ready_preflight(),
        runner=generated_runner,
        probe=generated_probe,
        asset_id_factory=lambda: ASSET_ID,
    )

    def frame_runner(argv: tuple[str, ...], _timeout: float) -> None:
        output = Path(argv[-1])
        if "%06d" in output.name:
            for sequence in range(1, 51):
                output.with_name(
                    output.name.replace("%06d", f"{sequence:06d}")
                ).write_bytes(b"generated-frame")
            (output.parent / "unexpected.png").write_bytes(b"generated-frame")
        else:
            output.write_bytes(b"generated-frame")

    with pytest.raises(
        module.PrivateVisualCorpusError,
        match="^private_overlay_review_incomplete$",
    ):
        module.prepare_review_material(
            root,
            ASSET_ID,
            runner=frame_runner,
            probe=generated_probe,
        )

    review_root = root / "runtime/test-corpus/visual/private-overlay/review-frames"
    assert not (review_root / ASSET_ID).exists()


def test_review_prepare_uses_one_held_descriptor_for_all_frame_reads(
    tmp_path: Path,
) -> None:
    module = tool()
    root = repository(tmp_path)
    module.capture_private_asset(
        root,
        25,
        preflight=ready_preflight(),
        postflight=lambda: ready_preflight(),
        runner=generated_runner,
        probe=generated_probe,
        asset_id_factory=lambda: ASSET_ID,
    )
    sources: list[str] = []

    def frame_runner(argv: tuple[str, ...], _timeout: float) -> None:
        source = argv[argv.index("-i") + 1]
        sources.append(source)
        output = Path(argv[-1])
        if "%06d" in output.name:
            for sequence in range(1, 51):
                output.with_name(
                    output.name.replace("%06d", f"{sequence:06d}")
                ).write_bytes(b"generated-frame")
        else:
            output.write_bytes(b"generated-frame")

    module.prepare_review_material(
        root,
        ASSET_ID,
        runner=frame_runner,
        probe=generated_probe,
    )

    assert len(sources) == 3
    assert len(set(sources)) == 1
    assert sources[0].startswith("/dev/fd/")


def test_review_prepare_rejects_in_place_media_change_even_when_bytes_restore(
    tmp_path: Path,
) -> None:
    module = tool()
    root = repository(tmp_path)
    module.capture_private_asset(
        root,
        25,
        preflight=ready_preflight(),
        postflight=lambda: ready_preflight(),
        runner=generated_runner,
        probe=generated_probe,
        asset_id_factory=lambda: ASSET_ID,
    )
    media = (
        root
        / "runtime/test-corpus/visual/private-overlay/assets"
        / f"{ASSET_ID}.mkv"
    )
    calls = 0

    def frame_runner(argv: tuple[str, ...], _timeout: float) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            media.write_bytes(b"changed-private-video-bytes")
            media.chmod(0o600)
        elif calls == 3:
            media.write_bytes(MEDIA)
            media.chmod(0o600)
            current = media.stat()
            os.utime(
                media,
                ns=(current.st_atime_ns, current.st_mtime_ns + 1_000_000),
            )
        output = Path(argv[-1])
        if "%06d" in output.name:
            for sequence in range(1, 51):
                output.with_name(
                    output.name.replace("%06d", f"{sequence:06d}")
                ).write_bytes(b"generated-frame")
        else:
            output.write_bytes(b"generated-frame")

    with pytest.raises(
        module.PrivateVisualCorpusError,
        match="^private_overlay_identity_mismatch$",
    ):
        module.prepare_review_material(
            root,
            ASSET_ID,
            runner=frame_runner,
            probe=generated_probe,
        )

    review = (
        root
        / "runtime/test-corpus/visual/private-overlay/review-frames"
        / ASSET_ID
    )
    assert not review.exists()


def test_review_prepare_real_ffmpeg_creates_explicit_last_frame(
    tmp_path: Path,
) -> None:
    module = tool()
    root = repository(tmp_path)

    def real_video_runner(argv: tuple[str, ...], _timeout: float) -> None:
        completed = subprocess.run(
            (
                module.FFMPEG_EXECUTABLE,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=320x180:r=10",
                "-t",
                "2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-an",
                "-f",
                "matroska",
                argv[-1],
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
        assert completed.returncode == 0

    module.capture_private_asset(
        root,
        25,
        preflight=ready_preflight(),
        postflight=lambda: ready_preflight(),
        runner=real_video_runner,
        probe=generated_probe,
        asset_id_factory=lambda: ASSET_ID,
    )

    result = module.prepare_review_material(root, ASSET_ID)

    assert result.sample_frame_count == 4
    assert result.last_frame_present is True


def test_review_status_prints_no_receipt_detail_or_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = tool()
    root = repository(tmp_path)
    monkeypatch.setattr(module, "REPOSITORY_ROOT", root)
    monkeypatch.setattr(
        module,
        "review_status",
        lambda _root, _asset_id: module.ReviewStatus(
            private_asset_id=ASSET_ID,
            state="complete",
        ),
    )

    assert module.main(["review-status", "--private-asset-id", ASSET_ID]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "result=PASS",
        "operation=review-status",
        f"private_asset_id={ASSET_ID}",
        "review_state=complete",
    ]


def test_review_status_revalidates_changed_media(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = tool()
    root = repository(tmp_path)
    overlay = root / "runtime/test-corpus/visual/private-overlay"
    assets = overlay / "assets"
    results = overlay / "results"
    for directory in (overlay, assets, overlay / "review-frames", results, overlay / "temp"):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
    media = assets / f"{ASSET_ID}.mkv"
    media.write_bytes(MEDIA + b"changed")
    media.chmod(0o600)
    index = overlay / "index.json"
    index.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "assets": [{"private_asset_id": ASSET_ID, "basename": media.name}],
            }
        ),
        encoding="ascii",
    )
    index.chmod(0o600)
    descriptor_path = root / "tests/fixtures/visual_corpus/private_overlay.json"
    descriptor_path.parent.mkdir(parents=True)
    descriptor_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_type": "PRIVATE_LOCAL_CAPTURE",
                "assets": [
                    {
                        "private_asset_id": ASSET_ID,
                        "sha256": __import__("hashlib").sha256(MEDIA).hexdigest(),
                        "bytes": len(MEDIA),
                        "duration_ms": 25000,
                        "codec": "hevc",
                        "width": 2560,
                        "height": 1440,
                        "fps": 10.0,
                        "scenario_ids": ["WIDE-02", "NEG-01"],
                        "authorization_review": "approved",
                        "privacy_review": "approved",
                    }
                ],
            }
        ),
        encoding="ascii",
    )
    receipt = results / f"{ASSET_ID}.review.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "private_asset_id": ASSET_ID,
                "sha256": __import__("hashlib").sha256(MEDIA).hexdigest(),
                "reviewer_type": "human",
                "sampling_interval_ms": 500,
                "first_frame_reviewed": True,
                "last_frame_reviewed": True,
                "realtime_playback_reviewed": True,
                "authorization_review": "approved",
                "privacy_review": "approved",
            }
        ),
        encoding="ascii",
    )
    receipt.chmod(0o600)
    monkeypatch.setattr(module, "probe_private_media", generated_probe)

    assert module.review_status(root, ASSET_ID).state == "incomplete"


def test_validate_command_reports_public_and_local_readiness_separately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = tool()
    root = repository(tmp_path)
    descriptor_path = root / "tests/fixtures/visual_corpus/private_overlay.json"
    descriptor_path.parent.mkdir(parents=True)
    descriptor_path.write_text("{}", encoding="ascii")
    overlay = root / "runtime/test-corpus/visual/private-overlay"
    overlay.mkdir(parents=True)
    asset = PrivateOverlayDescriptor.model_validate(
        {
            "schema_version": 1,
            "source_type": "PRIVATE_LOCAL_CAPTURE",
            "assets": [
                {
                    "private_asset_id": ASSET_ID,
                    "sha256": "1" * 64,
                    "bytes": 1,
                    "duration_ms": 25000,
                    "codec": "hevc",
                    "width": 1,
                    "height": 1,
                    "fps": 10.0,
                    "scenario_ids": ["WIDE-02", "NEG-01"],
                    "authorization_review": "approved",
                    "privacy_review": "approved",
                }
            ],
        }
    )
    monkeypatch.setattr(module, "load_private_overlay_descriptor", lambda _path: asset)
    monkeypatch.setattr(
        module,
        "validate_private_overlay",
        lambda *_args, **_kwargs: PrivateOverlayValidation(
            readiness=LocalOverlayReadiness.LOCAL_PARTIAL,
            reason="private_overlay_valid",
            asset_count=1,
            scenario_count=2,
            scenario_ids=(ScenarioId.WIDE_02, ScenarioId.NEG_01),
            content_review_complete=True,
        ),
    )
    monkeypatch.setattr(
        module,
        "load_manifest",
        lambda _path: SimpleNamespace(readiness=CorpusReadiness.PARTIAL),
    )

    assert module._validate_command(root) == 0
    assert capsys.readouterr().out.splitlines() == [
        "result=PASS",
        "operation=validate",
        "public_readiness=PARTIAL",
        "local_readiness=LOCAL_READY",
        "reason=private_overlay_ready",
        "asset_count=1",
        "scenario_count=2",
    ]


def test_validate_command_requires_both_fixed_local_scenarios(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = tool()
    root = repository(tmp_path)
    descriptor_path = root / "tests/fixtures/visual_corpus/private_overlay.json"
    descriptor_path.parent.mkdir(parents=True)
    descriptor_path.write_text("{}", encoding="ascii")
    overlay = root / "runtime/test-corpus/visual/private-overlay"
    overlay.mkdir(parents=True)
    monkeypatch.setattr(
        module,
        "load_private_overlay_descriptor",
        lambda _path: SimpleNamespace(),
    )
    monkeypatch.setattr(
        module,
        "validate_private_overlay",
        lambda *_args, **_kwargs: PrivateOverlayValidation(
            readiness=LocalOverlayReadiness.LOCAL_PARTIAL,
            reason="private_overlay_valid",
            asset_count=1,
            scenario_count=1,
            scenario_ids=(ScenarioId.WIDE_02,),
            content_review_complete=True,
        ),
    )
    monkeypatch.setattr(
        module,
        "load_manifest",
        lambda _path: SimpleNamespace(readiness=CorpusReadiness.PARTIAL),
    )

    assert module._validate_command(root) == 0
    output = capsys.readouterr().out.splitlines()
    assert "public_readiness=PARTIAL" in output
    assert "local_readiness=LOCAL_PARTIAL" in output
    assert "reason=private_overlay_scenario_invalid" in output
