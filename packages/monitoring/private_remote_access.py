"""Pure, bounded evidence evaluation for private Dashboard access."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


MAX_STATUS_BYTES = 1_048_576
FIXED_PROXY_TARGET = "http://127.0.0.1:8080"
_SERVE_FIELDS = frozenset({"TCP", "Web", "AllowFunnel"})


class RemoteCode(StrEnum):
    NOT_INSTALLED = "REMOTE_NOT_INSTALLED"
    NOT_AUTHENTICATED = "REMOTE_NOT_AUTHENTICATED"
    DASHBOARD_UNHEALTHY = "REMOTE_DASHBOARD_UNHEALTHY"
    POLICY_UNVERIFIED = "REMOTE_POLICY_UNVERIFIED"
    SERVE_UNCONFIGURED = "REMOTE_SERVE_UNCONFIGURED"
    SERVE_CONFLICT = "REMOTE_SERVE_CONFLICT"
    READY_SOFTWARE = "REMOTE_READY_SOFTWARE"
    READY_DEVICE_GATE = "REMOTE_READY_DEVICE_GATE"


@dataclass(frozen=True)
class TailnetEvidence:
    authenticated: bool


@dataclass(frozen=True)
class ServeEvidence:
    configured: bool
    fixed_https_proxy: bool
    funnel_present: bool
    conflict: bool


@dataclass(frozen=True)
class ListenerEvidence:
    dashboard_available: bool
    go2rtc_loopback_only: bool


@dataclass(frozen=True)
class DashboardEvidence:
    health_ok: bool
    basic_auth_required: bool


@dataclass(frozen=True)
class RemoteAccessReport:
    code: RemoteCode
    tailnet_authenticated: bool
    serve_fixed: bool
    funnel_absent: bool
    dashboard_healthy: bool
    basic_auth_required: bool
    go2rtc_private: bool
    policy_reviewed: bool


def _load_object(payload: bytes) -> dict[str, Any] | None:
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_STATUS_BYTES:
        return None
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return document if type(document) is dict else None


def parse_tailnet_status(payload: bytes) -> TailnetEvidence:
    document = _load_object(payload)
    if document is None:
        return TailnetEvidence(authenticated=False)
    self_status = document.get("Self")
    authenticated = bool(
        document.get("BackendState") == "Running"
        and type(self_status) is dict
        and self_status.get("Online") is True
    )
    return TailnetEvidence(authenticated=authenticated)


def parse_serve_status(payload: bytes) -> ServeEvidence:
    document = _load_object(payload)
    if document is None:
        return _serve_conflict(configured=False)
    if not document:
        return ServeEvidence(False, False, False, False)

    funnel_present = bool(document.get("AllowFunnel"))
    fixed = _is_fixed_serve_document(document)
    return ServeEvidence(
        configured=True,
        fixed_https_proxy=fixed,
        funnel_present=funnel_present,
        conflict=funnel_present or not fixed,
    )


def _serve_conflict(*, configured: bool) -> ServeEvidence:
    return ServeEvidence(
        configured=configured,
        fixed_https_proxy=False,
        funnel_present=False,
        conflict=True,
    )


def _is_fixed_serve_document(document: dict[str, Any]) -> bool:
    if not set(document).issubset(_SERVE_FIELDS):
        return False

    tcp = document.get("TCP")
    web = document.get("Web")
    if type(tcp) is not dict or set(tcp) != {"443"}:
        return False
    tcp_443 = tcp.get("443")
    if type(tcp_443) is not dict or tcp_443 != {"HTTPS": True}:
        return False
    if type(web) is not dict or len(web) != 1:
        return False

    host, route = next(iter(web.items()))
    if (
        type(host) is not str
        or not host.endswith(":443")
        or not host[:-4]
        or any(character.isspace() for character in host)
        or type(route) is not dict
        or set(route) != {"Handlers"}
    ):
        return False
    handlers = route.get("Handlers")
    return bool(
        type(handlers) is dict
        and handlers == {"/": {"Proxy": FIXED_PROXY_TARGET}}
    )


def evaluate_remote_access(
    *,
    installed: bool,
    tailnet: TailnetEvidence,
    serve: ServeEvidence,
    listeners: ListenerEvidence,
    dashboard: DashboardEvidence,
    policy_reviewed: bool,
) -> RemoteAccessReport:
    dashboard_healthy = dashboard.health_ok and listeners.dashboard_available
    if not installed:
        code = RemoteCode.NOT_INSTALLED
    elif not tailnet.authenticated:
        code = RemoteCode.NOT_AUTHENTICATED
    elif not dashboard_healthy or not dashboard.basic_auth_required:
        code = RemoteCode.DASHBOARD_UNHEALTHY
    elif (
        not listeners.go2rtc_loopback_only
        or serve.funnel_present
        or serve.conflict
    ):
        code = RemoteCode.SERVE_CONFLICT
    elif not policy_reviewed:
        code = RemoteCode.POLICY_UNVERIFIED
    elif not serve.configured or not serve.fixed_https_proxy:
        code = RemoteCode.SERVE_UNCONFIGURED
    else:
        code = RemoteCode.READY_SOFTWARE

    return RemoteAccessReport(
        code=code,
        tailnet_authenticated=tailnet.authenticated,
        serve_fixed=serve.fixed_https_proxy,
        funnel_absent=not serve.funnel_present,
        dashboard_healthy=dashboard_healthy,
        basic_auth_required=dashboard.basic_auth_required,
        go2rtc_private=listeners.go2rtc_loopback_only,
        policy_reviewed=policy_reviewed,
    )


__all__ = [
    "DashboardEvidence",
    "FIXED_PROXY_TARGET",
    "ListenerEvidence",
    "MAX_STATUS_BYTES",
    "RemoteAccessReport",
    "RemoteCode",
    "ServeEvidence",
    "TailnetEvidence",
    "evaluate_remote_access",
    "parse_serve_status",
    "parse_tailnet_status",
]
