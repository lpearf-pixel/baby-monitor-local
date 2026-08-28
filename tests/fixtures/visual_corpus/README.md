# Visual regression corpus fixture

This directory contains contracts, source/license metadata, deterministic preparation
recipes and reviewed observational baselines only. It never contains downloaded or
generated media.

Use the repository corpus tool to place private local artifacts under the ignored
`runtime/test-corpus/visual` directory. A public URL is not permission to commit a file:
the manifest's redistribution and Git decisions remain authoritative.

`manifest.json` starts in `DESIGN_ONLY` state. It becomes `READY` only after the exact
source revision, checksum, time range and objective labels have been reviewed and the
first-stage admission gate passes.
