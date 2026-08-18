# Next Work

The repository baseline, environment software and functional Guardian loop are
complete. Do not restart completed milestones. Execute the following stages in order;
the detailed approved specs and plans remain authoritative for behavior.

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
   Software contract checks are green; the real-device scenarios remain outstanding.
5. E4 — take M2/Ollama offline and confirm gauge, storage, state and notification
   independence.
6. E5 — run the gauge/watchdog path for 24 hours without scheduling backlog; complete
   the remaining state/notification, load-shedding and two-phone payload checks.

**Codex can:** run bounded readiness checks, guide the approved workflow, validate
closed outputs, diagnose recoverable failures and update redacted documentation.

**Human required:** provide one local bounding-box annotation at position 2, operate the
authenticated Dashboard, position/read the physical gauge, provide reference comparisons,
supervise scene changes and keep the i9 running.

**Acceptance and tests:** Follow environment plan E1–E5 and approved environment spec
section 18. Every published daylight reading meets the error target; unreliable input
is `unavailable`; M2 outage does not stop the environment path; 24-hour evidence shows
no backlog. Run focused software checks only if code changes become separately approved.

**Next:** P1 three-browser HD acceptance.

## P1 — Three-browser HD real-device acceptance

**Status:** Pending. Installed source/codec and Guardian live-view checks have passed;
the browser matrix has not.

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

**Status:** Pending. The supervised seven-scene synthetic gate passed; real Baby
posture, face-obstruction and bed-exit accuracy remain unaccepted.

**Prerequisites:** P0 and P1 complete; private bed-zone acceptance complete; adult
supervision and normal care only.

**Codex can:** prepare the closed observation checklist, verify redacted status/event
contracts, aggregate fixed outcomes and update checkpoints.

**Human required:** supervise continuously and classify naturally occurring safe
observations. Never stage obstruction, prone position, bed exit or another hazard.

**Acceptance and tests:** Follow V1 plan Task 13 G1. Store no household media, model
prose, coordinates or free-form notes. Passing proves only the observed scenes and does
not authorize unattended care.

**Next:** P3 audio/cry design and implementation.

## P3 — Audio and cry candidates

**Status:** Separately approved and resequenced for parallel software work on
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
