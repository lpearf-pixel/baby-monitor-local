# Private Local Visual Corpus Overlay Design

**Date:** 2026-08-29

**Status:** Approved on 2026-08-29. Software Tasks 1–2 are complete locally. Current
implementation authority ends at Task 2. This document authorizes no camera access,
capture, real descriptor, replay, baseline operation or remote operation.

## 1. Goal

Add an optional, fail-closed private local overlay beside the existing public visual
corpus. The overlay may describe and validate owner-authorized household video without
placing media locations, camera identity or household details in Git. It provides a
separate `LOCAL_READY` signal for local regression work while leaving public corpus
readiness and public-source reproducibility unchanged.

The current target is one reviewed 20–30 second video-only asset that may cover both
`WIDE-02` and `NEG-01`. A second distinct capture may be retained as a candidate, but
the same frames must never be represented as two clips.

## 2. Non-goals

- Do not change the existing `PUBLIC_DATASET + DIRECT_HTTPS` contract or reinterpret
  any committed public source.
- Do not make private media downloadable, portable, redistributable or reproducible by
  another checkout.
- Do not put a local path, host identity, camera URI, household description, frame,
  thumbnail, contact sheet or review note in Git.
- Do not use private media to claim that the public corpus is `READY`.
- Do not generate, compare or promote a baseline containing private media without a
  separate approved baseline design. Default behavior is rejection.
- Do not change Guardian rules, model output, Voice, Camera Reply, PTZ, Xiaomi producer
  lifecycle, Baby Care or production stores.

## 3. Additive contract boundary

### 3.1 Public contract remains authoritative and unchanged

`tests/fixtures/visual_corpus/manifest.json` remains the public corpus manifest.
Its current source records, `SourceType`, `DownloadMethod`, HTTPS validation,
`PUBLIC_DATASET + DIRECT_HTTPS` preparation path and public readiness enum remain
unchanged. Public validation and replay must produce the same result when no private
overlay is present.

The public manifest must reject `PRIVATE_LOCAL_CAPTURE`. The private overlay must
reject `REAL`, `PUBLIC_DATASET`, `SYNTHETIC`, `DIRECT_HTTPS`, `MANUAL`,
`APPLICATION_ONLY` and `NOT_AVAILABLE`. The two source namespaces are therefore
mutually exclusive rather than variants accepted by the same public source record.

### 3.2 Private source type

The private overlay has one literal source type:

```text
PRIVATE_LOCAL_CAPTURE
```

It exists only in the private overlay contract. It is not added as a permissible value
inside `VisualCorpusManifest` or `VisualCorpusSource`.

The tracked descriptor is an identity and review envelope, not a source locator. Its
structural keys are `schema_version`, `source_type` and `assets`. Each asset object
permits exactly these metadata fields and no others:

```text
private_asset_id
sha256
bytes
duration_ms
codec
width
height
fps
scenario_ids
authorization_review
privacy_review
```

`private_asset_id` is a randomly generated opaque identifier matching
`plc-[0-9a-f]{32}`. It must not encode a person, family role, room, date, device,
address, project path or media digest.

`sha256` is lowercase hexadecimal. `bytes` is positive and at most 128 MiB.
`duration_ms` is between 10,000 and 60,000 inclusive; the first supervised capture
targets 20,000–30,000 ms. `codec` is a closed video codec value. `width`, `height` and
finite positive `fps` record probed media facts. `scenario_ids` is unique and bounded by
the existing `ScenarioId` vocabulary. `authorization_review` and `privacy_review` are
closed states `pending`, `approved` or `rejected`.

Unknown keys fail closed. The descriptor has no extension field and no prose field.

### 3.3 Forbidden tracked values

No tracked private-overlay value may contain or resolve to:

- `source_url` or any other URL field;
- a `file://` URI;
- an absolute or relative filesystem path;
- `.` or `..` path components, slash, backslash or percent-encoded path separators;
- a hostname, local hostname, IP address or port;
- an RTSP, HTTP, HTTPS, Xiaomi, MISS, CS2 or camera URI;
- a camera DID, model identity, token, key or account reference.

Schema validation rejects forbidden keys before inspecting values. A bounded defensive
value scan then rejects locator-shaped or identity-shaped strings in all remaining
string fields. Errors expose only stable reason codes, never the rejected value.

## 4. Ignored overlay layout

The only mapping from `private_asset_id` to a real file exists under ignored runtime:

```text
runtime/test-corpus/visual/private-overlay/
  index.json
  assets/
  review-frames/
  results/
  temp/
```

The overlay root and every child directory are mode `0700`. `index.json`, original
video files, derived review frames, local results and temporary artifacts are mode
`0600`. Every component is owned by the current login user, remains below the canonical
overlay root and is neither a symlink nor a hard link. The mapping stores only an
overlay-relative basename; it is itself ignored and must never be printed.

Raw files and derived frames are never added to Git, uploaded, redistributed, attached
to an issue or copied into an ordinary log. They remain local until the owner separately
authorizes deletion. A missing overlay is normal and must not be auto-created by public
validation.

## 5. Capture boundary

Private capture is a separately supervised runtime action. Before capture:

- Camera Reply must be explicitly false with no pending playback;
- no speaker or PTZ action may be called;
- the installed configuration must contain one Xiaomi source with `transport=auto`;
- exactly one existing shared Xiaomi producer must already be active;
- the capture must attach one sequential video consumer to the existing loopback
  `source` alias and must not connect to a camera URI or start another producer.

If any precondition is unknown, capture does not start. Captures run one at a time.
Output is video-only from the first persisted byte; audio is excluded rather than
recorded and removed later. A temporary owner-private file is atomically published only
after bounded process settlement and media validation.

The capture tool must not accept a caller-supplied source URL, destination path,
ffmpeg argument, codec override, hostname, port or camera identifier. Fixed loopback
and duration choices come from the approved implementation contract.

## 6. Content admission

Software validation never approves household content. A human must review the entire
candidate at no coarser than 500 ms and separately inspect the first and last frames.
One real-time playback is also required to catch transient content between sampled
frames.

For `WIDE-02` and `NEG-01`, one continuous admitted interval must satisfy all of:

- real, non-looped `crib_wide` or `room_wide` footage;
- no baby, adult, body part or person image;
- no person or baby visible in a mirror, glass, screen, photograph or other reflection;
- no address, name, document, QR code, account screen or other private identifier;
- no title, cut, fade, digital zoom, synthetic scale or camera movement;
- `baby_visibility=not_visible`;
- `adult_visibility=absent`;
- `object_state=empty`;
- `wide_content_role=empty_or_object_only`.

`privacy_review=approved` means the human completed this gate for the exact SHA-256.
Changing one byte invalidates review. A model prediction, source title or room setup
description cannot set either review state to approved.

## 7. Local media validation

For every tracked private asset, the local validator resolves only through ignored
`index.json` and checks, in order:

1. canonical overlay root, ownership, directory modes and bounded inventory;
2. mapping uniqueness and exact `private_asset_id` match;
3. regular file, owner, `0600`, link count one and no symlink component;
4. exact byte length and streaming SHA-256;
5. exactly one video stream and zero audio, subtitle or data streams;
6. duration, codec, dimensions and frame rate against tracked metadata;
7. unique allowed `scenario_ids` and authorization/privacy states;
8. content-review evidence bound to the same digest;
9. no duplicated asset or digest represented as two clips.

Any mismatch returns one stable failure code, publishes no local readiness and runs no
replay or baseline command. Validation does not delete ambiguous files.

## 8. Readiness separation

Public readiness remains the existing `DESIGN_ONLY | PARTIAL | READY` value derived
only from `VisualCorpusManifest`. Private files and metadata never change it.

The overlay reports a separate runtime-only value:

```text
LOCAL_UNAVAILABLE
LOCAL_PARTIAL
LOCAL_READY
```

`LOCAL_UNAVAILABLE` covers an absent or unreadable overlay. `LOCAL_PARTIAL` covers a
valid overlay that lacks approved coverage. `LOCAL_READY` requires every selected
private asset to pass local media validation and human content admission for the
requested local scenario set.

Status output always reports both values. For the current repository, a valid private
asset covering `WIDE-02` and `NEG-01` may yield
`public_readiness=PARTIAL` and `local_readiness=LOCAL_READY`; it must never yield public
`READY`.

## 9. Multi-scenario identity

One private asset may carry both `WIDE-02` and `NEG-01` exactly once in
`scenario_ids`. The runtime creates one clip identity from its opaque asset ID and
projects both scenario groups from that one result. The same digest or mapping entry
must not appear as two clip identities, and scenario coverage must not inflate the
unique clip count.

## 10. Baseline boundary

All current baseline generate, compare and promote paths remain public-only. Presence
of `PRIVATE_LOCAL_CAPTURE` in an input set causes a stable fail-closed result before a
candidate or baseline file is created. No fallback silently drops private clips.

Any future use of private media in baseline work requires a separate approved design
covering local-only baseline storage, identity, review, retention and deletion. Until
that approval, private overlay replay may produce ignored diagnostic aggregates only;
baseline promotion is prohibited.

## 11. Migration impact

- No public manifest or source record migrates.
- The current 13 public clips, prepared artifacts and public `PARTIAL` readiness remain
  byte-for-byte unchanged.
- Existing public download, prepare, replay and validation commands behave identically
  when the optional tracked descriptor or ignored overlay is absent.
- A future implementation adds a new overlay contract, validator and explicit local
  commands; it does not overload `VisualCorpusSource.source_url` or add a private enum
  value to the public manifest.
- Existing ignored research files are not discovered or adopted automatically.
- Install, launchd, go2rtc, Camera Reply and production workers receive no migration.

## 12. Fail-closed reason classes

The implementation uses bounded stable classes including:

```text
private_overlay_metadata_invalid
private_overlay_forbidden_locator
private_overlay_unavailable
private_overlay_mapping_invalid
private_overlay_permissions_invalid
private_overlay_identity_mismatch
private_overlay_media_invalid
private_overlay_audio_present
private_overlay_review_incomplete
private_overlay_scenario_invalid
private_overlay_duplicate_clip
private_overlay_capture_precondition_failed
private_baseline_operation_forbidden
```

These codes expose no value, path, file name, hostname, media property, review detail or
underlying exception.

## 13. Validator test matrix

| Area | Required positive case | Required rejection cases |
|---|---|---|
| Public compatibility | Existing public manifest validates unchanged | Public manifest containing `PRIVATE_LOCAL_CAPTURE` |
| Source exclusivity | Private descriptor accepts only its literal type | Every public source/download type in private descriptor |
| Tracked metadata | Exact allowlisted fields and valid opaque ID | Unknown field, `source_url`, path, URI, hostname, IP, camera identity |
| Identity | Unique opaque IDs and unique digests | Duplicate ID, duplicate digest, semantic/path-like ID |
| Overlay containment | Owner-private regular file below canonical root | Escape, symlink, hard link, wrong owner/mode, unknown inventory entry |
| File facts | Exact bytes and SHA-256 | Missing file, byte mismatch, digest mismatch, changing file |
| Media facts | One video stream, matching duration/codec/size/fps | Audio or other stream, out-of-range duration, metadata mismatch |
| Review | Exact-digest authorization and privacy approval | Pending/rejected review, review for different digest |
| Scenarios | One asset with unique `WIDE-02`,`NEG-01` | Duplicate scenario, unknown scenario, two clips for one digest |
| Readiness | Public `PARTIAL` plus local `LOCAL_READY` | Overlay changes public readiness or invalid overlay reports ready |
| Baseline | Public-only baseline remains unchanged | Any private generate/compare/promote request before output creation |
| Capture | Existing producer, Camera Reply false, video-only output | Unknown flag, second producer, speaker/PTZ path, audio persistence |

Tests use generated media and temporary directories only. They never open the camera,
read a household file or encode a real private digest into a fixture.

## 14. Acceptance boundary

This specification is accepted only after owner review. Software implementation, local
capture and private baseline use are separate later authorities. An implementation is
not complete until the public 42-test corpus gate remains green, new overlay tests pass,
tracked-media/privacy scans pass, and public validation still reports the same 13-clip
`PARTIAL` corpus in the absence of a public empty-wide source.
