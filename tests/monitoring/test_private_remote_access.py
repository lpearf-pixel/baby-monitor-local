from __future__ import annotations

import json

import pytest

from packages.monitoring.private_remote_access import (
    DashboardEvidence,
    ListenerEvidence,
    RemoteCode,
    ServeEvidence,
    TailnetEvidence,
    evaluate_remote_access,
    parse_serve_status,
    parse_tailnet_status,
)


RUNNING = b'{"BackendState":"Running","Self":{"Online":true}}'
FIXED_SERVE = b'''{
  "TCP":{"443":{"HTTPS":true}},
  "Web":{"node.example.invalid:443":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:8080"}}}}
}'''
FUNNEL_SERVE = b'''{
  "TCP":{"443":{"HTTPS":true}},
  "Web":{"node.example.invalid:443":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:8080"}}}},
  "AllowFunnel":{"node.example.invalid:443":true}
}'''


def test_tailnet_status_accepts_only_running_online_self() -> None:
    evidence = parse_tailnet_status(RUNNING)

    assert evidence == TailnetEvidence(authenticated=True)


@pytest.mark.parametrize(
    "payload",
    (
        b"",
        b"[]",
        b"not-json",
        b'{"BackendState":"Stopped","Self":{"Online":true}}',
        b'{"BackendState":"Running","Self":{"Online":false}}',
        b'{"BackendState":"Running","Self":null}',
        b'{"BackendState":true,"Self":{"Online":true}}',
    ),
)
def test_tailnet_status_fails_closed_for_logged_out_or_malformed_payloads(
    payload: bytes,
) -> None:
    assert parse_tailnet_status(payload) == TailnetEvidence(authenticated=False)


def test_tailnet_status_rejects_payload_above_the_fixed_cap() -> None:
    payload = b"{" + b" " * 1_048_575 + b"}"

    assert len(payload) == 1_048_577
    assert parse_tailnet_status(payload).authenticated is False


def test_serve_status_accepts_one_fixed_https_proxy_without_preserving_host() -> None:
    evidence = parse_serve_status(FIXED_SERVE)

    assert evidence == ServeEvidence(
        configured=True,
        fixed_https_proxy=True,
        funnel_present=False,
        conflict=False,
    )
    assert "example.invalid" not in repr(evidence)


def test_empty_serve_status_is_unconfigured_without_a_conflict() -> None:
    assert parse_serve_status(b"{}") == ServeEvidence(
        configured=False,
        fixed_https_proxy=False,
        funnel_present=False,
        conflict=False,
    )


@pytest.mark.parametrize(
    "document",
    (
        [],
        {"TCP": {"443": {"HTTPS": True}}},
        {
            "TCP": {"443": {"HTTPS": True}},
            "Web": {
                "one.example.invalid:443": {
                    "Handlers": {"/": {"Proxy": "http://127.0.0.1:8080"}}
                },
                "two.example.invalid:443": {
                    "Handlers": {"/": {"Proxy": "http://127.0.0.1:8080"}}
                },
            },
        },
        {
            "TCP": {"443": {"HTTPS": True}},
            "Web": {
                "node.example.invalid:443": {
                    "Handlers": {
                        "/": {"Proxy": "http://127.0.0.1:8080"},
                        "/extra": {"Proxy": "http://127.0.0.1:8080"},
                    }
                }
            },
        },
        {
            "TCP": {"443": {"HTTPS": True}},
            "Web": {
                "node.example.invalid:443": {
                    "Handlers": {"/extra": {"Proxy": "http://127.0.0.1:8080"}}
                }
            },
        },
        {
            "TCP": {"443": {"HTTPS": False}},
            "Web": {
                "node.example.invalid:443": {
                    "Handlers": {"/": {"Proxy": "http://127.0.0.1:8080"}}
                }
            },
        },
        {
            "TCP": {"443": {"HTTPS": True}, "8443": {"HTTPS": True}},
            "Web": {
                "node.example.invalid:443": {
                    "Handlers": {"/": {"Proxy": "http://127.0.0.1:8080"}}
                }
            },
        },
        {
            "TCP": {"443": {"HTTPS": True}},
            "Web": {
                "node.example.invalid:443": {
                    "Handlers": {"/": {"Proxy": "http://127.0.0.1:1984"}}
                }
            },
        },
        {
            "TCP": {"443": {"HTTPS": True}},
            "Web": {
                "node.example.invalid:8443": {
                    "Handlers": {"/": {"Proxy": "http://127.0.0.1:8080"}}
                }
            },
        },
        {
            "TCP": {"443": {"HTTPS": True}},
            "Web": {
                "node.example.invalid:443": {
                    "Handlers": {"/": {"Proxy": "http://127.0.0.1:8080"}}
                }
            },
            "UnknownExposure": {"8443": True},
        },
    ),
)
def test_serve_status_marks_every_nonfixed_route_as_a_conflict(
    document: object,
) -> None:
    payload = json.dumps(document).encode("utf-8")

    evidence = parse_serve_status(payload)

    assert evidence.fixed_https_proxy is False
    assert evidence.conflict is True


@pytest.mark.parametrize("payload", (b"", b"not-json", b"null"))
def test_serve_status_marks_malformed_payload_as_a_conflict(payload: bytes) -> None:
    evidence = parse_serve_status(payload)

    assert evidence.fixed_https_proxy is False
    assert evidence.conflict is True


def test_serve_status_rejects_payload_above_the_fixed_cap() -> None:
    payload = b"{" + b" " * 1_048_575 + b"}"

    assert len(payload) == 1_048_577
    assert parse_serve_status(payload).conflict is True


def test_serve_status_detects_funnel_even_when_the_proxy_is_otherwise_fixed() -> None:
    evidence = parse_serve_status(FUNNEL_SERVE)

    assert evidence == ServeEvidence(
        configured=True,
        fixed_https_proxy=True,
        funnel_present=True,
        conflict=True,
    )


def _evaluate(**overrides: object):
    values: dict[str, object] = {
        "installed": True,
        "tailnet": TailnetEvidence(authenticated=True),
        "serve": parse_serve_status(FIXED_SERVE),
        "listeners": ListenerEvidence(
            dashboard_available=True,
            go2rtc_loopback_only=True,
        ),
        "dashboard": DashboardEvidence(
            health_ok=True,
            basic_auth_required=True,
        ),
        "policy_reviewed": True,
    }
    values.update(overrides)
    return evaluate_remote_access(**values)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    (
        ({"installed": False}, RemoteCode.NOT_INSTALLED),
        (
            {"tailnet": TailnetEvidence(authenticated=False)},
            RemoteCode.NOT_AUTHENTICATED,
        ),
        (
            {"dashboard": DashboardEvidence(False, True)},
            RemoteCode.DASHBOARD_UNHEALTHY,
        ),
        (
            {"dashboard": DashboardEvidence(True, False)},
            RemoteCode.DASHBOARD_UNHEALTHY,
        ),
        (
            {"listeners": ListenerEvidence(False, True)},
            RemoteCode.DASHBOARD_UNHEALTHY,
        ),
        (
            {"listeners": ListenerEvidence(True, False)},
            RemoteCode.SERVE_CONFLICT,
        ),
        ({"serve": parse_serve_status(FUNNEL_SERVE)}, RemoteCode.SERVE_CONFLICT),
        ({"policy_reviewed": False}, RemoteCode.POLICY_UNVERIFIED),
        ({"serve": parse_serve_status(b"{}")}, RemoteCode.SERVE_UNCONFIGURED),
        ({}, RemoteCode.READY_SOFTWARE),
    ),
)
def test_remote_state_precedence_is_closed_and_deterministic(
    overrides: dict[str, object], expected: RemoteCode
) -> None:
    assert _evaluate(**overrides).code is expected


def test_serve_conflict_is_not_hidden_by_missing_policy_acknowledgement() -> None:
    report = _evaluate(
        serve=parse_serve_status(FUNNEL_SERVE),
        policy_reviewed=False,
    )

    assert report.code is RemoteCode.SERVE_CONFLICT


def test_software_evaluation_never_synthesizes_device_acceptance() -> None:
    reports = (
        _evaluate(),
        _evaluate(installed=False),
        _evaluate(policy_reviewed=False),
        _evaluate(serve=parse_serve_status(b"{}")),
    )

    assert all(report.code is not RemoteCode.READY_DEVICE_GATE for report in reports)


def test_ready_report_contains_only_derived_bounded_facts() -> None:
    report = _evaluate()

    assert report.code is RemoteCode.READY_SOFTWARE
    assert report.tailnet_authenticated is True
    assert report.serve_fixed is True
    assert report.funnel_absent is True
    assert report.dashboard_healthy is True
    assert report.basic_auth_required is True
    assert report.go2rtc_private is True
    assert report.policy_reviewed is True
