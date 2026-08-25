# Task 15.4b: WS2021 final-artifact provenance

## Delivered behavior

The private training checkpoint now records only three final-artifact provenance
values: configured epoch count, the SHA-256 of the exact dataset manifest bytes, and
the one-based best-loss epoch. A private checkpoint sidecar also binds those values to
the checkpoint SHA-256. Export accepts the sidecar only when that binding and the
strict value schema are valid, then copies the three allowed values into model
metadata. The artifact `check` action now requires the current valid dataset and fails
closed unless its manifest SHA-256 matches the exported metadata, in addition to the
existing exact ONNX/XML/BIN digest checks.

Metadata intentionally contains no paths, filenames, sample counts, images,
calibration, or secrets. Inference, thresholds, ROI/model ordering, collection, and
runtime private data are unchanged.

## Historical and bootstrap behavior

Historical checkpoints and metadata that lack complete provenance are rejected by
export or `check`; they cannot be presented as final private-artifact evidence. A new
`train-bootstrap` run writes the same bounded provenance, but the existing policy that
bootstrap artifacts do not close Task 15.4b remains unchanged. Only the later approved
private train/export/check sequence can provide final-artifact evidence.

## Files and interfaces changed

- `tools/ws2021_cpu_train.py`: records provenance in the checkpoint and private
  checkpoint sidecar.
- `tools/ws2021_model.py`: validates the checkpoint binding, exports the bounded
  `training_provenance` metadata object, and compares it with the dataset manifest in
  `check`.
- `tests/monitoring/test_ws2021_model.py`: covers capture, propagation, absence, and
  manifest-mismatch rejection.

The exported metadata interface adds exactly:

```json
{"training_provenance":{"best_epoch":17,"configured_epochs":80,"dataset_manifest_sha256":"<sha256>"}}
```

The values shown are schema examples, not evidence from a private training run.

## RED/GREEN evidence

RED was observed before production edits using the repository Python 3.11 virtual
environment: `tests/monitoring/test_ws2021_model.py` produced 4 expected failures and
7 passes. The failures showed that missing metadata provenance was accepted,
checkpoint provenance was not propagated, a mismatched manifest was accepted, and the
training-provenance helper did not exist. The shell `python` command was unavailable;
this was an interpreter-shim issue before collection and was not treated as test
evidence.

GREEN verification after implementation:

- `.venv-alpha/bin/python -m pytest -q tests/monitoring/test_ws2021_model.py`:
  11 passed.
- `.venv-alpha/bin/python -m pytest -q tests/monitoring/test_ws2021_model.py tests/gauge/test_locator.py`:
  23 passed.
- `.venv-alpha/bin/python -m py_compile tools/ws2021_cpu_train.py tools/ws2021_model.py`:
  passed.
- `make -n alpha-ws2021-model-train alpha-ws2021-model-export alpha-ws2021-model-check`:
  passed and retained the explicit commands.
- `git diff --check`: passed.
- Targeted tracked-diff scan for credentials, private keys, private network literals,
  runtime media, SQLite and generated settings: no matches.

## Limits and remaining gates

These software checks prove only the bounded provenance and fail-closed artifact
contract. They do not prove a private dataset exists, model quality, live
localization, real-device geometry, privacy review of collected crops, performance, or
the installed-i9 acceptance gate. No private training, export, artifact check, runtime
data access, push, merge, or remote operation was performed.

## Git handoff

Implementation commit: `4eb11fe27b44372fe63b0110d3ac1371fdfb1512`
(`feat: attest ws2021 training provenance`). The active branch was
`codex/guardian-live-acceptance`; its upstream was one commit behind after the local
implementation commit. No unrelated files were changed or staged.

Next product slice: conduct the approved private Task 15.4b train/export/check sequence
after sufficient reviewed private crops exist, then record redacted evidence before any
claim of a final WS2021 artifact.
