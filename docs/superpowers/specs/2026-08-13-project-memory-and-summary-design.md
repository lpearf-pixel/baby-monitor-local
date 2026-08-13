# Project Memory and Summary Design

## Goal

Make a new Work session able to take over `baby-monitor-local` safely without
reconstructing durable rules or the current delivery state from chat history.

## Authoritative entry points

### `AGENTS.md`

`AGENTS.md` is the durable project rulebook. It contains information that should
remain valid across feature slices:

- product purpose and system boundaries;
- hardware and service ownership;
- privacy, safety and secret-management rules;
- protected branches and Git authorization boundaries;
- configuration and shell-script conventions;
- focused versus full verification policy;
- the required takeover and final-report workflow.

It must not contain transient PIDs, local paths, private addresses, credentials,
household data, or a detailed chronological progress log.

### `SUMMARY.md`

`SUMMARY.md` is the current handoff snapshot. It contains:

- repository, branch and release-line status;
- the deployed architecture and supported hardware;
- completed capabilities and the latest verification evidence;
- real-device gates that remain incomplete;
- known limitations and the ordered next work;
- stable commands and links to detailed project records.

The summary records the distinction between software verification and household
acceptance. It must never turn synthetic tests into claims of real-camera,
two-phone, accuracy, performance or unattended-care acceptance.

## Relationship to existing documentation

`docs/STATUS.md`, `docs/CHECKPOINT.md`, `docs/NEXT.md`, approved specifications
and implementation plans remain the detailed evidence trail. `AGENTS.md` and
`SUMMARY.md` provide compact entry points and link to those records rather than
copying their full chronology.

When facts conflict, repository state and fresh verification override prose.
The summary must identify its update date and should be refreshed at meaningful
checkpoints, releases, branch changes, or changes to the next priority.

## Scope

This documentation slice may modify only:

- `AGENTS.md`;
- `SUMMARY.md`;
- this design record and its implementation plan.

It does not change application code, tests, thresholds, runtime configuration,
models, media, credentials, Git remotes, protected branches, pull requests or
deployment state.

## Verification

Completion requires:

- Markdown files contain no placeholders or contradictory branch claims;
- referenced repository paths and Make targets exist;
- `git diff --check` succeeds;
- a sensitive-literal scan finds no credentials, private keys, household media,
  private network addresses or local absolute deployment paths;
- unrelated `uv.lock` remains untracked and unchanged;
- the final diff contains only the approved documentation scope.

