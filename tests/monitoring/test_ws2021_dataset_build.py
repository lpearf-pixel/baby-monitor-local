from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from packages.monitoring.ws2021_dataset import (
    NegativeSample,
    PrivateCropStore,
    _render_positive,
    build_training_dataset,
)


def _jpeg(index: int, *, width: int = 180, height: int = 220) -> bytes:
    image = np.full((height, width, 3), 160 + index % 40, dtype=np.uint8)
    cv2.rectangle(image, (15, 15), (width - 16, height - 16), (10, 10, 10), 4)
    cv2.putText(
        image,
        str(index),
        (35, height // 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (240, 240, 240),
        3,
    )
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


def _source(tmp_path: Path, count: int = 12) -> Path:
    root = tmp_path / "source"
    store = PrivateCropStore(root)
    for index in range(count):
        assert store.save(_jpeg(index))
    return root


def _manifest(root: Path) -> dict[str, object]:
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def test_split_precedes_augmentation_and_is_deterministic(tmp_path: Path) -> None:
    source = _source(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_counts = build_training_dataset(source, first, augmentation_count=2)
    second_counts = build_training_dataset(source, second, augmentation_count=2)

    assert first_counts == second_counts
    first_manifest = _manifest(first)
    assert first_manifest == _manifest(second)
    by_digest: dict[str, set[str]] = {}
    for sample in first_manifest["samples"]:  # type: ignore[index]
        by_digest.setdefault(sample["source_digest"], set()).add(sample["split"])
        if sample["augmented"]:
            assert sample["split"] == "train"
    assert all(len(splits) == 1 for splits in by_digest.values())
    assert {sample["split"] for sample in first_manifest["samples"]} == {  # type: ignore[index]
        "train",
        "val",
    }


def test_dataset_uses_relative_crop_annotations_and_bounded_transforms(
    tmp_path: Path,
) -> None:
    output = tmp_path / "dataset"
    build_training_dataset(_source(tmp_path), output, augmentation_count=1)
    manifest = _manifest(output)

    for sample in manifest["samples"]:  # type: ignore[index]
        assert not Path(sample["image"]).is_absolute()
        assert not Path(sample["label"]).is_absolute()
        assert (output / sample["image"]).is_file()
        label = (output / sample["label"]).read_text(encoding="ascii").strip()
        assert label.startswith("0 ")
        values = [float(value) for value in label.split()[1:]]
        assert all(0 <= value <= 1 for value in values)
        transform = sample["transform"]
        assert -3 <= transform["rotation_degrees"] <= 3
        assert 0.10 <= transform["scale"] <= 0.35
        assert 0.75 <= transform["brightness"] <= 1.25

    for split in ("train", "val"):
        annotation_path = output / manifest["coco_annotations"][split]
        coco = json.loads(annotation_path.read_text(encoding="ascii"))
        assert coco["categories"] == [{"id": 1, "name": "ws2021"}]
        assert all(image["width"] == image["height"] == 640 for image in coco["images"])
        image_ids = {image["id"] for image in coco["images"]}
        assert all(annotation["image_id"] in image_ids for annotation in coco["annotations"])
        assert all(annotation["category_id"] == 1 for annotation in coco["annotations"])
        assert all(annotation["area"] > 0 for annotation in coco["annotations"])


def test_positive_render_uses_deterministic_nonuniform_synthetic_background() -> None:
    source = cv2.imdecode(np.frombuffer(_jpeg(7), dtype=np.uint8), cv2.IMREAD_COLOR)

    first, _, _ = _render_positive(
        source,
        digest="a" * 64,
        variant=0,
        augmented=False,
    )
    second, _, _ = _render_positive(
        source,
        digest="a" * 64,
        variant=0,
        augmented=False,
    )

    assert first == second
    rendered = cv2.imdecode(np.frombuffer(first, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert float(rendered[:100, :100].std()) > 2.0


def test_negative_sample_requires_license_metadata_and_emits_empty_label(
    tmp_path: Path,
) -> None:
    negative_path = tmp_path / "negative.jpg"
    negative_path.write_bytes(_jpeg(99, width=640, height=480))
    with pytest.raises(ValueError, match="ws2021_dataset_invalid"):
        NegativeSample(
            path=negative_path,
            license_id="",
            source_url="https://example.test/negative",
        )

    output = tmp_path / "dataset"
    build_training_dataset(
        _source(tmp_path),
        output,
        negatives=(
            NegativeSample(
                path=negative_path,
                license_id="CC0-1.0",
                source_url="https://example.test/negative",
            ),
        ),
    )
    negatives = [
        sample
        for sample in _manifest(output)["samples"]  # type: ignore[index]
        if sample["class_name"] == "background"
    ]
    assert len(negatives) == 1
    assert (output / negatives[0]["label"]).read_text(encoding="ascii") == ""
    assert negatives[0]["license_id"] == "CC0-1.0"
    assert negatives[0]["source_url"].startswith("https://")


def test_generated_negatives_are_deterministic_and_have_empty_labels(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_counts = build_training_dataset(
        _source(tmp_path),
        first,
        synthetic_negative_count=4,
    )
    second_counts = build_training_dataset(
        tmp_path / "source",
        second,
        synthetic_negative_count=4,
    )

    assert first_counts.negative == 4
    assert _manifest(first) == _manifest(second)
    negatives = [
        sample
        for sample in _manifest(first)["samples"]  # type: ignore[index]
        if sample["class_name"] == "background"
    ]
    assert len(negatives) == 4
    assert all(sample["license_id"] == "project-generated" for sample in negatives)
    assert all((first / sample["label"]).read_text(encoding="ascii") == "" for sample in negatives)


def test_builder_rejects_tampered_or_full_frame_source(tmp_path: Path) -> None:
    source = _source(tmp_path, count=1)
    metadata_path = next(source.glob("*.json"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["width"] = 2560
    metadata["height"] = 1440
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="ws2021_dataset_invalid"):
        build_training_dataset(source, tmp_path / "dataset")


def test_dataset_cli_outputs_only_status_and_aggregate_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tools.ws2021_dataset import main

    source = _source(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "ws2021_dataset.py",
            "--source",
            str(source),
            "--output",
            str(tmp_path / "dataset"),
        ],
    )
    assert main() == 0
    output = capsys.readouterr().out.splitlines()
    assert output[0] == "ws2021_dataset=ok"
    assert {line.split("=", 1)[0] for line in output[1:]} == {
        "train_count",
        "val_count",
        "negative_count",
    }
    assert str(tmp_path) not in "\n".join(output)
