from __future__ import annotations

import os
from pathlib import Path
import sys
from collections.abc import Callable, Iterator


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.vision.scene_acceptance import (  # noqa: E402
    OUTCOMES,
    SCENES,
    GuardianSceneAcceptanceStore,
)


def run_scene_acceptance(
    state_root: Path,
    input_values: Iterator[str],
    emit: Callable[[str], None],
    *,
    simulated: bool = False,
) -> int:
    try:
        if next(input_values) != "YES" or next(input_values) != "YES":
            emit("FAIL scene safety safety_not_confirmed")
            emit("guardian_scene_test=FAIL")
            return 1
    except StopIteration:
        emit("FAIL scene safety safety_not_confirmed")
        emit("guardian_scene_test=FAIL")
        return 1
    emit("PASS scene safety")

    store = GuardianSceneAcceptanceStore(state_root)
    try:
        state = store.load_or_start()
        if state["state"] != "incomplete":
            return _emit_final(state["state"], emit, simulated=simulated)

        counts = {
            scene: sum(trial["scene"] == scene for trial in state["trials"])
            for scene in SCENES
        }
        for scene in SCENES:
            while counts[scene] < 10:
                emit(f"READY scene trial scene={scene} count={counts[scene] + 1}")
                try:
                    outcome = next(input_values)
                except StopIteration:
                    emit("INCOMPLETE scene input")
                    emit("guardian_scene_test=INCOMPLETE")
                    return 2
                if outcome not in OUTCOMES:
                    emit("FAIL scene input invalid_outcome")
                    emit("guardian_scene_test=FAIL")
                    return 1
                state = store.record(scene, outcome)
                counts[scene] += 1
                emit(
                    f"PASS scene trial scene={scene} count={counts[scene]} "
                    f"outcome={outcome}"
                )
            scene_outcomes = [
                trial["outcome"]
                for trial in state["trials"]
                if trial["scene"] == scene
            ]
            emit(
                f"SUMMARY scene {scene} "
                f"correct={scene_outcomes.count('correct')} "
                f"false_positive={scene_outcomes.count('false_positive')} "
                f"missed={scene_outcomes.count('missed')} "
                f"unavailable={scene_outcomes.count('unavailable')}"
            )
        state = store.finalize()
        return _emit_final(state["state"], emit, simulated=simulated)
    except Exception:
        emit("FAIL scene storage storage_failed")
        emit("guardian_scene_test=FAIL")
        return 1


def _emit_final(
    state: object,
    emit: Callable[[str], None],
    *,
    simulated: bool,
) -> int:
    if simulated:
        emit("guardian_scene_test=SIMULATED")
        return 0 if state == "passed" else 1
    if state == "passed":
        emit("guardian_scene_test=PASS")
        return 0
    emit("guardian_scene_test=FAIL")
    return 1


def _terminal_inputs(terminal: object) -> Iterator[str]:
    prompts = iter(
        (
            "Confirm no real infant is used. Type YES: ",
            "Confirm an adult is supervising. Type YES: ",
        )
    )
    for prompt in prompts:
        terminal.write(prompt)
        terminal.flush()
        value = terminal.readline()
        if value == "":
            return
        yield value.rstrip("\n")
    while True:
        terminal.write("Enter outcome (correct|false_positive|missed|unavailable): ")
        terminal.flush()
        value = terminal.readline()
        if value == "":
            return
        yield value.rstrip("\n")


def main() -> int:
    test_mode = os.environ.get("BABY_MONITOR_GUARDIAN_SCENE_TEST_MODE") == "1"
    if test_mode:
        state_value = os.environ.get("BABY_MONITOR_GUARDIAN_SCENE_STATE_ROOT", "")
        if not state_value:
            print("FAIL scene test_mode hooks_missing")
            print("guardian_scene_test=FAIL")
            return 1
        return run_scene_acceptance(
            Path(state_value),
            iter(line.rstrip("\n") for line in sys.stdin),
            print,
            simulated=True,
        )
    if not sys.stdin.isatty():
        print("FAIL scene interactive interactive_required")
        print("guardian_scene_test=FAIL")
        return 1
    with open("/dev/tty", "r+", encoding="utf-8") as terminal:
        return run_scene_acceptance(
            ROOT / "runtime/status/guardian-scene-acceptance",
            _terminal_inputs(terminal),
            print,
        )


if __name__ == "__main__":
    raise SystemExit(main())
