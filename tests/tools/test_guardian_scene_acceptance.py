from __future__ import annotations

from collections.abc import Iterator
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys

from services.vision.scene_acceptance import SCENES, GuardianSceneAcceptanceStore
from tools.guardian_scene_acceptance import _terminal_inputs, run_scene_acceptance


def answers(*values: str) -> Iterator[str]:
    return iter(values)


def interrupted_answers() -> Iterator[str]:
    yield "YES"
    yield "YES"
    yield "READY"
    yield "correct"
    raise KeyboardInterrupt


def full_answers(*, obstruction_miss: bool = False) -> list[str]:
    values = ["YES", "YES"]
    for scene in SCENES:
        values.append("READY")
        values.extend(["correct"] * 10)
        if scene == "camera_obstruction" and obstruction_miss:
            values[-1] = "missed"
    return values


def test_safety_rejection_writes_no_state(tmp_path: Path) -> None:
    lines: list[str] = []

    code = run_scene_acceptance(tmp_path, answers("NO"), lines.append)

    assert code == 1
    assert lines == [
        "FAIL scene safety safety_not_confirmed",
        "guardian_scene_test=FAIL",
    ]
    assert list(tmp_path.iterdir()) == []


def test_complete_simulation_records_all_trials_but_never_physical_pass(
    tmp_path: Path,
) -> None:
    lines: list[str] = []

    code = run_scene_acceptance(
        tmp_path,
        iter(full_answers(obstruction_miss=True)),
        lines.append,
        simulated=True,
    )

    assert code == 0
    assert lines[-1] == "guardian_scene_test=SIMULATED"
    stored = GuardianSceneAcceptanceStore(tmp_path).load()
    assert stored["state"] == "passed"
    assert len(stored["trials"]) == 70


def test_eof_keeps_incomplete_run_and_resume_does_not_duplicate_trials(
    tmp_path: Path,
) -> None:
    first_lines: list[str] = []
    first = run_scene_acceptance(
        tmp_path,
        answers("YES", "YES", "READY", "correct", "correct"),
        first_lines.append,
    )

    assert first == 2
    assert first_lines[-1] == "guardian_scene_test=INCOMPLETE"
    assert len(GuardianSceneAcceptanceStore(tmp_path).load()["trials"]) == 2

    remaining = ["YES", "YES", "READY"] + ["correct"] * 8
    for _scene in SCENES[1:]:
        remaining.extend(["READY"] + ["correct"] * 10)
    second_lines: list[str] = []
    second = run_scene_acceptance(tmp_path, iter(remaining), second_lines.append)

    assert second == 0
    assert second_lines[-1] == "guardian_scene_test=PASS"
    assert len(GuardianSceneAcceptanceStore(tmp_path).load()["trials"]) == 70


def test_keyboard_interrupt_keeps_fixed_incomplete_output(tmp_path: Path) -> None:
    lines: list[str] = []

    code = run_scene_acceptance(tmp_path, interrupted_answers(), lines.append)

    assert code == 2
    assert lines[-2:] == [
        "INCOMPLETE scene input",
        "guardian_scene_test=INCOMPLETE",
    ]
    assert len(GuardianSceneAcceptanceStore(tmp_path).load()["trials"]) == 1


def test_negative_scene_false_positive_fails_gate(tmp_path: Path) -> None:
    values = full_answers()
    values[3] = "false_positive"
    lines: list[str] = []

    code = run_scene_acceptance(tmp_path, iter(values), lines.append)

    assert code == 1
    assert lines[-1] == "guardian_scene_test=FAIL"


def test_invalid_outcome_reprompts_without_recording_a_trial(tmp_path: Path) -> None:
    values = full_answers()
    values.insert(3, "")
    lines: list[str] = []

    code = run_scene_acceptance(tmp_path, iter(values), lines.append)

    assert code == 0
    assert "RETRY scene input invalid_outcome" in lines
    assert len(GuardianSceneAcceptanceStore(tmp_path).load()["trials"]) == 70


def test_output_contains_only_fixed_ascii_status_lines(tmp_path: Path) -> None:
    lines: list[str] = []

    run_scene_acceptance(tmp_path, iter(full_answers()), lines.append)

    assert all(line.isascii() for line in lines)
    assert not any(str(tmp_path) in line for line in lines)
    assert not any("http" in line or "ntfy" in line for line in lines)
    assert "PREPARE scene empty_bed trials_remaining=10 type=READY" in lines
    assert "INPUT scene trial scene=empty_bed count=1/10" in lines
    assert "SUMMARY scene empty_bed correct=10 false_positive=0 missed=0 unavailable=0" in lines


def test_corrupt_existing_state_fails_closed_without_replacement(tmp_path: Path) -> None:
    target = tmp_path / "guardian-scene-acceptance.json"
    target.write_text("private-corrupt-state", encoding="utf-8")
    lines: list[str] = []

    code = run_scene_acceptance(tmp_path, answers("YES", "YES"), lines.append)

    assert code == 1
    assert lines[-2:] == [
        "FAIL scene storage storage_failed",
        "guardian_scene_test=FAIL",
    ]
    assert target.read_text(encoding="utf-8") == "private-corrupt-state"


def test_cli_requires_terminal_before_creating_state(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "tools/guardian_scene_acceptance.py"],
        cwd=Path(__file__).resolve().parents[2],
        env=os.environ.copy(),
        input="YES\n" * 2,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "FAIL scene interactive interactive_required",
        "guardian_scene_test=FAIL",
    ]
    assert not (tmp_path / "guardian-scene-acceptance.json").exists()


def test_makefile_exposes_scene_command_without_running_it() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["make", "-n", "alpha-guardian-scene-test"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "./.venv-alpha/bin/python tools/guardian_scene_acceptance.py"
    ]


def test_terminal_inputs_use_separate_read_and_prompt_streams() -> None:
    input_stream = StringIO("YES\nYES\nREADY\ncorrect\n")
    output_stream = StringIO()

    values = list(_terminal_inputs(input_stream, output_stream))

    assert values == ["YES", "YES", "READY", "correct"]
    assert output_stream.getvalue().startswith("Confirm no real infant")
