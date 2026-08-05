from __future__ import annotations

import os
import shlex
from pathlib import Path


def load_local_env_file(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        name, separator, raw_value = line.partition("=")
        if not separator or not name.replace("_", "A").isalnum():
            raise ValueError("environment file contains an invalid assignment")
        parsed = shlex.split(raw_value, comments=False, posix=True)
        if len(parsed) > 1:
            raise ValueError("environment file contains an invalid value")
        os.environ.setdefault(name, parsed[0] if parsed else "")
