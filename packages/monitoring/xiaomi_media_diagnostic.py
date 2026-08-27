"""Pure, fail-closed parsing for the shared Xiaomi media producer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import parse_qsl

import yaml


NegotiatedProtocol = Literal["cs2+udp", "cs2+tcp", "unavailable"]

_MAX_PAYLOAD_BYTES = 1_048_576
_PROTOCOLS = frozenset({"cs2+udp", "cs2+tcp"})
_ALIASES = frozenset(
    {
        "analysis",
        "analysis_realtime",
        "gauge",
        "audio_analysis",
        "live",
        "source_compat",
    }
)
_VIDEO_MEDIA = "video, recvonly, H265"
_CAMERA_AUDIO_MEDIA = "audio, recvonly, OPUS/48000/2"
_SPEAKER_MEDIA = "audio, sendonly, OPUS/48000/2"
_CONFIG_ERROR = "xiaomi_media_config_invalid"
_MEDIA_ERROR = "xiaomi_media_unavailable"


class XiaomiMediaDiagnosticError(ValueError):
    """A redacted, stable diagnostic failure."""


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError:
            raise XiaomiMediaDiagnosticError(_CONFIG_ERROR) from None
        if duplicate:
            raise XiaomiMediaDiagnosticError(_CONFIG_ERROR)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True, slots=True)
class _SourceObservation:
    producer_id: int
    negotiated_protocol: Literal["cs2+udp", "cs2+tcp"]
    producer_generation: int
    consumer_count: int
    video_media_ready: bool
    camera_audio_media_ready: bool
    speaker_media_ready: bool
    video_bytes: int
    audio_bytes: int


@dataclass(frozen=True, slots=True)
class XiaomiMediaSnapshot:
    configured_transport: Literal["auto"]
    producer_count: int
    negotiated_protocol: NegotiatedProtocol
    producer_generation: int
    consumer_count: int
    video_media_ready: bool
    camera_audio_media_ready: bool
    speaker_media_ready: bool
    video_bytes_increased: bool
    audio_bytes_increased: bool
    producer_replaced: bool


def validate_single_source_config(payload: bytes) -> None:
    """Require one transport-auto Xiaomi source and source-derived aliases."""

    if type(payload) is not bytes or not 0 < len(payload) <= _MAX_PAYLOAD_BYTES:
        raise XiaomiMediaDiagnosticError(_CONFIG_ERROR)
    try:
        document = yaml.load(payload, Loader=_UniqueKeyLoader)
    except (UnicodeError, yaml.YAMLError, XiaomiMediaDiagnosticError):
        raise XiaomiMediaDiagnosticError(_CONFIG_ERROR) from None
    if not isinstance(document, dict) or not isinstance(document.get("streams"), dict):
        raise XiaomiMediaDiagnosticError(_CONFIG_ERROR)
    streams = document["streams"]
    source = streams.get("source")
    if type(source) is not str or not source.startswith("xiaomi:"):
        raise XiaomiMediaDiagnosticError(_CONFIG_ERROR)
    try:
        query = parse_qsl(source.partition("?")[2], keep_blank_values=True)
    except ValueError:
        raise XiaomiMediaDiagnosticError(_CONFIG_ERROR) from None
    if any(key.lower() == "transport" for key, _value in query):
        raise XiaomiMediaDiagnosticError(_CONFIG_ERROR)

    xiaomi_sources = [
        value
        for value in streams.values()
        if type(value) is str and value.startswith("xiaomi:")
    ]
    if xiaomi_sources != [source]:
        raise XiaomiMediaDiagnosticError(_CONFIG_ERROR)
    for name, value in streams.items():
        if name != "source" and (
            type(value) is not str or not value.startswith("ffmpeg:source#")
        ):
            raise XiaomiMediaDiagnosticError(_CONFIG_ERROR)
    for name in _ALIASES:
        value = streams.get(name)
        if type(value) is not str or not value.startswith("ffmpeg:source#"):
            raise XiaomiMediaDiagnosticError(_CONFIG_ERROR)


def parse_source_observation(payload: bytes) -> _SourceObservation:
    """Parse one bounded `/api/streams?src=source` response without retaining secrets."""

    if type(payload) is not bytes or not 0 < len(payload) <= _MAX_PAYLOAD_BYTES:
        raise XiaomiMediaDiagnosticError(_MEDIA_ERROR)
    try:
        document = json.loads(payload, object_pairs_hook=_closed_object)
    except (UnicodeError, json.JSONDecodeError, XiaomiMediaDiagnosticError):
        raise XiaomiMediaDiagnosticError(_MEDIA_ERROR) from None
    if not isinstance(document, dict):
        raise XiaomiMediaDiagnosticError(_MEDIA_ERROR)
    producers = document.get("producers")
    consumers = document.get("consumers")
    if (
        not isinstance(producers, list)
        or len(producers) != 1
        or not isinstance(consumers, list)
    ):
        raise XiaomiMediaDiagnosticError(_MEDIA_ERROR)
    producer = producers[0]
    if not isinstance(producer, dict):
        raise XiaomiMediaDiagnosticError(_MEDIA_ERROR)

    producer_id = _bounded_int(producer.get("id"), minimum=1)
    protocol = producer.get("protocol")
    generation = _bounded_int(producer.get("producer_generation"), minimum=0)
    if producer_id is None or protocol not in _PROTOCOLS or generation is None:
        raise XiaomiMediaDiagnosticError(_MEDIA_ERROR)

    medias = producer.get("medias")
    if not isinstance(medias, list) or not all(
        type(media) is str for media in medias
    ):
        raise XiaomiMediaDiagnosticError(_MEDIA_ERROR)
    ready = (
        _VIDEO_MEDIA in medias,
        _CAMERA_AUDIO_MEDIA in medias,
        _SPEAKER_MEDIA in medias,
    )
    if not all(ready):
        raise XiaomiMediaDiagnosticError(_MEDIA_ERROR)

    video_bytes, audio_bytes = _receiver_bytes(producer.get("receivers"))
    return _SourceObservation(
        producer_id=producer_id,
        negotiated_protocol=protocol,
        producer_generation=generation,
        consumer_count=len(consumers),
        video_media_ready=ready[0],
        camera_audio_media_ready=ready[1],
        speaker_media_ready=ready[2],
        video_bytes=video_bytes,
        audio_bytes=audio_bytes,
    )


def compare_source_observations(
    before: _SourceObservation, after: _SourceObservation
) -> XiaomiMediaSnapshot:
    replaced = (
        before.producer_id != after.producer_id
        or before.negotiated_protocol != after.negotiated_protocol
    )
    return XiaomiMediaSnapshot(
        configured_transport="auto",
        producer_count=1,
        negotiated_protocol=after.negotiated_protocol,
        producer_generation=after.producer_generation,
        consumer_count=after.consumer_count,
        video_media_ready=after.video_media_ready,
        camera_audio_media_ready=after.camera_audio_media_ready,
        speaker_media_ready=after.speaker_media_ready,
        video_bytes_increased=not replaced and after.video_bytes > before.video_bytes,
        audio_bytes_increased=not replaced and after.audio_bytes > before.audio_bytes,
        producer_replaced=replaced,
    )


def _closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise XiaomiMediaDiagnosticError(_MEDIA_ERROR)
        result[key] = value
    return result


def _bounded_int(value: object, *, minimum: int) -> int | None:
    if type(value) is not int or not minimum <= value <= 9_007_199_254_740_991:
        return None
    return value


def _receiver_bytes(receivers: object) -> tuple[int, int]:
    if not isinstance(receivers, list):
        raise XiaomiMediaDiagnosticError(_MEDIA_ERROR)
    video: list[int] = []
    audio: list[int] = []
    for receiver in receivers:
        if not isinstance(receiver, dict) or not isinstance(
            receiver.get("codec"), dict
        ):
            raise XiaomiMediaDiagnosticError(_MEDIA_ERROR)
        codec = receiver["codec"]
        byte_count = _bounded_int(receiver.get("bytes", 0), minimum=0)
        if byte_count is None:
            raise XiaomiMediaDiagnosticError(_MEDIA_ERROR)
        if codec.get("codec_name") == "hevc" and codec.get("codec_type") == "video":
            video.append(byte_count)
        elif (
            codec.get("codec_name") == "opus"
            and codec.get("codec_type") == "audio"
            and codec.get("sample_rate") == 48000
            and codec.get("channels") == 2
        ):
            audio.append(byte_count)
    if len(video) != 1 or len(audio) != 1:
        raise XiaomiMediaDiagnosticError(_MEDIA_ERROR)
    return video[0], audio[0]
