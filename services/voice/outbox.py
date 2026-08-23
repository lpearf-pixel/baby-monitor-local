"""Private restart-safe queue for signed Voice Care intent envelopes."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from packages.contracts.voice_care import parse_voice_care_intent
from services.voice.client import VoiceCareClient, VoiceSemanticResponse
from services.voice.keychain import KeychainSecretStore


OUTBOX_INVALID = "voice_outbox_invalid"
OUTBOX_KEY_ACCOUNT = "voice-outbox-key.v1"
_ACTIVE_STATE = "pending"
_TERMINAL_STATES = {
    "delivered",
    "awaiting_confirmation",
    "reconcile_required",
    "rejected",
}


@dataclass(frozen=True, slots=True)
class OutboxEntry:
    request_id: str
    state: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    request_id: str
    state: str
    semantic_code: str | None
    response: VoiceSemanticResponse | None


class VoiceIntentOutbox:
    """Encrypt signed JSON and retain only bounded delivery metadata in SQLite."""

    def __init__(
        self,
        database_path: Path,
        keychain: KeychainSecretStore,
        *,
        now: Callable[[], datetime] | None = None,
        random_bytes: Callable[[int], bytes] = os.urandom,
        retention_seconds: int = 1_800,
        max_items: int = 128,
    ) -> None:
        if (
            type(retention_seconds) is not int
            or not 1 <= retention_seconds <= 86_400
            or type(max_items) is not int
            or not 1 <= max_items <= 1_024
        ):
            raise ValueError(OUTBOX_INVALID)
        self._path = Path(database_path)
        self._keychain = keychain
        self._now = now or (lambda: datetime.now(UTC))
        self._random_bytes = random_bytes
        self._retention_seconds = retention_seconds
        self._max_items = max_items
        self._initialize()

    def _require_now(self) -> datetime:
        value = self._now()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(OUTBOX_INVALID)
        return value

    def _prepare_path(self) -> None:
        try:
            parent = self._path.parent
            if self._path.is_symlink() or parent.is_symlink():
                raise ValueError
            parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            parent_stat = parent.stat()
            if not stat.S_ISDIR(parent_stat.st_mode):
                raise ValueError
            os.chmod(parent, 0o700)
            if not self._path.exists():
                descriptor = os.open(
                    self._path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                os.close(descriptor)
            path_stat = self._path.lstat()
            if not stat.S_ISREG(path_stat.st_mode) or stat.S_IMODE(path_stat.st_mode) != 0o600:
                raise ValueError
        except (OSError, ValueError):
            raise ValueError(OUTBOX_INVALID) from None

    def _connect(self) -> sqlite3.Connection:
        self._prepare_path()
        try:
            connection = sqlite3.connect(self._path, timeout=1.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.execute("PRAGMA secure_delete = ON")
            return connection
        except sqlite3.Error:
            raise ValueError(OUTBOX_INVALID) from None

    def _initialize(self) -> None:
        try:
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS voice_intent_outbox (
                        request_id TEXT PRIMARY KEY,
                        payload_digest TEXT NOT NULL,
                        created_epoch REAL NOT NULL,
                        expires_epoch REAL NOT NULL,
                        state TEXT NOT NULL CHECK(state IN (
                            'pending', 'delivered', 'awaiting_confirmation',
                            'reconcile_required', 'rejected'
                        )),
                        nonce BLOB,
                        ciphertext BLOB,
                        result_code TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_voice_intent_outbox_state_created
                        ON voice_intent_outbox(state, created_epoch);
                    PRAGMA user_version = 1;
                    """
                )
        except (OSError, sqlite3.Error, ValueError):
            raise ValueError(OUTBOX_INVALID) from None

    def _key(self) -> bytes:
        try:
            return self._keychain.get_or_create(OUTBOX_KEY_ACCOUNT, size=32)
        except Exception:
            raise ValueError(OUTBOX_INVALID) from None

    def enqueue(self, signed_intent: bytes) -> OutboxEntry:
        try:
            if type(signed_intent) is not bytes or not 0 < len(signed_intent) <= 16_384:
                raise ValueError
            intent = parse_voice_care_intent(signed_intent)
            request_id = str(intent.requestId)
            digest = hashlib.sha256(signed_intent).hexdigest()
            now = self._require_now()
            expires_epoch = intent.issuedAt.timestamp() + self._retention_seconds
            if expires_epoch <= now.timestamp():
                raise ValueError
            nonce = self._random_bytes(12)
            if type(nonce) is not bytes or len(nonce) != 12:
                raise ValueError
            ciphertext = AESGCM(self._key()).encrypt(
                nonce,
                signed_intent,
                f"{request_id}:{digest}".encode("ascii"),
            )
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM voice_intent_outbox WHERE state != ? AND expires_epoch < ?",
                    (_ACTIVE_STATE, now.timestamp()),
                )
                existing = connection.execute(
                    "SELECT * FROM voice_intent_outbox WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if existing is not None:
                    if existing["payload_digest"] != digest:
                        raise ValueError
                    return _entry(existing)
                count = connection.execute(
                    "SELECT COUNT(*) FROM voice_intent_outbox"
                ).fetchone()[0]
                if count >= self._max_items:
                    raise ValueError
                connection.execute(
                    """
                    INSERT INTO voice_intent_outbox(
                        request_id, payload_digest, created_epoch, expires_epoch,
                        state, nonce, ciphertext, result_code
                    ) VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL)
                    """,
                    (
                        request_id,
                        digest,
                        now.timestamp(),
                        expires_epoch,
                        nonce,
                        ciphertext,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM voice_intent_outbox WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
            return _entry(row)
        except Exception:
            raise ValueError(OUTBOX_INVALID) from None

    def pending_count(self) -> int:
        try:
            with self._connect() as connection:
                return int(
                    connection.execute(
                        "SELECT COUNT(*) FROM voice_intent_outbox WHERE state = 'pending'"
                    ).fetchone()[0]
                )
        except Exception:
            raise ValueError(OUTBOX_INVALID) from None

    def deliver(self, client: VoiceCareClient) -> tuple[DeliveryResult, ...]:
        results: list[DeliveryResult] = []
        try:
            now = self._require_now()
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT * FROM voice_intent_outbox
                    WHERE state = 'pending'
                    ORDER BY created_epoch, request_id
                    """
                ).fetchall()
            for row in rows:
                request_id = str(row["request_id"])
                if now.timestamp() >= float(row["expires_epoch"]):
                    self._finish(request_id, "reconcile_required", None)
                    results.append(
                        DeliveryResult(request_id, "reconcile_required", None, None)
                    )
                    continue
                signed = self._decrypt(row)
                try:
                    response = client.send(signed)
                except Exception:
                    response = VoiceSemanticResponse.temporarily_unavailable()
                state = _state_for_response(response)
                if state != "pending":
                    self._finish(request_id, state, response.code)
                results.append(DeliveryResult(request_id, state, response.code, response))
            return tuple(results)
        except Exception:
            raise ValueError(OUTBOX_INVALID) from None

    def _decrypt(self, row: sqlite3.Row) -> bytes:
        try:
            request_id = str(row["request_id"])
            digest = str(row["payload_digest"])
            nonce = bytes(row["nonce"])
            ciphertext = bytes(row["ciphertext"])
            signed = AESGCM(self._key()).decrypt(
                nonce,
                ciphertext,
                f"{request_id}:{digest}".encode("ascii"),
            )
            if hashlib.sha256(signed).hexdigest() != digest:
                raise ValueError
            intent = parse_voice_care_intent(signed)
            if str(intent.requestId) != request_id:
                raise ValueError
            return signed
        except Exception:
            raise ValueError(OUTBOX_INVALID) from None

    def _finish(self, request_id: str, state: str, code: str | None) -> None:
        if state not in _TERMINAL_STATES:
            raise ValueError(OUTBOX_INVALID)
        try:
            with self._connect() as connection:
                changed = connection.execute(
                    """
                    UPDATE voice_intent_outbox
                    SET state = ?, nonce = NULL, ciphertext = NULL, result_code = ?
                    WHERE request_id = ? AND state = 'pending'
                    """,
                    (state, code, request_id),
                ).rowcount
                if changed != 1:
                    raise ValueError
        except Exception:
            raise ValueError(OUTBOX_INVALID) from None


def _entry(row: sqlite3.Row) -> OutboxEntry:
    return OutboxEntry(
        request_id=str(row["request_id"]),
        state=str(row["state"]),
        created_at=datetime.fromtimestamp(float(row["created_epoch"]), UTC),
        expires_at=datetime.fromtimestamp(float(row["expires_epoch"]), UTC),
    )


def _state_for_response(response: VoiceSemanticResponse) -> str:
    if response.code == "temporarily_unavailable":
        return "pending"
    if response.code == "saved":
        return "delivered"
    if response.code in {"accepted_pending", "needs_confirmation"}:
        return "awaiting_confirmation"
    if response.code == "rejected":
        return "rejected"
    return "reconcile_required"


__all__ = [
    "OUTBOX_INVALID",
    "OUTBOX_KEY_ACCOUNT",
    "DeliveryResult",
    "OutboxEntry",
    "VoiceIntentOutbox",
]
