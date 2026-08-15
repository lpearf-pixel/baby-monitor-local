# Baby Monitor Local Project Summary

Updated: 2026-08-14

## Snapshot

- Repository: `lpearf-pixel/baby-monitor-local` (public).
- Stable Xiaomi line: `stable/xiaomi-alpha` at `0df20ae`.
- Local working line: `codex/guardian-evidence-retention` at `00e2934`.
- Published i9 acceptance line: `codex/guardian-live-acceptance` at `c4b2de0`.
  The remote commit has the same source tree as local `00e2934`; connector-generated
  history makes the commit IDs different.
- The evidence-retention line is based on the published Dashboard snapshot `69e2d5b`;
  the Dashboard remains complete and its published branch is not rewritten.
- Remote branch `codex/baby-guardian-event-loop` remains at its earlier squash snapshot
  `27274d8`; it is not rewritten or force-pushed.
- The feature branch has not been merged into `stable/xiaomi-alpha` or `main`. No PR
  was created for the squash publication.
- The current priority is to pull the published acceptance branch on the installed i9,
  reinstall development/acceptance dependencies and rerun the automatic gate. The
  installed performance recheck remains intentionally deferred and must not block it.
- The earlier untracked `uv.lock` was never staged or published; the recovered checkout
  does not recreate or claim ownership of it.

Always run fresh Git checks before relying on the commit references above.

## Product Scope

Baby Monitor Local is a local-first monitoring and candidate-alert system for:

- Xiaomi Smart Camera 2 Pan-Tilt, model MJSXJ17CM;
- Intel i9 Mac as the always-on camera and guardian host;
- M2 Mac as the local Ollama semantic-review host;
- WS2021 analog temperature/humidity gauge in the camera view;
- two Android phones for authenticated viewing and ntfy alerts;
- 256 GB camera microSD loop recording as the independent continuous-recording path.

The product provides viewing, environment observations and bounded candidate safety
events. It is not medical monitoring and does not authorize unattended care. Mi Home
continues to own audio, two-way talk, PTZ and camera recording/history controls.

Baby Guardian is the local perception/event layer. The separate Baby Care product may
later consume normalized Guardian events through a read-only integration; Guardian
must not write the Baby Care database directly.

## Deployment Architecture

```text
Xiaomi camera + WS2021 gauge
    -> Intel i9: go2rtc, Dashboard, gauge/watchdog, visual worker
    -> OpenCV/OpenVINO watch candidates + deterministic risk state
    -> restricted loopback SSH forwarding to M2 Ollama semantic review
    -> local SQLite events/outbox + privacy-processed evidence
    -> text-only ntfy delivery to two Android phones
```

Important ownership boundaries:

- Live viewing, microSD recording and Mi Home remain useful when AI is unavailable.
- Visual, gauge, watchdog, Dashboard, go2rtc and model-tunnel services degrade
  independently.
- Normal analysis frames use a bounded in-memory ring. Only event evidence that has
  already passed bed-zone crop and privacy masking may be saved locally.
- go2rtc administration and the model bridge remain loopback-only. External access
  must be authenticated and private; Tailscale Funnel and router port forwarding are
  prohibited.

## Completed Capabilities

### Xiaomi Alpha viewing

- Password-protected Dashboard with 1280x720, 10 FPS MJPEG preview and snapshots.
- 1x/2x/3x zoom, full-screen viewing and drag-to-pan display behavior.
- On-demand 2560x1440 native H.265 viewing with a VideoToolbox H.264 compatibility
  fallback, single producer sharing and safe shutdown/rollback.
- Xiaomi subtype probe/apply with transactional rollback; real i9 testing selected
  subtype 3 for the high-resolution source.
- PTZ command safety skeleton exists, but production control correctly remains
  `PTZ_DISABLED`.

### Environment monitoring

- WS2021 schema-v2 Dashboard calibration flow and controlled frame bursts.
- Independent day/night gauge reader, SQLite WAL history, incidents and trends.
- Deterministic normal, severe, unreadable and recovery states with redacted
  notification payloads.
- One controlled i9 visual-source outage confirmed that gauge monitoring continued
  independently while source-offline and recovery notifications completed.

### Visual analysis

- Strict schema-v1 semantic observations for face obstruction, prone position and
  out-of-bed candidates.
- Deterministic confirmation, recovery, low-confidence downgrade, deduplication and
  adult-intervention audit logic.
- Required normalized bed/privacy polygons, 15 percent bed crop expansion, privacy
  masking before encode, fixed 960x540 safe frames and a bounded 40-second ring.
- One continuous local analysis stream, disconnect/freeze detection, bounded reconnect
  and single-flight semantic scheduling.
- Fixed local Qwen review contract with bounded four-frame requests, strict parsing,
  degradation/recovery behavior and independent visual/tunnel launchd units.
- Optional OpenCV/OpenVINO realtime watch layer with 5/3/1 FPS degradation and bounded
  metrics. The fast layer may request review but cannot open or recover a risk alert.

### Latest visual-model experiment

- The downloaded JoyAI GGUF identifies as `qwen3vl`, but Ollama registered only the
  `completion` capability. With a real synthetic test image it read only a filename-like
  label and returned all visual fields as uncertain. It is therefore rejected for visual
  integration until a matching vision projector/runtime package is available and passes
  the grounded-image gate. Earlier answers produced with a missing image path are invalid.
- The existing `qwen3-vl:8b-instruct-q4_K_M` correctly read the synthetic control text,
  yellow mannequin, coarse lying pose, hidden face and in-bed status. The first larger
  image run took 23.96 seconds; a warm run after resizing the longest edge to 640 pixels
  took 3.32 seconds, which the user accepted as an experiment baseline.
- The repository production contract is still fixed at 960x540 safe frames and bounded
  four-frame requests. The 640-pixel result is evidence for a future approved optimization,
  not an implemented configuration change. Qwen remains asynchronous event review;
  OpenCV/OpenVINO owns the fast candidate cadence and the deterministic i9 state machine
  owns alert decisions.

### Guardian event loop

- Stable event IDs and idempotent SQLite lifecycle persistence for risk open/recovery.
- Restart restoration of open risks without restoring stale candidate counters.
- Standalone and linked adult-intervention audit records.
- Redacted structured diagnostics isolated from worker failures.
- Immediate privacy-processed JPEG evidence plus bounded pre-10/post-30-second animated
  WebP evidence from the safe-frame ring.
- Private atomic evidence files and explicit collecting, ready, failed and interrupted
  lifecycle states.
- Persistent idempotent notification outbox for risk open, linked adult intervention
  and recovery.
- Off-thread bounded ntfy delivery with causal ordering, retry exhaustion and no
  duplicate successful sends.
- Evidence initialization before outbox visibility, preventing a notification/evidence
  race.
- Read-only authenticated queries join the existing event and evidence state in SQLite,
  validate a closed response schema and never expose evidence keys, filesystem paths,
  model details or media.
- The Dashboard shows the newest 20 events, pins unresolved events within that fixed
  set, highlights them, and displays collecting, ready, failed, interrupted or no
  evidence. It loads immediately and refreshes every 15 seconds; a failed refresh keeps
  the old list and marks it as potentially stale.
- Guardian evidence cleanup now runs immediately with the visual runtime and then once
  per day. It applies the centralized 30-day/30-GiB defaults, protects open events,
  collecting evidence, notification-pending evidence and records whose recovery notice
  is not terminal, deletes only controlled media plus the eligible evidence row, and
  leaves the risk event/audit history queryable. Directory-descriptor traversal rejects
  symlinked ancestors, while exact eligibility is rechecked under one SQLite writer
  lock. Cleanup, logging or scheduler failures are redacted and isolated from visual
  analysis.

### Operations

- `make alpha-guardian-start` reuses the idempotent Alpha startup and then checks
  go2rtc, Dashboard, visual worker, gauge worker, environment watchdog, realtime
  models/metrics and the Ollama bridge when semantic review is enabled.
- `make alpha-guardian-test` runs repository, software, installation, service, media
  and isolation stages with fixed redacted PASS/FAIL output.
- The automatic test command does not send a real ntfy notification, synthesize a Baby
  risk or write production event/evidence data.
- `make alpha-guardian-test-live` is a separate supervised acceptance command. It
  requires an interactive terminal, two safety confirmations, readiness, one clearly
  labeled text-only non-risk notification, confirmations from both phones, and checks
  of the authenticated live view and event list. Its hook-only software mode can emit
  only `SIMULATED`, never a physical PASS.

## Verification Evidence

The latest complete clean-environment software gate, including the current TestClient
dependency closure, was:

- Python repository suite: `741 passed`;
- Dashboard Node suite: `73 passed`;
- Python compilation: passed;
- all tracked shell syntax, ASCII and LF checks: passed;
- Make dry-run and `git diff --check`: passed;
- tracked runtime/media/SQLite and sensitive-literal checks: passed;
- package consistency (`pip check`): passed.

The previous live-acceptance focused review recorded `38 passed`; the wider
Guardian-focused gate recorded `126 passed`. A fresh i9 install exposed that current
Starlette TestClient requires `httpx2`, while the installer omitted development extras.
`00e2934` adds the current and legacy HTTP client dependencies and installs `[dev]`;
the fix was published as remote `c4b2de0`. A clean temporary environment then recorded
`71 passed` for focused deployment/API coverage before the `741`-test full suite.

These results prove software behavior against synthetic fixtures. They do not prove
the installed i9 services, real Xiaomi stream, household scene accuracy, two Android
deliveries, sustained performance or safe unattended care.

## Current Git State

| Item | State |
|---|---|
| Protected default branch | `main`; unchanged by guardian work |
| Stable Xiaomi branch | `stable/xiaomi-alpha` at `0df20ae` |
| Local working branch | `codex/guardian-evidence-retention` at `00e2934` |
| Published i9 acceptance branch | `codex/guardian-live-acceptance` at `c4b2de0` |
| Local/remote tree | identical: `137611024da2e4d02547a4fd35cb4335cfafb32c` |
| Guardian evidence-retention runtime implementation | `718af9a` |
| Guardian evidence-retention safety closure | `e3cd69c` |
| Guardian live-notification helper | `d862f2a` |
| Guardian supervised live acceptance | `67db75d` |
| Published Dashboard base | `69e2d5b` |
| Published pre-Dashboard checkpoint | `checkpoint/guardian-r4-pre-dashboard-20260813` → `08dbc90` |
| Preserved legacy remote branch | `codex/baby-guardian-event-loop` at `27274d8` |
| PR/merge | No guardian PR; not merged |
| Protected branches | `main` and `stable/xiaomi-alpha`; unchanged |

The local and published branches intentionally have different connector-generated
commit histories but the same current source tree. Continue deployment from the
published `codex/guardian-live-acceptance` tip. Do not force-push or merge the legacy
branch into this line without a separate integration decision.

## Pending Real-Device Acceptance

- On the installed i9, switch to/pull `codex/guardian-live-acceptance`, verify at least
  `c4b2de0`, then run `make alpha-install`, `make alpha-guardian-start` and
  `make alpha-guardian-test`. The earlier attempt failed before runtime checks because
  the clean environment lacked `httpx2`; that repository defect is fixed but the i9
  rerun has not yet been reported.
- Complete private bed-zone configuration and the restricted i9-to-M2 semantic bridge.
- Validate real semantic response shape, cold/hot latency and daylight, darkness,
  mosquito-net, adult, empty-bed and safe simulated-obstruction scenes.
- Run `make alpha-guardian-test-live` on the installed i9 with no real infant present,
  an adult supervising, and both Android phones available. This is the pending physical
  proof for one harmless acceptance message, authenticated live view and event list;
  software simulation does not establish delivery.
- Complete WS2021 real calibration, 30 daylight comparisons, night/glare/occlusion
  rejection and the independent 24-hour environment gate.
- Apply the visual launchd scheduling update on i9, observe for 3 minutes and run the
  full 10-minute performance sampler. Production previously fell to 1 FPS, while a
  foreground single-variable run reached the 5 FPS / 180 ms P95 budget.
- Complete three-browser HD acceptance and the final 72-hour camera, i9, M2, network,
  storage and two-phone release gate before tagging `v0.1.0`.

## Known Limitations

- Two parents cannot yet acknowledge an event independently.
- False-positive feedback is not implemented.
- The later FFmpeg original-video ring upgrade is deferred; current evidence uses the
  privacy-safe animated WebP design.
- Real Baby posture, face obstruction and bed-exit accuracy remain unaccepted.
- Audio/cry candidates are deferred.
- The available JoyAI GGUF is completion-only in the tested Ollama runtime and is not
  an accepted visual model. Its official Linux/NVIDIA-oriented package is not an M2
  deployment substitute without a separately validated compatible runtime.
- Remote private viewing and the 72-hour release gate remain unfinished.
- This system does not detect breathing, heart rate, suffocation or medical emergencies.

## Next Priorities

1. Pull `codex/guardian-live-acceptance` on the i9, run `make alpha-install`, then run
   `make alpha-guardian-start` and `make alpha-guardian-test`. Only after that passes,
   run the separate supervised `make alpha-guardian-test-live` with two phones.
2. Complete household synthetic candidate-scene validation and the
   deferred scheduling/performance acceptance.
3. Define per-parent acknowledgement and false-positive feedback only through a future
   contract where Baby Care consumes Guardian's read-only feed and owns identity/write
   state; do not create a second identity model inside Guardian.
4. Consider the FFmpeg ring-buffer upgrade after the functional and real-device gates.
5. Design audio/cry or voice-care interaction only after the visual guardian loop is
   functionally closed, as a separate contract that preserves Baby Care write ownership.

## Operating Commands

Primary guardian entry points:

```bash
make alpha-guardian-start
make alpha-guardian-test
make alpha-guardian-test-live
```

Common service operations:

```bash
make alpha-status
make alpha-visual-status
make alpha-logs
make alpha-stop
```

Deferred visual performance operations:

```bash
make alpha-visual-launchd-update
make alpha-visual-performance
make alpha-visual-diagnostic
```

Do not paste large raw logs into chat. Prefer the fixed status/diagnostic outputs and
only the bounded log window needed to identify the first actionable failure.

## Detailed Records

- [Project status](docs/STATUS.md)
- [Verification checkpoints](docs/CHECKPOINT.md)
- [Ordered next work](docs/NEXT.md)
- [Product overview](README.md)
- [Security policy](SECURITY.md)
- [Roadmap](ROADMAP.md)
- [Approved specifications](docs/superpowers/specs/)
- [Implementation plans](docs/superpowers/plans/)

## Takeover Checklist

1. Read `AGENTS.md` completely, then this file.
2. Read `docs/STATUS.md`, `docs/CHECKPOINT.md` and `docs/NEXT.md` for detailed history.
3. Verify repository root, remote, branch, HEAD, upstream, dirty state and recent log.
4. Preserve `uv.lock` and any other user changes; do not reset or clean.
5. Reconcile local and remote feature histories before any push or branch integration.
6. Continue the installed-i9 acceptance rerun from published branch
   `codex/guardian-live-acceptance`; do not start acknowledgement, audio or Baby Care
   writes until that gate and a separate design are approved.
7. Use focused tests for the slice and the full gate only at the next milestone or
   stable-branch integration.
8. Do not push, create a PR, merge, tag or modify `main` without explicit approval.
