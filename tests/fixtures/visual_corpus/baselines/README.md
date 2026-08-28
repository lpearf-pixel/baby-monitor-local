# Visual Regression Baselines

This directory contains promoted aggregate baselines only. A baseline records the
current software output for a checksum-pinned public corpus; it is not infant-safety
ground truth and must not be used to weaken Guardian acceptance criteria.

Promotion is explicit and fail closed. The candidate must match its supplied SHA-256,
all mandatory scenario clips must pass, and the three reviewed wide-view content roles
must be present. Promotion never replaces an existing baseline.

Downloaded videos, decoded frames, per-frame observations, household media, local model
files and runtime databases are prohibited here. Those artifacts remain in ignored
private runtime storage.

The first-stage manifest is currently `PARTIAL`, so no tracked v1 baseline is promoted
yet. A candidate result set may still be generated locally for replay diagnostics, but
it is not the canonical comparison baseline until corpus admission reaches `READY`.
