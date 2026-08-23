from __future__ import annotations

import json
import sys
from pathlib import Path


_REASONS = {
    "accepted_pending", "saved", "needs_identity", "needs_confirmation",
    "identity_mismatch", "state_conflict", "temporarily_unavailable", "rejected",
    "voice_disabled", "voice_runtime_unavailable", "voice_startup_failed",
    "voice_worker_unavailable", "voice_audio_unavailable", "voice_model_unavailable",
    "voice_output_unavailable", "idle", "ignored",
}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    path = Path(args[0]) if len(args) == 1 else Path("runtime/status/voice.json")
    try:
        payload = json.loads(path.read_text(encoding="ascii"))
        if set(payload) != {
            "schema_version",
            "checked_at",
            "worker_state",
            "reason",
            "processed_count",
            "last_latency_ms",
        }:
            raise ValueError
        state = payload["worker_state"]
        reason = payload["reason"]
        count = payload["processed_count"]
        latency = payload["last_latency_ms"]
        if (
            payload["schema_version"] != 1
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
        f"voice_status={state} reason={reason} processed_count={count} "
        f"last_latency_ms={latency_text}"
    )
    return 0 if state in {"disabled", "healthy"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
