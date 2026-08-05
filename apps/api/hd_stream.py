from __future__ import annotations

import asyncio
import ipaddress
import json
import secrets
import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from threading import Lock
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit, urlunsplit

from websockets.asyncio.client import connect


H264_CODEC_REQUEST = ",".join(
    [
        "avc1.42E01E",
        "avc1.4D0029",
        "avc1.640029",
        "avc1.640033",
    ]
)
H265_CODEC_REQUEST = "hvc1.1.6.L153.B0"
MAX_MSE_DESCRIPTION_BYTES = 4096


class HdProfile(str, Enum):
    NATIVE = "native"
    COMPAT = "compat"


class HdCode(str, Enum):
    BUSY = "HD_BUSY"
    CODEC_UNSUPPORTED = "HD_CODEC_UNSUPPORTED"
    TRANSCODE_UNAVAILABLE = "HD_TRANSCODE_UNAVAILABLE"
    UPSTREAM_FAILED = "HD_UPSTREAM_FAILED"


class HdBusyError(RuntimeError):
    pass


class HdClientDisconnected(RuntimeError):
    pass


class _HdProtocolError(RuntimeError):
    def __init__(self, code: HdCode) -> None:
        super().__init__(code.value)
        self.code = code


class HdBrowserSocket(Protocol):
    headers: Mapping[str, str]
    peer_host: str | None

    async def accept(self) -> None: ...

    async def receive(self) -> str | bytes: ...

    async def wait_for_disconnect(self) -> None: ...

    async def send_text(self, value: str) -> None: ...

    async def send_bytes(self, value: bytes) -> None: ...

    async def close(self, *, code: int, reason: str = "") -> None: ...


class HdUpstream(Protocol):
    async def __aenter__(self) -> "HdUpstream": ...

    async def __aexit__(self, *exc: object) -> None: ...

    async def send(self, value: str) -> None: ...

    def __aiter__(self) -> AsyncIterator[str | bytes]: ...


@dataclass(frozen=True)
class HdTicket:
    value: str
    expires_in: int


@dataclass(frozen=True)
class _HdRelayProfile:
    upstream_uri: str
    codec_request: str
    codec_prefix: str
    unavailable_code: HdCode

    @property
    def mse_request(self) -> str:
        return json.dumps(
            {"type": "mse", "value": self.codec_request},
            separators=(",", ":"),
        )


class HdTicketStore:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        ttl_seconds: int = 10,
        capacity: int = 64,
    ) -> None:
        self._clock = clock
        self._ttl_seconds = ttl_seconds
        self._capacity = capacity
        self._tickets: dict[str, tuple[float, HdProfile]] = {}
        self._lock = Lock()

    def _purge_expired(self, now: float) -> None:
        for value, (expires_at, _profile) in list(self._tickets.items()):
            if expires_at <= now:
                del self._tickets[value]

    def issue(self, profile: HdProfile) -> HdTicket:
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            if len(self._tickets) >= self._capacity:
                raise HdBusyError
            value = secrets.token_urlsafe(32)
            self._tickets[value] = (now + self._ttl_seconds, profile)
            return HdTicket(value=value, expires_in=self._ttl_seconds)

    def consume(self, value: str) -> HdProfile | None:
        with self._lock:
            self._purge_expired(self._clock())
            ticket = self._tickets.pop(value, None)
            return None if ticket is None else ticket[1]


class HdConnectionGate:
    def __init__(self, *, limit: int = 2) -> None:
        self._limit = limit
        self._active = 0
        self._lock = asyncio.Lock()

    async def try_acquire(self) -> bool:
        async with self._lock:
            if self._active >= self._limit:
                return False
            self._active += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            self._active -= 1


class HdOriginPolicy:
    @staticmethod
    def _is_loopback(peer_host: str | None) -> bool:
        if peer_host is None:
            return False
        try:
            return ipaddress.ip_address(peer_host).is_loopback
        except ValueError:
            return False

    def allows(self, headers: Mapping[str, str], peer_host: str | None) -> bool:
        origin = headers.get("origin", "")
        host = headers.get("host", "").strip().lower()
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        allowed = {host}
        if self._is_loopback(peer_host):
            forwarded_host = headers.get("x-forwarded-host", "").split(",", 1)[0]
            if forwarded_host.strip():
                allowed.add(forwarded_host.strip().lower())
        return parsed.netloc.lower() in allowed


def _fixed_upstream_uri(base_url: str, stream_name: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("go2rtc HD upstream must be an HTTP loopback URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("go2rtc HD upstream must be a loopback URL without credentials")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise ValueError("go2rtc HD upstream must use a loopback IP address") from exc
    if not address.is_loopback:
        raise ValueError("go2rtc HD upstream must use a loopback IP address")
    scheme = "ws" if parsed.scheme == "http" else "wss"
    path = f"{parsed.path.rstrip('/')}/api/ws"
    return urlunsplit(
        (scheme, parsed.netloc, path, urlencode({"src": stream_name}), "")
    )


def _mse_description_codecs(value: str) -> list[str] | None:
    try:
        message = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(message, dict) or set(message) != {"type", "value"}:
        return None
    if message["type"] != "mse" or not isinstance(message["value"], str):
        return None
    mime = message["value"]
    prefix = 'video/mp4; codecs="'
    if not mime.startswith(prefix) or not mime.endswith('"'):
        return None
    codecs = [codec.strip() for codec in mime[len(prefix) : -1].split(",")]
    if not codecs or any(not codec for codec in codecs):
        return None
    return codecs


class HdStreamService:
    def __init__(
        self,
        *,
        upstream_base_url: str = "http://127.0.0.1:1984",
        native_stream_name: str = "source",
        compat_stream_name: str = "source_compat",
        connector: Callable[..., HdUpstream] = connect,
        ticket_store: HdTicketStore | None = None,
        connection_gate: HdConnectionGate | None = None,
        origin_policy: HdOriginPolicy | None = None,
        ticket_timeout_seconds: float = 3.0,
        max_message_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        self._profiles = {
            HdProfile.NATIVE: _HdRelayProfile(
                upstream_uri=_fixed_upstream_uri(
                    upstream_base_url, native_stream_name
                ),
                codec_request=H265_CODEC_REQUEST,
                codec_prefix="hvc1.",
                unavailable_code=HdCode.CODEC_UNSUPPORTED,
            ),
            HdProfile.COMPAT: _HdRelayProfile(
                upstream_uri=_fixed_upstream_uri(
                    upstream_base_url, compat_stream_name
                ),
                codec_request=H264_CODEC_REQUEST,
                codec_prefix="avc1.",
                unavailable_code=HdCode.TRANSCODE_UNAVAILABLE,
            ),
        }
        self._connector = connector
        self._tickets = ticket_store or HdTicketStore()
        self._connections = connection_gate or HdConnectionGate()
        self._origin_policy = origin_policy or HdOriginPolicy()
        self._ticket_timeout_seconds = ticket_timeout_seconds
        self._max_message_bytes = max_message_bytes

    def issue_ticket(self, profile: HdProfile) -> HdTicket:
        return self._tickets.issue(profile)

    @staticmethod
    async def _close(
        socket: HdBrowserSocket,
        *,
        code: int,
        reason: str = "",
    ) -> None:
        try:
            await socket.close(code=code, reason=reason)
        except HdClientDisconnected:
            return

    async def _send_failure(self, socket: HdBrowserSocket, code: HdCode) -> None:
        message = json.dumps(
            {"type": "error", "value": code.value},
            separators=(",", ":"),
        )
        try:
            await socket.send_text(message)
        except HdClientDisconnected:
            return
        await self._close(socket, code=1013, reason=code.value)

    async def _forward(
        self,
        upstream: HdUpstream,
        socket: HdBrowserSocket,
        relay_profile: _HdRelayProfile,
    ) -> None:
        description_received = False
        async for message in upstream:
            if not description_received:
                if not isinstance(message, str) or (
                    len(message.encode("utf-8")) > MAX_MSE_DESCRIPTION_BYTES
                ):
                    raise _HdProtocolError(HdCode.UPSTREAM_FAILED)
                codecs = _mse_description_codecs(message)
                if codecs is None:
                    raise _HdProtocolError(HdCode.UPSTREAM_FAILED)
                if not all(
                    codec.startswith(relay_profile.codec_prefix)
                    for codec in codecs
                ):
                    raise _HdProtocolError(relay_profile.unavailable_code)
                await socket.send_text(message)
                description_received = True
                continue
            if not isinstance(message, bytes):
                raise _HdProtocolError(HdCode.UPSTREAM_FAILED)
            if len(message) > self._max_message_bytes:
                raise _HdProtocolError(HdCode.UPSTREAM_FAILED)
            await socket.send_bytes(message)
        if not description_received:
            raise _HdProtocolError(relay_profile.unavailable_code)

    async def _forward_until_browser_closes(
        self,
        upstream: HdUpstream,
        socket: HdBrowserSocket,
        relay_profile: _HdRelayProfile,
    ) -> None:
        forward_task = asyncio.create_task(
            self._forward(upstream, socket, relay_profile)
        )
        disconnect_task = asyncio.create_task(socket.wait_for_disconnect())
        tasks = (forward_task, disconnect_task)
        try:
            done, _pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if disconnect_task in done:
                try:
                    await disconnect_task
                except HdClientDisconnected:
                    pass
                raise HdClientDisconnected
            await forward_task
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def serve(self, socket: HdBrowserSocket) -> None:
        if not self._origin_policy.allows(socket.headers, socket.peer_host):
            await self._close(socket, code=1008)
            return

        await socket.accept()
        try:
            ticket = await asyncio.wait_for(
                socket.receive(),
                timeout=self._ticket_timeout_seconds,
            )
        except (TimeoutError, HdClientDisconnected):
            await self._close(
                socket, code=1008, reason=HdCode.UPSTREAM_FAILED.value
            )
            return
        if not isinstance(ticket, str) or len(ticket.encode("utf-8")) > 1024:
            await self._close(
                socket, code=1008, reason=HdCode.UPSTREAM_FAILED.value
            )
            return
        profile = self._tickets.consume(ticket)
        if profile is None:
            await self._close(
                socket, code=1008, reason=HdCode.UPSTREAM_FAILED.value
            )
            return
        relay_profile = self._profiles[profile]

        if not await self._connections.try_acquire():
            await self._send_failure(socket, HdCode.BUSY)
            return

        try:
            try:
                async with self._connector(
                    relay_profile.upstream_uri,
                    max_size=max(self._max_message_bytes, 4096),
                    open_timeout=3,
                    close_timeout=1,
                    proxy=None,
                ) as upstream:
                    await upstream.send(relay_profile.mse_request)
                    await self._forward_until_browser_closes(
                        upstream, socket, relay_profile
                    )
            except HdClientDisconnected:
                return
            except _HdProtocolError as exc:
                await self._send_failure(socket, exc.code)
                return
            except Exception:
                await self._send_failure(socket, HdCode.UPSTREAM_FAILED)
                return
            await self._close(socket, code=1000)
        finally:
            await self._connections.release()
