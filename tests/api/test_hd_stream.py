from __future__ import annotations

import base64
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from apps.api.hd_stream import (
    H264_CODEC_REQUEST,
    MSE_REQUEST,
    HdBusyError,
    HdClientDisconnected,
    HdCode,
    HdConnectionGate,
    HdStreamService,
    HdTicketStore,
)


def _decoded_bytes(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def test_issued_ticket_contains_at_least_256_bits_and_ten_second_metadata() -> None:
    store = HdTicketStore()

    ticket = store.issue()

    assert len(_decoded_bytes(ticket.value)) >= 32
    assert ticket.expires_in == 10


def test_ticket_is_consumed_only_once() -> None:
    store = HdTicketStore()
    ticket = store.issue()

    assert store.consume(ticket.value) is True
    assert store.consume(ticket.value) is False


def test_ticket_expires_at_the_ten_second_boundary() -> None:
    now = [100.0]
    store = HdTicketStore(clock=lambda: now[0])
    ticket = store.issue()

    now[0] = 109.999
    assert store.consume(ticket.value) is True

    expired = store.issue()
    now[0] = 119.999
    assert store.consume(expired.value) is False


def test_concurrent_ticket_consumption_has_exactly_one_winner() -> None:
    store = HdTicketStore()
    ticket = store.issue()

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(store.consume, [ticket.value] * 8))

    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 7


def test_full_store_rejects_issue_without_evicting_valid_ticket() -> None:
    store = HdTicketStore(capacity=2)
    first = store.issue()
    second = store.issue()

    with pytest.raises(HdBusyError):
        store.issue()

    assert store.consume(first.value) is True
    assert store.consume(second.value) is True


def test_expired_cleanup_restores_ticket_capacity() -> None:
    now = [50.0]
    store = HdTicketStore(clock=lambda: now[0], capacity=1)
    expired = store.issue()

    now[0] = 60.0
    replacement = store.issue()

    assert store.consume(expired.value) is False
    assert store.consume(replacement.value) is True


@dataclass
class FakeBrowserSocket:
    ticket_message: str | bytes = ""
    origin: str = "http://monitor.test:8080"
    host: str = "monitor.test:8080"
    forwarded_host: str | None = None
    peer_host: str = "192.0.2.10"
    receive_delay: float = 0.0
    disconnect_on_binary: bool = False
    accepted: bool = False
    close_code: int | None = None
    close_reason: str = ""
    text_messages: list[str] = field(default_factory=list)
    binary_messages: list[bytes] = field(default_factory=list)

    @property
    def headers(self) -> dict[str, str]:
        headers = {"origin": self.origin, "host": self.host}
        if self.forwarded_host is not None:
            headers["x-forwarded-host"] = self.forwarded_host
        return headers

    async def accept(self) -> None:
        self.accepted = True

    async def receive(self) -> str | bytes:
        if self.receive_delay:
            await asyncio.sleep(self.receive_delay)
        return self.ticket_message

    async def send_text(self, value: str) -> None:
        self.text_messages.append(value)

    async def send_bytes(self, value: bytes) -> None:
        if self.disconnect_on_binary:
            raise HdClientDisconnected
        self.binary_messages.append(value)

    async def close(self, *, code: int, reason: str = "") -> None:
        self.close_code = code
        self.close_reason = reason


class FakeUpstream:
    def __init__(self, incoming: list[str | bytes]) -> None:
        self._incoming = iter(incoming)
        self.sent: list[str] = []
        self.closed = False

    async def __aenter__(self) -> "FakeUpstream":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self.closed = True

    async def send(self, value: str) -> None:
        self.sent.append(value)

    def __aiter__(self) -> "FakeUpstream":
        return self

    async def __anext__(self) -> str | bytes:
        try:
            return next(self._incoming)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class RecordingConnector:
    def __init__(self, incoming: list[str | bytes] | None = None) -> None:
        self.upstream = FakeUpstream(incoming or [])
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, uri: str, **options: Any) -> FakeUpstream:
        self.calls.append((uri, options))
        return self.upstream


def _mse_description(codec: str = "avc1.640033") -> str:
    return json.dumps(
        {"type": "mse", "value": f'video/mp4; codecs="{codec}"'},
        separators=(",", ":"),
    )


def test_non_loopback_upstream_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="loopback"):
        HdStreamService(upstream_base_url="http://camera.invalid:1984")


def test_cross_origin_request_closes_before_accept_or_upstream_access() -> None:
    connector = RecordingConnector()
    service = HdStreamService(connector=connector)
    socket = FakeBrowserSocket(origin="http://other.test:8080")

    asyncio.run(service.serve(socket))

    assert socket.accepted is False
    assert socket.close_code == 1008
    assert connector.calls == []


def test_forwarded_host_is_trusted_only_from_a_loopback_peer() -> None:
    connector = RecordingConnector()
    service = HdStreamService(connector=connector)
    ticket = service.issue_ticket()
    socket = FakeBrowserSocket(
        ticket_message=ticket.value,
        origin="https://monitor.tail.test",
        forwarded_host="monitor.tail.test",
        peer_host="192.0.2.10",
    )

    asyncio.run(service.serve(socket))

    assert socket.accepted is False
    assert connector.calls == []

    loopback_ticket = service.issue_ticket()
    loopback = FakeBrowserSocket(
        ticket_message=loopback_ticket.value,
        origin="https://monitor.tail.test",
        forwarded_host="monitor.tail.test",
        peer_host="127.0.0.1",
    )

    asyncio.run(service.serve(loopback))

    assert loopback.accepted is True
    assert len(connector.calls) == 1


@pytest.mark.parametrize(
    "ticket_message",
    ["missing-ticket", b"binary-ticket", "x" * 1025],
)
def test_invalid_ticket_never_opens_upstream(ticket_message: str | bytes) -> None:
    connector = RecordingConnector()
    service = HdStreamService(connector=connector)
    socket = FakeBrowserSocket(ticket_message=ticket_message)

    asyncio.run(service.serve(socket))

    assert socket.accepted is True
    assert socket.close_reason == HdCode.FALLBACK.value
    assert connector.calls == []


def test_late_ticket_never_opens_upstream() -> None:
    connector = RecordingConnector()
    service = HdStreamService(connector=connector, ticket_timeout_seconds=0.01)
    socket = FakeBrowserSocket(ticket_message="late", receive_delay=0.05)

    asyncio.run(service.serve(socket))

    assert socket.close_reason == HdCode.FALLBACK.value
    assert connector.calls == []


def test_reused_ticket_never_opens_a_second_upstream() -> None:
    connector = RecordingConnector([_mse_description(), b"fragment"])
    service = HdStreamService(connector=connector)
    ticket = service.issue_ticket()

    asyncio.run(service.serve(FakeBrowserSocket(ticket_message=ticket.value)))
    reused = FakeBrowserSocket(ticket_message=ticket.value)
    asyncio.run(service.serve(reused))

    assert len(connector.calls) == 1
    assert reused.close_reason == HdCode.FALLBACK.value


def test_relay_uses_fixed_source_request_then_forwards_description_and_binary() -> None:
    description = _mse_description()
    connector = RecordingConnector([description, b"init-and-media"])
    service = HdStreamService(connector=connector)
    ticket = service.issue_ticket()
    socket = FakeBrowserSocket(ticket_message=ticket.value)

    asyncio.run(service.serve(socket))

    assert connector.calls[0][0] == "ws://127.0.0.1:1984/api/ws?src=source"
    assert connector.upstream.sent == [MSE_REQUEST]
    assert json.loads(MSE_REQUEST) == {
        "type": "mse",
        "value": H264_CODEC_REQUEST,
    }
    assert socket.text_messages == [description]
    assert socket.binary_messages == [b"init-and-media"]
    assert connector.upstream.closed is True
    assert socket.close_code == 1000


@pytest.mark.parametrize(
    "incoming",
    [
        [b"binary-before-description"],
        [json.dumps({"type": "mse", "value": 'video/mp4; codecs="hvc1.1.6"'})],
        [json.dumps({"type": "unexpected", "value": "redacted"})],
        [_mse_description(), "second-text-message"],
    ],
)
def test_protocol_disorder_or_unsupported_codec_fails_closed(
    incoming: list[str | bytes],
) -> None:
    connector = RecordingConnector(incoming)
    service = HdStreamService(connector=connector)
    ticket = service.issue_ticket()
    socket = FakeBrowserSocket(ticket_message=ticket.value)

    asyncio.run(service.serve(socket))

    assert json.loads(socket.text_messages[-1]) == {
        "type": "error",
        "value": HdCode.FALLBACK.value,
    }
    assert socket.close_reason == HdCode.FALLBACK.value
    assert connector.upstream.closed is True


def test_oversized_upstream_message_fails_closed() -> None:
    connector = RecordingConnector([_mse_description(), b"12345"])
    service = HdStreamService(connector=connector, max_message_bytes=4)
    ticket = service.issue_ticket()
    socket = FakeBrowserSocket(ticket_message=ticket.value)

    asyncio.run(service.serve(socket))

    assert socket.binary_messages == []
    assert socket.close_reason == HdCode.FALLBACK.value
    assert connector.upstream.closed is True


def test_oversized_mse_description_fails_closed() -> None:
    oversized = _mse_description("avc1." + ("A" * 5000))
    connector = RecordingConnector([oversized])
    service = HdStreamService(connector=connector)
    ticket = service.issue_ticket()
    socket = FakeBrowserSocket(ticket_message=ticket.value)

    asyncio.run(service.serve(socket))

    assert oversized not in socket.text_messages
    assert socket.close_reason == HdCode.FALLBACK.value
    assert connector.upstream.closed is True


def test_busy_gate_rejects_before_upstream_access() -> None:
    async def scenario() -> tuple[RecordingConnector, FakeBrowserSocket]:
        gate = HdConnectionGate(limit=2)
        assert await gate.try_acquire() is True
        assert await gate.try_acquire() is True
        connector = RecordingConnector()
        service = HdStreamService(connector=connector, connection_gate=gate)
        ticket = service.issue_ticket()
        socket = FakeBrowserSocket(ticket_message=ticket.value)
        await service.serve(socket)
        await gate.release()
        await gate.release()
        return connector, socket

    connector, socket = asyncio.run(scenario())

    assert connector.calls == []
    assert json.loads(socket.text_messages[-1]) == {
        "type": "error",
        "value": HdCode.BUSY.value,
    }
    assert socket.close_reason == HdCode.BUSY.value


def test_client_disconnect_still_closes_upstream() -> None:
    connector = RecordingConnector([_mse_description(), b"fragment"])
    service = HdStreamService(connector=connector)
    ticket = service.issue_ticket()
    socket = FakeBrowserSocket(
        ticket_message=ticket.value,
        disconnect_on_binary=True,
    )

    asyncio.run(service.serve(socket))

    assert connector.upstream.closed is True
