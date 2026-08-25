from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from tools.voice_asr_capture_macos import (
    FIXED_EXECUTION_PATH,
    parse_capture_result,
    parse_evaluation_result,
    run_login_capture,
    run_login_evaluation,
    run_terminal_job,
)


def _pending_request_id(root: Path) -> str:
    lines = (root / "runtime/status/voice-asr-capture.request").read_text(
        encoding="ascii"
    ).splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("request_id=")
    return lines[0].split("=", 1)[1]


def _request_payload(request_id: str, operation: str) -> str:
    return f"request_id={request_id}\noperation={operation}\n"


def _capture_success(request_id: str) -> str:
    return (
        "prompt_id=negative_weather\nprompt=今天天气不错\n"
        "result=PASS\noperation=capture-fixed\nduration_ms=8000\n"
        "encrypted_clip_persisted=true\n"
        f"request_id={request_id}\ncapture_job_complete=true\n"
    )


def _capture_vad_failure(request_id: str, segment_count: int) -> str:
    return (
        "prompt_id=negative_weather\nprompt=今天天气不错\n"
        "result=FAIL\noperation=capture-fixed\n"
        "reason=voice_asr_calibration_failed\n"
        "failure_stage=vad\n"
        f"detected_segment_count={segment_count}\n"
        f"request_id={request_id}\ncapture_job_complete=true\n"
    )


def _large_launchctl_domain(*, size: int, include_operator: bool) -> str:
    prefix = "gui/501 = {\nservices = {\n"
    operator = (
        "0\t-\tcom.babymonitor.voice-asr-operator\n"
        if include_operator
        else ""
    )
    suffix = "}\n}\n"
    padding_size = size - len(prefix) - len(operator) - len(suffix)
    assert padding_size >= 0
    return prefix + ("x" * padding_size) + operator + suffix


@pytest.mark.parametrize(
    "prompt_id",
    ["free_form", "negative_weather\nProgramArguments", ""],
)
def test_capture_rejects_non_fixed_prompt_ids(tmp_path: Path, prompt_id: str) -> None:
    with pytest.raises(ValueError, match="^voice_asr_capture_unavailable$"):
        run_login_capture(
            tmp_path,
            prompt_id,
            opener=lambda *_args, **_kwargs: _Result(),
            sleeper=lambda _: None,
            platform_name="darwin",
        )


def test_capture_result_accepts_only_the_exact_bounded_success_block() -> None:
    request_id = "a" * 32
    result = parse_capture_result(
        "\n".join(
            (
                "prompt_id=negative_weather",
                "prompt=今天天气不错",
                "result=PASS",
                "operation=capture-fixed",
                "duration_ms=8000",
                "encrypted_clip_persisted=true",
                f"request_id={request_id}",
                "capture_job_complete=true",
                "",
            )
        ),
        "negative_weather",
        request_id,
    )

    assert result == (
        "result=PASS",
        "operation=capture-fixed",
        "prompt_id=negative_weather",
        "duration_ms=8000",
        "encrypted_clip_persisted=true",
    )


def test_capture_result_requires_the_callers_matching_request_id() -> None:
    matching = "a" * 32
    output = "\n".join(
        (
            "prompt_id=negative_weather",
            "prompt=今天天气不错",
            "result=PASS",
            "operation=capture-fixed",
            "duration_ms=8000",
            "encrypted_clip_persisted=true",
            f"request_id={matching}",
            "capture_job_complete=true",
            "",
        )
    )

    assert (
        parse_capture_result(output, "negative_weather", matching)[0]
        == "result=PASS"
    )
    with pytest.raises(ValueError, match="^voice_asr_capture_unavailable$"):
        parse_capture_result(output, "negative_weather", "b" * 32)


@pytest.mark.parametrize(
    "output",
    [
        "result=PASS\noperation=capture-fixed\nduration_ms=8000\n",
        "result=PASS\noperation=capture-fixed\nduration_ms=7999\n"
        "encrypted_clip_persisted=true\n",
        "result=PASS\noperation=capture-fixed\nduration_ms=8000\n"
        "encrypted_clip_persisted=true\ntranscript=private\n"
        "capture_job_complete=true\n",
        "result=FAIL\noperation=capture-fixed\nreason=voice_asr_calibration_failed\n"
        "capture_job_complete=true\n",
    ],
)
def test_capture_result_rejects_incomplete_or_extra_output(output: str) -> None:
    with pytest.raises(ValueError, match="^voice_asr_capture_unavailable$"):
        parse_capture_result(output, "negative_weather", "a" * 32)


class _Result:
    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def test_login_capture_uses_fixed_background_launchagent_without_gui(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    calls: list[list[str]] = []

    def opener(command_line: list[str], **_: object) -> _Result:
        calls.append(command_line)
        status = root / "runtime/status/voice-asr-capture.txt"
        status.write_text(
            _capture_success(_pending_request_id(root)), encoding="utf-8"
        )
        return _Result()

    printed: list[str] = []
    result = run_login_capture(
        root,
        "negative_weather",
        opener=opener,
        sleeper=lambda _: None,
        printer=printed.append,
        platform_name="darwin",
        uid_getter=lambda: 501,
    )

    assert result == 0
    assert calls == [
        [
            "/bin/launchctl",
            "kickstart",
            "-k",
            "gui/501/com.babymonitor.voice-asr-operator",
        ]
    ]
    assert not (root / "runtime/status/voice-asr-capture.request").exists()
    assert printed[:2] == [
        "prompt=今天天气不错",
        "capture_starts_in_seconds=10",
    ]
    assert printed[10] == "capture_starts_in_seconds=1"
    assert printed[11] == "capture_now=true"
    assert printed[-1] == "encrypted_clip_persisted=true"


def test_login_capture_publishes_request_only_after_countdown(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    pending = root / "runtime/status/voice-asr-capture.request"
    early_jobs: list[str] = []
    attempted_early_kickstart = False

    def sleeper(_seconds: float) -> None:
        nonlocal attempted_early_kickstart
        if attempted_early_kickstart:
            return
        attempted_early_kickstart = True
        try:
            run_terminal_job(
                root,
                sleeper=lambda _: None,
                printer=lambda _: None,
                job_runner=lambda _root, prompt_id: early_jobs.append(prompt_id) or 0,
                require_confirmation=False,
                countdown_seconds=0,
            )
        except ValueError:
            pass

    def opener(_command: list[str], **_: object) -> _Result:
        assert pending.is_file()
        (root / "runtime/status/voice-asr-capture.txt").write_text(
            _capture_success(_pending_request_id(root)), encoding="utf-8"
        )
        return _Result()

    assert (
        run_login_capture(
            root,
            "negative_weather",
            opener=opener,
            sleeper=sleeper,
            printer=lambda _: None,
            platform_name="darwin",
            uid_getter=lambda: 501,
        )
        == 0
    )
    assert attempted_early_kickstart
    assert early_jobs == []


def test_login_capture_waits_for_the_terminal_success_sentinel(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    def opener(_command: list[str], **_: object) -> _Result:
        (root / "runtime/status/voice-asr-capture.txt").write_text(
            "prompt_id=negative_weather\nprompt=今天天气不错\n",
            encoding="utf-8",
        )
        return _Result()

    sleep_count = 0

    def sleeper(_: float) -> None:
        nonlocal sleep_count
        sleep_count += 1
        if (root / "runtime/status/voice-asr-capture.request").exists():
            (root / "runtime/status/voice-asr-capture.txt").write_text(
                _capture_success(_pending_request_id(root)),
                encoding="utf-8",
            )

    assert (
        run_login_capture(
            root,
            "negative_weather",
            opener=opener,
            sleeper=sleeper,
            printer=lambda _: None,
            platform_name="darwin",
            uid_getter=lambda: 501,
        )
        == 0
    )
    assert sleep_count == 11


def test_login_capture_fails_closed_when_terminal_job_fails(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    output: list[str] = []

    def sleeper(_: float) -> None:
        request = root / "runtime/status/voice-asr-capture.request"
        if request.exists():
            (root / "runtime/status/voice-asr-capture.txt").write_text(
                _capture_vad_failure(_pending_request_id(root), 2),
                encoding="utf-8",
            )

    assert (
        run_login_capture(
            root,
            "negative_weather",
            opener=lambda _command, **_kwargs: _Result(),
            sleeper=sleeper,
            printer=output.append,
            platform_name="darwin",
            uid_getter=lambda: 501,
        )
        == 1
    )
    assert output[-5:] == [
        "result=FAIL",
        "operation=capture-fixed",
        "reason=voice_asr_calibration_failed",
        "failure_stage=vad",
        "detected_segment_count=2",
    ]


def test_fixed_terminal_runner_keeps_path_and_invocation_source_controlled() -> None:
    command = (
        Path(__file__).parents[2] / "tools/voice_asr_capture_macos.command"
    ).read_text(encoding="ascii")

    assert f'export PATH="{FIXED_EXECUTION_PATH}"' in command
    assert "tools.voice_asr_capture_macos terminal-job" in command
    assert "launchctl" not in command


def test_terminal_job_waits_for_operator_before_countdown(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    status = root / "runtime/status"
    status.mkdir(parents=True)
    (status / "voice-asr-capture.request").write_text(
        _request_payload("a" * 32, "negative_weather"), encoding="ascii"
    )
    prompts: list[str] = []
    countdown: list[str] = []
    jobs: list[str] = []

    result = run_terminal_job(
        root,
        input_fn=lambda prompt: prompts.append(prompt) or "",
        sleeper=lambda _: None,
        printer=countdown.append,
        job_runner=lambda _root, prompt_id: jobs.append(prompt_id) or 0,
    )

    assert result == 0
    assert prompts == [""]
    assert countdown[:2] == [
        "prompt=今天天气不错",
        "press_enter_to_start_countdown=",
    ]
    assert countdown[2] == "capture_starts_in_seconds=10"
    assert countdown[-1] == "capture_starts_in_seconds=1"
    assert jobs == ["negative_weather"]


def test_background_job_counts_down_without_terminal_input(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    status = root / "runtime/status"
    status.mkdir(parents=True)
    (status / "voice-asr-capture.request").write_text(
        _request_payload("a" * 32, "negative_weather"), encoding="ascii"
    )
    countdown: list[str] = []
    jobs: list[str] = []

    result = run_terminal_job(
        root,
        input_fn=lambda _prompt: pytest.fail("background job read stdin"),
        sleeper=lambda _: None,
        printer=countdown.append,
        job_runner=lambda _root, prompt_id: jobs.append(prompt_id) or 0,
        require_confirmation=False,
    )

    assert result == 0
    assert "press_enter_to_start_countdown=" not in countdown
    assert countdown[1] == "capture_starts_in_seconds=10"
    assert jobs == ["negative_weather"]


def test_operator_atomically_claims_and_consumes_each_request_once(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    status = root / "runtime/status"
    status.mkdir(parents=True)
    pending = status / "voice-asr-capture.request"
    active = status / "voice-asr-capture.active"
    pending.write_text(
        _request_payload("a" * 32, "negative_weather"), encoding="ascii"
    )
    observed: list[tuple[bool, bool]] = []

    assert (
        run_terminal_job(
            root,
            sleeper=lambda _: None,
            printer=lambda _: None,
            job_runner=lambda _root, _prompt_id: observed.append(
                (pending.exists(), active.exists())
            )
            or 0,
            require_confirmation=False,
            countdown_seconds=0,
        )
        == 0
    )
    assert observed == [(False, True)]
    assert not pending.exists()
    assert not active.exists()
    with pytest.raises(ValueError, match="^voice_asr_capture_unavailable$"):
        run_terminal_job(
            root,
            sleeper=lambda _: None,
            printer=lambda _: None,
            job_runner=lambda _root, _prompt_id: 0,
            require_confirmation=False,
            countdown_seconds=0,
        )


def test_losing_claim_never_removes_the_winners_active_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import voice_asr_capture_macos as capture_macos

    root = tmp_path / "repo"
    status = root / "runtime/status"
    status.mkdir(parents=True)
    pending = status / "voice-asr-capture.request"
    active = status / "voice-asr-capture.active"
    pending.write_text(
        _request_payload("a" * 32, "negative_weather"), encoding="ascii"
    )
    original_link = capture_macos.os.link
    claim_barrier = threading.Barrier(2)

    def racing_link(source: Path, target: Path, **kwargs: object) -> None:
        claim_barrier.wait(timeout=2)
        original_link(source, target, **kwargs)

    monkeypatch.setattr(capture_macos.os, "link", racing_link)
    claims: list[object] = []
    failures: list[BaseException] = []

    def claim() -> None:
        try:
            claims.append(capture_macos._claim_request(root))
        except BaseException as error:  # pragma: no cover - asserted below
            failures.append(error)

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert len(claims) == 1
    assert len(failures) == 1
    assert active.is_file()
    assert active.read_text(encoding="ascii") == _request_payload(
        "a" * 32, "negative_weather"
    )


def test_concurrent_parent_capture_fails_without_replacing_first_request(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    first_launched = threading.Event()
    release_first = threading.Event()
    first_result: list[int | BaseException] = []

    def successful_opener(_command: list[str], **_: object) -> _Result:
        first_launched.set()
        assert release_first.wait(timeout=2)
        (root / "runtime/status/voice-asr-capture.txt").write_text(
            _capture_success(_pending_request_id(root)),
            encoding="utf-8",
        )
        return _Result()

    def first_call() -> None:
        try:
            first_result.append(
                run_login_capture(
                    root,
                    "negative_weather",
                    opener=successful_opener,
                    sleeper=lambda _: None,
                    printer=lambda _: None,
                    platform_name="darwin",
                    uid_getter=lambda: 501,
                )
            )
        except BaseException as error:  # pragma: no cover - asserted below
            first_result.append(error)

    thread = threading.Thread(target=first_call)
    thread.start()
    assert first_launched.wait(timeout=2)
    first_request = (root / "runtime/status/voice-asr-capture.request").read_bytes()
    try:
        with pytest.raises(ValueError, match="^voice_asr_capture_unavailable$"):
            run_login_capture(
                root,
                "negative_weather",
                opener=successful_opener,
                sleeper=lambda _: None,
                printer=lambda _: None,
                platform_name="darwin",
                uid_getter=lambda: 501,
            )
        assert (root / "runtime/status/voice-asr-capture.request").read_bytes() == first_request
    finally:
        release_first.set()
        thread.join(timeout=2)
    assert first_result == [0]


def test_timeout_cancels_operator_and_removes_only_owned_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import voice_asr_capture_macos as capture_macos

    root = tmp_path / "repo"
    root.mkdir()
    calls: list[list[str]] = []
    monkeypatch.setattr(capture_macos, "_WAIT_SECONDS", 0)

    def opener(command: list[str], **_: object) -> _Result:
        calls.append(command)
        if command[1] == "print":
            return _Result(stdout="state = exited\n")
        return _Result()

    with pytest.raises(ValueError, match="^voice_asr_capture_unavailable$"):
        run_login_capture(
            root,
            "negative_weather",
            opener=opener,
            sleeper=lambda _: None,
            printer=lambda _: None,
            platform_name="darwin",
            uid_getter=lambda: 501,
        )

    target = "gui/501/com.babymonitor.voice-asr-operator"
    assert calls == [
        ["/bin/launchctl", "kickstart", "-k", target],
        ["/bin/launchctl", "kill", "SIGTERM", target],
        ["/bin/launchctl", "print", target],
    ]
    assert not (root / "runtime/status/voice-asr-capture.request").exists()
    assert not (root / "runtime/status/voice-asr-capture.active").exists()


def test_timeout_kills_and_confirms_real_async_operator_before_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import voice_asr_capture_macos as capture_macos

    root = tmp_path / "repo"
    root.mkdir()
    ready = tmp_path / "operator-ready"
    late_mutation = tmp_path / "late-mutation"
    process: subprocess.Popen[str] | None = None
    monkeypatch.setattr(capture_macos, "_WAIT_SECONDS", 0)
    monkeypatch.setattr(capture_macos, "_STOP_WAIT_SECONDS", 0, raising=False)

    def opener(command: list[str], **_: object) -> _Result:
        nonlocal process
        action = command[1]
        if action == "kickstart":
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    (
                        "import pathlib,signal,sys,time;"
                        "signal.signal(signal.SIGTERM,lambda *_: None);"
                        "pathlib.Path(sys.argv[1]).write_text('ready');"
                        "time.sleep(0.3);"
                        "pathlib.Path(sys.argv[2]).write_text('late')"
                    ),
                    str(ready),
                    str(late_mutation),
                ],
                text=True,
            )
            deadline = time.monotonic() + 2
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert ready.exists()
            return _Result()
        assert process is not None
        if action == "kill":
            if command[2] == "SIGTERM":
                process.terminate()
            else:
                assert command[2] == "SIGKILL"
                process.kill()
                process.wait(timeout=2)
            return _Result()
        assert action == "print"
        running = process.poll() is None
        return _Result(
            stdout=(
                f"state = running\npid = {process.pid}\n"
                if running
                else "state = exited\n"
            )
        )

    with pytest.raises(ValueError, match="^voice_asr_capture_unavailable$"):
        run_login_capture(
            root,
            "negative_weather",
            opener=opener,
            sleeper=lambda _: None,
            printer=lambda _: None,
            platform_name="darwin",
            uid_getter=lambda: 501,
        )

    assert process is not None
    process.wait(timeout=2)
    time.sleep(0.35)
    assert not late_mutation.exists()


def test_unconfirmed_operator_exit_leaves_durable_blocking_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import voice_asr_capture_macos as capture_macos

    root = tmp_path / "repo"
    root.mkdir()
    calls: list[list[str]] = []
    monkeypatch.setattr(capture_macos, "_WAIT_SECONDS", 0)
    monkeypatch.setattr(capture_macos, "_STOP_WAIT_SECONDS", 0, raising=False)

    def never_stops(command: list[str], **_: object) -> _Result:
        calls.append(command)
        if command[1] == "print":
            return _Result(stdout="state = running\npid = 123\n")
        return _Result()

    with pytest.raises(ValueError, match="^voice_asr_capture_unavailable$"):
        run_login_capture(
            root,
            "negative_weather",
            opener=never_stops,
            sleeper=lambda _: None,
            printer=lambda _: None,
            platform_name="darwin",
            uid_getter=lambda: 501,
        )

    status = root / "runtime/status"
    assert (status / "voice-asr-capture.blocked").is_file()
    assert (status / "voice-asr-capture.request").exists() or (
        status / "voice-asr-capture.active"
    ).exists()
    calls_before_retry = list(calls)
    with pytest.raises(ValueError, match="^voice_asr_capture_unavailable$"):
        run_login_capture(
            root,
            "negative_weather",
            opener=never_stops,
            sleeper=lambda _: None,
            printer=lambda _: None,
            platform_name="darwin",
            uid_getter=lambda: 501,
        )
    assert calls == calls_before_retry


def test_nonzero_operator_print_keeps_protection_and_prevents_late_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import voice_asr_capture_macos as capture_macos

    root = tmp_path / "repo"
    root.mkdir()
    ready = tmp_path / "operator-ready"
    late_mutation = tmp_path / "late-mutation"
    process: subprocess.Popen[str] | None = None
    calls: list[list[str]] = []
    monkeypatch.setattr(capture_macos, "_WAIT_SECONDS", 0)
    monkeypatch.setattr(capture_macos, "_STOP_WAIT_SECONDS", 0)

    def opener(command: list[str], **_: object) -> _Result:
        nonlocal process
        calls.append(command)
        action = command[1]
        if action == "kickstart":
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    (
                        "import pathlib,signal,sys,time;"
                        "signal.signal(signal.SIGTERM,lambda *_: None);"
                        "pathlib.Path(sys.argv[1]).write_text('ready');"
                        "time.sleep(0.3);"
                        "pathlib.Path(sys.argv[2]).write_text('late')"
                    ),
                    str(ready),
                    str(late_mutation),
                ],
                text=True,
            )
            deadline = time.monotonic() + 2
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert ready.exists()
            return _Result()
        assert process is not None
        if action == "kill":
            if command[2] == "SIGTERM":
                process.terminate()
            else:
                assert command[2] == "SIGKILL"
                process.kill()
                process.wait(timeout=2)
            return _Result()
        assert action == "print"
        return _Result(returncode=113)

    with pytest.raises(ValueError, match="^voice_asr_capture_unavailable$"):
        run_login_capture(
            root,
            "negative_weather",
            opener=opener,
            sleeper=lambda _: None,
            printer=lambda _: None,
            platform_name="darwin",
            uid_getter=lambda: 501,
        )

    assert process is not None
    if process.poll() is None:
        process.kill()
    process.wait(timeout=2)
    # The child attempts its mutation after 0.3 seconds; waiting beyond that proves
    # the parent did not return while the unconfirmed process could still write.
    time.sleep(0.35)
    status = root / "runtime/status"
    assert not late_mutation.exists()
    assert (status / "voice-asr-capture.blocked").is_file()
    assert (status / "voice-asr-capture.request").is_file()
    assert [command[2] for command in calls if command[1] == "kill"] == [
        "SIGTERM",
        "SIGKILL",
    ]


def test_explicit_kickstart_failure_is_retriable_without_a_blocker(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    failed_calls: list[list[str]] = []

    def failed_kickstart(command: list[str], **_: object) -> _Result:
        failed_calls.append(command)
        if command[1] == "kickstart":
            raise subprocess.CalledProcessError(5, command)
        if command[1] == "print":
            return _Result(stdout="state = running\npid = 123\n")
        return _Result()

    with pytest.raises(subprocess.CalledProcessError):
        run_login_capture(
            root,
            "negative_weather",
            opener=failed_kickstart,
            sleeper=lambda _: None,
            printer=lambda _: None,
            platform_name="darwin",
            uid_getter=lambda: 501,
        )

    status = root / "runtime/status"
    assert failed_calls == [
        [
            "/bin/launchctl",
            "kickstart",
            "-k",
            "gui/501/com.babymonitor.voice-asr-operator",
        ]
    ]
    assert not (status / "voice-asr-capture.blocked").exists()
    assert not (status / "voice-asr-capture.request").exists()
    assert not (status / "voice-asr-capture.active").exists()

    def successful_retry(command: list[str], **_: object) -> _Result:
        assert command[1] == "kickstart"
        (status / "voice-asr-capture.txt").write_text(
            _capture_success(_pending_request_id(root)), encoding="utf-8"
        )
        return _Result()

    assert (
        run_login_capture(
            root,
            "negative_weather",
            opener=successful_retry,
            sleeper=lambda _: None,
            printer=lambda _: None,
            platform_name="darwin",
            uid_getter=lambda: 501,
        )
        == 0
    )


@pytest.mark.parametrize("failure_kind", ("timeout", "interrupt"))
def test_uncertain_kickstart_failure_stops_real_async_operator_before_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    from tools import voice_asr_capture_macos as capture_macos

    root = tmp_path / "repo"
    root.mkdir()
    ready = tmp_path / "operator-ready"
    late_mutation = tmp_path / "late-mutation"
    process: subprocess.Popen[str] | None = None
    calls: list[list[str]] = []
    monkeypatch.setattr(capture_macos, "_STOP_WAIT_SECONDS", 0)

    def opener(command: list[str], **_: object) -> _Result:
        nonlocal process
        calls.append(command)
        action = command[1]
        if action == "kickstart":
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    (
                        "import pathlib,signal,sys,time;"
                        "signal.signal(signal.SIGTERM,lambda *_: None);"
                        "pathlib.Path(sys.argv[1]).write_text('ready');"
                        "time.sleep(0.3);"
                        "pathlib.Path(sys.argv[2]).write_text('late')"
                    ),
                    str(ready),
                    str(late_mutation),
                ],
                text=True,
            )
            deadline = time.monotonic() + 2
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert ready.exists()
            if failure_kind == "timeout":
                raise subprocess.TimeoutExpired(command, timeout=10)
            raise KeyboardInterrupt
        assert process is not None
        if action == "kill":
            if command[2] == "SIGTERM":
                process.terminate()
            else:
                assert command[2] == "SIGKILL"
                process.kill()
                process.wait(timeout=2)
            return _Result()
        assert action == "print"
        return _Result(returncode=113)

    try:
        caught: BaseException | None = None
        try:
            run_login_capture(
                root,
                "negative_weather",
                opener=opener,
                sleeper=lambda _: None,
                printer=lambda _: None,
                platform_name="darwin",
                uid_getter=lambda: 501,
            )
        except BaseException as error:
            caught = error
        assert type(caught) is ValueError
        assert str(caught) == "voice_asr_capture_unavailable"
        assert process is not None
        process.wait(timeout=2)
        # The child attempts its mutation after 0.3 seconds. Once it has exited,
        # absence of the marker proves the parent stopped it before returning.
        assert not late_mutation.exists()
        status = root / "runtime/status"
        assert (status / "voice-asr-capture.blocked").is_file()
        assert (status / "voice-asr-capture.request").is_file()
        assert [command[2] for command in calls if command[1] == "kill"] == [
            "SIGTERM",
            "SIGKILL",
        ]
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=2)


def test_recovery_boots_out_exact_operator_then_clears_one_owned_request(
    tmp_path: Path,
) -> None:
    from tools import voice_asr_capture_macos as capture_macos

    root = tmp_path / "repo"
    status = root / "runtime/status"
    status.mkdir(parents=True)
    request_id = "a" * 32
    pending = status / "voice-asr-capture.request"
    active = status / "voice-asr-capture.active"
    blocked = status / "voice-asr-capture.blocked"
    pending.write_text(
        _request_payload(request_id, "negative_weather"), encoding="ascii"
    )
    os.link(pending, active)
    blocked.write_text(
        "reason=operator_exit_unconfirmed\n" f"request_id={request_id}\n",
        encoding="ascii",
    )
    calls: list[list[str]] = []

    def opener(command: list[str], **_: object) -> _Result:
        calls.append(command)
        if command[1] == "bootout":
            return _Result(returncode=3)
        assert command[1:] == ["print", "gui/501"]
        return _Result(stdout="gui/501 = {\nservices = {\n}\n}\n")

    printed: list[str] = []
    assert (
        capture_macos.recover_login_job(
            root,
            opener=opener,
            printer=printed.append,
            platform_name="darwin",
            uid_getter=lambda: 501,
        )
        == 0
    )

    assert calls == [
        [
            "/bin/launchctl",
            "bootout",
            "gui/501/com.babymonitor.voice-asr-operator",
        ],
        ["/bin/launchctl", "print", "gui/501"],
    ]
    assert printed == ["result=PASS", "operation=recover", "state=cleared"]
    assert str(root) not in "\n".join(printed)
    assert not pending.exists()
    assert not active.exists()
    assert not blocked.exists()


def test_recovery_accepts_only_one_exact_legacy_pending_request(tmp_path: Path) -> None:
    from tools import voice_asr_capture_macos as capture_macos

    root = tmp_path / "repo"
    status = root / "runtime/status"
    status.mkdir(parents=True)
    pending = status / "voice-asr-capture.request"
    pending.write_text("negative_weather\n", encoding="ascii")
    pending.chmod(0o600)

    def opener(command: list[str], **_: object) -> _Result:
        if command[1] == "bootout":
            return _Result()
        return _Result(stdout="gui/501 = {\nservices = {\n}\n}\n")

    printed: list[str] = []
    assert (
        capture_macos.recover_login_job(
            root,
            opener=opener,
            printer=printed.append,
            platform_name="darwin",
            uid_getter=lambda: 501,
        )
        == 0
    )
    assert printed == ["result=PASS", "operation=recover", "state=cleared"]
    assert not pending.exists()


@pytest.mark.parametrize(
    "payload",
    ("private_request\n", "negative_weather\nextra\n"),
)
def test_recovery_preserves_unknown_legacy_pending_request(
    tmp_path: Path, payload: str
) -> None:
    from tools import voice_asr_capture_macos as capture_macos

    root = tmp_path / "repo"
    status = root / "runtime/status"
    status.mkdir(parents=True)
    pending = status / "voice-asr-capture.request"
    pending.write_text(payload, encoding="ascii")
    pending.chmod(0o600)

    def opener(command: list[str], **_: object) -> _Result:
        if command[1] == "bootout":
            return _Result()
        return _Result(stdout="gui/501 = {\nservices = {\n}\n}\n")

    with pytest.raises(ValueError, match="^voice_asr_capture_unavailable$"):
        capture_macos.recover_login_job(
            root,
            opener=opener,
            printer=lambda _: None,
            platform_name="darwin",
            uid_getter=lambda: 501,
        )
    assert pending.read_text(encoding="ascii") == payload


@pytest.mark.parametrize(
    ("domain_output", "should_recover"),
    (
        pytest.param(
            _large_launchctl_domain(size=131_344, include_operator=False),
            True,
            id="large-label-absent",
        ),
        pytest.param(
            _large_launchctl_domain(size=131_344, include_operator=True),
            False,
            id="large-label-present",
        ),
        pytest.param(
            _large_launchctl_domain(size=262_145, include_operator=False),
            False,
            id="oversize-unknown",
        ),
    ),
)
def test_recovery_bounds_large_domain_output_without_missing_operator_label(
    tmp_path: Path, domain_output: str, should_recover: bool
) -> None:
    from tools import voice_asr_capture_macos as capture_macos

    root = tmp_path / "repo"
    root.mkdir()

    def opener(command: list[str], **_: object) -> _Result:
        if command[1] == "bootout":
            return _Result()
        assert command[1:] == ["print", "gui/501"]
        return _Result(stdout=domain_output)

    printed: list[str] = []
    if should_recover:
        assert (
            capture_macos.recover_login_job(
                root,
                opener=opener,
                printer=printed.append,
                platform_name="darwin",
                uid_getter=lambda: 501,
            )
            == 0
        )
        assert printed == ["result=PASS", "operation=recover", "state=clean"]
    else:
        with pytest.raises(ValueError, match="^voice_asr_capture_unavailable$"):
            capture_macos.recover_login_job(
                root,
                opener=opener,
                printer=printed.append,
                platform_name="darwin",
                uid_getter=lambda: 501,
            )
        assert printed == []
    assert domain_output not in "\n".join(printed)


@pytest.mark.parametrize(
    ("print_result"),
    (
        pytest.param(_Result(returncode=113), id="print-failed"),
        pytest.param(_Result(stdout="unstructured\n"), id="print-unrecognized"),
    ),
)
def test_recovery_preserves_protected_state_when_absence_is_not_confirmed(
    tmp_path: Path, print_result: _Result
) -> None:
    from tools import voice_asr_capture_macos as capture_macos

    root = tmp_path / "repo"
    status = root / "runtime/status"
    status.mkdir(parents=True)
    request_id = "a" * 32
    pending = status / "voice-asr-capture.request"
    blocked = status / "voice-asr-capture.blocked"
    pending.write_text(
        _request_payload(request_id, "negative_weather"), encoding="ascii"
    )
    blocked.write_text(
        "reason=operator_exit_unconfirmed\n" f"request_id={request_id}\n",
        encoding="ascii",
    )
    original_pending = pending.read_bytes()
    original_blocked = blocked.read_bytes()

    def opener(command: list[str], **_: object) -> _Result:
        if command[1] == "bootout":
            return _Result()
        assert command[1:] == ["print", "gui/501"]
        return print_result

    with pytest.raises(ValueError, match="^voice_asr_capture_unavailable$"):
        capture_macos.recover_login_job(
            root,
            opener=opener,
            printer=lambda _: None,
            platform_name="darwin",
            uid_getter=lambda: 501,
        )

    assert pending.read_bytes() == original_pending
    assert blocked.read_bytes() == original_blocked


def test_invalid_mismatched_completion_preserves_another_active_request(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    other_request_id = "b" * 32
    calls: list[list[str]] = []

    def opener(command: list[str], **_: object) -> _Result:
        calls.append(command)
        status = root / "runtime/status"
        (status / "voice-asr-capture.active").write_text(
            f"request_id={other_request_id}\noperation=negative_weather\n",
            encoding="ascii",
        )
        (status / "voice-asr-capture.txt").write_text(
            "prompt_id=negative_weather\nprompt=今天天气不错\n"
            "result=PASS\noperation=capture-fixed\nduration_ms=8000\n"
            "encrypted_clip_persisted=true\n"
            f"request_id={other_request_id}\ncapture_job_complete=true\n",
            encoding="utf-8",
        )
        if command[1] == "print":
            return _Result(stdout="state = exited\n")
        return _Result()

    with pytest.raises(ValueError, match="^voice_asr_capture_unavailable$"):
        run_login_capture(
            root,
            "negative_weather",
            opener=opener,
            sleeper=lambda _: None,
            printer=lambda _: None,
            platform_name="darwin",
            uid_getter=lambda: 501,
        )

    assert (root / "runtime/status/voice-asr-capture.active").read_text(
        encoding="ascii"
    ) == f"request_id={other_request_id}\noperation=negative_weather\n"
    assert not (root / "runtime/status/voice-asr-capture.request").exists()
    assert any(command[1:3] == ["kill", "SIGTERM"] for command in calls)


def test_background_operator_launchagent_is_non_persistent_and_not_run_at_load() -> None:
    root = Path(__file__).parents[2]
    plist = (
        root
        / "deploy/launchd/com.babymonitor.voice-asr-operator.plist.example"
    ).read_text(encoding="ascii")
    installer = (root / "tools/install_alpha_macos.sh").read_text(encoding="ascii")
    startup = (root / "tools/start_alpha.sh").read_text(encoding="ascii")
    shutdown = (root / "tools/stop_alpha.sh").read_text(encoding="ascii")

    assert "com.babymonitor.voice-asr-operator" in plist
    assert "tools.voice_asr_capture_macos" in plist
    assert "login-job" in plist
    assert "RunAtLoad" not in plist
    assert "KeepAlive" not in plist
    assert "runtime/status/voice-asr-capture.txt" in plist
    assert "<string>/dev/null</string>" in plist
    assert "voice-asr-operator.err" not in plist
    assert "com.babymonitor.voice-asr-operator.plist.example" in installer
    assert "com.babymonitor.voice-asr-operator.plist" in installer
    assert 'VOICE_ASR_OPERATOR_LABEL="com.babymonitor.voice-asr-operator"' in startup
    assert 'VOICE_ASR_OPERATOR_LABEL="com.babymonitor.voice-asr-operator"' in shutdown
    assert '${GAUGE_DOMAIN}/${VOICE_ASR_OPERATOR_LABEL}' in shutdown


def test_login_paraformer_evaluation_uses_same_background_identity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outputs: list[tuple[str, str]] = []

    def opener(_command: list[str], **_: object) -> _Result:
        request_id = _pending_request_id(root)
        output = (
            "result=PASS\noperation=paraformer\ngate_passed=true\n"
            "selected_model=paraformer\nparaformer_available=true\n"
            "paraformer_samples_evaluated=6\nparaformer_exact_matches=6\n"
            "paraformer_wake_matches=6\nparaformer_latency_p50_ms=500\n"
            "paraformer_latency_p95_ms=600\n"
            "paraformer_mismatch_prompt_ids=none\n"
            "paraformer_edit_distance_total=0\nparaformer_passed=true\n"
            f"request_id={request_id}\nlogin_job_complete=true\n"
        )
        outputs.append((request_id, output))
        (root / "runtime/status/voice-asr-capture.txt").write_text(
            output, encoding="utf-8"
        )
        return _Result()

    printed: list[str] = []
    assert (
        run_login_evaluation(
            root,
            "paraformer",
            opener=opener,
            sleeper=lambda _: None,
            printer=printed.append,
            platform_name="darwin",
            uid_getter=lambda: 501,
        )
        == 0
    )
    assert not (root / "runtime/status/voice-asr-capture.request").exists()
    request_id, output = outputs[0]
    assert printed == list(parse_evaluation_result(output, "paraformer", request_id))


def test_login_preflight_uses_same_background_identity(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outputs: list[tuple[str, str]] = []

    def opener(_command: list[str], **_: object) -> _Result:
        request_id = _pending_request_id(root)
        output = (
            "result=PASS\noperation=preflight\n"
            "voice_preflight=available\ngate_passed=true\n"
            "asr_profile=paraformer\nkeychain=available\n"
            "asr_artifact=available\nsilero_artifact=available\n"
            f"request_id={request_id}\nlogin_job_complete=true\n"
        )
        outputs.append((request_id, output))
        (root / "runtime/status/voice-asr-capture.txt").write_text(
            output, encoding="utf-8"
        )
        return _Result()

    printed: list[str] = []
    assert (
        run_login_evaluation(
            root,
            "preflight",
            opener=opener,
            sleeper=lambda _: None,
            printer=printed.append,
            platform_name="darwin",
            uid_getter=lambda: 501,
        )
        == 0
    )
    request_id, output = outputs[0]
    assert printed == list(parse_evaluation_result(output, "preflight", request_id))


@pytest.mark.parametrize(
    "output",
    [
        "result=PASS\noperation=preflight\nvoice_preflight=available\n"
        "gate_passed=true\nasr_profile=private\nkeychain=available\n"
        "asr_artifact=available\nsilero_artifact=available\n"
        "request_id=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\nlogin_job_complete=true\n",
        "result=FAIL\noperation=preflight\nvoice_preflight=unavailable\n"
        "gate_passed=false\nreason=private_path\n"
        "request_id=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\nlogin_job_complete=true\n",
    ],
)
def test_preflight_result_accepts_only_fixed_aggregate_values(output: str) -> None:
    with pytest.raises(ValueError, match="^voice_asr_capture_unavailable$"):
        parse_evaluation_result(output, "preflight", "a" * 32)


def test_evaluation_result_rejects_transcript_output() -> None:
    with pytest.raises(ValueError, match="^voice_asr_capture_unavailable$"):
        parse_evaluation_result(
            "result=FAIL\noperation=paraformer\ntranscript=private\n"
            "login_job_complete=true\n",
            "paraformer",
            "a" * 32,
        )
