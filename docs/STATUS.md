# Project Status

## Current phase

- Repository: initialized and public.
- Design: approved.
- Environment monitoring design and implementation plan: approved on 2026-08-05.
- Active development branch: `codex/basic-usable-alpha`.
- Xiaomi-first delivery scope: fixed to MJSXJ17CM for the first usable release;
  the proposed UVC USB source remains deferred behind the existing frame-source
  adapter boundary.
- Usable Alpha: password-protected Dashboard, 720p MJPEG preview, on-demand native
  or VideoToolbox 1440p HD view, snapshot, safe HD rollback, ntfy test delivery,
  and Xiaomi subtype probe/apply are implemented.
- Environment implementation: contracts, schema v2 Dashboard calibration, controlled
  frame bursts, day/night reader, independent worker, SQLite history, deterministic
  incidents, redacted ntfy payloads and authenticated Dashboard are implemented.
- Local branch HEAD before this status refresh: `08963d6`; the branch is 29 commits
  ahead of `origin/codex/basic-usable-alpha` and the working tree was clean.
- Fresh software gate on 2026-08-05: 316 Python tests and 70 Node browser tests passed;
  `git diff --check` and the tracked runtime/media boundary check passed.
- Next gate: install this fixed Xiaomi Alpha on the Intel i9, reconnect the real
  camera, and run source/HD/browser/notification/environment calibration checks.
  Software-only tests do not satisfy that hardware gate.

## Pull request checkpoint

- Draft PR #4 was last verified open and unmerged on 2026-08-05.
- At that design gate, the GitHub PR head was `e010605` while the local environment
  work was based on `00ec882` and subsequent local commits. No fetch, push, merge or
  `main` modification was performed as part of the environment implementation.
- The current environment could not authenticate GitHub CLI to refresh PR metadata;
  no push, merge, or `main` modification was attempted during this delivery refresh.

## Not yet in the usable Alpha

- JoyAI/Qwen visual risk review and the M2 model bridge.
- Automatic face-obstruction, prone-position, bed-exit, or adult-intervention alerts.
- Event video ring/export and cry/audio candidate detection.
- Verified Tailscale external access, real PTZ control, or the 72-hour release gate.

## Safety gates

- No household images, baby footage, credentials, device keys, tokens, or private network details may enter this public repository.
- `main` contains reviewed documentation and stable code only.
- All implementation work proceeds through feature branches and pull requests.
- Environment monitoring is read-only: no actuator API or automatic device control.
