# Project Status

## Current phase

- Repository: initialized and public.
- Design: approved.
- Environment monitoring design and implementation plan: approved on 2026-08-05.
- Stable Xiaomi Alpha commit: `0df20ae` on `stable/xiaomi-alpha`.
- Active local development branch: `codex/voice-care-v1-gate-v1`.
- 2026-08-20 go2rtc lifecycle correction: the installed macOS path now has one
  user-level launchd owner. `alpha-start` bootstraps a missing job, kickstarts only a
  loaded unhealthy job, never falls back to a second direct process, and verifies the
  exact launchd PID owns the loopback API listener. `alpha-stop` unloads that job and
  never selects a process by port or legacy PID file. Two consecutive installed starts
  retained one PID and one process. `alpha-go2rtc-restart` restarts only go2rtc.
  The remaining UDP timeout was traced to an unstable macOS Local Network code
  identity: default ad-hoc signing used a designated requirement based on the changing
  code hash. go2rtc now runs from a fixed app bundle whose explicit designated
  requirement is the stable bundle identifier. After LaunchServices registration,
  both a launchd-only restart and an unchanged app refresh passed `alpha-source-check`
  with `cs2+udp`, H.265, native `2560x1440`, live `1280x720` and positive bytes.
  Visual returned to 5 FPS; gauge and Dashboard remained healthy. A deliberately rapid
  back-to-back consumer teardown can still produce one transient camera-session miss;
  the normal persistent-worker path and bounded single-component restart are green.
- WS2021 current localization path: fixed lower-right schema-v2 ROI with bounded
  consecutive-frame stabilization; the trained OpenVINO detector remains fallback
  only when fixed-ROI mode is not selected. Same-aspect resolution scaling is accepted;
  invalid geometry and aspect-ratio drift fail closed.
- 2026-08-18 live check: five-frame source burst produced three stable fixed-ROI
  observations, but the dual-face needle reader initially returned `calibration_invalid`.
  Task 5 adaptive geometry is implemented (`c001507`), calibrated-center pointer fallback
  is implemented (`ecf8aa8`), and day temperature now uses grayscale needle evidence when
  red is weak (`8b27da1`). The full gauge suite is 81 passed. The latest live five-frame
  read is available at approximately 29.3C / 59.5%RH with confidence exactly 0.75. This
  is a live smoke result, not E2 accuracy evidence.
- Layered diagnostic: perspective rectification and both face ROIs succeed, but no
  humidity circle candidate is within the approved bounds and the nearest temperature
  center is ~0.393R away (limit 0.25R). Treat the current calibration as stale and
  require a new schema-v2 geometry calibration; do not widen the limits.
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
  metrics, and the realtime model available. Ollama bridge health requires loopback
  HTTP 200; launchd `running` alone is insufficient. A recent M2→i9 login did not
  establish the configured i9→M2 `-L` forward (`http=000`); the stale listener was
  stopped and E4 controlled recovery remains pending.
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
  contract tests pass. Later A2–A7 slices below add the decoder, classifier boundary,
  state machine and disabled-by-default worker; household accuracy and production model
  approval remain unaccepted, and an unavailable source track must fail closed.
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

- Voice Care cross-product scope is split from current audio/cry work:
  `docs/superpowers/plans/2026-08-19-voice-care-v1.md` records completed Gate V0 and the
  approved Gate V1 implementation sequence. Gate V0 completed on 2026-08-20: source
  HEVC+Opus and alias Opus were confirmed, actual 60-second and 10-minute
  receive/discard windows passed, synthetic Opus compatibility passed, and
  cleanup/isolation checks left visual, gauge and watchdog PIDs unchanged. Gate V1
  Baby Local Task 1 is software-complete and independently reviewed: strict disabled-
  by-default settings, a closed four-artifact registry, canonical source/runtime
  manifests, fixed ignored runtime paths and atomic local install/conversion boundaries
  now exist. Whisper conversion consumes only pinned manifest-validated local
  Transformers bundles and validates the faster-whisper layout. Fresh focused evidence
  is 61 passed. No model was downloaded or enabled; real source-manifest recording and
  i9 conversion remain operator gates. Task 2 is now also complete and reviewed: the
  VAD boundary maps malformed/model output to a stable unavailable result, and the
  collector enforces exact 500 ms pre-roll, 800 ms terminal silence and 8-second limits
  in bounded bytearrays. Reset, close, validation failure and terminal return have
  non-vacuous overwrite-before-clear tests. Fresh evidence is 23 passed. Task 3's
  software slice and installed-i9 gate are complete and independently reviewed:
  local-only base/small ASR, exact wake matching, closed benchmark-only typed slots,
  aggregate-only reports and a fail-closed isolated converter now exist. Both pinned
  model bundles were materialized. The 72-sample generated Mandarin gate selected
  `base`: 24/24 wake, 0/48 false wakes, 24/24 typed slots and p95 2,196 ms. `small`
  failed closed with one false wake and p95 5,772 ms. Fresh focused evidence is 114
  passed and the full Python suite is 1,024 passed. SpeechBrain execution, household
  adult accuracy, the production worker and Baby Care intent delivery remain later
  gates.
- Voice Care Task 6 is complete at `84e9a17`. Baby Local vendors the exact schema and
  combined valid/invalid corpus from Baby Care commit
  `bb1337226c1948695159d14199c9bb73cdaf115a`, verifies fixed SHA-256 values, rejects
  noncanonical/private envelope content and maps only a closed feeding grammar into
  typed payloads. Fresh evidence is 19 focused and 103 adjacent tests; Baby Care's
  read-only verifier returns `CONTRACT_OK`. No speaker profile, household audio,
  signed delivery, production worker or Baby Care write is enabled. Task 7 status follows.
- Voice Care Task 7's local software boundary is complete at `e850b8d`. It provides a
  Security.framework generic-password adapter with no secret argv, a Keychain-backed
  AES-GCM profile store with canonical 0600 files, bounded adult-only enrollment and the
  four closed identity states. Fresh evidence is 18 focused, 121 adjacent and 1,061
  full Python tests. A real Keychain write/delete was deliberately not performed by the
  software gate; converted ECAPA installation, adult enrollment and household accuracy
  remain pending while Voice Care stays disabled.
- Voice Care Task 9 is complete at `b8f0002`. A Keychain-backed Ed25519 identity signs
  the exact canonical Baby Care envelope and one-time pairing challenge; the strict
  client exposes only closed semantic responses. A bounded mode-0600 SQLite outbox
  encrypts signed intent bytes with a separate Keychain-backed AES-GCM key, preserves
  request-ID idempotency across restart, retries only while fresh and converts expired
  ambiguity to reconciliation. Fresh evidence is 27 focused, 108 adjacent and 1,088
  full Python tests; the matching Baby Care vector passes 53 contract tests at
  `9b4f150`. No production endpoint or care write was exercised in that slice.
- Voice Care Task 10's software boundary is committed at `31e8332`. It adds only one
  separately supervised interactive Voice job, fixed semantic TTS through stdin,
  bounded playback/cancellation/ducking, a transcript-free in-memory command pipeline
  and redacted status. Fresh evidence is 140 Voice, 73 frontend, 133 Guardian-focused
  and 1,106 full Python tests. The isolated worktree's installed Guardian gate was not
  accepted: 13 checks passed and 6 installation/realtime checks failed because private
  runtime and installed assets were deliberately absent there. The published final head
  `614ea69` is now deployed to the actual Intel i9; `make alpha-guardian-test` passes
  19/19. Voice launchd is installed and cleanly stopped as `voice_disabled`; no household
  audio, enrollment or care write was exercised.
- Voice Care Task 11 local synthetic Gate V1 is complete at Baby Local `e4cd5d5` and
  Baby Care `bca9b9e`. Generated PCM reaches VAD, exact wake, ASR result, explicit adult
  claim, synthetic speaker state, canonical Ed25519 signing and the encrypted outbox;
  outage retry sends identical signed bytes and persists no transcript/audio. The Baby
  Care side uses an authenticated Dad takeover and real disposable PostgreSQL 16 to
  commit/read back bottle and direct feeding, idempotently replay confirmation, correct
  through the existing revision route, and fail closed for cancel, identity mismatch
  and injected commit failure. Full local evidence is 1,108 Python plus 73 frontend
  passed; Baby Care is 458 passed / 115 opt-in skipped plus real PostgreSQL 2/2. This is
  synthetic software evidence only. Exact-head CI passed at Baby Local `c554334` / run
  `32680519119` and Baby Care `53e69d4` / run `32680603091`; final documentation heads
  also pass runs `32680892081` and `32680891893`. Installed i9 readiness is complete;
  ECAPA installation and supervised two-adult Gate V2 remain open.
- Voice Care Gate V2 ECAPA runtime validation is complete locally. The Intel i9 uses a
  separate pinned speaker environment, manifest-validated immutable artifact and one
  bounded persistent offline embedding child. The current generated-only gate passed
  5/5 finite L2-normalized 192-dimensional embeddings at p50 284 ms / p95 311 ms and
  reported `raw_audio_persisted=false`. Fresh software evidence is 1,156 Python and 73
  frontend tests; the production deployment checkout remains Guardian 19/19. This is
  runtime/shape/latency evidence only: Voice is still disabled and Dad/Mom accuracy,
  replay/overlap rejection, private enrollment, Baby Care pairing and production writes
  remain pending. The implementation is published through `7dd0155`; exact-head CI run
  `32699249559` passed all Python, frontend, schema, compile, shell and go2rtc jobs.
- Voice Care Gate V2 is blocked at the installed-i9 ASR/VAD accuracy gate before
  enrollment. Six fixed prompted clips are present only in the ignored encrypted corpus.
  A signed stable Keychain helper copied the same legacy key bytes to helper-owned v2;
  two real user-launchd reads passed without exposing the key. The one-shot base/small
  matrix exhausted all four approved global decode profiles. No candidate passed: base
  `care_hotwords` and beam10 were best at 5/6 exact, 6/6 wake and P95 2,246/2,145 ms;
  small failed accuracy and latency. Official Silero passed the generated control and
  five private prompts, while `negative_weather` produced two spans. Gain correctly did
  not run because private RMS was not 12 dB below control. Current stable blockers are
  `asr_candidate_unavailable` and `vad_candidate_unavailable`; Voice stays disabled.
  Local commits are `de499b7`, `f61e2ed` and `305232f`; that baseline's Voice tests were
  233 passed.
- The approved Paraformer amendment is software-complete at `4677fec`. Its fixed public
  artifact and complete hash-locked five-distribution x86_64 environment install through
  a clean staging venv and atomic macOS publication. The isolated runner uses a single
  deadline for nonblocking PCM write and response read, verifies model files into a
  child-private snapshot and settles the process on failure. Exact-head user-launchd
  acceptance evaluated all six encrypted clips at p50 509 ms / p95 529 ms, but only 5/6
  were exact and 1/6 satisfied the unchanged wake boundary; the sole exact mismatch was
  public ID `negative_weather` with edit distance 2. Result:
  `asr_candidate_unavailable`; Voice remains disabled. Fresh Voice tests are 250/250,
  full Python is 1,302/1,302, and independent review found no Critical/Important issue.
- Task 5F implementation `6e933a6` adds the approved source-controlled
  punctuation-free boundary without fuzzy wake matching or transcript rewriting. The
  fixed care-vocabulary prefix is only a
  lexical boundary; repeated/unknown/incidental continuations fail closed and the
  existing typed parser still decides the full command. Fresh exact-head user-launchd
  evidence is 5/6 exact, 6/6 wake, p50 506 ms and p95 540 ms. `negative_weather`
  remains the only exact mismatch at edit distance 2 and still yields two Silero spans. Voice remains
  disabled; fresh software evidence is Voice 267/267 and full Python 1,319/1,319.
- Task 5D installed non-interactive preflight is complete at `41da786`. Its fixed
  disabled-mode login-LaunchAgent path reads only the Voice helper and validates the
  fixed Paraformer and Silero artifacts; it does not decode audio or run inference.
  After explicitly approved recovery removed one stale legacy pending request through
  `aacefd9`, the installed command passed with Keychain and both artifacts available.
  A later clean `negative_weather` rerecord closed Task 5 without changing thresholds:
  Paraformer passed 6/6 exact and 6/6 wake at p50 587 ms / p95 661 ms, while Silero
  passed all six prompts with exactly one span each. Installed source/speaker/ECAPA
  preconditions also pass; the generated ECAPA gate is 5/5, 192 dimensions, p95 433 ms.
  Dad enrollment remains unopened because the PTY/chat workflow started five-second
  captures before the remote operator could reliably see and speak the challenge. A
  transcript-free real diagnostic reported edit distance 17, length delta +6 and no
  wake/challenge/digit match, proving the wrong time window rather than a near miss.
  Sandbox PTY audio also fails independently as `operation_not_permitted`; only logged-in
  i9 execution counts as real audio evidence. Voice remains disabled and no profile was
  created. The next slice is a local bounded readiness/countdown gate, not another blind
  enrollment attempt.
- The separately approved continuous listen-only mode is accepted locally through
  `4590489`. It composes the fixed Xiaomi audio alias, bounded in-memory PCM pump,
  stateful Silero VAD, local Paraformer, exact `小小` wake controller, an eight-second
  one-follow-up dialogue window and fixed i9-speaker TTS. It constructs no Baby Care
  client, signer, outbox, family identity or care-write path and does not persist raw
  audio or ordinary transcripts. A real repeated-utterance trial exposed that one
  terminated Paraformer child left the long-running worker permanently unavailable;
  `ce6dfb6` now performs one bounded local rebuild and retries the same memory-only PCM
  once, while invalid PCM and a second failure remain closed. The real recovery path
  replaced the child without replacing the Voice worker. `3e9673d` also requires
  readiness status to be written after the current Voice start rather than accepting a
  recently healthy stale file; `15a2ff8` tightens that boundary to microseconds.
  `07eef64` keeps the protocol alive after a bounded empty no-match, and `4590489`
  resumes capture immediately after listen-only playback so the follow-up prefix is not
  clipped while full-care retains its 0.5-second guard. Fresh focused evidence is
  325/325 Voice tests plus
  Python compile, shell syntax, plist lint, Make dry-run and diff checks. On the actual
  i9, the Voice-only launchd job reports `healthy / listen_only_idle`, owns its FFmpeg
  audio child, and the Xiaomi source remains PASS. Supervised household acoustic
  acceptance passed at least 5 standalone wakes, 3 dialogues, 3 timeouts, 5 negatives
  and no self-trigger. The operator confirmed both replies were audible. Exact count
  deltas matched the spoken trials, the Voice/model/audio PIDs remained stable through
  the final matrix, source health stayed PASS and the recent raw-audio file count was
  zero. This proves only the supervised room trial, not arbitrary speakers, noise or
  unattended-care safety.
- P4 authenticated private remote access is software-complete through `a265312`, with
  a repository Guardian fixture synchronization at `5dca783`. The pure bounded parser,
  read-only macOS audit, exact-confirmation fixed Serve adapter, four Make interfaces,
  minimum synthetic `tcp:443` grant and private-access runbook are implemented. Fresh
  gates are P4 95 passed/1 sandbox-only socket skip, adjacent API 123 passed, frontend
  73 passed and full Python 1,514 passed; compilation, shell, Make, diff and reviewed
  privacy scans passed. No real Tailscale software was installed or authenticated, no
  policy or Serve state was changed and no phone gate was run. Dashboard-health
  recovery, private grant merge, fixed Serve apply and two-iPhone cellular acceptance
  remain pending and are explicitly deferred by the user to the final optional stage.
- Voice Gate V3 camera-reply software Tasks 1–7 are implemented through `e358aaf`,
  with the real macOS TTY correction at `5768894`. The supervised generated-tone gate
  passed, but V3E failed closed during the first interaction batch: the operator saw a
  stuck interaction and unexpected camera movement, while bounded runtime evidence
  recorded four reply completions followed by a CS2 UDP timeout and Voice audio EOF.
  The private camera-reply flag is back to `false`, the current marker is not accepted,
  the Voice worker is healthy on the prior i9-speaker path, and source health is PASS.
  Camera Reply is not a delivered capability and must not be re-enabled without a new
  approved design that resolves backchannel lifecycle/reconnect safety.
- Installed-i9 audio-source discovery now verifies that the Xiaomi source exposes HEVC
  video plus Opus audio and that the fixed loopback `audio_analysis` alias exposes only
  Opus. The real input is supported 48 kHz stereo Opus; the fixed FFmpeg boundary
  normalizes it to mono 16 kHz PCM. The 600-second gate decoded 19,200,000 bytes with
  output discarded and no residual consumer. No household audio was persisted. The
  camera still requires the existing interactive-user macOS local-network context;
  A8 model/license and household accuracy remain unaccepted.
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
- The WS2021 CPU bootstrap no longer inherits YOLOX's zero warmup learning rate and
  snapshots cloned best weights instead of shared live storage. Positive augmentation
  now uses deterministic nonuniform generated backgrounds and the training set includes
  fixed project-generated negatives. The corrected 20-epoch bootstrap, OpenVINO export
  and digest check pass; this remains a collection seed until a live localization and
  the multi-position/night gates pass.
- Fresh live inference now produces three NMS candidates above the unchanged 0.75
  threshold instead of no candidate, but every box is out of bounds and none passes
  the approved outer-quadrilateral/two-circle geometry. Candidate layout validation
  now runs before ambiguity resolution and still fails closed. A subsequent calibrated
  collection attempt rejected all 11 frames at the privacy gate and persisted zero
  crops; no privacy rule was bypassed.
- After Task 15, resume environment-plan E2–E5 with 30 daylight comparisons,
  darkness/infrared/glare/occlusion/gauge-movement fail-closed checks, M2/Ollama outage
  isolation and the independent 24-hour run.
- 2026-08-17 fixed-ROI software slice: fixed lower-right schema-v2 localization and
  bounded frame stabilization are integrated; 95 gauge/environment tests, model
  artifact check and live source check passed. This does not prove real-device reads,
  30 daylight comparisons, night/IR/occlusion/movement gates or 24-hour stability.
- Ordered later stages retain normal-care-only real-Baby Guardian observation,
  separately approved audio/cry work and the final 72-hour local release gate. Private
  Tailscale access is deferred until last and is not a current prerequisite. Voice Gate
  V3 failed closed and remains disabled; the accepted i9 speaker remains production
  output. `docs/NEXT.md` owns the detailed prerequisites, Codex/human boundary,
  acceptance and handoff for each stage.
