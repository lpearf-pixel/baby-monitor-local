# Xiaomi Subtype Probe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely identify the native high-resolution Xiaomi CS2 subtype for MJSXJ17CM without exposing credentials or leaving an experimental configuration active.

**Architecture:** Extend the existing quality module with a source-only health probe and a pure subtype URL transform. Add an orchestrator that writes one candidate at a time, restarts Alpha through an injected boundary, records only derived media data, and restores the exact original YAML in a `finally` block. The CLI and Make target invoke that orchestrator; a successful scan still restores the original configuration and reports only a recommended subtype.

**Tech Stack:** Python 3.11, PyYAML, urllib, pytest, GNU Make, existing Alpha start/stop scripts.

## Global Constraints

- Probe numeric subtype values `0` through `5`; `subtype=hd` remains the pre-probe baseline and is not silently replaced.
- Remove `transport=tcp` from every candidate so Xiaomi CS2 can negotiate `cs2+udp` automatically.
- Never print or persist a complete `xiaomi://` URI, Xiaomi UID/Token/DID/MAC, LAN IP, account data, or image bytes.
- Always restore the exact original config and restart the original service state after success, failure, or `KeyboardInterrupt`.
- Suppress `start_alpha.sh` output during probing because it can include a LAN address.
- Never use Tailscale Funnel and never add router port forwarding.
- Keep PR #4 Draft until native-resolution and longer-running Intel i9 gates pass.

---

### Task 1: Source-only media probe and subtype transformation

**Files:**
- Modify: `packages/monitoring/alpha_quality.py`
- Modify: `tests/monitoring/test_alpha_quality.py`
- Modify: `tests/monitoring/test_alpha_quality_health.py`

**Interfaces:**
- Produces: `with_source_subtype(config: dict[str, Any], subtype: int) -> dict[str, Any]`
- Produces: `check_source_health(base_url: str, *, opener=urlopen) -> HealthResult`
- Preserves: `check_hd_health(base_url, dashboard_url, *, opener=urlopen) -> HealthResult`

- [x] **Step 1: Write the failing transform tests**

```python
def test_source_subtype_candidate_preserves_unknown_parameters_and_input() -> None:
    original = {"streams": {"source": "xiaomi://123:cn@192.0.2.10?did=456&subtype=hd&transport=tcp&vendor_hint=keep"}}
    updated = with_source_subtype(original, 3)
    assert "subtype=3" in updated["streams"]["source"]
    assert "transport=" not in updated["streams"]["source"]
    assert "vendor_hint=keep" in updated["streams"]["source"]
    assert "subtype=hd" in original["streams"]["source"]

@pytest.mark.parametrize("subtype", [-1, 6])
def test_source_subtype_candidate_rejects_out_of_range(subtype: int) -> None:
    with pytest.raises(QualityConfigError, match="INVALID_SUBTYPE"):
        with_source_subtype({"streams": {"source": "xiaomi://123:cn@example.invalid?did=456"}}, subtype)
```

- [x] **Step 2: Run RED**

Run: `pytest -q tests/monitoring/test_alpha_quality.py`

Expected: collection fails because `with_source_subtype` is missing.

- [x] **Step 3: Implement the pure transform**

```python
def with_source_subtype(config: dict[str, Any], subtype: int) -> dict[str, Any]:
    if subtype not in range(6):
        raise QualityConfigError("INVALID_SUBTYPE")
    result = deepcopy(config)
    streams = _streams(result)
    source = streams.get("source")
    if not isinstance(source, str) or not source.startswith("xiaomi://"):
        raise QualityConfigError("SOURCE_NOT_CONFIGURED")
    parsed = urlsplit(source)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key not in {"subtype", "transport"}]
    query.append(("subtype", str(subtype)))
    streams["source"] = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
    return result
```

- [x] **Step 4: Write the failing source-only health tests**

```python
def test_source_health_returns_only_derived_media_fields() -> None:
    opener = working_opener(live_jpeg=jpeg(1280, 720))
    result = check_source_health("http://127.0.0.1:1984", opener=opener)
    assert result.code == "PASS"
    assert result.protocol == "cs2+udp"
    assert result.bytes_received == 50000
    assert result.source_dimensions == (1280, 720)
    assert "xiaomi://" not in repr(result)
```

- [x] **Step 5: Run RED, implement extraction, then run GREEN**

Run: `pytest -q tests/monitoring/test_alpha_quality_health.py`

Implementation: move the existing catalog, producer, media, byte-counter and source-JPEG checks into `check_source_health`; make `check_hd_health` call it before checking `live` and Dashboard.

Expected: all existing health tests and the new source-only test pass.

### Task 2: Transactional subtype scan

**Files:**
- Create: `packages/monitoring/subtype_probe.py`
- Create: `tests/monitoring/test_subtype_probe.py`

**Interfaces:**
- Produces: `ProbeAttempt(subtype, code, protocol, bytes_received, source_dimensions)`
- Produces: `ProbeSummary(attempts, recommended_subtype, backup)`
- Produces: `probe_subtypes(config_path, backups_dir, candidates, restart, health_check, now) -> ProbeSummary`

- [x] **Step 1: Write the failing transactional tests**

```python
def test_probe_restores_original_after_success(tmp_path: Path) -> None:
    original_text = "streams:\n  source: xiaomi://123:cn@example.invalid?did=456&subtype=hd\n"
    config = tmp_path / "go2rtc.yaml"
    config.write_text(original_text, encoding="utf-8")
    seen: list[str] = []
    health_results = iter([
        HealthResult("PASS", protocol="cs2+udp", bytes_received=2000, source_dimensions=(864, 480)),
        HealthResult("PASS", protocol="cs2+udp", bytes_received=4000, source_dimensions=(2560, 1440)),
    ])
    summary = probe_subtypes(
        config,
        tmp_path / "backups",
        (2, 3),
        lambda: seen.append(config.read_text()),
        lambda: next(health_results),
        datetime(2026, 8, 4, 16, 0, tzinfo=timezone.utc),
    )
    assert config.read_text(encoding="utf-8") == original_text
    assert summary.recommended_subtype == 3
    assert len(seen) == 3

def test_probe_restores_original_when_health_check_raises(tmp_path: Path) -> None:
    original_text = "streams:\n  source: xiaomi://123:cn@example.invalid?did=456&subtype=hd\n"
    config = tmp_path / "go2rtc.yaml"
    config.write_text(original_text, encoding="utf-8")
    seen: list[str] = []
    def fail() -> HealthResult:
        raise RuntimeError("probe failed")
    with pytest.raises(RuntimeError, match="probe failed"):
        probe_subtypes(
            config,
            tmp_path / "backups",
            (3,),
            lambda: seen.append(config.read_text()),
            fail,
            datetime(2026, 8, 4, 16, 0, tzinfo=timezone.utc),
        )
    assert config.read_text(encoding="utf-8") == original_text
    assert seen[-1] == original_text
```

- [x] **Step 2: Run RED**

Run: `pytest -q tests/monitoring/test_subtype_probe.py`

Expected: collection fails because the module does not exist.

- [x] **Step 3: Implement minimal transactional orchestration**

```python
def probe_subtypes(
    config_path: Path,
    backups_dir: Path,
    candidates: Sequence[int],
    restart: Callable[[], None],
    health_check: Callable[[], HealthResult],
    now: datetime,
) -> ProbeSummary:
    original_text = config_path.read_text(encoding="utf-8")
    original_mode = stat.S_IMODE(config_path.stat().st_mode)
    original = _read_yaml_mapping(config_path, missing_code="SOURCE_NOT_CONFIGURED")
    backups_dir.mkdir(parents=True, exist_ok=True)
    backup = backups_dir / f"go2rtc-subtype-probe-{now.strftime('%Y%m%d-%H%M%S')}.yaml"
    backup.write_text(original_text, encoding="utf-8")
    backup.chmod(original_mode)
    attempts: list[ProbeAttempt] = []
    try:
        for subtype in candidates:
            _atomic_write(config_path, yaml.safe_dump(with_source_subtype(original, subtype), sort_keys=False, allow_unicode=True), original_mode)
            restart()
            result = health_check()
            attempts.append(ProbeAttempt(subtype, result.code, result.protocol, result.bytes_received, result.source_dimensions))
    finally:
        _atomic_write(config_path, original_text, original_mode)
        restart()
    passing = [attempt for attempt in attempts if attempt.code == "PASS" and attempt.source_dimensions is not None]
    best = max(passing, key=lambda attempt: attempt.source_dimensions[0] * attempt.source_dimensions[1], default=None)
    return ProbeSummary(tuple(attempts), None if best is None else best.subtype, backup)
```

- [x] **Step 4: Run GREEN and mutation-check restoration**

Run: `pytest -q tests/monitoring/test_subtype_probe.py`

Expected: success, failure, invalid-candidate and interruption cases all pass; deleting the `finally` restoration makes at least one test fail.

### Task 3: CLI, Make target, and safe operator output

**Files:**
- Modify: `tools/alpha_quality.py`
- Modify: `Makefile`
- Modify: `tests/monitoring/test_alpha_quality_cli.py`
- Modify: `tests/deploy/test_alpha_commands.py`
- Modify: `docs/runbooks/ALPHA_QUICKSTART.md`

**Interfaces:**
- Produces: `tools/alpha_quality.py probe-subtypes --config runtime/go2rtc.yaml --backups runtime/backups --base-url http://127.0.0.1:1984 --restart-command "make --no-print-directory alpha-restart"`
- Produces: `make alpha-subtype-probe`

- [x] **Step 1: Write RED CLI and Make behavior tests**

The CLI test runs against a temporary config with injected no-op restart and fixture health callback at the package boundary, asserting output lines use only:

```text
subtype=3 result=PASS protocol=cs2+udp bytes_received=50000 source_dimensions=2560x1440
recommended_subtype=3
original_config_restored=true
```

The Make test asserts `alpha-subtype-probe` calls the CLI with candidates `0 1 2 3 4 5`, local go2rtc base URL and the repository restart command.

- [x] **Step 2: Run RED**

Run: `pytest -q tests/monitoring/test_alpha_quality_cli.py tests/deploy/test_alpha_commands.py`

Expected: failures because the command and Make target are absent.

- [x] **Step 3: Implement CLI and Make target**

The production restart function executes `bash tools/stop_alpha.sh` then `bash tools/start_alpha.sh` with stdout/stderr captured. It raises `QualityConfigError("ALPHA_RESTART_FAILED")` without echoing captured output. CLI catches errors, prints only the stable error code to stderr, and returns `2`.

- [x] **Step 4: Run GREEN and leak assertions**

Run: `pytest -q tests/monitoring/test_alpha_quality_cli.py tests/deploy/test_alpha_commands.py`

Expected: PASS; combined output contains none of `xiaomi://`, `V1:`, `did=`, `192.0.2.10`.

### Task 4: Full verification and Draft PR update

**Files:**
- Modify: `docs/superpowers/plans/2026-08-04-xiaomi-subtype-probe.md`

- [x] **Step 1: Run complete local gates**

Run:

```bash
pytest -q
python -m compileall -q apps packages services tools
bash -n tools/*.sh
python -m json.tool config/settings.schema.json >/dev/null
```

Expected: every command exits `0`.

- [x] **Step 2: Re-fetch PR #4 HEAD and refuse a non-fast-forward write**

Expected current head before publication: `3925315e3be9c5a6b1dcf289425f55dcca106af6`, unless the connector reports a newer commit that is first reconciled.

- [x] **Step 3: Commit only the planned files to `codex/basic-usable-alpha`**

Commit message: `Add safe Xiaomi subtype probe`

- [x] **Step 4: Confirm PR #4 remains Draft and wait for fresh CI**

Expected: PR state `open`, `draft=true`, and the workflow run for the new head finishes successfully.

- [x] **Step 5: Run the Intel i9 gate only after CI passes**

```bash
cd ~/dev/baby-monitor-local
make alpha-update
make alpha-subtype-probe
```

Only the subtype/result/protocol/byte-count/dimensions summary is returned to the project; no runtime config or image is shared.
