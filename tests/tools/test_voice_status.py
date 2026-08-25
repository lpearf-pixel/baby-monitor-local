from __future__ import annotations

import json
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
