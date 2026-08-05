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

1. Revise and approve the visual-review spec for the selected M2 backend
   (JoyAI/MLX interaction layer or the existing Qwen/Ollama baseline).
2. Implement bed-zone/privacy-mask setup, deterministic camera freeze checks,
   bounded frame memory, model review, and risk state machine.
3. Add event screenshot/video evidence and real-time text alerts without making the
   model a prerequisite for live viewing.

## P3 — Release gate

Add audio candidates and private Tailscale access, then complete the 72-hour i9,
camera, M2, network, storage, and two-phone acceptance before tagging `v0.1.0`.
