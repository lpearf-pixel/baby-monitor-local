# Voice Contextual/Hotword Isolated A/B Result

**Date:** 2026-08-28
**Decision:** Reject the candidate; keep the current production Paraformer unchanged.

## Scope

This checkpoint evaluated one fixed ContextualParaformer candidate on the Intel i9 in
an ignored, isolated environment. It did not edit Voice settings, launchd definitions,
the installed model manifest or the Xiaomi/go2rtc path. It did not restart Voice or
read the camera. The generated corpus was temporary and contained no household audio.

## Fixed candidate

- model revision: `8f0881c891ceba7360e215b04e54cad564a68c41`
- FunASR source revision: `67d6d880841e0c8f3a33e0f98d3bfc2122e34eff`
- FunASR runtime: `funasr_onnx==0.4.2`
- bundle manifest SHA-256:
  `7a77621ef509ad4074cb357425f0c449fbb5bc60a4dd94baa1534cbbb8d5b9aa`
- `model_quant.onnx` SHA-256:
  `f404e6eb532b54fd95761e2b4be4ed1998e8cff3cb3b930a9bee1f2d556e5035`
- `model_eb.onnx` SHA-256:
  `d31446a5af664291a2922cca253a4200a523f347d6fc3cb1bff356bf60a116b6`

The isolated install and artifact/environment check both returned `ready`. During the
first actual execution, two software defects were reproduced and fixed with regression
tests: macOS generated speech had no subprocess timeout, and pinned FunASR returns
`preds` as a fixed text/token tuple rather than a bare string. The corrected adapter
retains strict output validation, and generated speech now has a 15-second per-item
bound.

## Generated/public A/B

Both engines received the same 24 positive and 48 adversarial-negative PCM samples in
the same order. The final aggregate result was:

| Metric | Current Paraformer | Contextual candidate |
|---|---:|---:|
| evaluated | 72 | 72 |
| correct overall | 69 | 69 |
| positive correct | 21/24 | 21/24 |
| negative rejected | 48/48 | 48/48 |
| false accepts | 0 | 0 |
| exact low-risk matches | 18 | 18 |
| high-risk candidates | 3 | 3 |
| latency p50 | 133 ms | 164 ms |
| latency p95 | 298 ms | 294 ms |
| peak RSS | not measured | 1,666,121,728 bytes |
| gate | FAIL | FAIL |

Both engines rejected all three medication-complete positives. The candidate therefore
missed the mandatory 24/24 positive gate even though its negative, latency and memory
gates passed. Adding medication phrases to hotword bias is explicitly outside the
approved low-risk hotword policy, and the gate was not weakened.

## Private and production gates

The public gate failed, so the retained private-local diagnostic gate was not opened.
No private PCM, transcript, filename, path or family data was read or serialized by
this A/B result. The production switch gate remains closed: the current sherpa
Paraformer, Voice worker and launchd configuration were not changed or restarted.

## Handoff

The ContextualParaformer candidate is retained only as ignored evaluation state and is
not approved for deployment. The accepted operational workaround remains the combined
single-sentence care command. Any different model, different hotword policy or revised
public corpus requires a new design rather than changing this failed result.
