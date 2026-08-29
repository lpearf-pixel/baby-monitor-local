# Private Visual Corpus Overlay

## Purpose

The private overlay can hold one owner-authorized, local-only video for repeatable
visual regression without placing a household locator, media file, frame or review note
in Git. It does not make the public corpus `READY` and cannot enter the public baseline.

The software-only closure does not authorize camera access. Run capture only during the
separate Task 8 owner-supervised gate.

## Fixed boundaries

- Camera Reply must be false and speaker state must be closed.
- Capture attaches to the existing loopback shared `source` producer. It never accepts
  a camera URI, host, port, destination, codec or ffmpeg override.
- Installed Xiaomi transport configuration remains `auto`; the negotiated result may
  be `cs2+udp` or `cs2+tcp`.
- Capture duration is exactly 20, 25 or 30 seconds and output is video-only.
- The producer protocol, generation and consumer count must match before and after.
- Runtime directories are owner mode `0700`; media, frames, receipts and indexes are
  owner mode `0600` and stay ignored.
- A model cannot approve content. Review requires every 500 ms, explicit first and last
  frames and one real-time playback by a human.
- Review approval is valid only for the exact current SHA-256.
- Deletion, upload, redistribution, replay and baseline use require separate authority.

## Read-only checks

Public corpus status:

```text
make alpha-visual-corpus-validate
```

Private overlay status:

```text
make alpha-visual-private-validate
```

Capture preflight, with no recording:

```text
make alpha-visual-private-capture-preflight
```

An absent private overlay returns `private_overlay_unavailable`. That is normal before
Task 8 and must not be converted into a success.

## Supervised capture

Do not run this section during software Tasks 1-7. After fresh Task 8 authority, first
run the preflight above. Then run exactly one duration choice:

```text
make alpha-visual-private-capture PRIVATE_VISUAL_DURATION=25
```

The command prints only an opaque asset ID and bounded media facts. It does not print an
ignored path or camera identity. A failure or interruption creates no accepted mapping.
Do not retry by restarting go2rtc or changing transport.

## Review preparation

After a successful supervised capture, use the opaque ID returned by capture:

```text
make alpha-visual-private-review-prepare PRIVATE_ASSET_ID=plc-00000000000000000000000000000000
```

Replace the example opaque ID with the captured ID. The command creates ignored review
frames only. It does not approve the content. Inspect the entire real-time video, every
500 ms frame, the first frame and the last frame. Reject any baby, adult, body part,
reflection, person image, private identifier, cut, fade, digital zoom or camera motion.

The ignored receipt is a strict JSON object bound to the same opaque ID and SHA-256. It
records only schema version, reviewer type `human`, 500 ms sampling, first/last review,
real-time playback acknowledgement and the two closed approval states. Unknown fields,
model-only review, a stale digest, pending or rejected state remain incomplete.

Review status is read-only:

```text
.venv-alpha/bin/python tools/private_visual_corpus.py review-status --private-asset-id plc-00000000000000000000000000000000
```

## Readiness and baseline

`public_readiness` comes only from the tracked public manifest. `local_readiness` comes
only from current private media and exact-digest review evidence. One private asset may
cover `WIDE-02` and `NEG-01`, but it remains one clip.

The public baseline loader rejects `PRIVATE_LOCAL_CAPTURE` envelopes and `plc-*` clip
identities as `private_baseline_operation_forbidden` before creating an output. Do not
run generate, compare or promote with private data. There is no private baseline
fallback and no silent public-only subset.

## Failure handling

Keep the first stable reason code. Do not paste underlying exceptions, media paths,
frames, room details or receipt contents into logs, issues or chat. Do not delete a
failed or rejected asset without separate owner approval. A software PASS proves only
the closed contract; it does not prove household content, camera accuracy or safe
unattended care.
