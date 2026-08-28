# Voice Local Diagnostic Session Resolution

Date: 2026-08-28

## Decision

The supervised Task 7 local diagnostic gate passed its bounded persistence and
memory-only restoration acceptance. This result validates the local diagnostic chain;
it does not accept household ASR accuracy generally, enable Camera Reply, write Baby
Care or authorize retention beyond the existing private bundle.

## Installed and software evidence

- Installed implementation: `528b31a`.
- SSH lifecycle readiness is bound to a pre-signal epoch, exact replacement worker PID,
  `listen_only` mode and `healthy` state.
- Affected tests: 61/61 passed.
- Complete Voice gate: 594/594 passed.
- Python compilation and `git diff --check`: passed.
- Independent review: 0 Critical and 0 Important.

## Supervised aggregate evidence

- Camera Reply remained false and no camera-speaker playback ran.
- go2rtc remained a single launchd-owned producer; no go2rtc restart occurred.
- The official source gate passed with observed `cs2+udp`, H265, native 2560x1440 and
  live 1280x720 video. Transport configuration remained `auto`.
- The retained ignored session contains 17 complete WAV/event pairs, 0 incomplete
  pairs and 1,211,164 bytes.
- All retained audio satisfies the fixed 16 kHz mono 16-bit WAV contract and the
  8-second per-utterance maximum. ASR was available for 17/17 records.
- Fixed aggregate classification observed one exact standalone wake and one exact
  Feeding action. Separate follow-up attempts remained ignored.
- i9 audio acknowledgement returned the fixed `voice_output_unavailable` outcome. This
  prevented the standalone wake from entering the armed follow-up state but did not
  invalidate ASR capture or the exact combined action classification.
- After diagnostic stop, two further adult utterances increased only in-memory Voice
  counters. The retained bundle remained 17 events and 17 audio files.

No household transcript, audio, session identifier, private path or free-form runtime
error is recorded here. The private bundle remains ignored and retained. Deleting it
requires separate explicit approval.

## Post-session output recovery

The existing bounded macOS runbook isolated a live output-session failure. A default
output device and `coreaudiod` were present, but system Ping returned
`AudioQueueStart (35)`. After daemon-only replacement, Ping passed in 2.551 seconds.

One supervised two-stage interaction then heard the wake reply but rejected its
follow-up as fixed `near_start` evidence. One subsequent single-sentence interaction
produced exactly one audible acknowledgement and incremented the fixed exact Feeding
counter to one. Voice stayed healthy, source stayed PASS and diagnostics stayed
inactive throughout this follow-up.

## Next slice

The current reliable operator path is the approved single-sentence interaction. The
next Voice device slice is the separately approved multi-action Task 8 for Feeding,
diaper change and burping. Do not derive a new correction rule from household evidence,
relax the closed classifier, enable Camera Reply or delete the private bundle.
