from __future__ import annotations

import argparse
import ipaddress
import os
import plistlib
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LABEL = "com.babymonitor.ollama-tunnel"
TEMPLATE_NAME = f"{LABEL}.plist.example"
PLIST_NAME = f"{LABEL}.plist"
_USER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9._-]{0,63}")
_LOCAL_HOST_PATTERN = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.local"
)


def configure_tunnel(
    *,
    target: str,
    identity: Path,
    project_root: Path = ROOT,
    home: Path | None = None,
) -> tuple[Path, Path]:
    resolved_root = project_root.resolve(strict=True)
    resolved_home = (home or Path.home()).resolve(strict=True)
    _validate_target(target)
    resolved_identity = _validate_identity(identity, resolved_home)

    template_path = resolved_root / "deploy/launchd" / TEMPLATE_NAME
    with template_path.open("rb") as source:
        payload = plistlib.load(source)
    replacements = {
        "__PROJECT_ROOT__": str(resolved_root),
        "__M2_SSH_TARGET__": target,
        "__M2_SSH_IDENTITY__": str(resolved_identity),
    }
    rendered = _replace(payload, replacements)
    if "__" in repr(rendered):
        raise ValueError("tunnel template contains unresolved placeholders")

    runtime_path = resolved_root / "runtime/launchd" / PLIST_NAME
    launch_path = resolved_home / "Library/LaunchAgents" / PLIST_NAME
    data = plistlib.dumps(rendered, fmt=plistlib.FMT_XML, sort_keys=False)
    _atomic_write(runtime_path, data)
    _atomic_write(launch_path, data)
    return runtime_path, launch_path


def _validate_target(target: str) -> None:
    if target.count("@") != 1:
        raise ValueError("target must be a private M2 SSH target")
    user, host = target.split("@", 1)
    if _USER_PATTERN.fullmatch(user) is None:
        raise ValueError("target must be a private M2 SSH target")
    if _LOCAL_HOST_PATTERN.fullmatch(host):
        return
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("target must be a private M2 SSH target") from exc
    if (
        address.version != 4
        or not address.is_private
        or address.is_loopback
        or address.is_unspecified
        or address.is_multicast
    ):
        raise ValueError("target must be a private M2 SSH target")


def _validate_identity(identity: Path, home: Path) -> Path:
    candidate = Path(os.path.expanduser(str(identity)))
    if candidate.is_symlink():
        raise ValueError("identity must be a regular local SSH key")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError("identity must be a regular local SSH key") from exc
    ssh_root = (home / ".ssh").resolve()
    if not resolved.is_file() or not resolved.is_relative_to(ssh_root):
        raise ValueError("identity must be inside the local .ssh directory")
    metadata = resolved.stat()
    if metadata.st_uid != os.geteuid():
        raise ValueError("identity must be owned by the current user")
    if metadata.st_mode & 0o777 not in {0o400, 0o600}:
        raise ValueError("identity must use mode 400 or 600")
    return resolved


def _replace(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _replace(child, replacements) for key, child in value.items()}
    if isinstance(value, list):
        return [_replace(child, replacements) for child in value]
    if isinstance(value, str):
        for old, new in replacements.items():
            value = value.replace(old, new)
    return value


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("refusing to replace a symlinked launch agent")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        output.write(data)
    try:
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure the restricted i9-to-M2 Ollama SSH tunnel."
    )
    parser.add_argument("--target", required=True, help="Dedicated user@private-M2-host")
    parser.add_argument("--identity", type=Path, required=True, help="Dedicated SSH private key")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        configure_tunnel(target=args.target, identity=args.identity)
    except Exception:
        print("ollama_tunnel_configuration_failed", file=sys.stderr)
        return 2
    print("ollama_tunnel_configured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
