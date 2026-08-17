# Project Status

## Current phase

- Repository: initialized and public.
- Design: approved.
- Environment monitoring design and implementation plan: approved on 2026-08-05.
- Stable Xiaomi Alpha commit: `0df20ae` on `stable/xiaomi-alpha`.
- Active local development branch: `codex/guardian-live-acceptance`.
- Xiaomi-first delivery scope: fixed to MJSXJ17CM for the first usable release;
  the proposed UVC USB source remains deferred behind the existing frame-source
  adapter boundary.
- Usable Alpha: password-protected Dashboard, 720p MJPEG preview, on-demand native
  or VideoToolbox 1440p HD view, snapshot, safe HD rollback, ntfy test delivery,
  and Xiaomi subtype probe/apply are implemented.
- Environment implementation: contracts, schema v2 Dashboard calibration, controlled
  frame bursts, day/night reader, independent worker, SQLite history, deterministic
  incidents, redacted ntfy payloads and authenticated Dashboard are implemented.
- Visual risk R1 core: strict schema-v1 model observations, independent face-obstruction,
  prone-position and out-of-bed tracks, two-review/10-second confirmation and recovery,
  low-confidence downgrade, adult-intervention audit, deduplication and restart snapshots
  are implemented as pure deterministic code.
- Visual frame R2a: explicit normalized bed/privacy polygons, 15%-expanded bed crop,
  privacy masking before resize/encode, fixed 960×540 quality-80 JPEG output, and a
  40-second/21-frame in-memory ring are implemented with generated-image tests.
- Visual capture R2b: the fixed private `analysis` profile, one continuous loopback
  MJPEG consumer, two-second privacy-safe sampling, conservative 60-second
  disconnect/freeze evidence with reconnect confirmation, bounded reconnect backoff,
  and ten-second single-flight review scheduling are implemented as local components.
- Visual runtime R3 software: strict disabled-by-default settings, the fixed
  `qwen3-vl:8b-instruct-q4_K_M` loopback-only Ollama client, four-frame/4 MiB
  request bounds, proxy-free 20-second calls, strict schema parsing, deterministic
  three-failure/60-second degradation and two-success recovery, real worker
  composition, and independent visual/tunnel launchd units are implemented locally.
- Realtime visual R3.5 software: an opt-in `analysis_realtime` 960×540/5 FPS path,
  privacy-safe OpenCV analysis, pinned YuNet/OpenVINO model verification, deterministic
  watch-only candidate tracks, 5/3/1 FPS load degradation, independent two-second Qwen
  ring sampling, and immediate urgent review scheduling are implemented locally.
  Missing models preserve motion, scene health and regular Qwen review while semantic
  tracks remain unavailable; the fast path cannot open or recover a risk alert.
- Realtime visual scheduling: the earlier i9 production gate exposed launchd
  `Background` scheduling at 1 FPS. The visual job now uses `Interactive`, and the
  installed i9 subsequently passed the full 10-minute gate at 5 FPS for all 60
  samples. The dedicated update command remains rollback-safe and changes only
  `com.babymonitor.visual`.
- Visual frame-health alerts: the restart-safe SQLite incident pipeline and
  privacy-safe ntfy delivery are deployed on the Intel i9. A fresh controlled
  `source_offline` event delivered one open alert, recovered after the fixed
  changing-frame window, delivered one recovery alert, and persisted both delivery
  markers. The outage window also contained five gauge records; the gauge,
  environment-watchdog, and visual launchd units stayed in their first run without
  exiting, real-time metrics remained available, and the Alpha health endpoint was
  healthy after recovery without a full-stack restart.
- Baby guardian R4 event core: deterministic alert/recovery transitions now have
  idempotent SQLite lifecycle records, stable event IDs, restart restoration,
  standalone/adjoined adult-intervention audit records, and privacy-safe JSON-line
  diagnostics. Persistence and log failures are isolated from the visual worker.
  Parent acknowledgement and false-positive feedback remain later R4 slices.
- Baby guardian R4 safe evidence: each newly created risk event now receives an
  immediate privacy-processed JPEG snapshot and a bounded pre-10/post-30-second
  animated WebP assembled only from the existing safe-frame ring. Evidence files use
  digest-only directories, private modes and atomic replacement; SQLite records
  collecting/ready/failed/interrupted status. Restart, shutdown, media, database and
  log failures cannot fabricate a ready clip or stop the visual worker.
- Baby guardian R4 risk notification: risk open, linked adult intervention and
  recovery now use a persistent idempotent SQLite outbox and a bounded off-thread
  ntfy dispatcher. Payloads are text-only and exclude media, local paths, private
  addresses, credentials, model text and unauthenticated links. Two-phone physical
  delivery was confirmed on two iPhones during the 2026-08-15 supervised i9 acceptance.
- Baby guardian option A operations: `make alpha-guardian-start` performs the existing
  idempotent Alpha startup followed by bounded readiness checks, and
  `make alpha-guardian-test` runs repository, software, installation, service, media
  and isolated guardian gates with fixed redacted PASS/FAIL output. The automatic
  command never sends a real ntfy test, synthesizes a risk, or writes production
  event/evidence data. The later supervised installed-i9 acceptance established
  readiness for its recorded run; future releases must rerun the automatic gate as
  fresh evidence rather than treating that checkpoint as permanent health.
- Baby guardian live acceptance: the separate `make alpha-guardian-test-live` command
  requires a controlling terminal, confirms that no real infant is present and that an
  adult is supervising, checks Guardian readiness, sends at most one clearly labeled
  text-only non-risk notification, and then confirms phone A, phone B, authenticated
  live view and the event list. Its hook-only test mode never reads production runtime
  configuration and ends in `SIMULATED`, never PASS. Physical execution passed on the
  installed Intel i9 on 2026-08-15: one non-risk message reached both iPhones, and the
  authenticated live view plus Guardian event list were visible.
- Baby guardian authenticated event Dashboard: a standalone read-only query service
  opens the existing SQLite database in query-only mode, joins event/evidence state and
  returns a strict media-free projection. The authenticated Dashboard loads the newest
  20 events immediately, pins unresolved events within that set, highlights them and
  refreshes every 15 seconds. Refresh failure retains the old list and shows a stale
  warning; no screenshot, clip, evidence key or media route was added.
- Baby guardian evidence retention: the visual runtime now starts an independent daily
  cleanup worker using centralized age/quota settings. Recovered terminal evidence is
  removed age-first and then oldest-first for quota, while open events, collecting
  evidence, notification-pending events and records without a terminal recovery notice
  remain protected. Exact eligibility and file deletion share one SQLite writer lock;
  descriptor-anchored `O_NOFOLLOW` traversal prevents symlink ancestors from redirecting
  deletion. Only controlled media and the evidence row are removed; event/audit history
  remains. Unsafe filesystem entries, database failures and scheduler failures fail
  closed with aggregate redacted logs.
- Fresh R3 software gate on 2026-08-06: 451 Python tests and 70 Node browser tests
  passed; Python compilation, shell syntax, `git diff --check`, tracked runtime/media
  boundaries, GitHub-token candidates and private-key markers passed. This remains a
  software-only result and does not represent real-camera or M2 accuracy.
- Fresh R3.5 software gate on 2026-08-07: 510 Python tests and 70 Node browser
  tests passed; Python compilation, shell syntax, schema parsing and
  `git diff --check` passed. The OpenPose output now uses PAF-connected person
  grouping rather than heatmap-peak counting; model/load health transitions,
  every-frame source health checks and blurred-camera watches have regression
  coverage. This remains synthetic software evidence, not an i9 household gate.
- Fresh Guardian retention software gate on 2026-08-13: 714 Python tests and 73 Node
  browser tests passed; Python compilation, tracked shell syntax, Make dry-runs,
  `git diff --check` and repository artifact/sensitive-literal scans passed. This is
  synthetic software evidence and does not establish installed-i9 storage behavior.
- Fresh Guardian live-acceptance software gate on 2026-08-14: 739 Python tests and
  73 Node browser tests passed; Python compilation, all tracked shell syntax/ASCII/LF,
  three Guardian Make dry-runs, `git diff --check`, and repository
  artifact/sensitive-literal scans passed. Focused live coverage recorded 38 passed and
  the wider Guardian-focused gate recorded 126 passed. This does not prove installed
  i9 readiness, real camera behavior, Dashboard reachability or delivery to either
  phone.
- The remote dependency-closure follow-up used a clean temporary Python 3.11
  environment and passed 71 focused deployment/API tests, 741 full Python tests,
  73 Node tests, `pip check`, compilation, shell checks, Make dry-runs and
  `git diff --check`. It adds `httpx2` for current Starlette TestClient while
  preserving `httpx` compatibility and makes `alpha-install` include acceptance
  extras. This is software evidence, not a substitute for installed-i9 acceptance.
- Guardian launchd scheduling/performance acceptance completed on the installed Intel
  i9 on 2026-08-15. The 10-minute gate held 5 FPS for all 60 samples with processing
  p50 100.836 ms, p95 130.789 ms and max 201.529 ms; the model remained available.
  Redacted rate-limited stage telemetry attributed the sole over-180 ms sample to the
  semantic stage without recording frames, events, paths or configuration.
  The supervised `make alpha-guardian-scene-test` software workflow is implemented
  with fixed seven-scene/ten-trial input, private resumable local state and no
  notification or production event writes. Its installed-i9 physical run passed on
  2026-08-15 with 10 operator-confirmed correct trials for each scene and no recorded
  false-positive, missed or unavailable outcome. The next slice is the independent
  24-hour environment calibration/stability gate.
  Per-parent acknowledgement and actor-bound false-positive feedback are deferred to a
  future contract where Baby Care consumes Guardian's read-only feed and owns
  identity/write state, so Guardian does not invent a second family identity model. The
  i9 launchd update and 10-minute performance sampler are complete.
  The i9 environment calibration and 24-hour gate remain independent and unfinished.

## Pull request checkpoint

- Draft PR #4 was last verified open and unmerged on 2026-08-05.
- At that design gate, the GitHub PR head was `e010605` while the local environment
  work was based on `00ec882` and subsequent local commits. No fetch, push, merge or
  `main` modification was performed as part of the environment implementation.
- The current environment could not authenticate GitHub CLI to refresh PR metadata;
  no push, merge, or `main` modification was attempted during this delivery refresh.

## Not yet in the usable Alpha

- Private bed-zone acceptance and real Baby validation of face-obstruction,
  prone-position, bed-exit and adult-intervention candidates. The installed
  i9-to-M2 bridge and supervised synthetic household-scene gate have passed.
- Authenticated parent feedback through the future Baby Care identity integration, the
  later FFmpeg clip upgrade, and cry/audio candidate detection. Guardian risk
  lifecycle persistence and safe-frame evidence export are complete locally;
  risk text ntfy and safe-frame evidence export are complete locally; deterministic
  source-health ntfy is already deployed and independently verified.
- Verified Tailscale external access, real PTZ control, or the 72-hour release gate.

## Safety gates

- No household images, baby footage, credentials, device keys, tokens, or private network details may enter this public repository.
- `main` contains reviewed documentation and stable code only.
- All implementation work proceeds through feature branches and pull requests.
- Environment monitoring is read-only: no actuator API or automatic device control.
- Visual model output is observation evidence only; the deterministic i9 state machine
  owns decisions, and every result remains an auxiliary candidate rather than medical
  or unattended-care assurance.

## Latest i9 operational status — 2026-08-15

- go2rtc startup now rejects a live-but-unhealthy PID, verifies the exact full command,
  and binds API acceptance to listener ownership by that same validated PID.
- Fresh software verification recorded 772 Python tests passed with one existing
  Starlette/httpx deprecation warning.
- The authoritative `kandysmith` runtime check reported the Xiaomi `cs2+udp` H.265
  source and Dashboard live stream healthy, the visual worker at 5 FPS with current
  metrics, the realtime model available, and the Ollama tunnel/bridge healthy.
- Runtime checks from `chatgpt-agent` are not authoritative for services in the
  `kandysmith` GUI domain. Launch future operational Codex sessions directly from the
  `kandysmith` SSH login; do not grant broad disk or sudo access.
- Environment E1 passed on 2026-08-16: the installed i9 saved a valid schema-v2
  calibration and valid reference JPEG with private file modes. No calibration ID,
  coordinates, image, path or household reading entered this checkpoint.
- The fixed native-resolution `gauge` MJPEG profile now supplies one continuous
  2560×1440 five-frame burst. The former `frame_source_unavailable` blocker is closed;
  a rectification correction now preserves the calibrated gauge-plane aspect ratio and
  supplies bounded search padding. Both ROI geometry gates and the temperature circle
  match pass; humidity remains fail-closed as `calibration_invalid`, so no E2 accuracy
  sample has been counted.
- Approved Task 15 now places i9-local WS2021 automatic localization before E2. Its
  strict single-candidate/fail-closed locator, fixed 640×640 preprocessing and validated
  schema-v2 geometry relocation contracts are implemented. Crop collection now passes
  only the bounded crop to private atomic persistence, rejects privacy overlap/backend
  failure, duplicates and poor quality, and exposes aggregate counts only. Dataset
  preparation now splits deterministically before train-only bounded augmentation,
  emits fixed 640×640 private files with relative labels, and requires licensed HTTPS
  metadata for negatives. The ignored Intel training environment now pins Torch 2.2.2
  and exact YOLOX commit `419778480ab6ec0590e5d3831b3afb3b46ab2aa3`; a synthetic
  640×640 CPU forward/loss/backward step passes. Model-independent worker integration
  now locates once per burst, validates the
  outer quadrilateral/two-circle layout and applies one migrated schema-v2 geometry to
  all five frames. Failure never reuses an old position. No detector weights or
  household images are tracked.
- Audio/cry software work has a separately approved current design with household PCM
  limited to bounded memory and no audio persistence. Stage A1 adds closed observation
  and failure contracts plus fixed mono 16 kHz, 15-second-buffer settings; focused
  contract tests pass. No decoder, classifier, worker or real-device audio acceptance
  is claimed yet, and an unavailable source track must fail closed.
- Audio Stage A2 adds a fixed loopback-only FFmpeg audio command with a bounded read
  timeout, closed source/stale/decoder failures and a frame-aligned 15-second in-memory
  PCM ring. EOF, process failure and malformed partial samples cannot produce an audio
  observation. No audio file or persistence interface exists.
- Audio Stage A3 adds deterministic s16le RMS/dBFS extraction, a bounded adaptive
  noise floor and a centralized loudness margin. Only quiet windows update the
  baseline; accepted loud windows cannot contaminate it. Before a pinned classifier,
  the output is limited to `quiet` or `sound`, never `cry_candidate`.
- Audio Stage A4 validates a relative in-project ONNX path and pinned SHA-256 before
  runtime creation, rejects symlink escape, accepts only a fixed one-second mono
  waveform and a finite `(1, 1)` probability, and maps missing, malformed or failing
  models to closed unavailable reasons. Tests use a fake runner and synthetic bytes;
  no production model, license or household accuracy is approved by this result.
- Installed-i9 audio-source discovery now verifies that the Xiaomi source exposes HEVC
  video plus Opus audio and that the fixed loopback `audio_analysis` alias exposes only
  Opus. A bounded two-second decode to mono 16 kHz PCM passed with output discarded;
  no household audio was persisted. The camera requires the existing automatic/UDP
  Xiaomi transport. In this macOS installation the source works from the interactive
  user session but timed out under launchd, so sustained service stability and A8
  household accuracy remain unaccepted.
- Audio Stage A5 adds a deterministic restart-safe state machine. Five continuous
  accepted cry seconds open a normal transition, ten escalate it to high, sustained
  available non-cry input recovers, and a repeat within 30 seconds becomes one merged
  high escalation. Unavailable input advances neither positive inference nor recovery;
  duplicate observations are idempotent and backwards/conflicting timestamps are
  rejected without changing state. Short candidate timing is deliberately not restored
  across restart.
- Audio Stage A6 maps only accepted state transitions into deterministic, idempotent
  `audio_cry_candidate` events and a causally ordered SQLite notification outbox in one
  transaction. Summaries and stages are closed constants; persisted metadata contains
  only the transition name, with no samples, paths, source details, model prose or
  media. The generic event-store schema is now version 4 and upgrades existing stores
  by adding the bounded audio notification queue.
- Audio Stage A7 composes the fixed decoder, loudness gate, pinned OpenVINO-backed ONNX
  classifier, state machine, atomic event sink and a mode-0600 bounded status file in
  an independent worker. It has its own launchd definition and Make status/software
  gates; an audio failure does not restart sibling services. Event persistence failure
  rolls state back and publishes only `internal_error`. The installed i9 launchd job
  was loaded with `audio.enabled=false`, exited 0 and remained stopped as designed;
  no household analysis, event or notification occurred.
- Installed-i9 Task 15.6b daylight position 1/5 completed with no baby present. The
  private store contains 60 paired crops/metadata records with 0700/0600 permissions,
  matching names, closed metadata fields and matching SHA-256 values. No media or
  sample identity entered Git or status output. The first full training run exposed an
  augmentation-scale mismatch (45%–80% instead of the approved roughly 10%–35% source
  width). The dataset builder is corrected, and a bounded 20-epoch collection seed was
  trained, exported and digest-checked locally. Position 2 still fails closed as
  `gauge_not_found`; its best predictions are not geometrically valid, while local
  feature/template and unconstrained shape searches are insufficiently reliable. One
  local position-2 bounding-box annotation is now required before collection continues.
- After Task 15, resume environment-plan E2–E5 with 30 daylight comparisons,
  darkness/infrared/glare/occlusion/gauge-movement fail-closed checks, M2/Ollama outage
  isolation and the independent 24-hour run.
- Ordered later stages are the three-browser HD gate, normal-care-only real-Baby
  Guardian observation, separately approved audio/cry work, authenticated private
  Tailscale access and the final 72-hour release gate. `docs/NEXT.md` owns the detailed
  prerequisites, Codex/human boundary, acceptance and handoff for each stage.
