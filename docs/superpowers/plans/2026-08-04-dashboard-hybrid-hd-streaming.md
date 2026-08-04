# Dashboard Hybrid HD Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prefer the Xiaomi camera's native 2560x1440 H.265 stream for 2x/3x and automatically use one shared on-demand 2560x1440 H.264 VideoToolbox stream when the browser cannot play native HEVC.

**Architecture:** Extend the fixed authenticated MSE relay with two server-owned profiles, `native` and `compat`. Patch the pinned Intel macOS go2rtc build so HEVC fMP4 advertises and writes `hvc1`; configure `source_compat` as a go2rtc-managed on-demand VideoToolbox producer. The browser keeps MJPEG visible while it tries native or compat, performs at most one native-to-compat transition, and never couples 2x/3x CSS transforms to a second connection.

**Tech Stack:** Python 3.11+, FastAPI/Starlette WebSocket, `websockets` 15+, PyYAML, dependency-free JavaScript, browser MediaSource/WebSocket APIs, Node 20+ test runner, Go 1.24+, go2rtc commit `b465651a94c1f637d566a8c660b4fad102b35153`, FFmpeg VideoToolbox, Bash/Make.

## Global Constraints

- The real `source` is `2560x1440 H265`; no code or document may treat it as verified H.264.
- `live` remains `ffmpeg:source#video=mjpeg#width=1280#height=720#raw=-r 10`.
- `source_compat` is exactly `ffmpeg:source#video=h264#hardware=videotoolbox#width=2560#height=1440#bitrate=6M`.
- Hardware compatibility mode must fail closed; never fall back to libx264.
- go2rtc remains loopback-only; the browser can select only `native` or `compat`, never a stream, URL, codec string, bitrate, or FFmpeg argument.
- Keep at most two global HD connections and one HD connection per Dashboard page.
- Keep MJPEG or the last decoded HD frame visible during every transition.
- 2x to 3x and 3x to 2x only change the render transform.
- PTZ remains `PTZ_DISABLED`.
- Do not commit binaries, credentials, Xiaomi URI fields, tokens, IDs, private addresses, logs, or household media.
- PR #4 remains Draft until CI and the three-browser real-device gate pass.

---

## File structure

- Create `patches/go2rtc-macos-hybrid-hd.patch`: exact pinned-source `udp4` and `hvc1` edits.
- Create `packages/monitoring/go2rtc_build.py`: platform-independent checkout, patch, metadata, backup, and atomic-install rules.
- Create `tools/go2rtc_build.py`: Intel macOS CLI that clones, verifies, patches, builds, signs, installs, reports, and rolls back.
- Create `tests/monitoring/test_go2rtc_build.py`: behavioral tests using temporary Git repositories and candidate binaries.
- Modify `tools/install_alpha_macos.sh` and `Makefile`: invoke or expose the reproducible build without overwriting runtime configuration.
- Modify `packages/monitoring/alpha_quality.py`: derived compat stream, source codec reporting, and health checks.
- Modify `config/go2rtc.alpha.yaml`: non-secret default `source_compat` profile.
- Modify monitoring and deploy tests for exact derived behavior.
- Modify `apps/api/hd_stream.py`: profile-bound tickets, fixed profile definitions, codec-specific relay validation, and typed failures.
- Modify `apps/api/alpha.py`: strict profile request model and unchanged opaque response.
- Modify `apps/api/runtime.py`: wire the fixed native and compat stream names.
- Modify API tests for ticket and relay contracts.
- Modify `apps/api/hd_player.js`: native capability choice, one compat transition, typed state, and resource cleanup.
- Modify `tests/frontend/hd_player.test.mjs`: real state transition and no-black-frame tests.
- Modify runbooks and status docs to remove the obsolete H.264 claim and define real-device evidence.

---

### Task 1: Reproducible go2rtc `udp4` plus `hvc1` build

**Files:**
- Create: `patches/go2rtc-macos-hybrid-hd.patch`
- Create: `packages/monitoring/go2rtc_build.py`
- Create: `tools/go2rtc_build.py`
- Create: `tests/monitoring/test_go2rtc_build.py`
- Modify: `Makefile`
- Modify: `tools/install_alpha_macos.sh`
- Test: `tests/monitoring/test_go2rtc_build.py`
- Test: `tests/deploy/test_alpha_commands.py`

**Interfaces:**
- Produces: `GO2RTC_COMMIT`, `verify_and_apply_patch(source_dir: Path, patch_path: Path, expected_commit: str = GO2RTC_COMMIT) -> str`.
- Produces: `BuildMetadata` with `upstream_commit`, `go_version`, `patch_sha256`, `binary_sha256`, `build_time`, and `platform`.
- Produces: `metadata_matches(path: Path, *, upstream_commit: str, patch_sha256: str, platform: str) -> bool`.
- Produces: `install_candidate(candidate: Path, destination: Path, backups_root: Path, metadata_path: Path, metadata: BuildMetadata, now: datetime) -> Path | None`.
- Produces CLI commands `ensure`, `rebuild`, `info`, and `rollback`.

- [x] **Step 1: Write RED patch-application tests**

Create a temporary Git repository containing the pinned pre-patch forms:

```python
def test_verify_and_apply_patch_changes_only_udp_socket_and_hevc_sample_entry(tmp_path):
    source = init_fixture_repo(
        tmp_path,
        {
            "pkg/xiaomi/miss/cs2/conn.go": 'conn, err := net.ListenUDP("udp", nil)\n',
            "pkg/iso/codecs.go": 'case core.CodecH265:\n\tm.StartAtom("hev1")\n',
        },
    )
    head = git_head(source)

    result = verify_and_apply_patch(source, PATCH, expected_commit=head)

    assert result == head
    assert 'ListenUDP("udp4", nil)' in read_cs2(source)
    assert 'StartAtom("hvc1")' in read_codecs(source)
```

Add separate literal-outcome tests for commit mismatch, patch context mismatch,
already-patched input, and a patch that changes any third file. These cases
must raise `Go2RTCBuildError` without modifying the fixture.

- [x] **Step 2: Run RED**

Run:

```bash
/tmp/baby-monitor-hybrid-hd-venv/bin/python -m pytest -q tests/monitoring/test_go2rtc_build.py
```

Expected: import failure because `go2rtc_build` does not exist.

- [x] **Step 3: Implement exact patch validation and application**

Define:

```python
GO2RTC_COMMIT = "b465651a94c1f637d566a8c660b4fad102b35153"
ALLOWED_PATCH_FILES = {
    "pkg/xiaomi/miss/cs2/conn.go",
    "pkg/iso/codecs.go",
}
```

`verify_and_apply_patch` must use argument-list subprocess calls, verify the
exact checkout SHA, obtain changed paths from `git apply --numstat`, require
the exact allowed set, run `git apply --check`, apply once, then assert the
`udp4` and `hvc1` postconditions and absence of the two old forms.

- [x] **Step 4: Run GREEN for patch behavior**

Run the focused command from Step 2. Expected: patch behavior tests pass.

- [x] **Step 5: Write RED metadata and atomic-install tests**

```python
def test_install_candidate_backs_up_old_binary_and_writes_verified_metadata(tmp_path):
    destination = executable(tmp_path / "go2rtc", b"old")
    candidate = executable(tmp_path / "candidate", b"new")
    metadata = metadata_for(candidate)

    backup = install_candidate(
        candidate, destination, tmp_path / "backups", tmp_path / "build.json",
        metadata, datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc),
    )

    assert destination.read_bytes() == b"new"
    assert backup is not None and (backup / "go2rtc").read_bytes() == b"old"
    assert json.loads((tmp_path / "build.json").read_text()) == metadata.as_dict()
```

Add tests proving an invalid candidate SHA or metadata write failure preserves
the old binary, `metadata_matches` requires commit+patch+platform, and rollback
backs up the current binary before restoring the newest valid backup.

- [x] **Step 6: Implement metadata, backup, install, and rollback**

Write temporary binary and metadata siblings, verify candidate SHA and
executable mode, then use `Path.replace` for atomic installation. Backups use:

```text
runtime/backups/go2rtc/YYYYmmdd-HHMMSS-<binary_sha256_prefix>/
```

The metadata serializer must use a fixed allowlist and never include source
paths, environment values, URLs, or command output.

- [x] **Step 7: Implement the macOS CLI and Make/install integration**

`tools/go2rtc_build.py ensure` must:

1. require Darwin x86_64 and Go >=1.24;
2. skip only when binary metadata matches commit, patch SHA, and platform;
3. clone the fixed upstream URL into `mktemp` and checkout the fixed commit;
4. call `verify_and_apply_patch`;
5. run `CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o <candidate> .`;
6. verify `file`, `go2rtc -version`, SHA256, and executable mode;
7. run `codesign --force --sign - <candidate>` before installation;
8. call `install_candidate` only after every check passes.

`make alpha-go2rtc-info`, `alpha-go2rtc-rebuild`, and
`alpha-go2rtc-rollback` delegate to this CLI. `alpha-install` calls `ensure`
instead of downloading the v1.9.14 release.

- [x] **Step 8: Verify Task 1**

Run:

```bash
/tmp/baby-monitor-hybrid-hd-venv/bin/python -m pytest -q \
  tests/monitoring/test_go2rtc_build.py tests/deploy/test_alpha_commands.py
bash -n tools/*.sh
git diff --check
```

- [x] **Step 9: Commit Task 1**

```bash
git add patches packages/monitoring/go2rtc_build.py tools/go2rtc_build.py \
  tools/install_alpha_macos.sh Makefile tests/monitoring/test_go2rtc_build.py \
  tests/deploy/test_alpha_commands.py
git commit -m "build: make go2rtc hybrid HD compatible"
```

---

### Task 2: Derived compat stream and codec-aware health evidence

**Files:**
- Modify: `packages/monitoring/alpha_quality.py`
- Modify: `config/go2rtc.alpha.yaml`
- Modify: `tests/monitoring/test_alpha_quality.py`
- Modify: `tests/monitoring/test_alpha_quality_health.py`
- Modify: `tests/deploy/test_alpha_commands.py`

**Interfaces:**
- Produces: `COMPAT_HD = "ffmpeg:source#video=h264#hardware=videotoolbox#width=2560#height=1440#bitrate=6M"`.
- Extends: `HealthResult.source_codec: str` with only normalized `H264`, `H265`, or empty.
- Extends: `QualityInfo.compat_profile: str` with `videotoolbox-1440p-6M` or `missing`.

- [x] **Step 1: Write RED config tests**

Add tests proving `upgrade_to_hd` inserts the exact `source_compat` value,
replaces an obsolete compat definition, remains idempotent, preserves the
Xiaomi URI and unknown keys, and reports only the derived compat profile.

```python
assert upgraded["streams"]["source_compat"] == COMPAT_HD
assert inspect_quality(upgraded).compat_profile == "videotoolbox-1440p-6M"
```

- [x] **Step 2: Run RED**

```bash
/tmp/baby-monitor-hybrid-hd-venv/bin/python -m pytest -q \
  tests/monitoring/test_alpha_quality.py tests/monitoring/test_alpha_quality_health.py
```

Expected: missing constant/field assertions fail.

- [x] **Step 3: Implement the derived config**

Set both derived streams in `upgrade_to_hd`, add `source_compat` to the default
template, and derive `QualityInfo.compat_profile` only by exact equality with
`COMPAT_HD`.

- [x] **Step 4: Add RED source codec tests**

Use complete synthetic `/api/streams?src=source&video` producer structures and
assert:

```python
assert check_source_health(...).source_codec == "H265"
assert "xiaomi://" not in repr(check_source_health(...))
```

Add H.264, missing video codec, malformed media, and secret-redaction cases.

- [x] **Step 5: Implement normalized codec extraction**

Accept only video media declarations containing the standalone codec tokens
`H264` or `H265`; never copy an entire media string or producer object into the
result. Propagate the normalized codec through every `check_hd_health` result.

- [x] **Step 6: Verify and commit Task 2**

```bash
/tmp/baby-monitor-hybrid-hd-venv/bin/python -m pytest -q \
  tests/monitoring/test_alpha_quality.py \
  tests/monitoring/test_alpha_quality_health.py \
  tests/deploy/test_alpha_commands.py
git diff --check
git add packages/monitoring/alpha_quality.py config/go2rtc.alpha.yaml tests
git commit -m "feat: add on-demand VideoToolbox HD profile"
```

---

### Task 3: Profile-bound tickets and fixed relay strategies

**Files:**
- Modify: `apps/api/hd_stream.py`
- Modify: `apps/api/alpha.py`
- Modify: `apps/api/runtime.py`
- Modify: `tests/api/test_hd_stream.py`
- Modify: `tests/api/test_alpha_app.py`
- Modify: `tests/api/test_runtime.py`

**Interfaces:**
- Produces: `HdProfile(str, Enum)` values `NATIVE="native"` and `COMPAT="compat"`.
- Changes: `HdTicketStore.issue(profile: HdProfile) -> HdTicket`.
- Changes: `HdTicketStore.consume(value: str) -> HdProfile | None`.
- Changes: `HdStreamService.issue_ticket(profile: HdProfile) -> HdTicket`.
- Adds: fixed internal `HdRelayProfile(stream_name, codec_request, codec_family, failure_code)`.

- [x] **Step 1: Write RED profile-ticket tests**

```python
ticket = store.issue(HdProfile.NATIVE)
assert store.consume(ticket.value) is HdProfile.NATIVE
assert store.consume(ticket.value) is None
```

Add expiry, capacity, concurrent single-use, and a native/compat ticket pair.
No response object may expose the stored profile.

- [x] **Step 2: Run RED ticket tests**

```bash
/tmp/baby-monitor-hybrid-hd-venv/bin/python -m pytest -q \
  tests/api/test_hd_stream.py -k 'ticket or profile'
```

- [x] **Step 3: Implement profile-bound storage and fixed definitions**

Use a ticket mapping to `(expires_at, HdProfile)`. Define only:

```python
NATIVE = HdRelayProfile("source", "hvc1.1.6.L153.B0", "hvc1.", HdCode.CODEC_UNSUPPORTED)
COMPAT = HdRelayProfile("source_compat", H264_CODEC_REQUEST, "avc1.", HdCode.TRANSCODE_UNAVAILABLE)
```

Construct and validate both loopback upstream URIs at service startup.

- [x] **Step 4: Write RED relay classification tests**

Test real service behavior with async fake sockets/upstreams:

- native sends only the HEVC offer and accepts only an `hvc1.` description;
- compat sends only the approved H.264 offer and accepts only `avc1.`;
- profile stream names are fixed and never taken from browser input;
- wrong description returns the profile-specific safe error;
- connect/protocol errors return `HD_UPSTREAM_FAILED`;
- disconnect closes upstream and releases the global gate;
- native close completes before a later compat connection acquires a slot.

- [x] **Step 5: Implement relay classification**

Replace broad H.264-only parsing with `_parse_mse_description(value) -> tuple[str, ...] | None`
and validate every returned codec against the selected profile family. Catch
only expected protocol/connection groups for public classification; never put
`str(exc)` into the result.

- [x] **Step 6: Write RED API request tests**

```python
response = app.post("/api/hd-session", headers=auth(), json={"profile": "native"})
assert response.json() == {"ticket": "opaque-ticket", "expires_in": 10}
assert fake.issued_profiles == [HdProfile.NATIVE]
```

Add compat, missing profile, unknown profile, extra field, unauthenticated, and
busy cases. Invalid bodies must issue no ticket.

- [x] **Step 7: Implement strict route and runtime wiring**

Add a Pydantic request model with `extra="forbid"`; pass its enum to
`issue_ticket`. Runtime constructs one service with fixed `source` and
`source_compat` names. The response remains ticket metadata only.

- [x] **Step 8: Verify and commit Task 3**

```bash
/tmp/baby-monitor-hybrid-hd-venv/bin/python -m pytest -q \
  tests/api/test_hd_stream.py tests/api/test_alpha_app.py tests/api/test_runtime.py
git diff --check
git add apps/api tests/api
git commit -m "feat: add fixed native and compat HD relays"
```

---

### Task 4: Native-first browser player with one compat transition

**Files:**
- Modify: `apps/api/hd_player.js`
- Modify: `tests/frontend/hd_player.test.mjs`

**Interfaces:**
- Keeps: `createHdPlayer(environment)` and `selectZoom(zoom)`.
- Adds internal: `HEVC_MIME = 'video/mp4; codecs="hvc1.1.6.L153.B0"'`.
- Adds internal: attempt profiles `native` and `compat`.
- Exposes: `statusElement.dataset.profile` only while active; value is `native` or `compat`.

- [x] **Step 1: Replace the obsolete H.265 rejection test with RED native tests**

Test these observable behaviors:

```javascript
test('HEVC-capable browser requests native and accepts hvc1', async () => {
  const fixture = playerFixture({mediaTypeSupported: () => true});
  const player = createHdPlayer(fixture.environment);
  player.selectZoom(2);
  await flushPromises();
  assert.deepEqual(await fixture.requests[0].jsonBody, {profile: 'native'});
  // deliver hvc1 description, media, and playing
  assert.equal(fixture.statusElement.textContent, 'HD_ACTIVE');
  assert.equal(fixture.statusElement.dataset.profile, 'native');
});
```

Add a browser without HEVC support that requests compat first and never opens
a native socket.

- [x] **Step 2: Run RED native-selection tests**

```bash
node --test tests/frontend/hd_player.test.mjs
```

Expected: existing POST has no JSON body and H.265 is rejected.

- [x] **Step 3: Implement profile-aware session creation and MIME validation**

POST `{profile}` with `Content-Type: application/json`. Native accepts only
`hvc1.`, compat accepts only `avc1.`. Keep the existing ticket-first-message,
same-origin WebSocket, append ordering, and generation isolation.

- [x] **Step 4: Write RED one-transition tests**

Test native description rejection, append error, autoplay rejection, socket
error, and native startup timeout before activation. Each must:

1. close and revoke native resources;
2. keep MJPEG visible;
3. issue exactly one compat POST/socket;
4. never hold both sockets open;
5. activate compat as `HD_ACTIVE` with dataset `compat` when it succeeds.

Also test compat failure performs no third attempt.

- [x] **Step 5: Implement bounded native-to-compat transition**

Track `attemptProfile`, `compatAttempted`, and a per-attempt generation. A
pre-activation native failure calls `startAttempt('compat')` after complete
native cleanup. A compat failure or post-activation failure uses the normal
no-black MJPEG restoration and blocks retries until 1x.

- [x] **Step 6: Write RED typed-status tests**

Assert exact final public values for `HD_CODEC_UNSUPPORTED`,
`HD_TRANSCODE_UNAVAILABLE`, `HD_UPSTREAM_FAILED`, `HD_TIMEOUT`, `HD_BUSY`, and
`HD_UNSUPPORTED`. Raw server values and thrown messages must map to
`HD_UPSTREAM_FAILED`.

- [x] **Step 7: Implement typed public failures without regression**

Extend the public allowlist, map server error messages strictly, classify the
final eight-second timer as `HD_TIMEOUT`, and clear `dataset.profile` on
cleanup/fallback. Do not change transform, drag, fullscreen, PTZ, snapshot, or
notification code.

- [x] **Step 8: Verify and commit Task 4**

```bash
node --test tests/frontend/*.test.mjs
git diff --check
git add apps/api/hd_player.js tests/frontend/hd_player.test.mjs
git commit -m "feat: prefer native HEVC with hardware fallback"
```

---

### Task 5: Operational health, documentation, and acceptance commands

**Files:**
- Modify: `tools/alpha_quality.py`
- Modify: `Makefile`
- Modify: `README.md`
- Modify: `docs/runbooks/ALPHA_QUICKSTART.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/superpowers/specs/2026-08-04-intel-macos-go2rtc-build-design.md`
- Modify: `tests/monitoring/test_alpha_quality_cli.py`
- Modify: `tests/deploy/test_hd_docs.py`

**Interfaces:**
- `make alpha-source-check` prints `source_codec=H265` and the existing derived dimensions/protocol/count values.
- `make alpha-go2rtc-info` prints only pinned commit, patch SHA, binary SHA, Go version, build time, and platform.
- The runbook provides profile/consumer/process checks that do not output URLs or credentials.

- [x] **Step 1: Write RED CLI and documentation contract tests**

Assert the health CLI includes normalized `source_codec`, quality info includes
the compat profile, and docs contain `H.265`, `source_compat`,
`VideoToolbox`, native/compat acceptance, and no obsolete “2560x1440 H.264
verified” statement.

- [x] **Step 2: Run RED**

```bash
/tmp/baby-monitor-hybrid-hd-venv/bin/python -m pytest -q \
  tests/monitoring/test_alpha_quality_cli.py tests/deploy/test_hd_docs.py
```

- [x] **Step 3: Implement safe output and update the runbook**

Document:

```bash
make alpha-update
make alpha-install
make alpha-restart
make alpha-go2rtc-info
make alpha-source-check
```

Add a three-browser result block containing active profile, visible detail,
handoff seconds, no-black result, 2x-to-3x reuse, MJPEG fallback, encoder count,
and `PTZ_DISABLED`. Consumer checks may print only stream name plus derived
producer/consumer counts.

- [x] **Step 4: Verify and commit Task 5**

```bash
/tmp/baby-monitor-hybrid-hd-venv/bin/python -m pytest -q \
  tests/monitoring/test_alpha_quality_cli.py tests/deploy/test_hd_docs.py \
  tests/deploy/test_alpha_commands.py
bash -n tools/*.sh
git diff --check
git add README.md Makefile tools/alpha_quality.py docs tests
git commit -m "docs: add hybrid HD deployment gate"
```

---

### Task 6: Complete verification and Draft PR publication

**Files:**
- Modify: `docs/superpowers/plans/2026-08-04-dashboard-hybrid-hd-streaming.md`
- Modify only if evidence changes: `docs/runbooks/ALPHA_QUICKSTART.md`

- [ ] **Step 1: Run the complete fresh local gate**

```bash
/tmp/baby-monitor-hybrid-hd-venv/bin/python -m pytest -q
node --test tests/frontend/*.test.mjs
/tmp/baby-monitor-hybrid-hd-venv/bin/python -m json.tool config/settings.schema.json >/dev/null
/tmp/baby-monitor-hybrid-hd-venv/bin/python -m compileall -q apps packages services tools
bash -n tools/*.sh
git diff --check
```

Record exact pass counts and warning counts; do not claim the real camera gate
from synthetic tests.

- [ ] **Step 2: Verify the real upstream patch**

In a temporary clone of the pinned go2rtc commit, run the production patch
verification and a Go build for the available host or `GOOS=darwin
GOARCH=amd64 CGO_ENABLED=0` when supported. Inspect the generated source so
H.265 writes `hvc1` and Xiaomi CS2 listens on `udp4`.

- [ ] **Step 3: Review the complete diff against the approved spec**

Confirm no generic proxy selector, software encoder fallback, permanent HD
producer, second HD socket for 2x/3x, physical PTZ adapter, secret fixture,
private address, binary, runtime file, or household media is present.

- [ ] **Step 4: Push only after remote-parent verification**

```bash
git fetch origin codex/basic-usable-alpha
git rev-parse origin/codex/basic-usable-alpha
git merge-base --is-ancestor origin/codex/basic-usable-alpha HEAD
git push origin codex/basic-usable-alpha
```

If the remote moved independently, stop and reconcile without force-pushing.

- [ ] **Step 5: Keep PR #4 Draft and verify GitHub Actions**

Update the Draft PR description with the real H.265 root cause, architecture,
automated evidence, and still-pending Intel i9/M2/Android gate. Do not mark the
PR Ready.

- [ ] **Step 6: Hand off the real-device gate**

Provide the exact i9 update/install/restart commands and the acceptance result
template. Only after i9 source/codec, native or compat profile, process count,
M2 Chrome, M2 Safari, and Android Chrome all pass may the final PR gate be
completed.
