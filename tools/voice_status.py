from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


_REASONS = {
    "accepted_pending", "saved", "needs_identity", "needs_confirmation",
    "identity_mismatch", "state_conflict", "temporarily_unavailable", "rejected",
    "voice_disabled", "voice_runtime_unavailable", "voice_startup_failed",
    "voice_worker_unavailable", "voice_audio_unavailable", "voice_model_unavailable",
    "voice_output_unavailable", "idle", "ignored",
    "listen_only_idle", "listen_only_ignored", "listen_only_acknowledging",
    "listen_only_armed", "listen_only_acknowledged", "listen_only_timeout",
}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    required_mode: str | None = None
    not_before_epoch_us: int | None = None
    if not args:
        path = Path("runtime/status/voice.json")
    elif len(args) == 1:
        path = Path(args[0])
    elif len(args) == 3 and args[1] == "--require-mode":
        path = Path(args[0])
        required_mode = args[2]
    elif (
        len(args) == 5
        and args[1] == "--require-mode"
        and args[3] == "--not-before-epoch-us"
    ):
        path = Path(args[0])
        required_mode = args[2]
        try:
            not_before_epoch_us = int(args[4])
        except ValueError:
            print("voice_status=unavailable")
            return 2
        if not 0 <= not_before_epoch_us <= 4_102_444_800_000_000:
            print("voice_status=unavailable")
            return 2
    else:
        print("voice_status=unavailable")
        return 2
    try:
        payload = json.loads(path.read_text(encoding="ascii"))
        if set(payload) != {
            "schema_version",
            "checked_at",
            "mode",
            "worker_state",
            "reason",
            "processed_count",
            "last_latency_ms",
        }:
            raise ValueError
        state = payload["worker_state"]
        mode = payload["mode"]
        reason = payload["reason"]
        count = payload["processed_count"]
        latency = payload["last_latency_ms"]
        checked_at = payload["checked_at"]
        if not_before_epoch_us is not None:
            if type(checked_at) is not str:
                raise ValueError
            checked = datetime.fromisoformat(checked_at)
            checked_epoch_us = int(checked.timestamp() * 1_000_000)
            if checked.tzinfo is None or checked_epoch_us < not_before_epoch_us:
                raise ValueError
        if (
            payload["schema_version"] != 2
            or mode not in {"disabled", "listen_only", "care"}
            or (required_mode is not None and mode != required_mode)
            or state not in {"disabled", "healthy", "degraded"}
            or reason not in _REASONS
            or type(count) is not int
            or not 0 <= count <= 9_007_199_254_740_991
            or (
                latency is not None
                and (type(latency) is not int or not 0 <= latency <= 30_000)
            )
        ):
            raise ValueError
    except Exception:
        print("voice_status=unavailable")
        return 2
    latency_text = "none" if latency is None else str(latency)
    print(
        f"voice_status={state} mode={mode} reason={reason} processed_count={count} "
        f"last_latency_ms={latency_text}"
    )
    return 0 if state in {"disabled", "healthy"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
