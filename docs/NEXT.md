# Next Work

The repository baseline and environment implementation are complete. Do not restart M0.

## P0 — Deliver the fixed Xiaomi Alpha on Intel i9

1. Transfer the fixed `codex/basic-usable-alpha` package or publish the 29 local
   commits only after explicit push approval.
2. On the i9 run `make alpha-install`, `make alpha-start`, and
   `make alpha-source-check`.
3. Apply the verified MJSXJ17CM native-HD subtype with
   `make alpha-subtype-apply`; retain the automatic rollback gate.
4. Check M2 Chrome/Safari and Android Chrome at 1x/2x/3x, including no-black-frame
   fallback and on-demand VideoToolbox shutdown.
5. Send test notifications to both Android phones and confirm no image or private
   address is included.

## P1 — Finish real environment acceptance

1. Complete one private WS2021 schema-v2 Dashboard calibration.
2. Record 30 daylight comparisons plus night, glare, and occlusion rejection.
3. Run the independent gauge/watchdog path for 24 hours with M2 offline.

## P2 — Add the local visual alert loop

1. R1 complete locally: strict Qwen observation contracts and the pure deterministic
   risk state machine are implemented and tested.
2. R2a complete locally: bed-zone crop, privacy masking, bounded JPEG preparation and
   the 40-second in-memory frame ring are implemented and tested with generated images.
3. R2b complete locally: a fixed private analysis stream, one continuous loopback
   consumer, deterministic disconnect/freeze checks, bounded reconnect and
   single-flight scheduling are implemented without a disk-backed normal-frame queue.
4. R3 software complete locally: fixed loopback Qwen/Ollama endpoint, strict client
   parsing, timeout, degraded/recovery behavior, production worker composition and
   independent launchd lifecycle. Next install the restricted tunnel and private bed
   zone, then verify real response schema, P95 latency and household candidate scenes.
5. R3.5 software complete locally. The performance recheck is intentionally deferred:
   retain the launchd update and 3/10-minute samplers, but do not let them block the
   guardian feature loop. Software tests do not establish installed-i9 performance or
   household accuracy.
6. Source-health ntfy open/recovery delivery and independent gauge/real-time service
   continuity passed one controlled i9 outage. Do not repeat a Baby posture or
   face-risk event for this completed gate.
7. R4 event core complete locally: deterministic risk transitions persist with stable
   IDs, restart restoration, adult-intervention audit and redacted JSON-line logs.
8. R4 safe evidence complete locally: a new risk event receives a privacy-processed
   screenshot and a bounded pre-10/post-30-second animated WebP; restart and shutdown
   mark incomplete captures explicitly instead of fabricating complete clips.
9. R4 risk text ntfy software complete locally: open, recovery and linked adult
   intervention use a persistent idempotent outbox and an off-thread bounded
   dispatcher; payloads are text-only and omit media, paths, private addresses,
   credentials and unauthenticated links. Physical delivery to both Android phones
   remains pending.
10. Option A startup, automatic acceptance and the separate supervised live acceptance
    are complete in software. On the installed i9 use published branch
    `codex/guardian-live-acceptance` at least at `c4b2de0`; after pulling, first run
    `make alpha-install`, then `make alpha-guardian-start`, then
    `make alpha-guardian-test`, and finally—with no
    real infant present, an adult supervising and both phones available—run
    `make alpha-guardian-test-live`. Preserve the fixed PASS/FAIL output. The automatic
    command remains notification-free; only the explicit live command sends one clearly
    labeled harmless text notification. Software `SIMULATED` is not physical proof.
    The previous automatic run stopped because the clean environment lacked the new
    Starlette `httpx2` dependency; the published fix also makes the installer include
    all development/acceptance extras. The i9 rerun remains pending.
11. Authenticated event queries and the media-free Dashboard list are complete locally.
    Evidence retention is also complete: cleanup uses the centralized 30-day/30-GiB
    limits while protecting open, collecting, notification-pending and
    recovery-notice-nonterminal records. Next complete the installed-i9/two-phone live
    run, household synthetic-scene validation and the deferred launchd performance
    gate. Per-parent
    acknowledgement and actor-bound false-positive
    feedback require a future contract where Baby Care consumes Guardian's read-only
    feed and owns identity/write state; they must not create a competing Guardian
    identity model. Live viewing must remain independent of AI.
    Upgrade to the FFmpeg ring-buffer option only after the functional guardian loop is
    complete.

## P3 — Release gate and deferred audio design

After visual Guardian acceptance, specify audio/cry and any voice-care interaction as
a separate work. Baby Monitor may own local camera-audio capture, wake/ASR and bounded
response plumbing; Baby Care owns family identity, corrections and final care-record
writes. Do not add direct Guardian-to-Baby-Care writes or let quiet-night behavior
weaken safety alerts. Then add private Tailscale access and complete the 72-hour i9,
camera, M2, network, storage, and two-phone acceptance before tagging `v0.1.0`.
