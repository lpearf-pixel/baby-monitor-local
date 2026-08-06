# Project Status

## Current phase

- Repository: initialized and public.
- Design: approved.
- Environment monitoring design and implementation plan: approved on 2026-08-05.
- Stable Xiaomi Alpha commit: `125fb44` on `stable/xiaomi-alpha`.
- Active local development branch: `codex/xiaomi-alpha-visual-risk-core`.
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
- Fresh R3 software gate on 2026-08-06: 451 Python tests and 70 Node browser tests
  passed; Python compilation, shell syntax, `git diff --check`, tracked runtime/media
  boundaries, GitHub-token candidates and private-key markers passed. This remains a
  software-only result and does not represent real-camera or M2 accuracy.
- Next visual gate: install the restricted i9-to-M2 SSH bridge, configure the private
  bed zone on i9, verify the real four-frame Qwen contract and P95 latency, and record
  daylight/night/occlusion/adult/empty-bed candidates before R4 evidence and alerts.
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
- Production visual worker/launchd deployment, authenticated parent feedback, event
  screenshot/video export, and cry/audio candidate detection.
- Verified Tailscale external access, real PTZ control, or the 72-hour release gate.

## Safety gates

- No household images, baby footage, credentials, device keys, tokens, or private network details may enter this public repository.
- `main` contains reviewed documentation and stable code only.
- All implementation work proceeds through feature branches and pull requests.
- Environment monitoring is read-only: no actuator API or automatic device control.
- Visual model output is observation evidence only; the deterministic i9 state machine
  owns decisions, and every result remains an auxiliary candidate rather than medical
  or unattended-care assurance.
