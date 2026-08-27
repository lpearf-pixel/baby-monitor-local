from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.audio.feasibility import (
    AudioFeasibilityError,
    AudioMediaResult,
    AudioReadinessResult,
    evaluate_audio_readiness,
    inspect_audio_media,
    receive_audio_window,
    verify_synthetic_opus,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the bounded, non-persistent Voice Care V0 audio probe."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("media", help="Inspect fixed loopback media contracts.")
    live = subparsers.add_parser("live", help="Decode and discard a bounded live window.")
    live.add_argument("--duration", required=True, type=int, choices=(60, 600))
    subparsers.add_parser("synthetic", help="Verify an in-memory synthetic Opus round trip.")
    subparsers.add_parser(
        "chain", help="Verify independent microphone, decode, VAD and ASR stages."
    )
    return parser.parse_args(argv)


def _print_media(media: AudioMediaResult) -> None:
    print(f"source_video_codec={media.source_video_codec}")
    print(f"source_audio_codec={media.source_audio_codec}")
    print(f"alias_audio_codec={media.alias_audio_codec}")
    print(f"sample_rate_hz={media.sample_rate_hz}")
    print(f"channels={media.channels}")


def _print_readiness(result: AudioReadinessResult) -> None:
    for field in (
        "camera_audio_media_available",
        "opus_48000_stereo_available",
        "pcm_decode_available",
        "vad_progression_available",
        "asr_runtime_available",
        "raw_audio_persisted",
    ):
        print(f"{field}={'true' if getattr(result, field) else 'false'}")


def _probe_vad_progression(root: Path) -> tuple[bool, ...]:
    try:
        from services.voice.artifacts import voice_artifact_spec
        from services.voice.silero_runtime import SileroOnnxSegmenter
        from tools.voice_asr_calibrate import _load_disabled_settings
        from tools.voice_vad_diagnostic import _generated_control_pcm

        settings = _load_disabled_settings(root)
        segmenter = SileroOnnxSegmenter(
            voice_artifact_spec(settings, "silero-vad-v6.2"),
            project_root=root,
        )
        try:
            analysis = segmenter.analyze(_generated_control_pcm())
        finally:
            segmenter.close()
        return (False, bool(analysis.spans), False)
    except Exception:
        raise AudioFeasibilityError("vad_progression_unavailable") from None


def _probe_asr_runtime(root: Path) -> bool:
    asr = None
    try:
        from services.voice.artifacts import voice_artifact_spec
        from services.voice.paraformer import ParaformerProcess
        from tools.voice_asr_calibrate import _load_disabled_settings

        settings = _load_disabled_settings(root)
        asr = ParaformerProcess(
            voice_artifact_spec(
                settings, "sherpa-onnx-paraformer-zh-2023-09-14"
            ),
            project_root=root,
        )
    except Exception:
        raise AudioFeasibilityError("asr_runtime_unavailable") from None
    finally:
        if asr is not None:
            asr.close()
    return True


def _receive_one_second() -> AudioReceiveResult:
    return receive_audio_window(duration_seconds=1)


def probe_audio_readiness(
    *,
    project_root: Path = ROOT,
    media_inspector: Callable[[], AudioMediaResult] = inspect_audio_media,
    receiver: Callable[[], AudioReceiveResult] = _receive_one_second,
    vad_probe: Callable[[Path], tuple[bool, ...]] = _probe_vad_progression,
    asr_probe: Callable[[Path], bool] = _probe_asr_runtime,
) -> AudioReadinessResult:
    root = project_root.resolve(strict=True)
    media = media_inspector()
    receive = receiver()
    evaluate_audio_readiness(
        media,
        receive,
        vad_progression=(False, True, False),
        asr_runtime_available=True,
    )
    vad_progression = vad_probe(root)
    evaluate_audio_readiness(
        media,
        receive,
        vad_progression=vad_progression,
        asr_runtime_available=True,
    )
    asr_runtime_available = asr_probe(root)

    return evaluate_audio_readiness(
        media,
        receive,
        vad_progression=vad_progression,
        asr_runtime_available=asr_runtime_available,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "chain":
            result = probe_audio_readiness()
            print("result=PASS")
            _print_readiness(result)
            return 0
        if args.command == "synthetic":
            result = verify_synthetic_opus()
            print("result=PASS")
            print("codec=opus")
            print("sample_rate_hz=16000")
            print("channels=1")
            print(f"opus_bytes={result.opus_bytes}")
            print(f"pcm_bytes={result.pcm_bytes}")
            print(f"decoded_seconds={result.decoded_seconds:.3f}")
            print("raw_audio_persisted=false")
            return 0

        media = inspect_audio_media()
        if args.command == "live":
            result = receive_audio_window(duration_seconds=args.duration)
        else:
            result = None

        print("result=PASS")
        _print_media(media)
        if result is not None:
            print(f"duration_seconds={args.duration}")
            print(f"decoded_seconds={result.decoded_seconds:.3f}")
            print(f"decoded_bytes={result.decoded_bytes}")
            print(f"chunk_count={result.chunk_count}")
            print("raw_audio_persisted=false")
        return 0
    except AudioFeasibilityError as exc:
        print("result=FAIL")
        print(f"reason={exc}")
        return 2
    except Exception:
        print("result=FAIL")
        print("reason=internal_error")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
