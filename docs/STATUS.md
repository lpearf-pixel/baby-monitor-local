# Project Status

## Current phase

- Repository: initialized and public.
- Design: approved.
- Environment monitoring design and implementation plan: approved on 2026-08-05.
- Active development branch: `codex/basic-usable-alpha`.
- Environment implementation: contracts, schema v2 Dashboard calibration, controlled
  frame bursts, day/night reader, independent worker, SQLite history, deterministic
  incidents, redacted ntfy payloads and authenticated Dashboard are implemented.
- Commit progression: design baseline `00ec882`, approved plan `4ac8353`, environment
  increments through `fc40c32`, followed by the integration commit containing this
  status update.
- Next gate: Intel i9 hardware calibration and accuracy/rejection/soak acceptance;
  software-only tests do not satisfy that gate.

## Pull request checkpoint

- Draft PR #4 was last verified open and unmerged on 2026-08-05.
- At that design gate, the GitHub PR head was `e010605` while the local environment
  work was based on `00ec882` and subsequent local commits. No fetch, push, merge or
  `main` modification was performed as part of the environment implementation.

## Safety gates

- No household images, baby footage, credentials, device keys, tokens, or private network details may enter this public repository.
- `main` contains reviewed documentation and stable code only.
- All implementation work proceeds through feature branches and pull requests.
- Environment monitoring is read-only: no actuator API or automatic device control.
