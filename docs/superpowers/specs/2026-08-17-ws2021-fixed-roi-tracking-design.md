# WS2021 Fixed Right-Corner ROI Tracking Design

## Goal

Make WS2021 localization reliable when the device remains mounted in the lower-right of the Xiaomi 1440p frame, while preserving fail-closed behavior and leaving the trained detector as an optional fallback.

## Scope

This slice covers localization only. It does not add temperature/humidity OCR, change the schema-v2 calibration format, alter privacy policy, or declare real-device accuracy. OCR is a later slice that consumes a validated, stabilized ROI.

## Approved behavior

1. Load the existing schema-v2 calibration and derive the fixed lower-right ROI from its `gauge_rect` and `gauge_quadrilateral`.
2. For each frame, inspect only that ROI. Accept a candidate only when the ROI is inside the source frame, has sufficient dimensions, and its required quadrilateral/display geometry remains valid.
3. Allow bounded pixel/normalized drift around the calibrated rectangle so ordinary camera compression and small movement do not cause false failures. Do not search the whole frame or silently expand the ROI.
4. Require a configurable bounded number of consecutive valid frames before a location is considered stable. Any invalid, obstructed, reflective, or missing frame resets the stability counter and returns an unavailable/fail-closed result.
5. Keep the trained OpenVINO detector as an explicit fallback path only when fixed-ROI mode is not configured. It must not override a fixed-ROI rejection.
6. Emit only bounded status/error codes and normalized geometry. No raw frames, crops, household media, or calibration data may be committed or logged.
7. Within the accepted fixed ROI, allow bounded per-burst adaptation of the two calibrated circular faces. Adaptation is in-memory only, requires consistent circle candidates across the burst, and never rewrites the persisted schema-v2 calibration.

## Data flow

`CapturedFrame` -> fixed lower-right ROI validator -> bounded temporal stabilizer -> existing WS2021 source/reader. The reader and event state machine remain unchanged. A later OCR slice will consume only stabilized ROI frames.

For camera movement, the reader may relocate each face center/radius inside the fixed ROI using bounded circle candidates. The candidate must remain near the calibrated face, be unique enough, and agree across the required consecutive frames. If either face fails, the whole reading remains unavailable.

## Failure and safety rules

- Missing or invalid schema-v2 calibration: unavailable with the existing calibration failure reason.
- ROI outside frame, too small, geometry invalid, obstructed, or unstable: unavailable; never fabricate a reading.
- Frame source failure: preserve existing source-unavailable behavior.
- No automatic PTZ or camera movement is introduced.
- Existing privacy guard remains authoritative before any persistence or model transmission.
- Adaptive face geometry is ephemeral per burst; the saved calibration remains unchanged until an explicit Dashboard calibration save.

## Verification

- Unit tests cover lower-right ROI bounds, bounded drift, geometry rejection, obstruction/reflection rejection, stability reset, and fail-closed outputs.
- Existing gauge/source and contract tests must remain green.
- A bounded local live smoke test records only aggregate counts; it does not prove household accuracy, OCR correctness, or unattended-care safety.

## Acceptance boundary

This design is accepted only when software tests pass and a controlled real-device run shows stable accepted frames with no invalid-frame leakage. It does not replace the required 30-group daytime comparison, night/IR/occlusion/movement gates, 24-hour stability gate, browser HD acceptance, or final 72-hour release gate.
