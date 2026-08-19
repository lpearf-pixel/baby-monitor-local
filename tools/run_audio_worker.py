from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.contracts.settings import AppSettings
from services.audio.classifier import CryClassifier
from services.audio.events import AudioEventPipeline
from services.audio.features import DynamicLoudnessGate
from services.audio.source import FixedAudioDecoder
from services.audio.state import AudioStateMachine
from services.audio.worker import AudioStatusWriter, AudioWorker
from services.events.store import EventStore


class _OpenVinoRunner:
    def __init__(self, model_path: Path) -> None:
        import openvino

        core = openvino.Core()
        model = core.read_model(model_path)
        if len(model.inputs) != 1 or len(model.outputs) != 1:
            raise ValueError("audio model requires one input and one output")
        self._compiled = core.compile_model(model, "CPU")
        self._input = model.inputs[0]
        self._output = model.outputs[0]

    def run(self, waveform):
        return self._compiled({self._input: waveform})[self._output]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the independent audio worker.")
    parser.add_argument("--settings", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        settings = AppSettings.load(args.settings)
        if not settings.audio.enabled:
            return 0
        data_dir = settings.app.data_dir
        if not data_dir.is_absolute():
            data_dir = ROOT / data_dir
        store = EventStore(data_dir / "events.sqlite3")
        store.migrate()
        worker = AudioWorker(
            settings=settings.audio,
            decoder=FixedAudioDecoder(settings.audio),
            gate=DynamicLoudnessGate(settings=settings.audio),
            classifier=CryClassifier(
                settings.audio,
                project_root=ROOT,
                runner_factory=_OpenVinoRunner,
            ),
            state_machine=AudioStateMachine(settings.audio),
            event_sink=AudioEventPipeline(store=store),
            status_writer=AudioStatusWriter(ROOT / "runtime/status/audio.json"),
        )
    except Exception:
        print("audio_worker_startup_failed", file=sys.stderr)
        return 2

    stop_event = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        worker.run(stop_event)
    except Exception:
        print("audio_worker_runtime_failed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
