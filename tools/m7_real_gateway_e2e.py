"""One-shot M7 -> Baby Care HTTP -> PostgreSQL isolation runner."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.request
import socket
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from packages.contracts.voice_care import parse_voice_care_intent
from services.voice.m7_gateway import M7BabyCareGateway, _envelope
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


def _sql(container: str, statement: str) -> None:
    result = subprocess.run(
        ["docker", "exec", container, "psql", "-U", "babycare", "-d", "babycare_test", "-v", "ON_ERROR_STOP=1", "-c", statement],
        check=False, text=True, capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"isolated_sql_failed:{result.stderr.strip()[:500]}")


class _ResponseLossTransport:
    """Drop one post-commit response while retaining the exact request bytes."""

    def __init__(self, inner):
        self._inner = inner
        self.drop_next = False
        self.last_body: bytes | None = None
        self.last_code: str | None = None

    def __call__(self, body: bytes) -> tuple[int, bytes]:
        self.last_body = body
        result = self._inner(body)
        try:
            self.last_code = str(json.loads(result[1].decode("utf-8")).get("code")) if result[0] == 200 else f"http_{result[0]}"
        except Exception:
            self.last_code = "malformed"
        if self.drop_next:
            self.drop_next = False
            raise TimeoutError("m7_injected_response_loss")
        return result


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    baby_care = (root / "../baby-care").resolve()
    if not (baby_care / "apps/api/src/app.ts").is_file():
        print("BLOCKED baby-care checkout missing", file=sys.stderr)
        return 2
    pg = f"m7-18-pg-{os.getpid()}"
    seed = secrets.token_bytes(32)
    env = os.environ.copy()
    def free_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]
    api_host_port = free_port()
    pg_host_port = free_port()
    env.update({"BABY_CARE_ROOT": "/workspace", "M7_DEVICE_SEED_HEX": seed.hex(),
                "API_PORT": "18080",
                "M7_API_NOW": "2026-10-15T08:00:00Z",
                "PG_HOST_PORT": str(pg_host_port),
                "TEST_DATABASE_URL": "postgres://babycare:synthetic-only@host.docker.internal:%s/babycare_test" % pg_host_port})
    harness = root / "tools/m7_baby_care_harness.mjs"
    container = None
    for _ in range(5):
        result = subprocess.run(
            ["docker", "run", "-d", "--rm", "--name", pg, "-e", "POSTGRES_USER=babycare",
             "-e", "POSTGRES_PASSWORD=synthetic-only", "-e", "POSTGRES_DB=babycare_test",
             "-p", f"127.0.0.1:{pg_host_port}:5432", "postgres:16-alpine"],
            check=False, text=True, capture_output=True,
        )
        if result.returncode == 0:
            container = result.stdout.strip()
            break
        if "address already in use" not in result.stderr.lower():
            raise RuntimeError(f"postgres_start_failed:{result.stderr.strip()[:500]}")
        pg_host_port = free_port()
        env["PG_HOST_PORT"] = str(pg_host_port)
        env["TEST_DATABASE_URL"] = "postgres://babycare:synthetic-only@host.docker.internal:%s/babycare_test" % pg_host_port
    if container is None:
        raise RuntimeError("postgres_port_allocation_failed")
    proc = None
    try:
        for _ in range(30):
            if subprocess.run(["docker", "exec", pg, "pg_isready", "-U", "babycare", "-d", "babycare_test"], capture_output=True).returncode == 0:
                break
        else:
            raise RuntimeError("postgres_not_ready")
        for _ in range(5):
            api_host_port = free_port()
            proc = subprocess.Popen([
                "docker", "run", "--rm", "--add-host", "host.docker.internal:host-gateway",
                "-e", "BABY_CARE_ROOT", "-e", "TEST_DATABASE_URL", "-e", "M7_DEVICE_SEED_HEX",
                "-e", "API_PORT", "-e", "M7_API_NOW", "-p", f"127.0.0.1:{api_host_port}:18080",
                "-v", f"{baby_care}:/workspace", "-v", "/workspace/node_modules",
                "-v", f"{harness}:/runner.mjs:ro",
                "-w", "/workspace/apps/api", "node:24-bookworm-slim", "bash", "-lc",
                "corepack enable >/dev/null 2>&1 && corepack prepare pnpm@10.17.1 --activate >/dev/null 2>&1 && pnpm install --frozen-lockfile --ignore-scripts >/dev/null 2>&1 && pnpm exec tsx /runner.mjs",
            ], env=env,
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            ready_line = proc.stdout.readline()
            if ready_line:
                break
            error = proc.stderr.read(4096).strip()
            if "address already in use" in error.lower():
                proc.wait(timeout=10)
                proc = None
                continue
            raise RuntimeError(f"api_harness_start_failed:{error[:1000]}")
        else:
            raise RuntimeError("api_port_allocation_failed")
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

        def make_flow(flow_transport, start_index: int):
            flow_gateway = M7BabyCareGateway(
                identity=EphemeralIdentity(seed), transport=flow_transport,
                device_id=ready["deviceId"], lease_id=ready["leaseId"],
                request_id_factory=(f"00000000-0000-4000-8000-{i:012d}" for i in range(start_index, start_index + 30)).__next__,
                clock=lambda: datetime(2026, 10, 15, 8, tzinfo=timezone.utc),
            )
            flow_executor = M6ToolExecutor(M7SessionBridge(flow_gateway), clock=lambda: datetime(2026, 10, 15, 8, tzinfo=timezone.utc))
            flow_orchestrator = M7Orchestrator(Unavailable(), flow_executor, fallback=lambda _: "fallback",
                                               deterministic_routing=True, sensitive_routing=True)
            return flow_gateway, flow_orchestrator, {"phase": "idle"}

        def prepare_proposal(flow_orchestrator, flow_context, breast="母乳六十一毫升", formula="配方奶三十一毫升"):
            for phrase in ("开始喂奶", breast, formula, "喂完了，结束喂奶"):
                flow_orchestrator.handle(phrase, flow_context, identity_bound=True)

        def prepare_direct_proposal(flow_orchestrator, flow_context):
            for phrase in ("开始喂奶", "亲喂十五分钟", "喂完了，结束喂奶"):
                flow_orchestrator.handle(phrase, flow_context, identity_bound=True)

        def set_api_now(value: str) -> None:
            proc.stdin.write(f"set-now {value}\n"); proc.stdin.flush()

        orchestrator = M7Orchestrator(Unavailable(), executor, fallback=lambda _: "fallback",
                                      deterministic_routing=True, sensitive_routing=True)
        context: dict[str, object] = {"phase": "idle"}
        outputs = []
        for text in ("开始喂奶", "母乳六十毫升", "配方奶三十毫升", "奶粉改成四十毫升", "喂完了，结束喂奶"):
            outcome = orchestrator.handle(text, context, identity_bound=True)
            outputs.append(outcome.code)
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
        cancel_flow.handle("配方奶三十毫升", cancel_context, identity_bound=True)
        cancelled = cancel_flow.handle("取消这次记录", cancel_context, identity_bound=True)
        cancelled_confirm = cancel_flow.handle("确认保存这次喂奶", cancel_context, identity_bound=True)
        bad_gateway = M7BabyCareGateway(
            identity=EphemeralIdentity(secrets.token_bytes(32)), transport=transport,
            device_id=ready["deviceId"], lease_id=ready["leaseId"],
            request_id_factory=(f"00000000-0000-4000-8000-{i:012d}" for i in range(200, 210)).__next__,
            clock=lambda: datetime(2026, 10, 15, 8, tzinfo=timezone.utc),
        )
        bad_exec = M6ToolExecutor(M7SessionBridge(bad_gateway), clock=lambda: datetime(2026, 10, 15, 8, tzinfo=timezone.utc))
        bad_identity = M7Orchestrator(Unavailable(), bad_exec, fallback=lambda _: "fallback", deterministic_routing=True)
        bad_identity_result = bad_identity.handle("开始喂奶", {}, identity_bound=True)
        unavailable_gateway = M7BabyCareGateway(
            identity=EphemeralIdentity(seed), transport=_transport("http://127.0.0.1:1"),
            device_id=ready["deviceId"], lease_id=ready["leaseId"],
            request_id_factory=(f"00000000-0000-4000-8000-{i:012d}" for i in range(300, 310)).__next__,
            clock=lambda: datetime(2026, 10, 15, 8, tzinfo=timezone.utc),
        )
        unavailable_exec = M6ToolExecutor(M7SessionBridge(unavailable_gateway), clock=lambda: datetime(2026, 10, 15, 8, tzinfo=timezone.utc))
        unavailable_result = M7Orchestrator(Unavailable(), unavailable_exec, fallback=lambda _: "fallback", deterministic_routing=True).handle("开始喂奶", {}, identity_bound=True)

        set_api_now("2026-10-15T08:01:00Z")
        concurrent_gateway, concurrent_flow, concurrent_context = make_flow(transport, 400)
        prepare_proposal(concurrent_flow, concurrent_context, "母乳六十一毫升", "配方奶三十一毫升")
        with ThreadPoolExecutor(max_workers=2) as pool:
            concurrent_results = list(pool.map(
                lambda _: concurrent_flow.handle("确认保存这次喂奶", concurrent_context, identity_bound=True),
                (1, 2),
            ))
        concurrent_codes = [result.code for result in concurrent_results]
        concurrent_count = int(_psql(pg, "select count(*) from care_events where source::text='voice'"))

        set_api_now("2026-10-15T08:02:00Z")
        rollback_gateway, rollback_flow, rollback_context = make_flow(transport, 500)
        prepare_proposal(rollback_flow, rollback_context, "母乳六十二毫升", "配方奶三十二毫升")
        _sql(pg, "create function m7_rollback_guard() returns trigger language plpgsql as $$ begin raise exception 'm7 injected rollback'; end; $$")
        _sql(pg, "create trigger m7_rollback_guard before insert on care_events for each row execute function m7_rollback_guard()")
        rollback_result = rollback_flow.handle("确认保存这次喂奶", rollback_context, identity_bound=True)
        rollback_count = int(_psql(pg, "select count(*) from care_events where source::text='voice'"))
        _sql(pg, "drop trigger m7_rollback_guard on care_events; drop function m7_rollback_guard()")
        rollback_recovery = rollback_flow.handle("确认保存这次喂奶", rollback_context, identity_bound=True)
        rollback_recovered_count = int(_psql(pg, "select count(*) from care_events where source::text='voice'"))

        set_api_now("2026-10-15T08:03:00Z")
        tamper_gateway, tamper_flow, tamper_context = make_flow(transport, 600)
        prepare_proposal(tamper_flow, tamper_context, "母乳六十三毫升", "配方奶三十三毫升")
        session_id = tamper_gateway._session_id
        current_version = tamper_gateway._version
        proposal_digest = tamper_gateway._proposal_digest
        if not session_id or current_version is None or not proposal_digest:
            raise RuntimeError("tamper_fixture_missing_authoritative_proposal")
        def send_tampered(request_id: str, expected_version: int, digest: str) -> str:
            body = EphemeralIdentity(seed).sign_intent(_envelope(
                request_id=request_id, device_id=ready["deviceId"], lease_id=ready["leaseId"],
                occurred_at=datetime(2026, 10, 15, 8, tzinfo=timezone.utc), intent_type="care_confirm",
                session_id=session_id, payload={"proposalDigest": digest, "expectedVersion": expected_version,
                                                "warningDigest": None, "confirmedWarningCodes": []},
            ))
            status, raw = transport(body)
            if status != 200:
                return f"http_{status}"
            return str(json.loads(raw.decode("utf-8"))["code"])
        tampered_digest = ("0" if proposal_digest[0] != "0" else "1") + proposal_digest[1:]
        tampered_digest_result = send_tampered("00000000-0000-4000-8000-000000000601", current_version, tampered_digest)
        old_version_result = send_tampered("00000000-0000-4000-8000-000000000602", current_version - 1, proposal_digest)
        tamper_count = int(_psql(pg, "select count(*) from care_events where source::text='voice'"))

        set_api_now("2026-10-15T08:04:00Z")
        loss_transport = _ResponseLossTransport(transport)
        loss_gateway, loss_flow, loss_context = make_flow(loss_transport, 700)
        prepare_direct_proposal(loss_flow, loss_context)
        loss_transport.drop_next = True
        response_lost = loss_flow.handle("确认保存这次喂奶", loss_context, identity_bound=True)
        response_lost_count = int(_psql(pg, "select count(*) from care_events where source::text='voice'"))
        response_lost_state = _psql(pg, "select state||':'||coalesce(final_care_event_id::text,'null')||':'||coalesce(warning_codes_json::text,'null') from voice_care_feeding_sessions where id='%s'" % loss_gateway._session_id)
        if loss_transport.last_body is None:
            raise RuntimeError("response_loss_request_not_captured")
        loss_request_id = str(json.loads(loss_transport.last_body.decode("utf-8"))["requestId"])
        time.sleep(0.2)
        replay_status, replay_raw = transport(loss_transport.last_body)
        replay_code = str(json.loads(replay_raw.decode("utf-8"))["code"]) if replay_status == 200 else f"http_{replay_status}"
        replay_count = int(_psql(pg, "select count(*) from care_events where source::text='voice'"))
        replay_receipt = _psql(pg, "select result_json::text from voice_care_intent_receipts where request_id='%s'" % loss_request_id)

        expired_gateway, expired_flow, expired_context = make_flow(transport, 800)
        prepare_proposal(expired_flow, expired_context, "母乳六十五毫升", "配方奶三十五毫升")
        set_api_now("2026-10-15T16:00:00Z")
        expired_result = expired_flow.handle("确认保存这次喂奶", expired_context, identity_bound=True)
        expired_count = int(_psql(pg, "select count(*) from care_events where source::text='voice'"))
        after_safety = _psql(pg, "select count(*) from care_events where source::text='voice'")
        if saved.code != "saved" or after != "1" or final != "1" or duplicate.code not in {"state_conflict", "saved"}:
            raise RuntimeError(f"e2e_assertion_failed outputs={outputs} duplicate={duplicate.code} counts={before},{after},{final} response={transport.state}")
        if rows != "expressed_breast_milk:60\nformula:40": raise RuntimeError(f"components={rows!r}")
        if concurrent_codes.count("saved") != 1 or any(code not in {"saved", "state_conflict", "temporarily_unavailable"} for code in concurrent_codes) or concurrent_count != 2:
            raise RuntimeError(f"concurrent_confirmation_failed codes={concurrent_codes} count={concurrent_count}")
        if rollback_result.code == "saved" or rollback_count != 2 or rollback_recovery.code != "saved" or rollback_recovered_count != 3:
            raise RuntimeError(f"rollback_failed first={rollback_result.code} count={rollback_count} recovery={rollback_recovery.code} recovered_count={rollback_recovered_count}")
        if tampered_digest_result not in {"state_conflict", "rejected"} or old_version_result not in {"state_conflict", "rejected"} or tamper_count != 3:
            raise RuntimeError(f"tamper_failed digest={tampered_digest_result} version={old_version_result} count={tamper_count}")
        response_replay_ok = response_lost.code == "temporarily_unavailable" and response_lost_count == 4 and replay_code == "saved" and replay_count == 4
        if expired_result.code not in {"rejected", "temporarily_unavailable", "state_conflict"} or expired_count != 4:
            raise RuntimeError(f"expired_confirmation_failed code={expired_result.code} count={expired_count}")
        safety_matrix_pass = response_replay_ok
        print(json.dumps({"RUNNER_EXECUTED": True, "POSTGRES_END_TO_END_PASS": True,
                          "SAFETY_MATRIX_PASS": safety_matrix_pass,
                          "outputs": outputs, "authority_records_before": 0,
                          "authority_records_after": 1, "duplicate_result": duplicate.code,
                          "components": rows.splitlines(), "llm_calls": 0,
                          "no_draft_confirm": no_draft.code,
                          "cancel_result": cancelled.code,
                          "cancel_then_confirm": cancelled_confirm.code,
                          "bad_identity_result": bad_identity_result.code,
                          "gateway_unavailable_result": unavailable_result.code,
                          "concurrent_codes": concurrent_codes,
                          "concurrent_authority_records": concurrent_count,
                          "rollback_result": rollback_result.code,
                          "rollback_count": rollback_count,
                          "rollback_recovery": rollback_recovery.code,
                          "rollback_recovered_count": rollback_recovered_count,
                          "tampered_digest_result": tampered_digest_result,
                          "old_version_result": old_version_result,
                          "tamper_authority_records": tamper_count,
                          "response_lost_result": response_lost.code,
                          "response_lost_authority_records": response_lost_count,
                          "same_request_replay": replay_code,
                          "replay_authority_records": replay_count,
                          "response_replay_observed_state": response_lost_state,
                          "response_replay_receipt_present": bool(replay_receipt),
                          "expired_result": expired_result.code,
                          "expired_authority_records": expired_count,
                          "authority_records_after_safety": int(after_safety)}))
        return 0 if safety_matrix_pass else 1
    finally:
        if proc is not None:
            try:
                proc.stdin.write("stop\n"); proc.stdin.flush(); proc.wait(timeout=10)
            except Exception:
                proc.kill()
        subprocess.run(["docker", "rm", "-f", pg], check=False, capture_output=True)


if __name__ == "__main__":
    raise SystemExit(main())
