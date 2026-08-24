from __future__ import annotations

from pathlib import Path

from services.voice.vad_diagnostic import (
    PrivateVadMetrics,
    VadDiagnosticReport,
)
from tools import voice_vad_diagnostic


class Diagnostic:
    def run(self) -> VadDiagnosticReport:
        return VadDiagnosticReport(
            gate_passed=False,
            reason="vad_candidate_unavailable",
            control_rms_dbfs_milli=-12_000,
            control_peak_milli=800,
            control_span_count=1,
            private=(
                PrivateVadMetrics(
                    "feeding_start_dad", -28_000, 200, 0, 12_000, 1
                ),
            ),
        )


def test_tool_prints_only_public_ids_and_aggregate_metrics(tmp_path: Path) -> None:
    output: list[str] = []

    result = voice_vad_diagnostic.main(
        project_root=tmp_path,
        diagnostic_builder=lambda _root: Diagnostic(),
        printer=output.append,
    )

    assert result == 1
    assert output == [
        "result=FAIL",
        "operation=vad-diagnostic",
        "reason=vad_candidate_unavailable",
        "gate_passed=false",
        "control_rms_dbfs_milli=-12000",
        "control_peak_milli=800",
        "control_span_count=1",
        "private_1_prompt_id=feeding_start_dad",
        "private_1_rms_dbfs_milli=-28000",
        "private_1_raw_peak_milli=200",
        "private_1_raw_span_count=0",
        "private_1_applied_gain_db_milli=12000",
        "private_1_final_span_count=1",
    ]
    assert "pcm" not in "\n".join(output)
