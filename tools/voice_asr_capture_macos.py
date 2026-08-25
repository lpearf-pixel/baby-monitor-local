"""Run supervised ASR rerecording under the macOS login launchd identity."""

from __future__ import annotations

import argparse
import fcntl
import os
import re
import secrets
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterator

from services.voice.asr_corpus import PRIVATE_ASR_PROMPTS


CAPTURE_UNAVAILABLE = "voice_asr_capture_unavailable"
FIXED_EXECUTION_PATH = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
_STATUS_RELATIVE = Path("runtime/status/voice-asr-capture.txt")
_REQUEST_RELATIVE = Path("runtime/status/voice-asr-capture.request")
_ACTIVE_REQUEST_RELATIVE = Path("runtime/status/voice-asr-capture.active")
_PARENT_LOCK_RELATIVE = Path("runtime/status/voice-asr-capture.lock")
_BLOCKED_RELATIVE = Path("runtime/status/voice-asr-capture.blocked")
_COMMAND_RELATIVE = Path("tools/voice_asr_capture_macos.command")
_TERMINAL_APP = "/System/Applications/Utilities/Terminal.app"
_OPERATOR_LABEL = "com.babymonitor.voice-asr-operator"
_EXPECTED_DURATION_MS = 8_000
_COUNTDOWN_SECONDS = 10
_WAIT_SECONDS = 180
_STOP_WAIT_SECONDS = 5
_DOMAIN_OUTPUT_LIMIT = 262_144


Runner = Callable[..., subprocess.CompletedProcess[str]]
Sleeper = Callable[[float], None]
Printer = Callable[[str], None]
InputFunction = Callable[[str], str]
JobRunner = Callable[[Path, str], int]
EvaluationJobRunner = Callable[[Path, str], int]
UidGetter = Callable[[], int]
_EVALUATIONS = frozenset({"paraformer", "vad-diagnostic", "preflight"})
_REQUEST_ID_PATTERN = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class _Request:
    request_id: str
    operation: str


@dataclass(frozen=True)
class _RequestOwnership:
    request_id: str
    device: int
    inode: int


@dataclass(frozen=True)
class _ClaimedRequest:
    request: _Request
    ownership: _RequestOwnership


@dataclass(frozen=True)
class _BlockedOwnership:
    request_id: str
    device: int
    inode: int


class _OperatorState(Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


class _KickstartState(Enum):
    DEFINITE_FAILURE = "definite_failure"
    LAUNCHED = "launched"
    POSSIBLY_LAUNCHED = "possibly_launched"


def parse_capture_result(
    output: str, prompt_id: str, request_id: str
) -> tuple[str, ...]:
    _validate_prompt_id(prompt_id)
    _validate_request_id(request_id)
    expected = {
        "prompt_id": prompt_id,
        "prompt": PRIVATE_ASR_PROMPTS[prompt_id],
        "result": "PASS",
        "operation": "capture-fixed",
        "duration_ms": str(_EXPECTED_DURATION_MS),
        "encrypted_clip_persisted": "true",
        "request_id": request_id,
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


def parse_evaluation_result(
    output: str, operation: str, request_id: str
) -> tuple[str, ...]:
    if operation not in _EVALUATIONS:
        raise ValueError(CAPTURE_UNAVAILABLE)
    _validate_request_id(request_id)
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
        if key != "request_id":
            rendered.append(line)
    allowed = (
        _paraformer_keys(values)
        if operation == "paraformer"
        else _preflight_keys(values)
        if operation == "preflight"
        else _vad_keys()
    )
    if set(values) != allowed or values.get("operation") != operation:
        raise ValueError(CAPTURE_UNAVAILABLE)
    if values.get("result") not in {"PASS", "FAIL"}:
        raise ValueError(CAPTURE_UNAVAILABLE)
    if values.get("gate_passed") not in {"true", "false"}:
        raise ValueError(CAPTURE_UNAVAILABLE)
    if values.get("request_id") != request_id:
        raise ValueError(CAPTURE_UNAVAILABLE)
    if (values["result"] == "PASS") != (values["gate_passed"] == "true"):
        raise ValueError(CAPTURE_UNAVAILABLE)
    if operation == "preflight" and not _valid_preflight_values(values):
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
        "request_id",
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
        "request_id",
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


def _preflight_keys(values: dict[str, str]) -> set[str]:
    keys = {
        "result",
        "operation",
        "voice_preflight",
        "gate_passed",
        "request_id",
    }
    if values.get("result") == "PASS":
        keys.update(
            {
                "asr_profile",
                "keychain",
                "asr_artifact",
                "silero_artifact",
            }
        )
    else:
        keys.add("reason")
    return keys


def _valid_preflight_values(values: dict[str, str]) -> bool:
    if values.get("result") == "PASS":
        return all(
            values.get(key) == expected
            for key, expected in {
                "operation": "preflight",
                "voice_preflight": "available",
                "gate_passed": "true",
                "asr_profile": "paraformer",
                "keychain": "available",
                "asr_artifact": "available",
                "silero_artifact": "available",
            }.items()
        )
    return (
        values.get("result") == "FAIL"
        and values.get("operation") == "preflight"
        and values.get("voice_preflight") == "unavailable"
        and values.get("gate_passed") == "false"
        and values.get("reason")
        in {
            "voice_preflight_unavailable",
            "voice_keychain_unavailable",
            "voice_model_unavailable",
        }
    )


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


def _validate_request_id(request_id: str) -> None:
    if type(request_id) is not str or _REQUEST_ID_PATTERN.fullmatch(request_id) is None:
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
    if operation == "preflight":
        from tools.run_voice_worker import main as worker_main

        return worker_main(
            [
                "--preflight",
                "--voice-models",
                str(project_root / "runtime/config/voice-care-models.json"),
            ],
            project_root=project_root,
        )
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
    claimed_request: _ClaimedRequest | None = None,
) -> int:
    claim = claimed_request or _claim_request(project_root)
    request = claim.request
    owns_claim = claimed_request is None
    try:
        if request.operation in _EVALUATIONS:
            return evaluation_runner(project_root, request.operation)
        prompt_id = request.operation
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
    finally:
        if owns_claim:
            _remove_owned_request(
                project_root / _ACTIVE_REQUEST_RELATIVE, claim.ownership
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rerecord one fixed ASR prompt with the macOS login identity"
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)
    record = subparsers.add_parser("record")
    record.add_argument("--prompt-id", required=True, choices=tuple(PRIVATE_ASR_PROMPTS))
    subparsers.add_parser("paraformer")
    subparsers.add_parser("vad-diagnostic")
    subparsers.add_parser("preflight")
    subparsers.add_parser("recover")
    subparsers.add_parser("login-job")
    subparsers.add_parser("terminal-job")
    arguments = parser.parse_args(argv)
    root = Path.cwd().resolve(strict=True)
    if arguments.operation == "recover":
        try:
            return recover_login_job(root)
        except (Exception, KeyboardInterrupt):
            print("result=FAIL")
            print("operation=recover")
            print(f"reason={CAPTURE_UNAVAILABLE}")
            return 1
    if arguments.operation in {"login-job", "terminal-job"}:
        claim: _ClaimedRequest | None = None
        try:
            claim = _claim_request(root)
            request = claim.request
            return_code = run_terminal_job(
                root,
                require_confirmation=arguments.operation == "terminal-job",
                countdown_seconds=(
                    _COUNTDOWN_SECONDS if arguments.operation == "terminal-job" else 0
                ),
                claimed_request=claim,
            )
            print(f"request_id={request.request_id}")
            print(
                "login_job_complete=true"
                if request.operation in _EVALUATIONS
                else "capture_job_complete=true"
            )
            return return_code
        except (Exception, KeyboardInterrupt):
            print("result=FAIL")
            print("operation=login-job")
            print(f"reason={CAPTURE_UNAVAILABLE}")
            if claim is not None:
                print(f"request_id={claim.request.request_id}")
            print(
                "capture_job_complete=true"
                if claim is not None
                and claim.request.operation not in _EVALUATIONS
                else "login_job_complete=true"
            )
            return 1
        finally:
            if claim is not None:
                _remove_owned_request(
                    root / _ACTIVE_REQUEST_RELATIVE, claim.ownership
                )
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
    with _parent_request_lock(root):
        status_path, request_path = _prepare_login_job(root)
        request = _new_request(prompt_id)
        target = f"gui/{uid_getter()}/{_OPERATOR_LABEL}"
        kickstart_state = _KickstartState.DEFINITE_FAILURE
        ownership: _RequestOwnership | None = None
        preserve_request = False
        try:
            status_path.write_text("", encoding="utf-8")
            status_path.chmod(0o600)
            printer(f"prompt={PRIVATE_ASR_PROMPTS[prompt_id]}")
            for remaining in range(_COUNTDOWN_SECONDS, 0, -1):
                printer(f"capture_starts_in_seconds={remaining}")
                sleeper(1)
            printer("capture_now=true")
            ownership = _write_request(request_path, request)
            kickstart_state = _KickstartState.POSSIBLY_LAUNCHED
            try:
                _kickstart_operator(opener, target)
            except subprocess.CalledProcessError:
                kickstart_state = _KickstartState.DEFINITE_FAILURE
                raise
            else:
                kickstart_state = _KickstartState.LAUNCHED
            _wait_for_status(status_path, "capture_job_complete=true\n", sleeper)
            result = parse_capture_result(
                status_path.read_text(encoding="utf-8"),
                prompt_id,
                request.request_id,
            )
            for line in result:
                printer(line)
            return 0
        except (Exception, KeyboardInterrupt):
            if (
                kickstart_state is not _KickstartState.DEFINITE_FAILURE
                and not _stop_operator(opener, target, sleeper)
            ):
                if ownership is not None:
                    preserve_request = True
                    _mark_blocked(root, ownership)
                raise ValueError(CAPTURE_UNAVAILABLE) from None
            raise
        finally:
            if ownership is not None and not preserve_request:
                _cleanup_owned_request(root, ownership)


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
    with _parent_request_lock(root):
        status_path, request_path = _prepare_login_job(root)
        request = _new_request(operation)
        target = f"gui/{uid_getter()}/{_OPERATOR_LABEL}"
        kickstart_state = _KickstartState.DEFINITE_FAILURE
        ownership: _RequestOwnership | None = None
        preserve_request = False
        try:
            status_path.write_text("", encoding="utf-8")
            status_path.chmod(0o600)
            ownership = _write_request(request_path, request)
            kickstart_state = _KickstartState.POSSIBLY_LAUNCHED
            try:
                _kickstart_operator(opener, target)
            except subprocess.CalledProcessError:
                kickstart_state = _KickstartState.DEFINITE_FAILURE
                raise
            else:
                kickstart_state = _KickstartState.LAUNCHED
            _wait_for_status(status_path, "login_job_complete=true\n", sleeper)
            rendered = parse_evaluation_result(
                status_path.read_text(encoding="utf-8"),
                operation,
                request.request_id,
            )
            for line in rendered:
                printer(line)
            return 0 if rendered[0] == "result=PASS" else 1
        except (Exception, KeyboardInterrupt):
            if (
                kickstart_state is not _KickstartState.DEFINITE_FAILURE
                and not _stop_operator(opener, target, sleeper)
            ):
                if ownership is not None:
                    preserve_request = True
                    _mark_blocked(root, ownership)
                raise ValueError(CAPTURE_UNAVAILABLE) from None
            raise
        finally:
            if ownership is not None and not preserve_request:
                _cleanup_owned_request(root, ownership)


def recover_login_job(
    project_root: Path,
    *,
    opener: Runner = subprocess.run,
    printer: Printer = print,
    platform_name: str = sys.platform,
    uid_getter: UidGetter = os.getuid,
) -> int:
    root = project_root.resolve(strict=True)
    if platform_name != "darwin":
        raise ValueError(CAPTURE_UNAVAILABLE)
    with _parent_request_lock(root):
        domain = f"gui/{uid_getter()}"
        target = f"{domain}/{_OPERATOR_LABEL}"
        _run(
            opener,
            ["/bin/launchctl", "bootout", target],
            check=False,
            capture_output=True,
        )
        if not _operator_label_is_absent(opener, domain):
            raise ValueError(CAPTURE_UNAVAILABLE)

        request_ownership: list[tuple[Path, _RequestOwnership]] = []
        request_ids: set[str] = set()
        for relative in (_REQUEST_RELATIVE, _ACTIVE_REQUEST_RELATIVE):
            path = root / relative
            if path.is_symlink():
                raise ValueError(CAPTURE_UNAVAILABLE)
            if path.exists():
                request = _read_request_path(path)
                ownership = _request_ownership(path, request.request_id)
                request_ownership.append((path, ownership))
                request_ids.add(request.request_id)

        blocked_path = root / _BLOCKED_RELATIVE
        blocked_ownership: _BlockedOwnership | None = None
        if blocked_path.is_symlink():
            raise ValueError(CAPTURE_UNAVAILABLE)
        if blocked_path.exists():
            blocked_ownership = _read_blocked_ownership(blocked_path)
            request_ids.add(blocked_ownership.request_id)
        if len(request_ids) > 1:
            raise ValueError(CAPTURE_UNAVAILABLE)

        for path, ownership in request_ownership:
            _remove_owned_request(path, ownership)
        if blocked_ownership is not None:
            _remove_owned_blocked(blocked_path, blocked_ownership)
        if any(
            path.is_symlink() or path.exists()
            for path in (
                root / _REQUEST_RELATIVE,
                root / _ACTIVE_REQUEST_RELATIVE,
                blocked_path,
            )
        ):
            raise ValueError(CAPTURE_UNAVAILABLE)

        printer("result=PASS")
        printer("operation=recover")
        printer("state=cleared" if request_ids else "state=clean")
        return 0


def _prepare_login_job(root: Path) -> tuple[Path, Path]:
    status_path = root / _STATUS_RELATIVE
    request_path = root / _REQUEST_RELATIVE
    status_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    status_path.parent.chmod(0o700)
    active_path = root / _ACTIVE_REQUEST_RELATIVE
    blocked_path = root / _BLOCKED_RELATIVE
    if (
        request_path.is_symlink()
        or request_path.exists()
        or active_path.is_symlink()
        or active_path.exists()
        or blocked_path.is_symlink()
        or blocked_path.exists()
        or status_path.is_symlink()
    ):
        raise ValueError(CAPTURE_UNAVAILABLE)
    return status_path, request_path


def _write_request(
    request_path: Path, request: _Request
) -> _RequestOwnership:
    _validate_request(request)
    temporary = request_path.with_suffix(".request.tmp")
    if temporary.is_symlink():
        raise ValueError(CAPTURE_UNAVAILABLE)
    temporary.write_text(_request_payload(request), encoding="ascii")
    temporary.chmod(0o600)
    temporary.replace(request_path)
    return _request_ownership(request_path, request.request_id)


def _read_request_path(request_path: Path) -> _Request:
    if request_path.is_symlink() or not request_path.is_file():
        raise ValueError(CAPTURE_UNAVAILABLE)
    value = request_path.read_text(encoding="ascii")
    lines = value.splitlines()
    if len(lines) != 2 or value != "\n".join(lines) + "\n":
        raise ValueError(CAPTURE_UNAVAILABLE)
    if not lines[0].startswith("request_id=") or not lines[1].startswith(
        "operation="
    ):
        raise ValueError(CAPTURE_UNAVAILABLE)
    request = _Request(
        request_id=lines[0].split("=", 1)[1],
        operation=lines[1].split("=", 1)[1],
    )
    _validate_request(request)
    return request


def _new_request(operation: str) -> _Request:
    request = _Request(request_id=secrets.token_hex(16), operation=operation)
    _validate_request(request)
    return request


def _validate_request(request: _Request) -> None:
    if type(request) is not _Request:
        raise ValueError(CAPTURE_UNAVAILABLE)
    _validate_request_id(request.request_id)
    if request.operation not in _EVALUATIONS:
        _validate_prompt_id(request.operation)


def _request_payload(request: _Request) -> str:
    return f"request_id={request.request_id}\noperation={request.operation}\n"


def _claim_request(project_root: Path) -> _ClaimedRequest:
    pending = project_root / _REQUEST_RELATIVE
    active = project_root / _ACTIVE_REQUEST_RELATIVE
    request = _read_request_path(pending)
    pending_ownership = _request_ownership(pending, request.request_id)
    if active.is_symlink() or active.exists():
        raise ValueError(CAPTURE_UNAVAILABLE)
    linked = False
    active_ownership: _RequestOwnership | None = None
    try:
        os.link(pending, active, follow_symlinks=False)
        linked = True
        active_ownership = _request_ownership(active, request.request_id)
        active.chmod(0o600)
        _remove_owned_request(pending, pending_ownership)
    except Exception:
        if linked and active_ownership is not None:
            _remove_owned_request(active, active_ownership)
        raise ValueError(CAPTURE_UNAVAILABLE) from None
    if active_ownership is None:
        raise ValueError(CAPTURE_UNAVAILABLE)
    return _ClaimedRequest(request=request, ownership=active_ownership)


def _request_ownership(path: Path, request_id: str) -> _RequestOwnership:
    _validate_request_id(request_id)
    if path.is_symlink():
        raise ValueError(CAPTURE_UNAVAILABLE)
    value = path.stat()
    if not stat.S_ISREG(value.st_mode):
        raise ValueError(CAPTURE_UNAVAILABLE)
    return _RequestOwnership(
        request_id=request_id,
        device=value.st_dev,
        inode=value.st_ino,
    )


def _remove_owned_request(path: Path, ownership: _RequestOwnership) -> None:
    try:
        if path.is_symlink() or not path.is_file():
            return
        value = path.stat()
        if value.st_dev != ownership.device or value.st_ino != ownership.inode:
            return
        request = _read_request_path(path)
        if request.request_id == ownership.request_id:
            path.unlink()
    except Exception:
        return


def _cleanup_owned_request(
    project_root: Path, ownership: _RequestOwnership
) -> None:
    _remove_owned_request(project_root / _REQUEST_RELATIVE, ownership)
    _remove_owned_request(project_root / _ACTIVE_REQUEST_RELATIVE, ownership)


def _mark_blocked(project_root: Path, ownership: _RequestOwnership) -> None:
    blocked = project_root / _BLOCKED_RELATIVE
    if blocked.is_symlink():
        raise ValueError(CAPTURE_UNAVAILABLE)
    temporary = blocked.with_suffix(".blocked.tmp")
    if temporary.is_symlink():
        raise ValueError(CAPTURE_UNAVAILABLE)
    temporary.write_text(
        "reason=operator_exit_unconfirmed\n"
        f"request_id={ownership.request_id}\n",
        encoding="ascii",
    )
    temporary.chmod(0o600)
    temporary.replace(blocked)


def _read_blocked_ownership(blocked: Path) -> _BlockedOwnership:
    if blocked.is_symlink() or not blocked.is_file():
        raise ValueError(CAPTURE_UNAVAILABLE)
    value = blocked.read_text(encoding="ascii")
    lines = value.splitlines()
    if (
        len(lines) != 2
        or value != "\n".join(lines) + "\n"
        or lines[0] != "reason=operator_exit_unconfirmed"
        or not lines[1].startswith("request_id=")
    ):
        raise ValueError(CAPTURE_UNAVAILABLE)
    request_id = lines[1].split("=", 1)[1]
    _validate_request_id(request_id)
    metadata = blocked.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(CAPTURE_UNAVAILABLE)
    return _BlockedOwnership(
        request_id=request_id,
        device=metadata.st_dev,
        inode=metadata.st_ino,
    )


def _remove_owned_blocked(
    blocked: Path, ownership: _BlockedOwnership
) -> None:
    try:
        current = _read_blocked_ownership(blocked)
        if current == ownership:
            blocked.unlink()
    except Exception:
        return


@contextmanager
def _parent_request_lock(project_root: Path) -> Iterator[None]:
    lock_path = project_root / _PARENT_LOCK_RELATIVE
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path.parent.chmod(0o700)
    if lock_path.is_symlink():
        raise ValueError(CAPTURE_UNAVAILABLE)
    descriptor = -1
    try:
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except (BlockingIOError, OSError):
        raise ValueError(CAPTURE_UNAVAILABLE) from None
    finally:
        if descriptor >= 0:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(descriptor)


def _kickstart_operator(opener: Runner, target: str) -> None:
    _run(
        opener,
        ["/bin/launchctl", "kickstart", "-k", target],
        capture_output=True,
    )


def _stop_operator(opener: Runner, target: str, sleeper: Sleeper) -> bool:
    for signal_name in ("SIGTERM", "SIGKILL"):
        try:
            _run(
                opener,
                ["/bin/launchctl", "kill", signal_name, target],
                capture_output=True,
            )
        except Exception:
            continue
        if _wait_for_operator_exit(opener, target, sleeper):
            return True
    return False


def _wait_for_operator_exit(
    opener: Runner, target: str, sleeper: Sleeper
) -> bool:
    deadline = time.monotonic() + _STOP_WAIT_SECONDS
    while True:
        if _operator_is_running(opener, target) is _OperatorState.STOPPED:
            return True
        if time.monotonic() >= deadline:
            return False
        sleeper(0.1)


def _operator_is_running(opener: Runner, target: str) -> _OperatorState:
    try:
        result = _run(
            opener,
            ["/bin/launchctl", "print", target],
            check=False,
            capture_output=True,
        )
    except Exception:
        return _OperatorState.UNKNOWN
    if result.returncode != 0:
        return _OperatorState.UNKNOWN
    output = result.stdout
    if type(output) is not str or len(output) > 16_384:
        return _OperatorState.UNKNOWN
    if re.search(r"(?m)^\s*(?:state = running|pid = [1-9][0-9]*)\s*$", output):
        return _OperatorState.RUNNING
    if re.search(r"(?m)^\s*state = (?:exited|not running)\s*$", output):
        return _OperatorState.STOPPED
    return _OperatorState.UNKNOWN


def _operator_label_is_absent(opener: Runner, domain: str) -> bool:
    try:
        result = _run(
            opener,
            ["/bin/launchctl", "print", domain],
            check=False,
            capture_output=True,
        )
    except Exception:
        return False
    output = result.stdout
    return (
        result.returncode == 0
        and type(output) is str
        and len(output) <= _DOMAIN_OUTPUT_LIMIT
        and re.search(
            rf"(?m)^\s*{re.escape(domain)} = \{{\s*$", output
        )
        is not None
        and _OPERATOR_LABEL not in output
    )


def _wait_for_status(status_path: Path, sentinel: str, sleeper: Sleeper) -> None:
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        output = status_path.read_text(encoding="utf-8")
        if output.endswith(sentinel):
            return
        sleeper(0.25)
    raise ValueError(CAPTURE_UNAVAILABLE)


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
