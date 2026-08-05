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
3. Complete R2b controlled capture composition, deterministic camera freeze checks and
   single-flight scheduling without adding a disk-backed normal-frame queue.
4. Implement R3 against the fixed loopback Qwen/Ollama endpoint and restricted M2 SSH
   bridge, including timeout, degraded and recovery behavior.
5. Add R4 event screenshot/video evidence, real-time text alerts and authenticated
   parent feedback without making the model a prerequisite for live viewing.

## P3 — Release gate

Add audio candidates and private Tailscale access, then complete the 72-hour i9,
camera, M2, network, storage, and two-phone acceptance before tagging `v0.1.0`.
