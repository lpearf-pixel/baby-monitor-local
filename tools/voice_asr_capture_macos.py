"""Run supervised ASR rerecording under the macOS login launchd identity."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from services.voice.asr_corpus import PRIVATE_ASR_PROMPTS


CAPTURE_UNAVAILABLE = "voice_asr_capture_unavailable"
FIXED_EXECUTION_PATH = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
_STATUS_RELATIVE = Path("runtime/status/voice-asr-capture.txt")
_REQUEST_RELATIVE = Path("runtime/status/voice-asr-capture.request")
_COMMAND_RELATIVE = Path("tools/voice_asr_capture_macos.command")
_TERMINAL_APP = "/System/Applications/Utilities/Terminal.app"
_OPERATOR_LABEL = "com.babymonitor.voice-asr-operator"
_EXPECTED_DURATION_MS = 8_000
_COUNTDOWN_SECONDS = 10
_WAIT_SECONDS = 180


Runner = Callable[..., subprocess.CompletedProcess[str]]
Sleeper = Callable[[float], None]
Printer = Callable[[str], None]
InputFunction = Callable[[str], str]
JobRunner = Callable[[Path, str], int]
EvaluationJobRunner = Callable[[Path, str], int]
UidGetter = Callable[[], int]
_EVALUATIONS = frozenset({"paraformer", "vad-diagnostic"})


def parse_capture_result(output: str, prompt_id: str) -> tuple[str, ...]:
    _validate_prompt_id(prompt_id)
    expected = {
        "prompt_id": prompt_id,
        "prompt": PRIVATE_ASR_PROMPTS[prompt_id],
        "result": "PASS",
        "operation": "capture-fixed",
        "duration_ms": str(_EXPECTED_DURATION_MS),
        "encrypted_clip_persisted": "true",
        "capture_job_complete": "true",
    }
    values: dict[str, str] = {}
    for line in output.splitlines():
        if not line or "=" not in line:
            raise ValueError(CAPTURE_UNAVAILABLE)
        key, value = line.split("=", 1)
        if key in values or key not in expected:
            raise ValueError(CAPTURE_UNAVAILABLE)
        values[key] = value
    if values != expected:
        raise ValueError(CAPTURE_UNAVAILABLE)
    return (
        "result=PASS",
        "operation=capture-fixed",
        f"prompt_id={prompt_id}",
        f"duration_ms={_EXPECTED_DURATION_MS}",
        "encrypted_clip_persisted=true",
    )


def parse_evaluation_result(output: str, operation: str) -> tuple[str, ...]:
    if operation not in _EVALUATIONS:
        raise ValueError(CAPTURE_UNAVAILABLE)
    lines = output.splitlines()
    if not lines or lines[-1] != "login_job_complete=true":
        raise ValueError(CAPTURE_UNAVAILABLE)
    values: dict[str, str] = {}
    rendered: list[str] = []
    for line in lines[:-1]:
        if "=" not in line:
            raise ValueError(CAPTURE_UNAVAILABLE)
        key, value = line.split("=", 1)
        if key in values:
            raise ValueError(CAPTURE_UNAVAILABLE)
        values[key] = value
        rendered.append(line)
    allowed = _paraformer_keys(values) if operation == "paraformer" else _vad_keys()
    if set(values) != allowed or values.get("operation") != operation:
        raise ValueError(CAPTURE_UNAVAILABLE)
    if values.get("result") not in {"PASS", "FAIL"}:
        raise ValueError(CAPTURE_UNAVAILABLE)
    if values.get("gate_passed") not in {"true", "false"}:
        raise ValueError(CAPTURE_UNAVAILABLE)
    if (values["result"] == "PASS") != (values["gate_passed"] == "true"):
        raise ValueError(CAPTURE_UNAVAILABLE)
    if not all(_bounded_aggregate_value(key, value) for key, value in values.items()):
        raise ValueError(CAPTURE_UNAVAILABLE)
    return tuple(rendered)


def _paraformer_keys(values: dict[str, str]) -> set[str]:
    keys = {
        "result",
        "operation",
        "gate_passed",
        "selected_model",
        "paraformer_available",
        "paraformer_samples_evaluated",
        "paraformer_exact_matches",
        "paraformer_wake_matches",
        "paraformer_latency_p50_ms",
        "paraformer_latency_p95_ms",
        "paraformer_mismatch_prompt_ids",
        "paraformer_edit_distance_total",
        "paraformer_passed",
    }
    if values.get("result") == "FAIL":
        keys.add("reason")
    return keys


def _vad_keys() -> set[str]:
    keys = {
        "result",
        "operation",
        "reason",
        "gate_passed",
        "control_rms_dbfs_milli",
        "control_peak_milli",
        "control_span_count",
    }
    for index in range(1, 7):
        keys.update(
            {
                f"private_{index}_prompt_id",
                f"private_{index}_rms_dbfs_milli",
                f"private_{index}_raw_peak_milli",
                f"private_{index}_raw_span_count",
                f"private_{index}_applied_gain_db_milli",
                f"private_{index}_final_span_count",
            }
        )
    return keys


def _bounded_aggregate_value(key: str, value: str) -> bool:
    if not value or len(value) > 256 or any(character.isspace() for character in value):
        return False
    if key == "paraformer_mismatch_prompt_ids":
        return value == "none" or all(
            item in PRIVATE_ASR_PROMPTS for item in value.split(",")
        )
    if key.endswith("_prompt_id"):
        return value in PRIVATE_ASR_PROMPTS
    return re.fullmatch(r"[A-Za-z0-9_.+-]+", value) is not None


def _validate_prompt_id(prompt_id: str) -> None:
    if type(prompt_id) is not str or prompt_id not in PRIVATE_ASR_PROMPTS:
        raise ValueError(CAPTURE_UNAVAILABLE)


def _job(project_root: Path, prompt_id: str) -> int:
    from tools.voice_asr_calibrate import main as calibration_main

    return calibration_main(
        ["capture-fixed", "--prompt-id", prompt_id],
        project_root=project_root,
        input_fn=lambda _: "",
    )


def _evaluation_job(project_root: Path, operation: str) -> int:
    if operation == "paraformer":
        from tools.voice_asr_calibrate import main as calibration_main

        return calibration_main(["paraformer"], project_root=project_root)
    if operation == "vad-diagnostic":
        from tools.voice_vad_diagnostic import main as diagnostic_main

        return diagnostic_main(project_root=project_root)
    raise ValueError(CAPTURE_UNAVAILABLE)


def run_terminal_job(
    project_root: Path,
    *,
    input_fn: InputFunction = input,
    sleeper: Sleeper = time.sleep,
    printer: Printer = lambda line: print(line, file=sys.stderr, flush=True),
    job_runner: JobRunner = _job,
    evaluation_runner: EvaluationJobRunner = _evaluation_job,
    require_confirmation: bool = True,
    countdown_seconds: int = _COUNTDOWN_SECONDS,
) -> int:
    request = _read_request(project_root)
    if request in _EVALUATIONS:
        return evaluation_runner(project_root, request)
    prompt_id = request
    printer(f"prompt={PRIVATE_ASR_PROMPTS[prompt_id]}")
    if require_confirmation:
        printer("press_enter_to_start_countdown=")
        if input_fn("") != "":
            raise ValueError(CAPTURE_UNAVAILABLE)
    if type(countdown_seconds) is not int or not 0 <= countdown_seconds <= 10:
        raise ValueError(CAPTURE_UNAVAILABLE)
    for remaining in range(countdown_seconds, 0, -1):
        printer(f"capture_starts_in_seconds={remaining}")
        sleeper(1)
    return job_runner(project_root, prompt_id)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rerecord one fixed ASR prompt with the macOS login identity"
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)
    record = subparsers.add_parser("record")
    record.add_argument("--prompt-id", required=True, choices=tuple(PRIVATE_ASR_PROMPTS))
    subparsers.add_parser("paraformer")
    subparsers.add_parser("vad-diagnostic")
    subparsers.add_parser("login-job")
    subparsers.add_parser("terminal-job")
    arguments = parser.parse_args(argv)
    root = Path.cwd().resolve(strict=True)
    if arguments.operation in {"login-job", "terminal-job"}:
        try:
            request = _read_request(root)
            return_code = run_terminal_job(
                root,
                require_confirmation=arguments.operation == "terminal-job",
                countdown_seconds=(
                    _COUNTDOWN_SECONDS if arguments.operation == "terminal-job" else 0
                ),
            )
            print(
                "login_job_complete=true"
                if request in _EVALUATIONS
                else "capture_job_complete=true"
            )
            return return_code
        except (Exception, KeyboardInterrupt):
            print("result=FAIL")
            print("operation=login-job")
            print(f"reason={CAPTURE_UNAVAILABLE}")
            print("login_job_complete=true")
            return 1
    if arguments.operation in _EVALUATIONS:
        try:
            return run_login_evaluation(root, str(arguments.operation))
        except (Exception, KeyboardInterrupt):
            print("result=FAIL")
            print(f"operation={arguments.operation}")
            print(f"reason={CAPTURE_UNAVAILABLE}")
            return 1
    try:
        return run_login_capture(root, str(arguments.prompt_id))
    except (Exception, KeyboardInterrupt):
        print("result=FAIL")
        print("operation=record")
        print(f"reason={CAPTURE_UNAVAILABLE}")
        return 1


def run_login_capture(
    project_root: Path,
    prompt_id: str,
    *,
    opener: Runner = subprocess.run,
    sleeper: Sleeper = time.sleep,
    printer: Printer = lambda line: print(line, flush=True),
    platform_name: str = sys.platform,
    uid_getter: UidGetter = os.getuid,
) -> int:
    root = project_root.resolve(strict=True)
    _validate_prompt_id(prompt_id)
    if platform_name != "darwin":
        raise ValueError(CAPTURE_UNAVAILABLE)
    status_path = root / _STATUS_RELATIVE
    request_path = root / _REQUEST_RELATIVE
    status_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    status_path.parent.chmod(0o700)
    if request_path.is_symlink() or status_path.is_symlink():
        raise ValueError(CAPTURE_UNAVAILABLE)
    temporary = request_path.with_suffix(".request.tmp")
    if temporary.is_symlink():
        raise ValueError(CAPTURE_UNAVAILABLE)
    temporary.write_text(f"{prompt_id}\n", encoding="ascii")
    temporary.chmod(0o600)
    temporary.replace(request_path)
    request_path.chmod(0o600)
    status_path.write_text("", encoding="utf-8")
    status_path.chmod(0o600)
    printer(f"prompt={PRIVATE_ASR_PROMPTS[prompt_id]}")
    for remaining in range(_COUNTDOWN_SECONDS, 0, -1):
        printer(f"capture_starts_in_seconds={remaining}")
        sleeper(1)
    printer("capture_now=true")
    _run(
        opener,
        [
            "/bin/launchctl",
            "kickstart",
            "-k",
            f"gui/{uid_getter()}/{_OPERATOR_LABEL}",
        ],
        capture_output=True,
    )
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        output = status_path.read_text(encoding="utf-8")
        if output.endswith("capture_job_complete=true\n"):
            break
        sleeper(0.25)
    result = parse_capture_result(status_path.read_text(encoding="utf-8"), prompt_id)
    for line in result:
        printer(line)
    return 0


def run_login_evaluation(
    project_root: Path,
    operation: str,
    *,
    opener: Runner = subprocess.run,
    sleeper: Sleeper = time.sleep,
    printer: Printer = print,
    platform_name: str = sys.platform,
    uid_getter: UidGetter = os.getuid,
) -> int:
    if operation not in _EVALUATIONS:
        raise ValueError(CAPTURE_UNAVAILABLE)
    root = project_root.resolve(strict=True)
    if platform_name != "darwin":
        raise ValueError(CAPTURE_UNAVAILABLE)
    status_path, request_path = _prepare_login_job(root)
    _write_request(request_path, operation)
    status_path.write_text("", encoding="utf-8")
    status_path.chmod(0o600)
    _run(
        opener,
        [
            "/bin/launchctl",
            "kickstart",
            "-k",
            f"gui/{uid_getter()}/{_OPERATOR_LABEL}",
        ],
        capture_output=True,
    )
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        output = status_path.read_text(encoding="utf-8")
        if output.endswith("login_job_complete=true\n"):
            break
        sleeper(0.25)
    rendered = parse_evaluation_result(
        status_path.read_text(encoding="utf-8"), operation
    )
    for line in rendered:
        printer(line)
    return 0 if rendered[0] == "result=PASS" else 1


def _prepare_login_job(root: Path) -> tuple[Path, Path]:
    status_path = root / _STATUS_RELATIVE
    request_path = root / _REQUEST_RELATIVE
    status_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    status_path.parent.chmod(0o700)
    if request_path.is_symlink() or status_path.is_symlink():
        raise ValueError(CAPTURE_UNAVAILABLE)
    return status_path, request_path


def _write_request(request_path: Path, value: str) -> None:
    if value not in _EVALUATIONS and value not in PRIVATE_ASR_PROMPTS:
        raise ValueError(CAPTURE_UNAVAILABLE)
    temporary = request_path.with_suffix(".request.tmp")
    if temporary.is_symlink():
        raise ValueError(CAPTURE_UNAVAILABLE)
    temporary.write_text(f"{value}\n", encoding="ascii")
    temporary.chmod(0o600)
    temporary.replace(request_path)
    request_path.chmod(0o600)


def _read_request(project_root: Path) -> str:
    request_path = project_root / _REQUEST_RELATIVE
    if request_path.is_symlink() or not request_path.is_file():
        raise ValueError(CAPTURE_UNAVAILABLE)
    value = request_path.read_text(encoding="ascii")
    if not value.endswith("\n") or value.count("\n") != 1:
        raise ValueError(CAPTURE_UNAVAILABLE)
    request = value[:-1]
    if request not in _EVALUATIONS:
        _validate_prompt_id(request)
    return request


def _run(
    runner: Runner,
    command: list[str],
    *,
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return runner(
        command,
        check=check,
        capture_output=capture_output,
        text=True,
        timeout=10,
    )


if __name__ == "__main__":
    raise SystemExit(main())
