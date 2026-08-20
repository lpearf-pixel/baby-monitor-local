from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.audio.feasibility import (
    AudioFeasibilityError,
    AudioMediaResult,
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
    return parser.parse_args(argv)


def _print_media(media: AudioMediaResult) -> None:
    print(f"source_video_codec={media.source_video_codec}")
    print(f"source_audio_codec={media.source_audio_codec}")
    print(f"alias_audio_codec={media.alias_audio_codec}")
    print(f"sample_rate_hz={media.sample_rate_hz}")
    print(f"channels={media.channels}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
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
