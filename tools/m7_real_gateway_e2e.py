"""One-shot M7 -> Baby Care HTTP -> PostgreSQL isolation runner."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import urllib.request
import socket
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from packages.contracts.voice_care import parse_voice_care_intent
from services.voice.m7_gateway import M7BabyCareGateway
from services.voice.m7_orchestrator import M7Orchestrator
from services.voice.m7_session import M6ToolExecutor, M7SessionBridge
from services.voice.signing import canonical_json_bytes


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class EphemeralIdentity:
    def __init__(self, seed: bytes) -> None:
        self._key = Ed25519PrivateKey.from_private_bytes(seed)

    def sign_intent(self, value: dict[str, object]) -> bytes:
        candidate = dict(value)
        candidate["signature"] = "A" * 86
        parse_voice_care_intent(canonical_json_bytes(candidate))
        signed = dict(value)
        signed["signature"] = _b64(self._key.sign(canonical_json_bytes(value)))
        return canonical_json_bytes(signed)


def _transport(base: str):
    state: dict[str, object] = {"status": None, "body": ""}
    def send(body: bytes) -> tuple[int, bytes]:
        request = urllib.request.Request(
            f"{base}/api/voice-care/intents",
            data=body,
            headers={"content-type": "application/vnd.baby-care.voice-intent+json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                raw = response.read(16_384)
                state.update(status=response.status, body=raw.decode("utf-8", "replace")[:500])
                return response.status, raw
        except Exception as error:
            state.update(status=getattr(error, "code", 599), body=str(error)[:500])
            return 599, b""
    send.state = state
    return send


def _psql(container: str, sql: str) -> str:
    result = subprocess.run(
        ["docker", "exec", container, "psql", "-U", "babycare", "-d", "babycare_test", "-At", "-c", sql],
        check=True, text=True, capture_output=True,
    )
    return result.stdout.strip()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    baby_care = (root / "../baby-care").resolve()
    if not (baby_care / "apps/api/src/app.ts").is_file():
        print("BLOCKED baby-care checkout missing", file=sys.stderr)
        return 2
    pg = f"m7-18-pg-{os.getpid()}"
    seed = secrets.token_bytes(32)
    env = os.environ.copy()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        api_host_port = sock.getsockname()[1]
    env.update({"BABY_CARE_ROOT": "/workspace", "M7_DEVICE_SEED_HEX": seed.hex(),
                "API_PORT": "18080",
                "TEST_DATABASE_URL": "postgres://babycare:synthetic-only@host.docker.internal:55443/babycare_test"})
    harness = root / "tools/m7_baby_care_harness.mjs"
    container = subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", pg, "-e", "POSTGRES_USER=babycare",
         "-e", "POSTGRES_PASSWORD=synthetic-only", "-e", "POSTGRES_DB=babycare_test",
         "-p", "55443:5432", "postgres:16-alpine"], check=True, text=True, capture_output=True,
    ).stdout.strip()
    proc = None
    try:
        for _ in range(30):
            if subprocess.run(["docker", "exec", pg, "pg_isready", "-U", "babycare", "-d", "babycare_test"], capture_output=True).returncode == 0:
                break
        else:
            raise RuntimeError("postgres_not_ready")
        proc = subprocess.Popen([
            "docker", "run", "--rm", "--add-host", "host.docker.internal:host-gateway",
            "-e", "BABY_CARE_ROOT", "-e", "TEST_DATABASE_URL", "-e", "M7_DEVICE_SEED_HEX",
            "-e", "API_PORT", "-p", f"{api_host_port}:18080",
            "-v", f"{baby_care}:/workspace", "-v", "/workspace/node_modules",
            "-v", f"{harness}:/runner.mjs:ro",
            "-w", "/workspace/apps/api", "node:24-bookworm-slim", "bash", "-lc",
            "corepack enable >/dev/null 2>&1 && corepack prepare pnpm@10.17.1 --activate >/dev/null 2>&1 && pnpm install --frozen-lockfile --ignore-scripts >/dev/null 2>&1 && pnpm exec tsx /runner.mjs",
        ], env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        ready_line = proc.stdout.readline()
        if not ready_line:
            error = proc.stderr.read(4096).strip()
            raise RuntimeError(f"api_harness_start_failed:{error[:1000]}")
        ready = json.loads(ready_line)
        if ready.get("ready") is not True:
            raise RuntimeError("api_not_ready")
        base = f"http://127.0.0.1:{api_host_port}"
        transport = _transport(base)
        gateway = M7BabyCareGateway(
            identity=EphemeralIdentity(seed), transport=transport,
            device_id=ready["deviceId"], lease_id=ready["leaseId"],
            request_id_factory=(f"00000000-0000-4000-8000-{i:012d}" for i in range(1, 30)).__next__,
            clock=lambda: datetime(2026, 10, 15, 8, tzinfo=timezone.utc),
        )
        executor = M6ToolExecutor(M7SessionBridge(gateway), clock=lambda: datetime(2026, 10, 15, 8, tzinfo=timezone.utc))
        class Unavailable:
            def complete(self, _text, _context):
                from services.voice.m7_llm import LlmUnavailable
                return LlmUnavailable()
        orchestrator = M7Orchestrator(Unavailable(), executor, fallback=lambda _: "fallback",
                                      deterministic_routing=True, sensitive_routing=True)
        context: dict[str, object] = {"phase": "idle"}
        outputs = []
        for text in ("开始喂奶", "母乳六十毫升", "配方奶三十毫升", "奶粉改成四十毫升", "喂完了，结束喂奶"):
            outcome = orchestrator.handle(text, context, identity_bound=True)
            outputs.append(outcome.code)
            if outcome.code == "accepted_pending": context["phase"] = "pending"
            if outcome.code == "needs_confirmation": context.update({"phase": "needs_confirmation", "proposal_version": 3})
        before = _psql(pg, "select count(*) from care_events where source::text='voice'")
        if before != "0": raise RuntimeError(f"authority_before_confirm={before}")
        saved = orchestrator.handle("确认保存这次喂奶", context, identity_bound=True)
        outputs.append(saved.code)
        after = _psql(pg, "select count(*) from care_events where source::text='voice'")
        rows = _psql(pg, "select liquid_type||':'||coalesce(amount_ml::text,'null') from feeding_components where session_event_id=(select id from care_events where source::text='voice' limit 1) order by liquid_type")
        duplicate = orchestrator.handle("确认保存这次喂奶", context, identity_bound=True)
        final = _psql(pg, "select count(*) from care_events where source::text='voice'")
        no_draft = orchestrator.handle("确认保存这次喂奶", {"phase": "idle"}, identity_bound=True)
        cancel_gateway = M7BabyCareGateway(
            identity=EphemeralIdentity(seed), transport=transport,
            device_id=ready["deviceId"], lease_id=ready["leaseId"],
            request_id_factory=(f"00000000-0000-4000-8000-{i:012d}" for i in range(100, 130)).__next__,
            clock=lambda: datetime(2026, 10, 15, 8, tzinfo=timezone.utc),
        )
        cancel_exec = M6ToolExecutor(M7SessionBridge(cancel_gateway), clock=lambda: datetime(2026, 10, 15, 8, tzinfo=timezone.utc))
        cancel_flow = M7Orchestrator(Unavailable(), cancel_exec, fallback=lambda _: "fallback",
                                     deterministic_routing=True, sensitive_routing=True)
        cancel_context: dict[str, object] = {"phase": "idle"}
        cancel_flow.handle("开始喂奶", cancel_context, identity_bound=True)
        cancel_context["phase"] = "pending"
        cancel_flow.handle("配方奶三十毫升", cancel_context, identity_bound=True)
        cancelled = cancel_flow.handle("取消这次记录", cancel_context, identity_bound=True)
        cancel_context["phase"] = "needs_confirmation"
        cancelled_confirm = cancel_flow.handle("确认保存这次喂奶", cancel_context, identity_bound=True)
        after_safety = _psql(pg, "select count(*) from care_events where source::text='voice'")
        if saved.code != "saved" or after != "1" or final != "1" or duplicate.code not in {"state_conflict", "saved"}:
            raise RuntimeError(f"e2e_assertion_failed outputs={outputs} duplicate={duplicate.code} counts={before},{after},{final} response={transport.state}")
        if rows != "expressed_breast_milk:60\nformula:40": raise RuntimeError(f"components={rows!r}")
        print(json.dumps({"RUNNER_EXECUTED": True, "POSTGRES_END_TO_END_PASS": True,
                          "outputs": outputs, "authority_records_before": 0,
                          "authority_records_after": 1, "duplicate_result": duplicate.code,
                          "components": rows.splitlines(), "llm_calls": 0,
                          "no_draft_confirm": no_draft.code,
                          "cancel_result": cancelled.code,
                          "cancel_then_confirm": cancelled_confirm.code,
                          "authority_records_after_safety": int(after_safety)}))
        return 0
    finally:
        if proc is not None:
            try:
                proc.stdin.write("stop\n"); proc.stdin.flush(); proc.wait(timeout=10)
            except Exception:
                proc.kill()
        subprocess.run(["docker", "rm", "-f", pg], check=False, capture_output=True)


if __name__ == "__main__":
    raise SystemExit(main())
