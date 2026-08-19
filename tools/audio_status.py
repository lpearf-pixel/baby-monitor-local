from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    path = Path(args[0]) if len(args) == 1 else Path("runtime/status/audio.json")
    try:
        payload = json.loads(path.read_text(encoding="ascii"))
        state = payload["worker_state"]
        observation = payload["observation_state"]
        reason = payload["failure_reason"] or "none"
    except Exception:
        print("audio_status=unavailable")
        return 2
    if state not in {"healthy", "degraded"}:
        print("audio_status=invalid")
        return 2
    print(f"audio_status={state} observation={observation} reason={reason}")
    return 0 if state == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
