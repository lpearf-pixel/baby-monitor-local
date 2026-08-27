from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tools.voice_status import main


def test_status_cli_accepts_schema_v2_and_prints_only_bounded_aggregates(
    tmp_path: Path, capsys,
) -> None:
    path = tmp_path / "voice.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "checked_at": "2026-08-25T00:00:00+00:00",
                "mode": "listen_only",
                "worker_state": "healthy",
                "reason": "listen_only_idle",
                "processed_count": 4,
                "last_latency_ms": 90,
            }
        ),
        encoding="ascii",
    )

    assert main([str(path)]) == 0
    assert capsys.readouterr().out == (
        "voice_status=healthy mode=listen_only reason=listen_only_idle "
        "processed_count=4 last_latency_ms=90\n"
    )


def test_status_cli_prints_fixed_transition_counts_without_text(
    tmp_path: Path, capsys,
) -> None:
    path = tmp_path / "voice.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "checked_at": "2026-08-25T00:00:00+00:00",
                "mode": "listen_only",
                "worker_state": "healthy",
                "reason": "listen_only_idle",
                "processed_count": 1,
                "last_latency_ms": None,
                "transition_counts": {
                    "armed_timeouts": 1,
                    "ignored_followups": 2,
                    "ignored_far": 3,
                    "ignored_near_reply_echo": 4,
                    "ignored_near_start": 5,
                    "listen_only_action_rejected": 6,
                    "listen_only_burping_exact": 7,
                    "listen_only_diaper_exact": 8,
                    "listen_only_feeding_corrected": 9,
                    "listen_only_feeding_exact": 10,
                    "listen_only_medication_candidate": 11,
                    "output_failures": 12,
                    "replay_frames": 13,
                    "replay_ignored": 14,
                    "replay_utterances": 15,
                    "reply_echo_ignored": 16,
                    "utterances": 17,
                    "vad_speech_frames": 18,
                },
            }
        ),
        encoding="ascii",
    )

    assert main([str(path)]) == 0
    assert capsys.readouterr().out.endswith(
        "transition_counts=armed_timeouts:1,ignored_followups:2,"
        "ignored_far:3,ignored_near_reply_echo:4,ignored_near_start:5,"
        "listen_only_action_rejected:6,listen_only_burping_exact:7,"
        "listen_only_diaper_exact:8,listen_only_feeding_corrected:9,"
        "listen_only_feeding_exact:10,listen_only_medication_candidate:11,"
        "output_failures:12,replay_frames:13,replay_ignored:14,"
        "replay_utterances:15,reply_echo_ignored:16,utterances:17,"
        "vad_speech_frames:18\n"
    )


def test_status_cli_rejects_transcript_even_when_other_fields_are_valid(
    tmp_path: Path, capsys,
) -> None:
    path = tmp_path / "voice.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "checked_at": "2026-08-25T00:00:00+00:00",
                "mode": "listen_only",
                "worker_state": "healthy",
                "reason": "listen_only_idle",
                "processed_count": 0,
                "last_latency_ms": None,
                "transcript": "private speech",
            }
        ),
        encoding="ascii",
    )

    assert main([str(path)]) == 2
    assert capsys.readouterr().out == "voice_status=unavailable\n"


def test_status_cli_can_require_listen_only_mode(tmp_path: Path, capsys) -> None:
    path = tmp_path / "voice.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "checked_at": "2026-08-25T00:00:00+00:00",
                "mode": "listen_only",
                "worker_state": "healthy",
                "reason": "listen_only_idle",
                "processed_count": 0,
                "last_latency_ms": None,
            }
        ),
        encoding="ascii",
    )

    assert main([str(path), "--require-mode", "listen_only"]) == 0
    assert "mode=listen_only" in capsys.readouterr().out


def test_status_cli_rejects_readiness_written_before_this_start(
    tmp_path: Path, capsys,
) -> None:
    path = tmp_path / "voice.json"
    payload = {
        "schema_version": 2,
        "checked_at": "2026-08-25T00:00:01.500001+00:00",
        "mode": "listen_only",
        "worker_state": "healthy",
        "reason": "listen_only_idle",
        "processed_count": 0,
        "last_latency_ms": None,
    }
    path.write_text(json.dumps(payload), encoding="ascii")
    not_before = str(
        int(datetime(2026, 8, 25, 0, 0, 1, 500_000, tzinfo=UTC).timestamp() * 1_000_000)
    )
    arguments = [
        str(path), "--require-mode", "listen_only", "--not-before-epoch-us", not_before
    ]

    assert main(arguments) == 0
    capsys.readouterr()

    payload["checked_at"] = "2026-08-25T00:00:01.499999+00:00"
    path.write_text(json.dumps(payload), encoding="ascii")
    assert main(arguments) == 2
    assert capsys.readouterr().out == "voice_status=unavailable\n"


def test_status_cli_rejects_malformed_start_epoch_without_raw_error(
    tmp_path: Path, capsys,
) -> None:
    path = tmp_path / "voice.json"
    path.write_text("{}", encoding="ascii")

    assert main(
        [
            str(path),
            "--require-mode",
            "listen_only",
            "--not-before-epoch-us",
            "not-an-epoch",
        ]
    ) == 2
    assert capsys.readouterr().out == "voice_status=unavailable\n"
