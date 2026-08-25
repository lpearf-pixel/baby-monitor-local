from __future__ import annotations

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
    result = parse_capture_result(
        "\n".join(
            (
                "prompt_id=negative_weather",
                "prompt=今天天气不错",
                "result=PASS",
                "operation=capture-fixed",
                "duration_ms=8000",
                "encrypted_clip_persisted=true",
                "capture_job_complete=true",
                "",
            )
        ),
        "negative_weather",
    )

    assert result == (
        "result=PASS",
        "operation=capture-fixed",
        "prompt_id=negative_weather",
        "duration_ms=8000",
        "encrypted_clip_persisted=true",
    )


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
        parse_capture_result(output, "negative_weather")


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
            "\n".join(
                (
                    "prompt_id=negative_weather",
                    "prompt=今天天气不错",
                    "result=PASS",
                    "operation=capture-fixed",
                    "duration_ms=8000",
                    "encrypted_clip_persisted=true",
                    "capture_job_complete=true",
                    "",
                )
            ),
            encoding="utf-8",
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
    assert (root / "runtime/status/voice-asr-capture.request").read_text(
        encoding="ascii"
    ) == "negative_weather\n"
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
            "prompt_id=negative_weather\nprompt=今天天气不错\n"
            "result=PASS\noperation=capture-fixed\nduration_ms=8000\n"
            "encrypted_clip_persisted=true\ncapture_job_complete=true\n",
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
        "negative_weather\n", encoding="ascii"
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
        "negative_weather\n", encoding="ascii"
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
    output = (
        "result=PASS\noperation=paraformer\ngate_passed=true\n"
        "selected_model=paraformer\nparaformer_available=true\n"
        "paraformer_samples_evaluated=6\nparaformer_exact_matches=6\n"
        "paraformer_wake_matches=6\nparaformer_latency_p50_ms=500\n"
        "paraformer_latency_p95_ms=600\n"
        "paraformer_mismatch_prompt_ids=none\n"
        "paraformer_edit_distance_total=0\nparaformer_passed=true\n"
        "login_job_complete=true\n"
    )

    def opener(_command: list[str], **_: object) -> _Result:
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
    assert (root / "runtime/status/voice-asr-capture.request").read_text(
        encoding="ascii"
    ) == "paraformer\n"
    assert printed == list(parse_evaluation_result(output, "paraformer"))


def test_evaluation_result_rejects_transcript_output() -> None:
    with pytest.raises(ValueError, match="^voice_asr_capture_unavailable$"):
        parse_evaluation_result(
            "result=FAIL\noperation=paraformer\ntranscript=private\n"
            "login_job_complete=true\n",
            "paraformer",
        )
