# Voice Listen-Only Operations

This mode continuously listens to the Xiaomi `audio_analysis` stream on the Intel i9.
It responds to exact `小小` through the i9 speaker, arms one eight-second follow-up,
and then returns to idle. It does not write Baby Care, identify Dad or Mom, persist
household audio or transcripts, or send audio to the M2 or a cloud service.

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

Expected interaction:

1. Say `小小` and wait for `我在，请说。` from the i9 speaker.
2. Within eight seconds say one closed care phrase such as `开始喂奶`.
3. The i9 says `我听到了。` and returns to idle without saving the care fact.
4. If no command follows, it returns silently to idle. Say `小小` again for a later
   interaction.

The current output is the i9 speaker. Mi Home's talk button and Xiaomi camera
backchannel are unrelated and remain outside this gate.
