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
