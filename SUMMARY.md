# Baby Monitor Local Project Summary

Updated: 2026-08-13

## Snapshot

- Repository: `lpearf-pixel/baby-monitor-local` (public).
- Stable Xiaomi line: `stable/xiaomi-alpha` at `0df20ae`.
- Active feature line: `codex/baby-guardian-event-loop`.
- Local guardian implementation history reached `fb3eee3` before this documentation
  slice. GitHub contains the content-equivalent squash commit `27274d8` on the same
  feature branch; both implementation snapshots have tree `adf3672`.
- The feature branch has not been merged into `stable/xiaomi-alpha` or `main`. No PR
  was created for the squash publication.
- The current priority is the functional guardian event loop. The installed i9
  performance recheck remains intentionally deferred and must not block that work.
- `uv.lock` is an existing untracked file in the Work checkout and is outside the
  approved guardian/documentation scope.

Always run fresh Git checks before relying on the commit references above. The current
local HEAD may include documentation commits created after `fb3eee3`.

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

### Operations

- `make alpha-guardian-start` reuses the idempotent Alpha startup and then checks
  go2rtc, Dashboard, visual worker, gauge worker, environment watchdog, realtime
  models/metrics and the Ollama bridge when semantic review is enabled.
- `make alpha-guardian-test` runs repository, software, installation, service, media
  and isolation stages with fixed redacted PASS/FAIL output.
- The automatic test command does not send a real ntfy notification, synthesize a Baby
  risk or write production event/evidence data.

## Verification Evidence

The latest complete software gate recorded before this documentation update was:

- Python repository suite: `682 passed`;
- Dashboard Node suite: `70 passed`;
- Python compilation: passed;
- new shell syntax, ASCII and LF checks: passed;
- Make dry-run and `git diff --check`: passed;
- tracked runtime/media/SQLite and sensitive-literal checks: passed;
- one existing Starlette/httpx deprecation warning remained.

The Option A startup/test slice also recorded focused Python `177 passed` and Node
`70 passed` before the final complete software gate.

These results prove software behavior against synthetic fixtures. They do not prove
the installed i9 services, real Xiaomi stream, household scene accuracy, two Android
deliveries, sustained performance or safe unattended care.

## Current Git State

| Item | State |
|---|---|
| Protected default branch | `main`; unchanged by guardian work |
| Stable Xiaomi branch | `stable/xiaomi-alpha` at `0df20ae` |
| Active feature branch | `codex/baby-guardian-event-loop` |
| Local implementation snapshot | `fb3eee3` |
| Remote squash snapshot | `27274d8` |
| Shared implementation tree | `adf3672` |
| PR/merge | No guardian PR; not merged |
| Preserved unrelated file | untracked `uv.lock` |

The local and remote feature histories are intentionally different because GitHub App
publication created a squash snapshot. Their implementation file trees were verified
identical at publication. Do not reset, rebase, force-push or blindly merge one history
into the other. Inspect the current checkout and reconcile by content before selecting
a future branch strategy.

## Pending Real-Device Acceptance

- Run `make alpha-guardian-start` and `make alpha-guardian-test` on the installed i9
  with the real camera and launchd jobs.
- Complete private bed-zone configuration and the restricted i9-to-M2 semantic bridge.
- Validate real semantic response shape, cold/hot latency and daylight, darkness,
  mosquito-net, adult, empty-bed and safe simulated-obstruction scenes.
- Confirm real notification display and offline recovery on both Android phones using
  a later explicit acceptance command. Option A does not send these messages.
- Complete WS2021 real calibration, 30 daylight comparisons, night/glare/occlusion
  rejection and the independent 24-hour environment gate.
- Apply the visual launchd scheduling update on i9, observe for 3 minutes and run the
  full 10-minute performance sampler. Production previously fell to 1 FPS, while a
  foreground single-variable run reached the 5 FPS / 180 ms P95 budget.
- Complete three-browser HD acceptance and the final 72-hour camera, i9, M2, network,
  storage and two-phone release gate before tagging `v0.1.0`.

## Known Limitations

- Authenticated risk-event queries and the Dashboard event list are not implemented.
- Two parents cannot yet acknowledge an event independently.
- False-positive feedback is not implemented.
- Evidence retention cleanup for the planned time/space limits is not implemented.
- The later FFmpeg original-video ring upgrade is deferred; current evidence uses the
  privacy-safe animated WebP design.
- Real Baby posture, face obstruction and bed-exit accuracy remain unaccepted.
- Audio/cry candidates are deferred.
- Remote private viewing and the 72-hour release gate remain unfinished.
- This system does not detect breathing, heart rate, suffocation or medical emergencies.

## Next Priorities

1. Add authenticated risk-event queries and a Dashboard event list.
2. Add separate acknowledgement state for both parents.
3. Add bounded false-positive feedback without training directly on household media.
4. Add a separate explicit two-phone notification and safe live-rehearsal acceptance
   command; do not add side effects to `alpha-guardian-test`.
5. Add evidence retention cleanup, then consider the FFmpeg ring-buffer upgrade.
6. Return to the deferred i9 scheduling/performance and environment acceptance gates.
7. Add audio/cry candidates only after the visual guardian loop is functionally closed.

## Operating Commands

Primary guardian entry points:

```bash
make alpha-guardian-start
make alpha-guardian-test
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
6. Continue with authenticated event queries unless fresh repository evidence shows a
   newer approved priority.
7. Use focused tests for the slice and the full gate only at the next milestone or
   stable-branch integration.
8. Do not push, create a PR, merge, tag or modify `main` without explicit approval.
