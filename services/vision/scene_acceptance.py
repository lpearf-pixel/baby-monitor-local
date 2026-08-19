from __future__ import annotations

import json
import math
import os
from pathlib import Path
import stat
import tempfile
import time
from collections.abc import Callable


SCENES = (
    "empty_bed",
    "doll_or_prop",
    "adult_in_frame",
    "infrared_night",
    "camera_obstruction",
    "mosquito_net_movement",
    "normal_turning_substitute",
)
OUTCOMES = ("correct", "false_positive", "missed", "unavailable")
_STATES = ("incomplete", "passed", "failed")
_FILENAME = "guardian-scene-acceptance.json"


class GuardianSceneAcceptanceStore:
    def __init__(
        self,
        root: Path,
        *,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._root = Path(root)
        self._path = self._root / _FILENAME
        self._wall_clock = wall_clock

    def start(self) -> dict[str, object]:
        self._ensure_safe_root()
        now = self._now()
        payload: dict[str, object] = {
            "schema_version": 1,
            "state": "incomplete",
            "started_at_unix": now,
            "updated_at_unix": now,
            "trials": [],
        }
        self._write(payload)
        return payload

    def load(self) -> dict[str, object]:
        self._ensure_safe_root(create=False)
        if self._path.is_symlink():
            raise ValueError("invalid scene acceptance state")
        try:
            payload = json.loads(
                self._path.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_pairs,
            )
        except (FileNotFoundError, json.JSONDecodeError) as failure:
            raise ValueError("invalid scene acceptance state") from failure
        _validate_payload(payload)
        return payload

    def load_or_start(self) -> dict[str, object]:
        if self._path.exists() or self._path.is_symlink():
            return self.load()
        return self.start()

    def record(self, scene: str, outcome: str) -> dict[str, object]:
        if scene not in SCENES or outcome not in OUTCOMES:
            raise ValueError("invalid scene acceptance trial")
        payload = self.load()
        if payload["state"] != "incomplete":
            raise ValueError("scene acceptance run is closed")
        trials = list(payload["trials"])
        if sum(trial["scene"] == scene for trial in trials) >= 10:
            raise ValueError("scene trial limit reached")
        now = self._next_time(payload["updated_at_unix"])
        trials.append(
            {
                "scene": scene,
                "ordinal": len(trials) + 1,
                "outcome": outcome,
                "recorded_at_unix": now,
            }
        )
        updated = {**payload, "updated_at_unix": now, "trials": trials}
        self._write(updated)
        return updated

    def finalize(self) -> dict[str, object]:
        payload = self.load()
        if payload["state"] != "incomplete":
            raise ValueError("scene acceptance run is closed")
        trials = payload["trials"]
        complete = all(
            sum(trial["scene"] == scene for trial in trials) == 10
            for scene in SCENES
        )
        if not complete:
            raise ValueError("scene acceptance run is incomplete")
        passed = True
        for scene in SCENES:
            outcomes = [
                trial["outcome"] for trial in trials if trial["scene"] == scene
            ]
            if scene == "camera_obstruction":
                passed = passed and outcomes.count("correct") >= 9
                passed = passed and "unavailable" not in outcomes
                passed = passed and "false_positive" not in outcomes
            else:
                passed = passed and all(outcome == "correct" for outcome in outcomes)
        now = self._next_time(payload["updated_at_unix"])
        completed = {
            **payload,
            "state": "passed" if passed else "failed",
            "updated_at_unix": now,
        }
        self._write(completed)
        return completed

    def _ensure_safe_root(self, *, create: bool = True) -> None:
        self._reject_symlink_ancestors()
        try:
            root_stat = os.lstat(self._root)
        except FileNotFoundError:
            if not create:
                raise ValueError("invalid scene acceptance state")
            self._root.mkdir(parents=True, mode=0o700)
            root_stat = os.lstat(self._root)
        if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
            raise ValueError("unsafe scene acceptance root")

    def _reject_symlink_ancestors(self) -> None:
        current = self._root.absolute()
        existing: list[Path] = []
        while True:
            if current.exists() or current.is_symlink():
                existing.append(current)
            if current.parent == current:
                break
            current = current.parent
        for path in existing:
            if stat.S_ISLNK(os.lstat(path).st_mode):
                raise ValueError("unsafe scene acceptance root")

    def _write(self, payload: dict[str, object]) -> None:
        _validate_payload(payload)
        self._ensure_safe_root()
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{_FILENAME}.", suffix=".tmp", dir=self._root
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path)
            os.chmod(self._path, 0o600)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            temporary.unlink(missing_ok=True)
            raise

    def _now(self) -> float:
        now = self._wall_clock()
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise ValueError("invalid scene acceptance time")
        return float(now)

    def _next_time(self, previous: object) -> float:
        now = self._now()
        if type(previous) not in (int, float) or now < previous:
            raise ValueError("invalid scene acceptance time")
        return now


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("invalid scene acceptance state")
        payload[key] = value
    return payload


def _validate_payload(payload: object) -> None:
    expected = {
        "schema_version",
        "state",
        "started_at_unix",
        "updated_at_unix",
        "trials",
    }
    if type(payload) is not dict or set(payload) != expected:
        raise ValueError("invalid scene acceptance state")
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
        or payload["state"] not in _STATES
    ):
        raise ValueError("invalid scene acceptance state")
    started = payload["started_at_unix"]
    updated = payload["updated_at_unix"]
    if not _valid_time(started) or not _valid_time(updated) or updated < started:
        raise ValueError("invalid scene acceptance state")
    trials = payload["trials"]
    if type(trials) is not list or len(trials) > len(SCENES) * 10:
        raise ValueError("invalid scene acceptance state")
    counts = {scene: 0 for scene in SCENES}
    for index, trial in enumerate(trials, start=1):
        if type(trial) is not dict or set(trial) != {
            "scene",
            "ordinal",
            "outcome",
            "recorded_at_unix",
        }:
            raise ValueError("invalid scene acceptance state")
        scene = trial["scene"]
        if (
            scene not in SCENES
            or trial["outcome"] not in OUTCOMES
            or type(trial["ordinal"]) is not int
            or trial["ordinal"] != index
            or not _valid_time(trial["recorded_at_unix"])
            or not started <= trial["recorded_at_unix"] <= updated
        ):
            raise ValueError("invalid scene acceptance state")
        counts[scene] += 1
        if counts[scene] > 10:
            raise ValueError("invalid scene acceptance state")


def _valid_time(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0
