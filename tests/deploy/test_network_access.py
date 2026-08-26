from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_installer_defaults_dashboard_to_lan_access() -> None:
    installer = read("tools/install_alpha_macos.sh")

    assert "BABY_MONITOR_BIND_HOST=0.0.0.0" in installer
    assert "BABY_MONITOR_PORT=8080" in installer


def test_start_script_uses_configurable_dashboard_listener() -> None:
    start_script = read("tools/start_alpha.sh")

    assert '--host "${BABY_MONITOR_BIND_HOST}"' in start_script
    assert '--port "${BABY_MONITOR_PORT}"' in start_script
    assert "LAN Dashboard:" in start_script


def test_start_script_preserves_immediate_proxy_peer_for_origin_policy() -> None:
    start_script = read("tools/start_alpha.sh")

    assert "--no-proxy-headers" in start_script


def test_camera_control_ports_remain_loopback_only() -> None:
    go2rtc = read("config/go2rtc.alpha.yaml")

    assert 'listen: "127.0.0.1:1984"' in go2rtc
    assert 'listen: "127.0.0.1:8554"' in go2rtc
    assert 'listen: "127.0.0.1:8555"' in go2rtc
    assert 'listen: "0.0.0.0:1984"' not in go2rtc


def test_runbook_documents_m2_lan_and_ssh_tunnel_access() -> None:
    runbook = read("docs/runbooks/ALPHA_QUICKSTART.md")

    assert "http://<i9局域网IP>:8080" in runbook
    assert "ssh -L 1984:127.0.0.1:1984" in runbook
    assert "make alpha-remote-preflight" in runbook
    assert "docs/runbooks/PRIVATE_REMOTE_ACCESS.md" in runbook
    assert "tailscale serve --bg" not in runbook
