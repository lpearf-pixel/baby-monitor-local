# Voice Listen-Only Operations

This mode continuously listens to the Xiaomi `audio_analysis` stream on the Intel i9.
It responds to the exact wake entries `小小` and `嘿，小小` through the i9 speaker,
arms one eight-second follow-up, and then returns to idle. `嘿` is the only optional
lead; the exact punctuation-free ASR form `嘿小小` is equivalent, while fuzzy,
repeated, sentence-internal and arbitrary-prefix matches remain rejected.
It does not write Baby Care, identify Dad or Mom, persist household audio or
transcripts, or send audio to the M2 or a cloud service.

The ignored `runtime/settings.yaml` must contain:

```yaml
voice_care:
  enabled: false
  listen_only_enabled: true
```

The fixed ignored `runtime/config/voice-care-models.json` continues to own the selected
Silero and Paraformer manifest digests. Do not copy those digests into tracked settings.

Use the bounded independent commands:

```bash
make alpha-voice-listen-start
make alpha-voice-listen-status
make alpha-voice-listen-stop
```

`start` waits up to 30 seconds for schema-v2 status with `mode=listen_only`. A disabled,
care, malformed or degraded status does not pass readiness. Voice start/stop does not
restart go2rtc, Dashboard, visual, gauge, environment or Guardian workers.

Before a supervised speech trial, run `make alpha-voice-listen-start` even if a prior
status file says healthy. The start command requires a status timestamp from the new
launch; `status` alone can describe a stopped job's stale file.

## Private diagnostic session

Ordinary listen-only operation stays memory-only. When aggregate counters are not
enough to diagnose a recognition miss, an adult may explicitly start the approved
private diagnostic session:

```bash
make alpha-voice-diagnostic-start
make alpha-voice-diagnostic-status
make alpha-voice-diagnostic-stop
```

The fixed session admits data for at most 30 minutes, 50 utterances and 16 MiB of
complete WAV/event pairs. It uses the existing single Xiaomi producer, VAD and
Paraformer call; it does not create another capture or transcription path. Camera Reply
must remain disabled, full-care Voice must remain disabled and listen-only Voice must
remain enabled before `start` can write anything.

Artifacts stay in ignored, owner-private runtime storage with `0700` directories and
`0600` files. The paired private event may contain the local ASR text, but normal Voice
logs, status commands, Dashboard, Git and chat remain transcript-free. Status prints
only counts, bytes, drops, failures and remaining time; it never prints a session ID,
path, filename, audio or transcript.

`stop` disables admission, restarts only Voice/ASR and retains the completed private
session for local diagnosis. Retained audio and text are sensitive household data, not
training data, and must never be committed or uploaded. There is intentionally no purge
command in this slice: deleting a retained session requires a separate explicit
approval. A normal Voice start neither creates nor renews diagnostics. Without a valid
current private marker, the worker retains no household PCM or transcript.

If an accepted phrase reports `voice_output_unavailable`, first test the macOS built-in
sound. When the built-in sound also blocks, restart only CoreAudio and retry:

```bash
/usr/bin/afplay -v 0.35 /System/Library/Sounds/Ping.aiff
sudo killall coreaudiod
```

macOS automatically relaunches the daemon. Do not disable SIP; on supported macOS,
`launchctl kickstart` for the protected system CoreAudio service is rejected by SIP.
This recovery does not restart go2rtc, the Xiaomi source or Guardian.

Expected interaction:

1. Either say the single sentence `嘿，小小，我要喂奶了`, or say `小小` and wait for
   `我在，请说。` from the i9 speaker.
2. For the two-stage form, within eight seconds say one closed care phrase such as
   `开始喂奶`.
3. A valid form makes the i9 say `我听到了。` exactly once and return to idle without
   saving the care fact.
4. If no command follows, it returns silently to idle. Say `小小` again for a later
   interaction.

The current output is the i9 speaker. Mi Home's talk button and Xiaomi camera
backchannel are unrelated and remain outside this gate.
