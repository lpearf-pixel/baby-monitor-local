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
5. R3.5 software complete locally. The first i9 10-minute gate failed at 1 FPS, while
   the controlled foreground run reached 5 FPS within the 180 ms P95 budget and
   isolated launchd `Background` scheduling as the bottleneck. Apply
   `make alpha-visual-launchd-update`, observe redacted metrics for 3 minutes, then
   rerun the complete 10-minute sampler before measuring candidate latency and the
   seven required household scenarios. Software tests do not establish installed-i9
   performance or household accuracy.
6. Source-health ntfy open/recovery delivery and independent gauge/real-time service
   continuity passed one controlled i9 outage. Do not repeat a Baby posture or
   face-risk event for this completed gate.
7. After the R3/R3.5 real-device gate, add R4 risk-event screenshot/video evidence,
   real-time risk text alerts and authenticated parent feedback without making the
   model a prerequisite for live viewing.

## P3 — Release gate

Add audio candidates and private Tailscale access, then complete the 72-hour i9,
camera, M2, network, storage, and two-phone acceptance before tagging `v0.1.0`.
