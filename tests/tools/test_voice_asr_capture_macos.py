from __future__ import annotations

import threading
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
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode


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

    def opener(_command: list[str], **_: object) -> _Result:
        status = root / "runtime/status/voice-asr-capture.txt"
        status.write_text(
            "result=FAIL\noperation=capture-fixed\n"
            "reason=voice_asr_calibration_failed\n"
            "capture_job_complete=true\n",
            encoding="utf-8",
        )
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


def test_concurrent_parent_capture_fails_without_replacing_first_request(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    first_waiting = threading.Event()
    release_first = threading.Event()
    first_result: list[int | BaseException] = []

    def first_sleeper(_seconds: float) -> None:
        if not first_waiting.is_set():
            first_waiting.set()
            assert release_first.wait(timeout=2)

    def successful_opener(_command: list[str], **_: object) -> _Result:
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
                    sleeper=first_sleeper,
                    printer=lambda _: None,
                    platform_name="darwin",
                    uid_getter=lambda: 501,
                )
            )
        except BaseException as error:  # pragma: no cover - asserted below
            first_result.append(error)

    thread = threading.Thread(target=first_call)
    thread.start()
    assert first_waiting.wait(timeout=2)
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
    ]
    assert not (root / "runtime/status/voice-asr-capture.request").exists()
    assert not (root / "runtime/status/voice-asr-capture.active").exists()


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
    assert calls[-1][1:3] == ["kill", "SIGTERM"]


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


def test_evaluation_result_rejects_transcript_output() -> None:
    with pytest.raises(ValueError, match="^voice_asr_capture_unavailable$"):
        parse_evaluation_result(
            "result=FAIL\noperation=paraformer\ntranscript=private\n"
            "login_job_complete=true\n",
            "paraformer",
            "a" * 32,
        )
