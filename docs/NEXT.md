# Next Work

The repository baseline, environment software and functional Guardian loop are
complete. Do not restart completed milestones. Execute the following stages in order;
the detailed approved specs and plans remain authoritative for behavior.

**Operational recovery gate (2026-08-20): PASS.** The i9 now has one launchd-owned
go2rtc app with a stable macOS Local Network designated requirement. A fresh source
check and a later unchanged app refresh plus single-component restart both returned
`cs2+udp`, H.265, native/live dimensions and positive bytes. Visual returned to 5 FPS;
gauge and Dashboard remained healthy. Keep `make alpha-go2rtc-restart` as the bounded
recovery path; do not reintroduce direct fallback, change source parameters or accept
Dashboard health alone as proof of video.

## P0 — Environment real-device acceptance (current)

**Status:** E1 persistence passed on 2026-08-16. The fixed native frame source and
non-16:9 rectification prerequisites pass, but a fixed private ROI still leaves the
humidity face fail-closed. Approved Task 15 now inserts i9-local automatic WS2021
localization before E2; its strict locator/schema-v2 relocation contracts and
privacy-safe crop persistence, deterministic dataset preparation and pinned Intel CPU
training/export tooling and model-independent worker integration are complete. The
first human-confirmed no-baby calibrated collection completed with 60 valid private
pairs. A 20-epoch private collection seed was exported and verified at the corrected
deployment scale, but it fails closed as `gauge_not_found` at daylight position 2/5.
The fixed ROI now stabilizes on the live source. Task 5 adaptive in-memory geometry is
software-complete and its focused/full gauge gates pass, but the end-to-end reader still
returns `calibration_invalid` for all five frames: the persisted geometry is outside the
approved adaptive bounds (humidity has no bounded circle candidate; temperature's nearest
center is about 0.393R away). A calibrated-center pointer fallback plus grayscale day
temperature signal now produces an available five-frame smoke reading at the 0.75 gate.
The next mainline action is E3: run the darkness/infrared, glare, occlusion and gauge
movement fail-closed acceptance. The 30 daylight manual comparisons are deferred and do
not block E3/E4/E5; OCR remains deferred.

**Prerequisites:** Run from the `kandysmith` login that owns the installed i9 GUI and
launchd services. Keep calibration files, reference images, databases and runtime
metrics in ignored local storage.

**Stages:**

1. E1 — complete one private WS2021 schema-v2 Dashboard calibration. **PASS**
2. Task 15 — fixed lower-right ROI stabilization is software-complete; resolve the
   live dual-face/needle calibration gate before any OCR work. Household full frames
   must never persist.
3. E2 — obtain an available automatically localized production reading. The 30 daylight
   manual comparisons against ±1℃ and ±5%RH are deferred and do not block the mainline.
4. E3 — verify darkness/infrared, glare, occlusion and gauge movement fail closed.
   Software contract checks are green; the real-device scenarios remain outstanding and
   are intentionally deferred by the current execution order.
5. E4 — take M2/Ollama offline and confirm gauge, storage, state and notification
   independence. **PASS (user-confirmed real interruption/recovery).** During the
   controlled M2/Ollama tunnel interruption, bridge failure remained fail-closed while
   camera, gauge and i9 workers continued normally; after reconnect, i9 port 11435
   returned HTTP 200. Keep the direction-mismatch recovery note in the runbook and do
   not treat launchd `running` alone as bridge health.
6. E5 — run the gauge/watchdog path for 24 hours without scheduling backlog; complete
   the remaining state/notification, load-shedding and two-phone payload checks. Short
   preflight is green and E4 is complete. **PASS (user-confirmed):** the authoritative
   i9 window contains 1,414 readings across the full 24 hours; the largest observed
   interval was `82.105s`, with no accumulated scheduling backlog indicated. Keep the
   bounded interval as a follow-up observation, not as a fabricated 60-second guarantee.

**Codex can:** run bounded readiness checks, guide the approved workflow, validate
closed outputs, diagnose recoverable failures and update redacted documentation.

**Human required:** provide one local bounding-box annotation at position 2, operate the
authenticated Dashboard, position/read the physical gauge, provide reference comparisons,
supervise scene changes and keep the i9 running.

**Acceptance and tests:** Follow environment plan E1–E5 and approved environment spec
section 18. Every published daylight reading meets the error target; unreliable input
is `unavailable`; M2 outage does not stop the environment path; 24-hour evidence shows
no backlog. Run focused software checks only if code changes become separately approved.

**Next:** P1 three-browser HD acceptance. E3 real-scene checks remain queued behind this
stage and must be completed before the final release gate.

## P1 — Three-browser HD real-device acceptance

**Status:** PASS (user-confirmed). M2 Chrome, M2 Safari and iPhone browser all opened
the live view and remained viewable at the checked scales. iPhone layout is usable but
not fully optimized; retain that as a UX follow-up, not a live-view blocker.

**Prerequisites:** P0 complete; i9 source and Dashboard healthy.

**Codex can:** run bounded source/status commands, provide the fixed matrix, collect
closed outcomes and diagnose recoverable native/compat failures.

**Human required:** visually check M2 Chrome, M2 Safari and iPhone browser behavior at
1x/2x/3x.

**Acceptance and tests:** Follow Hybrid HD plan Task 6 Step 6. Confirm visible detail,
no-black-frame fallback, profile selection and on-demand VideoToolbox shutdown without
exposing media or private addresses.

**Next:** P2 real-Baby Guardian observation gate.

## P2 — Real-Baby Guardian observation gate

**Status:** Deferred until a Baby is available. The supervised seven-scene synthetic
gate passed; real Baby posture, face-obstruction and bed-exit accuracy remain
unaccepted. Online video cannot substitute for this household gate.

**Prerequisites:** P0 and P1 complete; private bed-zone acceptance complete; adult
supervision and normal care only.

**Codex can:** prepare the closed observation checklist, verify redacted status/event
contracts, aggregate fixed outcomes and update checkpoints.

**Human required:** supervise continuously and classify naturally occurring safe
observations. Never stage obstruction, prone position, bed exit or another hazard.

**Acceptance and tests:** Follow V1 plan Task 13 G1. Store no household media, model
prose, coordinates or free-form notes. Passing proves only the observed scenes and does
not authorize unattended care.

**Next:** P3 audio/cry A8 production-model/license decision and supervised public-media
preflight; household audio remains disabled and memory-only.

## P3 — Audio and cry candidates

**Status:** Gate V0 complete; A8 remains blocked. Voice Care Gate V1 architecture and
dual-repository implementation order are approved. Baby Local Tasks 1–3 are complete
and reviewed; the installed-i9 gate selected Whisper `base`, while production Voice
Care remains disabled.
Audio/cry was separately approved and resequenced for parallel software work on
2026-08-17. Stages A1-A2 strict contracts/settings and bounded in-memory PCM source are
complete; Stage A3 loudness/dynamic noise floor is complete and Stage A4 pinned ONNX
classifier boundary is software-complete, with production artifact approval pending;
Stages A5-A7 deterministic state, text-only event/outbox integration, independent worker
and installed software gate are complete. The installed job is verified disabled by
default. The installed source and fixed audio-only
alias now expose Opus and passed a bounded no-persistence decode.

A Voice Care cross-product Gate V0 has its own plan:
`docs/superpowers/plans/2026-08-19-voice-care-v1.md`.
It completed on 2026-08-20 with:

- source HEVC+Opus and audio-alias Opus feasibility,
- independent 60-second and 10-minute receive-only windows,
- synthetic Opus encode/decode compatibility,
- explicit decoder stop cleanup and unchanged sibling-service PIDs.

No raw household audio was persisted. This clears only the audio-ingest prerequisite;
it does not clear A8 production-model/license or household-scenario requirements.

The same plan now owns Gate V1. Task 1 delivered closed model artifacts/settings with
validated local source and runtime manifests. Task 2 delivered bounded memory-only VAD
and exact 500 ms/800 ms/8-second capture. Task 3 delivered local-only ASR, exact wake,
closed typed benchmark slots, an isolated fail-closed converter and the installed-i9
gate. Whisper `base` passed all four generated-speech thresholds; `small` failed closed.
Baby Care M5 contract/device/write work and its synthetic feeding pilot are now locally
complete. Baby Local Task 6 vendors that exact contract and its closed parser passes the
cross-repository verifier. Baby Local Task 7 now supplies the fail-closed Keychain,
encrypted-profile, enrollment and hybrid-identity software boundary. Baby Local Task 9
now supplies canonical Ed25519 pairing/intent signatures, strict semantic parsing and a
bounded encrypted restart-safe outbox. Task 10 now supplies fixed TTS, an in-memory
closed command pipeline, bounded status and an independent disabled-by-default job. Its
published final head is installed on the actual i9 and exact Guardian acceptance passes
19/19 with Voice disabled. Task 11 synthetic Gate V1 is complete and published; exact-head
CI passed at Baby Local `c554334` / `32680519119` and Baby Care `53e69d4` /
`32680603091`, including real PostgreSQL 16 and production Compose evidence. The local
ECAPA runtime slice is now complete on the Intel i9: the generated-only gate passed 5/5
finite normalized 192-dimensional embeddings at p50 284 ms / p95 311 ms without raw
audio persistence, and the installed Guardian gate remains 19/19. Voice Care remains
disabled until the human identity/accuracy gate passes.

Gate V2 is ASR-first. The encrypted six-prompt corpus and stable signed Keychain helper
now pass real user-launchd access. The approved base/small x four-profile one-shot matrix
has been exhausted: no candidate reached 6/6 exact, although base care-hotword profiles
reached 5/6 with acceptable latency. Official Silero passes its generated control and
5/6 prompts; `negative_weather` splits into two spans, and gain is inapplicable because
the private signal is not 12 dB below control. The approved pinned Paraformer amendment
is also implementation-complete: its exact-head i9 run evaluated 6/6 clips at p50
506 ms / p95 540 ms at implementation `6e933a6` after Task 5F's deterministic
punctuation-free boundary. It now achieves 5/6 exact and 6/6 wake;
`negative_weather` is the sole exact mismatch and also
the only clip with two Silero spans. It fails closed as `asr_candidate_unavailable` and
`vad_candidate_unavailable`. Voice remains disabled.

A separate approved listen-only mode is now accepted locally through `4590489`.
It does not bypass or modify the full-care accuracy/enrollment gate: it only provides
continuous memory-only Xiaomi audio listening, exact `小小` wake, one bounded follow-up
and fixed i9-speaker acknowledgements, with no Baby Care write or family identity path.
Its long-running runtime performs one bounded Paraformer child rebuild/retry after
explicit model unavailability, treats bounded empty recognition as a safe no-match,
and requires microsecond-fresh lifecycle readiness. Its software gate is 325/325 and
installed readiness is healthy while the Xiaomi source remains PASS. Supervised
acoustic acceptance passed at least 5 wakes, 3 dialogues, 3 timeouts and 5 non-wake
controls with both fixed replies audible and no self-trigger.

**Prerequisites:** The current design approval permits synthetic/public-media software
work before P0–P2 complete. P0–P2 and A7 remain prerequisites for household
real-device acceptance; the source-track prerequisite is verified.

**Codex can:** prepare public/synthetic model evaluation after a redistributable model
and license are approved; it cannot truthfully complete household accuracy alone.

**Human required:** approve the design and later conduct private household acceptance;
never provide household audio for Git or chat.

**Acceptance and tests:** Follow
`docs/superpowers/plans/2026-08-17-audio-cry-candidates.md`.
Test timing, deduplication, quiet/adult-speech negatives and privacy using generated or
explicitly public media. Software tests do not prove household accuracy.

**Next:** Voice listen-only is complete. Full-care Voice remains disabled; its
`negative_weather` rerecord, replay/overlap, Dad/Mom enrollment and Baby Care binding
remain deferred behind the unchanged full-care gates. P4 authenticated private remote
access is the next independent product stage.

Installed non-interactive Voice preflight is complete at `41da786`: after the explicitly
approved removal of one stale legacy pending request through `aacefd9`, the login
LaunchAgent reported Keychain, fixed Paraformer and fixed Silero artifacts available.
Voice remains disabled and this does not change the required ASR/VAD 6/6 gate above.

## P4 — Authenticated private remote access

**Status:** Software complete. Installed i9 and two-iPhone acceptance pending; public
exposure remains prohibited.

**Prerequisites:** The software slice was explicitly approved and resequenced. The
installed gate requires a healthy Dashboard, approved private policy review and the
required local/account permissions.

**Codex can:** run the implemented bounded preflight/status/software checks and, only
after the human prerequisites pass, apply the one fixed Serve route through the exact
TTY confirmation workflow. Parser, adapter, Make, grants example and runbook tasks are
complete through `a265312`.

**Human required:** authenticate devices/accounts, approve external service changes and
confirm both phones from outside the home network.

**Acceptance and tests:** Tailscale Serve/ACL only; never Funnel or router forwarding.
Only the authenticated application is reachable; camera, go2rtc and SQLite remain
private; no credentials enter Git, commands, reports or chat.

**Next:** Complete the installed P4 policy/Serve and two-iPhone cellular acceptance when
the human prerequisites are available. Camera Reply V3 failed closed and is not a
release dependency unless a future approved redesign reopens it.

## Voice Gate V3 — Xiaomi camera reply

**Status:** Software implemented, supervised generated-tone gate passed, but V3E failed
closed during the first household interaction batch. The accepted i9 speaker remains
the production reply output; camera reply is disabled and its marker is not accepted.

**Prerequisites:** P4 software checkpoint complete. The real speaker gate additionally
requires a healthy installed `cs2+udp` source, current pinned go2rtc build metadata and
an adult at the camera. P4 phone installation/acceptance may proceed independently.

**Codex can:** preserve the failed evidence and keep the feature disabled. Any future
work must begin with a separately approved design addressing Xiaomi backchannel sender
lifecycle, reconnect cleanup and the observed camera movement; it may not resume with
another household playback trial.

**Human required:** no further camera-reply trial under the current plan. The completed
single-tone confirmation does not override the failed interaction gate.

**Acceptance and tests:** Follow
`docs/superpowers/specs/2026-08-26-xiaomi-camera-reply-design.md` and
`docs/superpowers/plans/2026-08-26-xiaomi-camera-reply.md`. Only the fixed replies
`我在，请说。` and `我听到了。` may play. Require zero duplicate replies,
self-triggers, stuck armed states or sibling-service regressions. Software tests never
operate the real speaker.

**Next:** Retain the accepted i9 speaker output. Complete P4 installed/two-iPhone
acceptance and make an explicit i9-only release-scope decision before P5; do not claim
partial camera-reply support.

## P5 — Final 72-hour release gate

**Status:** Not started.

**Prerequisites:** P0–P4, Voice Gate V3 PASS or a separate explicit release-scope
decision to retain i9-only output, and all remaining V1 release prerequisites complete;
no open high-risk release blocker.

**Codex can:** run the approved bounded sampler/checklist, aggregate machine-readable
and Markdown results, diagnose recoverable failures and run full software/security
gates.

**Human required:** maintain the real deployment, supervise disruptive checks and
confirm two-phone/private-access outcomes. Tagging or publication requires separate
explicit approval.

**Acceptance and tests:** Follow V1 Task 16 and the approved V1 acceptance criteria for
72 continuous hours across i9, camera, M2, network, storage and two phones. The earlier
10-minute visual and 24-hour environment gates do not substitute for this run.

**Next:** only after documented PASS, request explicit approval for release integration
or tagging; do not modify `main`, push, merge or tag implicitly.
