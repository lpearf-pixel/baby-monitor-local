from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def make_recipe(target: str) -> str:
    makefile = read("Makefile")
    match = re.search(
        rf"(?m)^{re.escape(target)}:\n(?P<body>(?:\t[^\n]*\n)+)", makefile
    )
    assert match is not None
    return match.group("body")


def fenced_commands(document: str) -> str:
    return "\n".join(re.findall(r"```(?:bash|sh|console)?\n(.*?)```", document, re.S))


def test_make_targets_use_only_fixed_repository_interfaces() -> None:
    assert make_recipe("alpha-remote-preflight") == (
        "\t@$(PYTHON) tools/private_remote_access.py preflight\n"
    )
    assert make_recipe("alpha-remote-status") == (
        "\t@$(PYTHON) tools/private_remote_access.py status\n"
    )
    assert make_recipe("alpha-remote-configure") == (
        "\t@$(PYTHON) tools/private_remote_access.py configure\n"
    )
    assert make_recipe("alpha-remote-test") == (
        "\t@$(PYTHON) -m pytest -q tests/monitoring/test_private_remote_access.py tests/tools/test_private_remote_access.py tests/deploy/test_private_remote_access.py tests/deploy/test_network_access.py\n"
    )


def test_grant_example_is_minimal_synthetic_json() -> None:
    policy = json.loads(read("config/tailscale.grants.example.hujson"))

    assert policy == {
        "tagOwners": {"tag:baby-monitor": ["autogroup:admin"]},
        "groups": {
            "group:baby-parents": [
                "parent-one@example.invalid",
                "parent-two@example.invalid",
            ]
        },
        "grants": [
            {
                "src": ["group:baby-parents"],
                "dst": ["tag:baby-monitor"],
                "ip": ["tcp:443"],
            }
        ],
    }
    parent_identities = policy["groups"]["group:baby-parents"]
    assert all(identity.endswith(".invalid") for identity in parent_identities)


def test_generic_startup_points_to_bounded_commands_not_raw_mutation() -> None:
    startup = read("tools/start_alpha.sh")
    installer = read("tools/install_alpha_macos.sh")
    combined = startup + installer

    assert "make alpha-remote-preflight" in combined
    assert "docs/runbooks/PRIVATE_REMOTE_ACCESS.md" in combined
    assert "tailscale serve --bg" not in combined.lower()
    assert "tailscale funnel" not in combined.lower()


def test_runbook_separates_read_only_audit_from_explicit_configuration() -> None:
    runbook = read("docs/runbooks/PRIVATE_REMOTE_ACCESS.md")
    commands = fenced_commands(runbook).lower()

    for command in (
        "make alpha-remote-preflight",
        "make alpha-remote-status",
        "make alpha-remote-configure",
        "make alpha-remote-test",
    ):
        assert command in commands
    assert "official tailscale standalone" in runbook.lower()
    assert "cli integration" in runbook.lower()
    assert "merge" in runbook.lower()
    assert "broader grant" in runbook.lower()
    assert "explicit approval" in runbook.lower()
    assert "tailscale serve --bg" not in commands
    assert "tailscale funnel" not in commands
    assert "tailscale reset" not in commands
    assert "tailscale logout" not in commands


def test_remote_operator_files_do_not_publish_private_or_broad_access() -> None:
    paths = (
        "config/tailscale.grants.example.hujson",
        "docs/runbooks/PRIVATE_REMOTE_ACCESS.md",
        "tools/start_alpha.sh",
        "tools/install_alpha_macos.sh",
    )
    combined = "\n".join(read(path) for path in paths)
    private_ipv4 = re.compile(
        r"(?<!127\.0\.0\.1)(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"192\.168\.\d{1,3}\.\d{1,3}|"
        r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})"
    )

    assert private_ipv4.search(combined) is None
    grant = json.loads(read("config/tailscale.grants.example.hujson"))
    assert grant["grants"][0]["ip"] == ["tcp:443"]
    assert "tskey-" not in combined.lower()
    assert "authkey" not in combined.lower()
