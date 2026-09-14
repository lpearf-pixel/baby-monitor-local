# Next Work

The repository baseline, environment software and functional Guardian loop are
complete. Do not restart completed milestones. Execute the following stages in order;
the detailed approved specs and plans remain authoritative for behavior.

## P0 — Environment real-device acceptance (current)

**Status:** E1 persistence passed on 2026-08-16. Task 15 software, privacy-safe crop
persistence, deterministic dataset preparation and pinned Intel CPU train/export
tooling are complete. Position 1 has 60 valid private pairs. On 2026-09-14 a fresh
80-epoch intermediate candidate (best epoch 76) trained, exported and passed exact
artifact/provenance checks plus `131 passed` gauge/environment/WS2021 regression. The
217-entry dataset separates 151/153 positives above the fixed 0.75 gate from 0/64
backgrounds, but this is training-inclusive evidence only. A no-persistence live
five-frame burst produced one 0.880226 NMS candidate that failed `gauge_box_invalid`;
diagnostic-only bounded clipping still failed the approved two-dial layout/refinement.
No threshold or production geometry rule was changed. The immediate mainline action is
position-2 schema-v2 Dashboard calibration and private collection with no baby or adult
present, then positions 3-5 and night/IR. Only after rebuilding the dataset and training
the final model may E2 automatic reading and E3 real-scene acceptance resume.

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

**Human required now:** place the upright, fully visible gauge at position 2 with safe
frame-edge margin and no baby/adult in view, then save a fresh schema-v2 calibration in
the authenticated Dashboard. Codex can then run the bounded calibrated collection and
all aggregate checks without seeing or reporting the household media.

**Acceptance and tests:** Follow environment plan E1–E5 and approved environment spec
section 18. Every published daylight reading meets the error target; unreliable input
is `unavailable`; M2 outage does not stop the environment path; 24-hour evidence shows
no backlog. Run focused software checks only if code changes become separately approved.

**Next:** finish Task 15 positions 2-5 and night/IR, rebuild and train the final private
model, then obtain one automatically localized available reading. E2 manual comparisons
and E3 real-scene checks remain required before the final release gate.

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

**Status:** Current next stage. Separately approved and resequenced for parallel software work on
2026-08-17. Stages A1-A2 strict contracts/settings and bounded in-memory PCM source are
complete; Stage A3 loudness/dynamic noise floor is complete and Stage A4 pinned ONNX
classifier boundary is software-complete, with production artifact approval pending;
Stages A5-A7 deterministic state, text-only event/outbox integration, independent worker
and installed software gate are complete. The installed job is verified disabled by
default. The installed source and fixed audio-only
alias now expose Opus and passed a bounded no-persistence decode. A7 remains required
before the supervised A8 stability and accuracy gate. A8 now awaits a production
model/license decision and supervised household scenarios.

**Prerequisites:** The current design approval permits synthetic/public-media software
work before P0–P2 complete. P0–P2 and A7 remain prerequisites for household
real-device acceptance; the source-track prerequisite is verified.

**Codex can:** reconcile V1 Task 10 with current architecture, draft the focused spec
and plan, implement against synthetic/public audio and run focused/full software gates.

**Human required:** approve the design and later conduct private household acceptance;
never provide household audio for Git or chat.

**Acceptance and tests:** Follow
`docs/superpowers/plans/2026-08-17-audio-cry-candidates.md`.
Test timing, deduplication, quiet/adult-speech negatives and privacy using generated or
explicitly public media. Software tests do not prove household accuracy.

**Next:** P4 authenticated private remote access.

## P4 — Authenticated private remote access

**Status:** Pending. Public exposure remains prohibited.

**Prerequisites:** P3 complete unless the user separately approves resequencing; an
approved private-access review and required local account permissions are available.

**Codex can:** reconcile V1 Task 7 with current iPhone clients, verify loopback binds,
prepare bounded Tailscale Serve/ACL steps and run configuration/security checks.

**Human required:** authenticate devices/accounts, approve external service changes and
confirm both phones from outside the home network.

**Acceptance and tests:** Tailscale Serve/ACL only; never Funnel or router forwarding.
Only the authenticated application is reachable; camera, go2rtc and SQLite remain
private; no credentials enter Git, commands, reports or chat.

**Next:** P5 final 72-hour release gate.

## P5 — Final 72-hour release gate

**Status:** Not started.

**Prerequisites:** P0–P4 and all remaining V1 release prerequisites complete; no open
high-risk release blocker.

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
