# Guardian Household Scene Acceptance Design

Date: 2026-08-15  
Status: Approved

## Goal

Add one supervised Intel i9 command, `make alpha-guardian-scene-test`, that records a
privacy-safe acceptance result for fixed household synthetic scenes without storing
frames, model prose, private coordinates or credentials.

This gate measures operator-observed candidate behavior. It does not create a medical
claim, authorize unattended care or replace direct adult supervision.

## Safety Preconditions

Production mode requires an interactive terminal and exact confirmation that:

- no real infant participates in a dangerous or simulated-risk pose;
- an adult supervises the entire run;
- props and adult demonstrations remain safe and reversible;
- no household media will be exported, committed or pasted into logs.

Failure or EOF at any confirmation ends the command before recording a result.

## Fixed Scene Matrix

The first gate contains exactly seven scene kinds:

1. empty bed;
2. doll or inert prop;
3. adult in frame;
4. infrared/night view;
5. safely simulated camera obstruction;
6. mosquito-net movement;
7. safe normal-turning substitute using a prop or adult demonstration.

Each scene requires at least ten supervised trials. A real infant is never used to
stage obstruction, prone positioning, bed exit or any other hazardous condition.

## Trial Classification

The operator records one fixed outcome per trial:

- `correct`: observed candidate behavior matched the scene expectation;
- `false_positive`: an unexpected candidate appeared;
- `missed`: an expected candidate did not appear within the bounded observation window;
- `unavailable`: the scene could not be evaluated because required analysis was not
  available.

Free-form notes are prohibited. The command stores no model response, reason code,
event payload, image, clip, URL, address, path, device identity or household detail.

## Runtime Data

Results are written only below the ignored repository `runtime/` tree. The file uses a
closed schema, mode `0600` and atomic same-directory replacement. It contains only:

- schema version;
- fixed scene kind;
- trial ordinal;
- fixed outcome;
- UTC timestamp;
- aggregate counts and completion state.

The command must reject symlinks, unexpected keys, duplicate trials, invalid outcomes,
time rollback and a result path outside its controlled runtime directory. Interrupted
runs remain explicitly incomplete and may resume without duplicating completed trials.

## Observation Boundary

The acceptance command may read only existing redacted Guardian status/candidate
signals needed to guide the operator. It must not:

- read or persist raw frames;
- create or recover Guardian risk events;
- write event/evidence databases;
- send ntfy notifications;
- change bed zones, thresholds, models or services;
- control PTZ or any environmental device;
- write the Baby Care database.

Live viewing, microSD recording, Dashboard, gauge monitoring and other workers remain
independent of this command.

## Output Contract

Terminal output is ASCII-only and contains fixed status lines. It reports scene name,
completed trial count, aggregate outcome counts and final state only. It never prints
underlying exceptions or runtime values.

The final marker is one of:

```text
guardian_scene_test=PASS
guardian_scene_test=FAIL
guardian_scene_test=INCOMPLETE
guardian_scene_test=SIMULATED
```

`PASS` requires all seven scenes and at least ten trials per scene, no `unavailable`
trial and the acceptance thresholds defined in the implementation plan. Thresholds
must be approved before implementation and may not be inferred from software fixtures.
Hook-only tests produce `SIMULATED`, never physical `PASS`.

## Verification

Software verification uses generated signals and temporary runtime directories only.
It covers safety rejection, schema validation, atomic persistence, resume behavior,
redacted output, fail-closed storage errors, no notification/event writes and the
Makefile entry point.

Physical verification occurs only on the installed Intel i9 under adult supervision.
The public checkpoint records aggregate fixed outcomes and gate state, never household
media or private configuration. Passing this gate establishes behavior only for the
tested scenes and run; it does not prove medical monitoring, all household conditions,
sustained performance or safe unattended care.
