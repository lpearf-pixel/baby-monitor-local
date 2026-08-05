from __future__ import annotations

from apps.api.alpha import create_app
from apps.api.runtime import runtime_from_env

app = create_app(runtime_from_env())
