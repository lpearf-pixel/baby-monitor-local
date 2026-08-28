from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def module():
    from tools import visual_corpus

    return visual_corpus


@pytest.mark.parametrize("option", ["--url", "--manifest", "--path", "--database"])
def test_cli_has_no_public_path_or_url_override(option: str) -> None:
    with pytest.raises(SystemExit):
        module().parser().parse_args(["replay", "--first-stage", option, "value"])


def test_fixed_repository_paths_are_not_environment_replaceable(
    monkeypatch,
) -> None:
    monkeypatch.setenv("VISUAL_CORPUS_ROOT", "/private/family")

    assert module().REPOSITORY_ROOT == ROOT
    assert module().MANIFEST_PATH == ROOT / "tests/fixtures/visual_corpus/manifest.json"
    assert module().CANDIDATE_PATH == (
        ROOT / "runtime/test-corpus/visual/results/visual-candidate.json"
    )


def test_first_stage_selection_matches_the_tracked_manifest() -> None:
    manifest = module().load_manifest(module().MANIFEST_PATH)

    assert module().FIRST_STAGE_CLIP_IDS == tuple(
        clip.clip_id for clip in manifest.clips
    )


def test_private_result_writer_is_canonical_0600_and_replaces_only_regular_owned(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "results" / "candidate.json"

    module().write_private_json(destination, {"z": 1, "a": 2})
    first = destination.read_bytes()
    module().write_private_json(destination, {"a": 3})

    assert first == b'{"a":2,"z":1}\n'
    assert destination.read_bytes() == b'{"a":3}\n'
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_private_result_writer_rejects_symlink_destination(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text("preserve", encoding="utf-8")
    destination = tmp_path / "candidate.json"
    destination.symlink_to(outside)

    with pytest.raises(RuntimeError, match="visual_corpus_result_unsafe"):
        module().write_private_json(destination, {"a": 1})

    assert outside.read_text(encoding="utf-8") == "preserve"


def test_promote_requires_explicit_digest() -> None:
    with pytest.raises(SystemExit):
        module().parser().parse_args(["promote"])


def test_stable_error_output_never_prints_underlying_exception(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        module(),
        "run_command",
        lambda _arguments: (_ for _ in ()).throw(
            RuntimeError("credential /private/family")
        ),
    )

    assert module().main(["validate"]) == 2
    output = capsys.readouterr().out
    assert output == "result=FAIL\nreason=visual_corpus_command_failed\n"
    assert "private" not in output


def test_keyboard_interrupt_has_stable_output_and_exit_130(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        module(),
        "run_command",
        lambda _arguments: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    assert module().main(["validate"]) == 130
    assert capsys.readouterr().out == (
        "result=FAIL\nreason=visual_corpus_interrupted\n"
    )


def test_result_writer_output_is_valid_canonical_json(tmp_path: Path) -> None:
    destination = tmp_path / "candidate.json"
    module().write_private_json(destination, {"status": "PASS", "count": 3})

    assert json.loads(destination.read_text(encoding="ascii")) == {
        "count": 3,
        "status": "PASS",
    }


def test_make_targets_are_fixed_and_side_effect_isolated() -> None:
    expected = {
        "alpha-visual-corpus-validate": "validate",
        "alpha-visual-corpus-prepare": "prepare --first-stage",
        "alpha-visual-regression": "replay --first-stage",
        "alpha-visual-regression-compare": "compare",
        "alpha-visual-regression-long": "long --minutes 30",
    }
    for target, suffix in expected.items():
        completed = subprocess.run(
            ["make", "-n", target],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0
        assert completed.stdout.strip() == (
            f"./.venv-alpha/bin/python tools/visual_corpus.py {suffix}"
        )
        lowered = completed.stdout.lower()
        assert "launchctl" not in lowered
        assert "go2rtc" not in lowered
        assert "camera" not in lowered


def test_make_promotion_passes_only_explicit_digest_variable() -> None:
    completed = subprocess.run(
        ["make", "-n", "alpha-visual-regression-promote", "BASELINE_SHA256=a"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == (
        "./.venv-alpha/bin/python tools/visual_corpus.py promote "
        "--expected-digest \"a\""
    )
