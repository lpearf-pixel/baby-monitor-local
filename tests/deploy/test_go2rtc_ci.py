from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_ci_verifies_and_cross_builds_the_pinned_go2rtc_patch() -> None:
    content = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    for expected in (
        "go2rtc-patch:",
        "actions/setup-go@v6",
        'go-version: "1.24.x"',
        "b465651a94c1f637d566a8c660b4fad102b35153",
        "verify_and_apply_patch",
        'StartAtom("hvc1")',
        'ListenUDP("udp4", nil)',
        "CGO_ENABLED=0 GOOS=darwin GOARCH=amd64 go build",
        "Mach-O 64-bit executable x86_64",
    ):
        assert expected in content

    assert "upload-artifact" not in content


def test_ci_compile_gate_includes_operational_tools() -> None:
    content = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "python -m compileall -q apps packages services tools" in content
