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
- Realtime visual scheduling: the i9 production gate failed with 60/60 samples at
  1 FPS while the same worker run in the foreground reached 5 FPS within the 180 ms
  P95 budget. The visual launchd template now uses `Interactive`, and a dedicated
  update command validates, backs up, atomically replaces, verifies, and rolls back
  only `com.babymonitor.visual`. The i9 installed job still requires the short
  post-update observation and full 10-minute performance gate.
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
  event/evidence data. It still must be run on the installed i9 to establish real
  camera and launchd readiness.
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
- Next Guardian slice: complete household synthetic-scene validation, then the
  deferred launchd scheduling/performance acceptance.
  Per-parent acknowledgement and actor-bound false-positive feedback are deferred to a
  future contract where Baby Care consumes Guardian's read-only feed and owns
  identity/write state, so Guardian does not invent a second family identity model. The
  i9 launchd update, 3-minute
  observation and 10-minute performance
  sampler are intentionally deferred and do not block this feature sequence.
  The i9 environment calibration and 24-hour gate remain independent and unfinished.

## Pull request checkpoint

- Draft PR #4 was last verified open and unmerged on 2026-08-05.
- At that design gate, the GitHub PR head was `e010605` while the local environment
  work was based on `00ec882` and subsequent local commits. No fetch, push, merge or
  `main` modification was performed as part of the environment implementation.
- The current environment could not authenticate GitHub CLI to refresh PR metadata;
  no push, merge, or `main` modification was attempted during this delivery refresh.

## Not yet in the usable Alpha

- Installed i9-to-M2 SSH bridge, private bed-zone configuration, and end-to-end
  household validation of face-obstruction, prone-position, bed-exit, or
  adult-intervention candidates.
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
