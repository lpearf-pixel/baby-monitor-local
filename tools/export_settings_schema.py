from __future__ import annotations

import json
from pathlib import Path

from packages.contracts.settings import AppSettings


def main() -> int:
    target = Path("config/settings.schema.json")
    payload = json.dumps(AppSettings.model_json_schema(), indent=2)
    target.write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
