from __future__ import annotations

from collections.abc import Callable

from apps.api.alpha import AlphaGateway
from apps.api.runtime import notification_gateway_from_env


def send_live_notification(
    gateway_factory: Callable[[], AlphaGateway] = notification_gateway_from_env,
) -> bool:
    try:
        gateway_factory().send_test_notification()
    except Exception:
        return False
    return True


def main() -> int:
    return 0 if send_live_notification() else 1


if __name__ == "__main__":
    raise SystemExit(main())
