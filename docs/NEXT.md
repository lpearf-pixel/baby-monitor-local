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

The daily command compatibility review is closed in software at `e786d2e`: exact
`嘿，小小，我要喂奶了` now reaches one listen-only acknowledgement while arbitrary
leads, near matches and all Baby Care writes remain closed. Before resuming Dad/Mom
enrollment, Web reviews the implementation/result record and the logged-in i9 performs
one supervised gold-phrase check with a single response and count increment.

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

**Next:** Voice listen-only is complete and the full-care ASR/VAD corpus passes 6/6.
The revised enrollment boundary is software-complete: it warms/drains the Xiaomi audio
during the local 15-second countdown and then captures one Silero-bounded utterance in
memory instead of opening a fragile five-second decoder window. Next run one logged-in-
i9 Dad enrollment, then Mom enrollment and the separately supervised replay/overlap
slice. Baby Care binding remains behind those gates. P4 authenticated private remote
access is explicitly deferred to the final optional stage.

Installed non-interactive Voice preflight is complete at `41da786`: after the explicitly
approved removal of one stale legacy pending request through `aacefd9`, the login
LaunchAgent reported Keychain, fixed Paraformer and fixed Silero artifacts available.
The later clean rerecord passed ASR/VAD 6/6; Voice remains disabled because enrollment
and replay/overlap acceptance are still open.

The bounded private Voice diagnostic Task 7 is complete on installed head `528b31a`.
One supervised session retained 17/17 valid private WAV/event pairs and proved both an
exact standalone wake and one exact Feeding action. Separate follow-up attempts remained
ignored because the standalone wake could not acknowledge or arm while i9 CoreAudio
reported `voice_output_unavailable`. After diagnostic stop, Voice processed two more
utterances in memory while the retained artifact count remained 17/17. The exact next
Voice slice is bounded CoreAudio output diagnosis followed by one supervised wake plus
follow-up check; do not lower recognition rules, enable Camera Reply or delete the
retained bundle without separate approval.

## P4 — Authenticated private remote access

**Status:** Software complete. Installed i9 and two-iPhone acceptance are explicitly
deferred by the user to the final optional stage; public exposure remains prohibited.

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

**Next:** Do not install or configure Tailscale now. Continue local-only product gates;
return to remote access only after the local release work when the user explicitly asks.

## Voice Gate V3 — Xiaomi camera reply

**Status:** Replacement lifecycle software Tasks 1–14 and supervised Task 15 are
complete. The resumed first attempt preserved the historical fail-closed timeout, then
`5fd457e` closed late internal playback cleanup and `b4da03f` corrected the supervised
probe to stop its fixed tone before waiting for human input. The clean matrix passed six
cumulative audible replies with no camera movement, one producer, generation 6, no
replacement and a current schema-v2 marker. The accepted i9 speaker remains the
production output because the ignored Camera Reply flag is still false.
The later controlled activation did not pass V3E: one live `嘿小小` reply was audible
from the camera but coincided with observed camera movement, so the flag was rolled back
to false and only Voice restarted. An i9-only control then accepted `嘿小小` once with
no movement; bare `小小` was not acoustically reliable. A subsequent isolated tone
passed without movement, but the next live retry played only `我在`, moved the camera,
returned AMBIGUOUS and left one stale internal playback producer after Xiaomi media
timeout/replacement. The installed user-facing wake phrase is therefore `嘿小小`, while
the internal normalized keyword remains `小小`; Camera Reply remains unaccepted.
The approved transport-auto amendment is recorded at `8654866`; Task 8 software is
complete at `f153cbd` with 62/62 synthetic checks. Its installed preflight was not run.

**Prerequisites:** Tasks 9 through 14 are complete at `1885da2`, `c85fb39`, `faa3d4b`,
`91c97bc`, `015f6e4` and `9bc032b`: configuration
stays `transport=auto`, runtime parsing requires one external Xiaomi producer, and reply
settlement owns the observed protocol plus nonzero generation. Task 14 later ran the
installed preflight, which failed closed; the installed media diagnostic did not run.
Real speaker playback Task 15 is complete; production activation remains a distinct
configuration change and still requires adult supervision plus the existing rollback.

**Codex can:** keep the private flag false, finish Task 16's bounded FFmpeg drain slice,
and prepare component-only recovery. Do not resume the full V3E matrix until the failed
marker is invalidated, go2rtc is recovered to exactly one producer, the runtime model
identity discrepancy is reconciled and one supervised fixed reply passes without
truncation, movement, timeout or replacement.

**Human required:** approve the production-output switch and supervise the fixed wake,
dialogue, silent-timeout and non-wake interactions. Forcing TCP/UDP or creating a second
connection remains prohibited.

**Acceptance and tests:** The original fixed vocabulary and privacy boundaries remain
in force. The replacement software gate passed all named lifecycle and review
regressions, 20 clean synthetic generations, exact patch provenance, zero post-stop
writes, zero pending responses/residual senders, propagated failures and no
Voice/source regression. Software tests never operate the real speaker.

**Task 11 result:** `D2_BOUNDARY_HARDENED_CAUSE_UNPROVEN`. Four pinned focused/race
fixtures pass; only raw read-error disclosure reproduced and was replaced by fixed
payload-free classification. This does not explain the real D2 media loss.

**Task 12 result:** software aggregate stages and strict 48 kHz stereo Opus are complete
at `91c97bc`; the live microphone chain remains unrun and no real readiness is claimed.

**Task 13 result:** generated reply delivery software is complete at `015f6e4`.
Zero payload cannot consume channel-3 sequence or produce a successful count; exact
pinned normal/race tests prove channel, sequence, header/payload offsets and bounded
successful packet/byte accounting. Python COMPLETE requires current-generation counter
growth. This is not an audibility claim.

**Task 14 result:** full software and review checkpoint is complete at `9bc032b`.
Full Python passes 1732/1732, frontend passes 73/73, and independent review is clean.
The installed preflight failed closed as `app_identity_invalid`; the installed media
diagnostic did not run. Decision: `MACOS_PREFLIGHT_BLOCKED`.

**Task 15 result:** `b4da03f` passed probe/Camera Reply/Voice software gates 27/27,
125/125 and 442/442, followed by 6/6 supervised audible replies without movement. Final
runtime evidence was one `transport=auto` producer, observed `cs2+udp`, generation 6,
increasing video/audio bytes, no replacement, healthy Voice and a current schema-v2
marker. No household audio was persisted and no full-stack restart occurred.

**Task 16 status:** COMPLETE at software head `16f7652`. The failed live retry provided
aggregate evidence for a finite-file EOF/stop race: a valid 1.40875-second TTS input was
realtime paced, stopped at nominal duration, returned AMBIGUOUS and left a stale
internal producer. A fixed 0.5-second cancellation-aware drain now precedes stop inside
the existing operation limit. Camera Reply 126/126, Voice 443/443 and exact pinned
normal/race protocol gates pass. No real speaker playback has validated the fix.

The historical installed recovery checkpoint at detached `16f7652` is complete: the
failed marker was deleted
with explicit approval, only go2rtc and Voice restarted, and the recovered source has
one Xiaomi producer, zero internal producer, closed/clean speaker state, video PASS and
a post-restart 60-second Opus receive PASS with no persistence. Camera Reply is disabled
and NOT_PROVEN. The authenticated Xiaomi device list confirms the matching real device
and configured source both report `chuangmi.camera.039a01`; do not substitute the
public `039c01` record.

The adult-supervised post-fix gate also passed. One isolated tone and one canonical
live wake each produced exactly one complete audible camera reply with no movement.
Final aggregate lifecycle was 2/2/2/2 with positive Opus packets/bytes, one Xiaomi
producer and zero internal/pending/residual/failure state; no new timeout/EOF occurred.
The private flag is false again. Count this as clean V3E standalone wake 1/5 only.

**Task 17 status:** V3E FAILED CLOSED after reaching all successful interaction quotas.
The run contained one launchd no-response and two missed follow-up acknowledgements, so
successful counts do not substitute for a clean matrix. The final reply lifecycle and
source were clean, the private flag is false, and Voice was restarted to healthy idle.

The launchd error-37 path is fixed locally at `03aec97`; Voice-only stop now waits for
both jobs to settle and fails closed after two seconds. The bounded post-prompt capture
design is implemented and installed at `6e54f55`. It retains only five 100 ms frames in
memory during drain, releases them only after same-generation closed settlement and
quarantines reply echo without consuming the armed turn. Affected tests pass 126/126,
the complete Voice gate passes 451/451, and installed Voice-only stop/start plus source
checks pass with Camera Reply disabled.

Aggregate-only stage evidence is now installed at `3069141`. A new attempt passed two
dialogues then failed on the third follow-up; a subsequent diagnostic dialogue passed
with ten replay frames but zero replay utterances. The successful follow-up therefore
used normal live input, and the intermittent miss is not evidence for enlarging the
buffer or lowering recognition thresholds.

**Next:** repeat all V3E quotas under adult supervision from fresh process/lifecycle
counters while reading fixed transition deltas after every group. Any miss, movement,
truncation, duplicate, producer replacement or residual state fails closed. Software,
installation and the single diagnostic success do not count as the complete device gate.

The next attempt is blocked before another full matrix: installed `73c88bf` classified
four of five follow-ups as rejected near-start text, with zero near-reply-echo and zero
far. Do not enlarge the tail buffer or accept arbitrary edit distance.

The user approved a multi-action ASR optimization design on 2026-08-27. Its
authoritative entry points are:

- `docs/superpowers/specs/2026-08-27-voice-care-multi-intent-asr-optimization-design.md`;
- `docs/superpowers/plans/2026-08-27-voice-care-multi-intent-asr-optimization.md`;
- `docs/reviews/2026-08-27-voice-care-multi-intent-asr-optimization-log.md`.

Software Tasks 1–7 are complete through `df7b762`. The implementation keeps Feeding as
the only external `VoiceCareIntentV1` contract, adds diaper change and burping only to
the internal closed listen-only classifier, and treats medication only as a silent
high-risk candidate. It explicitly rejects generic edit distance, cross-action
correction and open-ended intent classification. Fresh gates are focused 247/247,
Voice 524/524 and repository 1829/1829. The generated benchmark passed low-risk actions
18/18 and negatives 48/48 with zero false accepts; medication start passed 3/3 while
medication complete was rejected 3/3, so medication cannot enter supervised acceptance.

**Next:** wait for the adult to return. With separate approval, run Task 8 only for the
already software-qualified Feeding, diaper-change and burping actions from fresh fixed
counters while Camera Reply remains false. Do not run household capture unattended.
Medication requires a separate high-risk design before its Task 8 gate; do not install
a model, relax correction or infer a care record. Camera Reply V3E remains an independent
later gate.

## P5 — Final 72-hour release gate

**Status:** Not started.

**Prerequisites:** All remaining local V1 release prerequisites complete, explicit
i9-only Voice output, and no open high-risk local release blocker. Installed P4 remote
access is deferred and is not a prerequisite for this local-only release gate.

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
