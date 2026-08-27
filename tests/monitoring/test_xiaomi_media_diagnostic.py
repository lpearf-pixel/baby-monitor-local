from __future__ import annotations

import json

import pytest
import yaml

from packages.monitoring.xiaomi_media_diagnostic import (
    XiaomiMediaDiagnosticError,
    compare_source_observations,
    parse_source_observation,
    validate_single_source_config,
)


ALIASES = (
    "analysis",
    "analysis_realtime",
    "gauge",
    "audio_analysis",
    "live",
    "source_compat",
)


def _config(source: str = "xiaomi:private-marker?channel=0&subtype=0") -> bytes:
    streams = {"source": source}
    streams.update({name: "ffmpeg:source#video=copy" for name in ALIASES})
    return yaml.safe_dump({"streams": streams}).encode()


def _producer(
    *,
    producer_id: int = 41,
    protocol: str = "cs2+udp",
    generation: int = 0,
    video_bytes: int = 100,
    audio_bytes: int = 200,
) -> dict[str, object]:
    return {
        "id": producer_id,
        "protocol": protocol,
        "remote_addr": "private-address-marker",
        "url": "xiaomi://private-uri-marker",
        "medias": [
            "video, recvonly, H265",
            "audio, recvonly, OPUS/48000/2",
            "audio, sendonly, OPUS/48000/2",
        ],
        "receivers": [
            {
                "id": 91,
                "codec": {"codec_name": "hevc", "codec_type": "video"},
                "bytes": video_bytes,
            },
            {
                "id": 92,
                "codec": {
                    "codec_name": "opus",
                    "codec_type": "audio",
                    "sample_rate": 48000,
                    "channels": 2,
                },
                "bytes": audio_bytes,
            },
        ],
        "producer_generation": generation,
    }


def _payload(**producer: object) -> bytes:
    return json.dumps(
        {"producers": [_producer(**producer)], "consumers": [{"id": 7}]}
    ).encode()


def test_config_accepts_one_auto_xiaomi_source_and_derived_aliases() -> None:
    validate_single_source_config(_config())


@pytest.mark.parametrize("transport", ["udp", "tcp"])
def test_config_rejects_an_explicit_transport(transport: str) -> None:
    with pytest.raises(XiaomiMediaDiagnosticError, match="xiaomi_media_config_invalid"):
        validate_single_source_config(_config(f"xiaomi:private?transport={transport}"))


def test_config_rejects_a_second_xiaomi_uri() -> None:
    document = yaml.safe_load(_config())
    document["streams"]["other"] = "xiaomi:second-private-marker"

    with pytest.raises(XiaomiMediaDiagnosticError, match="xiaomi_media_config_invalid"):
        validate_single_source_config(yaml.safe_dump(document).encode())


def test_config_rejects_a_direct_xiaomi_alias() -> None:
    document = yaml.safe_load(_config())
    document["streams"]["live"] = "xiaomi:duplicate-private-marker"

    with pytest.raises(XiaomiMediaDiagnosticError, match="xiaomi_media_config_invalid"):
        validate_single_source_config(yaml.safe_dump(document).encode())


def test_config_rejects_an_alias_not_derived_from_source() -> None:
    document = yaml.safe_load(_config())
    document["streams"]["other"] = "rtsp://private-network-marker/stream"

    with pytest.raises(XiaomiMediaDiagnosticError, match="xiaomi_media_config_invalid"):
        validate_single_source_config(yaml.safe_dump(document).encode())


def test_config_rejects_duplicate_yaml_keys() -> None:
    payload = _config() + b"  source: xiaomi:replacement-private-marker\n"

    with pytest.raises(XiaomiMediaDiagnosticError, match="xiaomi_media_config_invalid"):
        validate_single_source_config(payload)


@pytest.mark.parametrize("protocol", ["cs2+udp", "cs2+tcp"])
def test_api_accepts_one_allowlisted_producer_and_idle_generation(protocol: str) -> None:
    observation = parse_source_observation(_payload(protocol=protocol, generation=0))

    assert observation.negotiated_protocol == protocol
    assert observation.producer_generation == 0
    assert observation.consumer_count == 1
    assert observation.video_media_ready is True
    assert observation.camera_audio_media_ready is True
    assert observation.speaker_media_ready is True


@pytest.mark.parametrize(
    "payload",
    [
        json.dumps({"producers": [], "consumers": []}).encode(),
        json.dumps(
            {
                "producers": [_producer(), _producer(producer_id=42)],
                "consumers": [],
            }
        ).encode(),
        _payload(protocol="cs2+quic"),
    ],
)
def test_api_rejects_zero_two_or_unknown_producers(payload: bytes) -> None:
    with pytest.raises(XiaomiMediaDiagnosticError, match="xiaomi_media_unavailable"):
        parse_source_observation(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda producer: producer.update(medias=["video, recvonly, H265"]),
        lambda producer: producer.update(receivers=[]),
        lambda producer: producer["receivers"][1]["codec"].update(
            sample_rate=16000
        ),
    ],
)
def test_api_rejects_malformed_or_incomplete_media(mutation) -> None:
    producer = _producer()
    mutation(producer)

    with pytest.raises(XiaomiMediaDiagnosticError, match="xiaomi_media_unavailable"):
        parse_source_observation(json.dumps({"producers": [producer], "consumers": []}).encode())


def test_comparison_reports_independent_video_and_audio_progress() -> None:
    before = parse_source_observation(_payload(video_bytes=100, audio_bytes=200))
    after = parse_source_observation(_payload(video_bytes=130, audio_bytes=200))

    snapshot = compare_source_observations(before, after)

    assert snapshot.configured_transport == "auto"
    assert snapshot.producer_count == 1
    assert snapshot.video_bytes_increased is True
    assert snapshot.audio_bytes_increased is False
    assert snapshot.producer_replaced is False


def test_comparison_fail_closes_when_producer_is_replaced() -> None:
    before = parse_source_observation(_payload(producer_id=41))
    after = parse_source_observation(
        _payload(producer_id=42, video_bytes=300, audio_bytes=400)
    )

    snapshot = compare_source_observations(before, after)

    assert snapshot.producer_replaced is True
    assert snapshot.video_bytes_increased is False
    assert snapshot.audio_bytes_increased is False


def test_parser_rejects_duplicate_json_keys_and_oversize_payload() -> None:
    with pytest.raises(XiaomiMediaDiagnosticError, match="xiaomi_media_unavailable"):
        parse_source_observation(b'{"producers":[],"producers":[],"consumers":[]}')
    with pytest.raises(XiaomiMediaDiagnosticError, match="xiaomi_media_unavailable"):
        parse_source_observation(b"x" * 1_048_577)
