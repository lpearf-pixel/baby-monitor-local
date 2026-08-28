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
    "listen_only_acknowledged_corrected", "listen_only_high_risk_candidate",
    "listen_only_replay_ignored", "listen_only_reply_echo_ignored",
    "listen_only_followup_near_start", "listen_only_followup_near_reply_echo",
    "listen_only_followup_far",
}
_TRANSITION_KEYS = (
    "armed_timeouts",
    "ignored_followups",
    "ignored_far",
    "ignored_near_reply_echo",
    "ignored_near_start",
    "voice_diagnostic_drops",
    "voice_diagnostic_failures",
    "voice_diagnostic_records",
    "listen_only_action_rejected",
    "listen_only_burping_exact",
    "listen_only_diaper_exact",
    "listen_only_feeding_corrected",
    "listen_only_feeding_exact",
    "listen_only_medication_candidate",
    "output_failures",
    "replay_frames",
    "replay_ignored",
    "replay_utterances",
    "reply_echo_ignored",
    "utterances",
    "vad_speech_frames",
)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    required_mode: str | None = None
    not_before_epoch_us: int | None = None
    required_worker_pid: int | None = None
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
        and args[3] in {"--not-before-epoch-us", "--require-worker-pid"}
    ):
        path = Path(args[0])
        required_mode = args[2]
        try:
            value = int(args[4])
        except ValueError:
            print("voice_status=unavailable")
            return 2
        if args[3] == "--not-before-epoch-us":
            not_before_epoch_us = value
            valid = 0 <= value <= 4_102_444_800_000_000
        else:
            required_worker_pid = value
            valid = 2 <= value <= 2_147_483_647
        if not valid:
            print("voice_status=unavailable")
            return 2
    elif (
        len(args) == 7
        and args[1] == "--require-mode"
        and args[3] == "--require-worker-pid"
        and args[5] == "--not-before-epoch-us"
    ):
        path = Path(args[0])
        required_mode = args[2]
        try:
            required_worker_pid = int(args[4])
            not_before_epoch_us = int(args[6])
        except ValueError:
            print("voice_status=unavailable")
            return 2
        if (
            not 2 <= required_worker_pid <= 2_147_483_647
            or not 0 <= not_before_epoch_us <= 4_102_444_800_000_000
        ):
            print("voice_status=unavailable")
            return 2
    else:
        print("voice_status=unavailable")
        return 2
    try:
        payload = json.loads(path.read_text(encoding="ascii"))
        base_keys = {
            "schema_version",
            "checked_at",
            "mode",
            "worker_state",
            "reason",
            "processed_count",
            "last_latency_ms",
        }
        allowed_key_sets = {
            frozenset(base_keys),
            frozenset(base_keys | {"transition_counts"}),
            frozenset(base_keys | {"worker_pid"}),
            frozenset(base_keys | {"transition_counts", "worker_pid"}),
        }
        if frozenset(payload) not in allowed_key_sets:
            raise ValueError
        state = payload["worker_state"]
        mode = payload["mode"]
        reason = payload["reason"]
        count = payload["processed_count"]
        latency = payload["last_latency_ms"]
        checked_at = payload["checked_at"]
        worker_pid = payload.get("worker_pid")
        transition_counts = payload.get("transition_counts")
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
            or (
                worker_pid is not None
                and (
                    type(worker_pid) is not int
                    or not 2 <= worker_pid <= 2_147_483_647
                )
            )
            or (
                required_worker_pid is not None
                and (worker_pid != required_worker_pid or state != "healthy")
            )
            or type(count) is not int
            or not 0 <= count <= 9_007_199_254_740_991
            or (
                latency is not None
                and (type(latency) is not int or not 0 <= latency <= 30_000)
            )
            or (
                transition_counts is not None
                and (
                    mode != "listen_only"
                    or not isinstance(transition_counts, dict)
                    or set(transition_counts) != set(_TRANSITION_KEYS)
                    or any(
                        type(transition_counts[key]) is not int
                        or not 0 <= transition_counts[key] <= 9_007_199_254_740_991
                        for key in _TRANSITION_KEYS
                    )
                )
            )
        ):
            raise ValueError
    except Exception:
        print("voice_status=unavailable")
        return 2
    latency_text = "none" if latency is None else str(latency)
    transition_text = ""
    if transition_counts is not None:
        transition_text = "\ntransition_counts=" + ",".join(
            f"{key}:{transition_counts[key]}" for key in _TRANSITION_KEYS
        )
    print(
        f"voice_status={state} mode={mode} reason={reason} processed_count={count} "
        f"last_latency_ms={latency_text}{transition_text}"
    )
    return 0 if state in {"disabled", "healthy"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
