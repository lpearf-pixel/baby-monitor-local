# Baby Monitor Local Project Summary

Updated: 2026-08-21

## Snapshot

- Repository: `lpearf-pixel/baby-monitor-local` (public).
- Stable Xiaomi line: `stable/xiaomi-alpha` at `0df20ae`.
- Active implementation line: `codex/voice-care-v1-gate-v1`, based on the approved
  `codex/voice-care-v1-design` checkpoint. Gate V1 Task 1 is local and has not been
  pushed from this worktree.
- The evidence-retention line is based on the published Dashboard snapshot `69e2d5b`;
  the Dashboard remains complete and its published branch is not rewritten.
- Remote branch `codex/baby-guardian-event-loop` remains at its earlier squash snapshot
  `27274d8`; it is not rewritten or force-pushed.
- The feature branch has not been merged into `stable/xiaomi-alpha` or `main`. No PR
  was created for the squash publication.
- The functional guardian event loop and installed-i9 10-minute performance gate are
  complete. On 2026-08-20 the recurring go2rtc restart defect was traced to mixed
  launchd/PID-file ownership: a launchd listener and a direct fallback could coexist,
  while the PID file named the non-listening process. macOS now uses one user-level
  launchd owner, has no direct fallback or port-selected kill path, and verifies the
  exact launchd process plus listener before accepting the API. Two idempotent starts
  kept one stable process, and `make alpha-go2rtc-restart` now restarts only go2rtc.
  A second cause was then isolated: ad-hoc signing gave every rebuilt go2rtc app a
  hash-based designated requirement, so macOS could treat each build as a new Local
  Network identity and silently drop CS2 UDP. The installed app now has the fixed
  bundle identifier and an explicit stable designated requirement. After one
  LaunchServices registration, an unchanged install refresh plus launchd-only restart
  passed the real source gate: `cs2+udp`, H.265, native `2560x1440`, live `1280x720`
  and positive received bytes. Visual returned to 5 FPS; gauge and Dashboard remained
  healthy. The correction passed the full Python `931 passed`, Dashboard Node
  `73 passed` and installed Guardian `19/19` automatic gates before commit.
  WS2021 E1 private schema-v2 calibration passed on
  2026-08-16. Its fixed 2560×1440 five-frame gauge burst is operational, and corrected
  non-16:9 rectification now passes both ROI geometry gates plus the temperature circle
  match. Humidity remains fail-closed as `calibration_invalid`. The approved i9-local
  automatic-localization Task 15 is now inserted before E2; strict localization and
  validated schema-v2 relocation contracts plus privacy-safe crop persistence are
  complete, as are deterministic private dataset preparation and pinned i9-local CPU
  training/export tooling and fail-closed gauge-worker integration. Daylight position
  1/5 completed with 60 valid private pairs. A private collection-seed model was trained,
  exported and digest-checked after correcting augmentation to the approved 1/10–1/3
  deployment scale, but position 2 remains `gauge_not_found`; low-confidence predictions,
  local feature templates and full-frame shape scans did not provide a safe label. The
  current gate is one local position-2 bounding-box annotation before automatic private
  collection can continue; no production threshold is reduced.
  The latest bootstrap rerun fixes the zero CPU learning rate and aliased best-state
  snapshot, adds deterministic generated backgrounds/negatives, and passes training,
  OpenVINO export and digest checks. It is still not a production artifact until live
  localization and the remaining private gates pass.
  Fresh live inference reaches three above-threshold NMS candidates, but all remain
  out of bounds and fail the strict outer-frame/two-dial layout. The validator now
  filters candidates before ambiguity resolution. A new calibrated capture was fully
  privacy-rejected with zero persistence; more safe private position diversity is
  still required.
- 2026-08-17 fixed-ROI follow-up: a schema-v2 lower-right ROI and bounded consecutive-
  frame stabilizer now run before the trained detector when automatic localization is
  enabled. Same-aspect 2560x1440 to 1280x720 scaling is accepted; aspect-ratio drift
  remains fail-closed. Gauge/environment tests recorded 95 passed; model artifact and
  live source checks passed. This does not prove real reading accuracy or E2 acceptance.
- 2026-08-18 live fixed-ROI read: 5-frame source burst yielded 3 stable ROI observations,
  but all five dual-face/needle reader attempts failed closed as `calibration_invalid`.
  Task 5 now provides bounded in-memory adaptive face geometry (`c001507`) plus a
  calibrated-center pointer fallback (`ecf8aa8`). Day temperature now uses the grayscale
  needle signal when the red mask is weak (`8b27da1`); the full gauge suite is 81 passed.
  A live five-frame read is now available at about 29.3C / 59.5%RH with confidence 0.75.
  Three independent bursts remained available at 29.32C +/-0.01C and 59.46%RH +/-0.02,
  all at confidence 0.75. This is still a software/live stability result, not E2 accuracy
  evidence. The 30 daylight manual comparisons are deferred and do not block the mainline.
- Live diagnosis confirms rectification and face ROIs succeed, but humidity has no
  bounded circle candidate and temperature's nearest center is ~0.393R away. A fresh
  schema-v2 calibration at the current camera view is required; fail-closed limits are
  not widened.
- The earlier untracked `uv.lock` was never staged or published; the recovered checkout
  does not recreate or claim ownership of it.

Always run fresh Git checks before relying on the commit references above.

## Product Scope

Baby Monitor Local is a local-first monitoring and candidate-alert system for:

- Xiaomi Smart Camera 2 Pan-Tilt, model MJSXJ17CM;
- Intel i9 Mac as the always-on camera and guardian host;
- M2 Mac as the local Ollama semantic-review host;
- WS2021 analog temperature/humidity gauge in the camera view;
- two iPhones for authenticated viewing and ntfy alerts;
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
    -> text-only ntfy delivery to two iPhones
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
- Ollama tunnel direction is fixed: normal operation is i9 `-L` to M2 loopback. An
  M2→i9 SSH login without explicit reverse `-R` does not provide the bridge; verify
  `/api/tags` HTTP 200 instead of trusting launchd `running`. The latest stale listener
  was stopped; E4 controlled isolation/recovery remains pending.

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
- On 2026-08-15 the installed Intel i9 completed this supervised command with no real
  infant present and an adult supervising. One labeled non-risk ntfy message reached
  both iPhones; the authenticated live view and Guardian event list were visible; the
  final result was `guardian_live_test=PASS`.
- The installed i9 also completed the supervised seven-scene household synthetic gate
  on 2026-08-15. Each fixed scene recorded 10 operator-confirmed `correct` trials with
  zero false-positive, missed or unavailable outcomes; the final result was
  `guardian_scene_test=PASS`. No household media or free-form model output was stored.

## Verification Evidence

The latest complete software gate, including Guardian live-acceptance coverage, was:

- Python repository suite: `931 passed` on the installed Intel i9;
- Dashboard Node suite: `73 passed`;
- Python compilation: passed;
- all tracked shell syntax, ASCII and LF checks: passed;
- Make dry-run and `git diff --check`: passed;
- tracked runtime/media/SQLite and sensitive-literal checks: passed;
- one existing Starlette/httpx deprecation warning remained.

The installed side-effect-bounded `make alpha-guardian-test` additionally passed all
19 repository, software, installation, service, media and isolation stages after the
go2rtc stable-identity correction.

The remote dependency-closure checkpoint additionally verified a clean temporary
Python 3.11 environment with `741 passed` after adding the current Starlette
TestClient dependency and making `alpha-install` install acceptance extras. That
portable result complements, but does not replace, the later installed-i9
`772 passed` result.

The live-acceptance focused review recorded `38 passed`; the wider Guardian-focused
gate recorded `126 passed`. The functional commits are `d862f2a` for the narrow,
redacted notification helper and `67db75d` for the supervised command.

These results prove software behavior against synthetic fixtures. They do not prove
household scene accuracy, sustained performance or safe unattended care. The separate
2026-08-15 supervised run establishes installed-i9 readiness for that run, text-only
delivery to two iPhones, authenticated live view and the Guardian event list.

The installed i9 also passed the 10-minute realtime production gate on 2026-08-15:
all 60 samples remained at 5 FPS, processing p50 was 100.836 ms, p95 was 130.789 ms,
maximum was 201.529 ms and the model remained available. This proves only that bounded
window, not 24/72-hour stability or unattended-care safety.

## Current Git State

| Item | State |
|---|---|
| Protected default branch | `main`; unchanged by guardian work |
| Stable Xiaomi branch | `stable/xiaomi-alpha` at `0df20ae` |
| Active feature branch | `codex/voice-care-v1-design` |
| Guardian evidence-retention runtime implementation | `718af9a` |
| Guardian evidence-retention safety closure | `e3cd69c` |
| Guardian live-notification helper | `d862f2a` |
| Guardian supervised live acceptance | `67db75d` |
| Guardian realtime stage telemetry | `2a385fc` |
| Installed-i9 performance checkpoint | `aca4639` |
| go2rtc unhealthy-process recovery | `c75683f` |
| go2rtc listener-ownership verification | `1b1732d` |
| Published Dashboard base | `69e2d5b` |
| Published pre-Dashboard checkpoint | `checkpoint/guardian-r4-pre-dashboard-20260813` → `08dbc90` |
| Preserved legacy remote branch | `codex/baby-guardian-event-loop` at `27274d8` |
| PR/merge | No guardian PR; not merged |
| Protected branches | `main` and `stable/xiaomi-alpha`; unchanged |

The current recovery started from `10f3466` on `codex/voice-care-v1-design`, equal to
its upstream before local edits. Nothing from this recovery slice had been pushed,
merged or opened as a PR at this checkpoint. Untracked `.local/`,
`Interactive` and `test.sh` were deliberately preserved.

## Latest Installed-i9 Runtime Evidence

After an operator-visible restart conflict, go2rtc could remain alive after failing to
bind its loopback API and RTSP listeners. Startup now distinguishes PID liveness from
service readiness, checks the full BSD `ps -ww` command, and requires the validated PID
to own the loopback API listener before accepting a healthy endpoint. Unknown processes
fail closed and are never selected or terminated by port alone.

Fresh software evidence for this repair is Python `772 passed` with the one existing
Starlette/httpx deprecation warning. The focused Alpha deployment file recorded
`26 passed`; the combined Guardian/Alpha deployment gate recorded `54 passed`.

The authoritative runtime check was run from the `kandysmith` GUI-login account that
owns the services. It reported `result=PASS`, `protocol=cs2+udp`, H.265 source video,
native `2560x1440` source dimensions, `1280x720` live dimensions and nonzero received
bytes. The visual worker was running at 5 FPS with current metrics, the realtime model
was available, and the independently supervised Ollama tunnel and bridge were running
and reachable. The Dashboard live view was visibly updating. No private address,
camera identifier, credentials, notification topic or household media is recorded here.

Codex sessions and macOS GUI services are account-scoped. A Codex process running as
`chatgpt-agent` may receive false offline results for services owned by `kandysmith`.
Installed runtime commands must therefore be executed by a Codex session launched
directly from the `kandysmith` SSH login, or manually in that shell. Do not grant broad
Full Disk Access or unrestricted sudo as a workaround.

The retention branch starts from the published Dashboard snapshot. This avoids
rewriting either the Dashboard or legacy squash history. Do not force-push or merge the
legacy branch into this line without a separate integration decision.

## Pending Real-Device Acceptance

- Complete private bed-zone acceptance and real Baby posture/face/bed-exit accuracy;
  the restricted i9-to-M2 bridge and supervised seven-scene synthetic gate have passed.
- Complete the deferred WS2021 30 daylight comparisons and the darkness/infrared,
  glare, occlusion and gauge-movement fail-closed checks. M2/Ollama isolation, the
  independent 24-hour environment gate and three-browser HD acceptance are already
  user-confirmed PASS; iPhone layout remains a UX follow-up.
- Complete the deferred real-Baby normal-care observation, audio/cry A8 model/license
  decision, authenticated private remote access and final 72-hour release gate before
  any `v0.1.0` tag decision.

## Known Limitations

- Two parents cannot yet acknowledge an event independently.
- False-positive feedback is not implemented.
- The later FFmpeg original-video ring upgrade is deferred; current evidence uses the
  privacy-safe animated WebP design.
- Real Baby posture, face obstruction and bed-exit accuracy remain unaccepted.
- Audio/cry software work was separately approved on 2026-08-17 with a strict
  no-household-audio-persistence boundary. Stages A1-A2 strict contracts/settings and
  bounded in-memory PCM source and deterministic loudness/noise-floor gate pass;
  the fail-closed pinned-ONNX classifier boundary and the deterministic cry state
  state machine, text-only atomic event/outbox integration, independent worker and
  installed software gate pass. The installed job remains disabled and stopped. No
  production cry model has been approved or enabled; A8 awaits that decision and
  supervised scenarios.
  The installed Xiaomi source and fixed loopback audio alias now expose Opus, and a
  bounded mono 16 kHz decode passed without persistence. Gate V0's 60-second and
  10-minute receive/discard windows now pass with explicit decoder cleanup; household
  cry/ASR accuracy remains unaccepted.
- Voice Care v1 is active under `docs/superpowers/specs/2026-08-19-voice-care-v1-design.md`.
  Its dedicated `docs/superpowers/plans/2026-08-19-voice-care-v1.md` records completed
  **Gate V0** and the approved dual-repository Gate V1 sequence. Gate V1 uses Silero
  VAD, a local OpenAI Whisper `base`/`small` i9 bake-off, exact normalized `小小` wake
  prefix, SpeechBrain ECAPA speaker verification and fixed macOS speech responses.
  Baby Local Task 1 is complete through `1cc1f51`: strict settings, closed model
  registry, canonical source/runtime manifests and atomic ignored-runtime installation
  are independently reviewed. Whisper conversion now accepts only pinned local
  Transformers bundles and validates the faster-whisper layout. Fresh focused evidence
  is 61 passed. Real model materialization/conversion and accuracy remain operator gates;
  no model, raw household audio or Voice Care record path is enabled. Task 2 is complete
  through `d750f05`: bounded bytearray-only VAD/utterance capture enforces exact 500 ms
  pre-roll, 800 ms terminal silence and 8-second limits, with fail-closed model errors
  and overwrite-before-clear evidence. Fresh Task 2 evidence is 23 passed. Task 3's
  software slice and installed-i9 gate are complete through `99eb8f7`: local-only
  base/small ASR, exact wake, closed benchmark slots and an isolated, pinned CTranslate2
  conversion environment are independently reviewed. Both local model bundles were
  materialized. The final 72-sample generated Mandarin gate selected `base` with 24/24
  wake, 0/48 false wakes, 24/24 typed slots and p95 2,196 ms; `small` failed closed.
  Fresh focused evidence is 114 passed and the full Python suite is 1,024 passed. This
  synthetic result does not prove household adult accuracy; no production Voice Care
  worker is enabled. Task 6 is complete at `84e9a17`: the exact Baby Care M5 schema and
  combined golden corpus are vendored from `bb1337226c1948695159d14199c9bb73cdaf115a`,
  strict canonical envelope validation and a closed feeding grammar now pass 19 focused
  and 103 adjacent tests, and Baby Care's read-only cross-repository verifier returns
  `CONTRACT_OK`. Task 7's software boundary is complete at `e850b8d`: a ctypes-only
  Security.framework adapter keeps secrets out of argv, encrypted profiles use a
  Keychain-protected AES-GCM key and canonical mode-0600 storage, and verification has
  only verified/uncertain/mismatch/not-enrolled outcomes. Fresh evidence is 18 focused,
  121 adjacent and 1,061 full Python tests. Voice Care remains disabled; converted
  ECAPA runtime installation, real adult enrollment/accuracy and real Keychain mutation
  remain later gates. Task 9 is complete at `b8f0002`: Ed25519 intent/pairing signing,
  strict semantic response parsing and a restart-safe AES-GCM SQLite outbox pass 27
  focused, 108 adjacent and 1,088 full Python tests. The shared signing vector also
  passes 53 Baby Care contract tests at `9b4f150`. No real endpoint, Keychain mutation,
  household audio or Baby Care write was used. Task 10's software boundary is committed
  at `31e8332`: fixed stdin-only TTS, capture ducking/guard, the in-memory closed command
  pipeline, bounded status and an independent launchd job pass 140 Voice, 73 frontend,
  133 Guardian-focused and 1,106 full Python tests. The isolated worktree installed gate
  remains 13 PASS / 6 FAIL only because its `.local`/private runtime/launchd/model assets
  are absent; it must be rerun after deployment to the actual i9 checkout. Task 11
  cross-repository synthetic Gate V1 is the next automatic slice.
- Remote private viewing and the 72-hour release gate remain unfinished.
- This system does not detect breathing, heart rate, suffocation or medical emergencies.

## Next Priorities

1. Continue WS2021 Task 15 with daylight positions 2–5, then night/IR collection and
   pinned i9-local training/OpenVINO export. Resume E2–E5 with 30 daylight comparisons,
   fail-closed scene checks, M2/Ollama isolation and 24-hour stability. E1 and the
   native-resolution continuous frame source are complete.
2. Defer normal-care-only real-Baby Guardian observation until a Baby is available; the
   three-browser HD gate is already user-confirmed PASS.
3. Complete the supervised, normal-care-only real-Baby Guardian observation gate;
   never stage a hazardous pose or persist household media/model prose.
4. Continue the approved audio/cry plan at Stage A8; a production model and
   license are still required before enablement; household audio remains
   memory-only.
5. Continue Voice Care Gate V1 Task 11 cross-repository synthetic closed loop. Baby
   Local Task 10 software is committed, while its installed `alpha-guardian-test` must
   be rerun after exact-head deployment to the actual i9 checkout. Keep Voice Care
   disabled; ECAPA installation and household adult accuracy remain installed/human
   gates.
6. Complete authenticated private remote access using Tailscale Serve/ACL only.
7. Complete the final 72-hour release gate before any release/tag decision.
8. Define per-parent acknowledgement and false-positive feedback only through a future
   contract where Baby Care consumes Guardian's read-only feed and owns identity/write
   state; do not create a second identity model inside Guardian.
9. Consider the FFmpeg ring-buffer upgrade after the functional and real-device gates.

## Operating Commands

Primary guardian entry points:

```bash
make alpha-guardian-start
make alpha-guardian-test
make alpha-guardian-test-live
make alpha-guardian-scene-test
```

Common service operations:

```bash
make alpha-status
make alpha-visual-status
make alpha-logs
make alpha-stop
```

Visual performance operations:

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
6. Continue the private WS2021 calibration and independent 24-hour environment gate;
   do not restart completed Guardian milestones.
7. Use focused tests for the slice and the full gate only at the next milestone or
   stable-branch integration.
8. Do not push, create a PR, merge, tag or modify `main` without explicit approval.
