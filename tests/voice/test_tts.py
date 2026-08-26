from __future__ import annotations

import threading
import subprocess
import struct
from pathlib import Path

import pytest

from services.voice.tts import (
    BoundedCommandRunner,
    RESPONSE_PHRASES,
    FixedVoiceSynthesizer,
    phrase_for_semantic_code,
)


def _aiff(frames: int = 8_000) -> bytes:
    sample_rate = b"\x40\x0c\xfa\x00\x00\x00\x00\x00\x00\x00"
    comm = struct.pack(">hIh", 1, frames, 16) + sample_rate
    sound = struct.pack(">II", 0, 0) + (b"\x00\x01" * frames)
    chunks = b"COMM" + struct.pack(">I", len(comm)) + comm
    chunks += b"SSND" + struct.pack(">I", len(sound)) + sound
    return b"FORM" + struct.pack(">I", 4 + len(chunks)) + b"AIFF" + chunks


class RecordingRunner:
    def __init__(self, outcomes: list[bool] | None = None) -> None:
        self.outcomes = outcomes or [True, True]
        self.calls: list[tuple[tuple[str, ...], bytes | None, float]] = []

    def run(self, command, *, input_bytes, timeout_seconds, cancelled) -> bool:
        self.calls.append((tuple(command), input_bytes, timeout_seconds))
        if command[0] == "/usr/bin/say":
            output = Path(command[command.index("-o") + 1])
            output.write_bytes(_aiff())
        return False if cancelled.is_set() else self.outcomes.pop(0)


class RecordingDucker:
    def __init__(self) -> None:
        self.events: list[str] = []

    def pause(self) -> None:
        self.events.append("pause")

    def resume(self) -> None:
        self.events.append("resume")


@pytest.mark.parametrize(
    ("code", "phrase"),
    [
        ("saved", "好的，已经记录。"),
        ("accepted_pending", "好的，已经开始记录，结束后我会再确认。"),
        ("temporarily_unavailable", "我听到了，但还没有保存，请稍后确认。"),
        ("listen_only_ready", "我在，请说。"),
        ("listen_only_received", "我听到了。"),
    ],
)
def test_semantic_response_uses_only_fixed_phrases(code: str, phrase: str) -> None:
    assert phrase_for_semantic_code(code) == phrase
    assert set(RESPONSE_PHRASES) == {
        "accepted_pending",
        "saved",
        "needs_identity",
        "needs_confirmation",
        "identity_mismatch",
        "state_conflict",
        "temporarily_unavailable",
        "rejected",
        "listen_only_ready",
        "listen_only_received",
    }


def test_synthesizer_uses_stdin_fixed_volume_ducking_and_guard(tmp_path: Path) -> None:
    runner = RecordingRunner()
    ducker = RecordingDucker()
    sleeps: list[float] = []
    synth = FixedVoiceSynthesizer(
        runner=runner,
        ducker=ducker,
        temporary_directory=tmp_path,
        sleep=sleeps.append,
    )

    assert synth.speak_code("saved", threading.Event()) is True

    say, playback = runner.calls
    assert say[0][:8] == (
        "/usr/bin/say",
        "-v",
        "Tingting",
        "-r",
        "180",
        "-f",
        "-",
        "-o",
    )
    assert say[0][-3:] == (
        "--file-format=AIFF",
        "--data-format=BEI16@16000",
        "--channels=1",
    )
    assert say[1] == "好的，已经记录。".encode("utf-8")
    assert "好的" not in " ".join(say[0])
    assert playback[0][:3] == ("/usr/bin/afplay", "-v", "0.35")
    assert playback[1] is None
    assert ducker.events == ["pause", "resume"]
    assert sleeps == [0.5]
    assert list(tmp_path.iterdir()) == []


def test_synthesizer_can_resume_immediately_for_exact_wake_followup(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    ducker = RecordingDucker()
    sleeps: list[float] = []
    synth = FixedVoiceSynthesizer(
        runner=runner,
        ducker=ducker,
        temporary_directory=tmp_path,
        sleep=sleeps.append,
        post_playback_guard_seconds=0.0,
    )

    assert synth.speak_code("listen_only_ready", threading.Event()) is True
    assert ducker.events == ["pause", "resume"]
    assert sleeps == []


def test_synthesizer_resumes_capture_when_output_fails_or_is_cancelled(tmp_path: Path) -> None:
    for cancelled, outcomes in ((False, [False]), (True, [True, True])):
        runner = RecordingRunner(outcomes)
        ducker = RecordingDucker()
        event = threading.Event()
        if cancelled:
            event.set()
        synth = FixedVoiceSynthesizer(
            runner=runner,
            ducker=ducker,
            temporary_directory=tmp_path,
            sleep=lambda _seconds: None,
        )

        assert synth.speak_code("saved", event) is False
        assert ducker.events == ["pause", "resume"]
        assert list(tmp_path.iterdir()) == []


def test_synthesizer_rejects_unknown_semantic_output(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="^voice_tts_unavailable$"):
        phrase_for_semantic_code("private_server_detail")


def test_command_runner_terminates_an_active_process_on_cancellation() -> None:
    event = threading.Event()

    class Process:
        returncode = None

        def __init__(self) -> None:
            self.terminated = False
            self.killed = False

        def communicate(self, *, input, timeout):
            event.set()
            raise subprocess.TimeoutExpired("say", timeout)

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            self.returncode = -15
            return self.returncode

        def kill(self):
            self.killed = True

    process = Process()
    runner = BoundedCommandRunner(opener=lambda *args, **kwargs: process)

    assert runner.run(
        ("/usr/bin/say", "-f", "-"),
        input_bytes=b"fixed phrase",
        timeout_seconds=1.0,
        cancelled=event,
    ) is False
    assert process.terminated is True
    assert process.killed is False
