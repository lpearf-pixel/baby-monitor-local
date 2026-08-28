# Visual regression corpus fixture

This directory contains contracts, source/license metadata, deterministic preparation
recipes and reviewed observational baselines only. It never contains downloaded or
generated media.

Use the repository corpus tool to place private local artifacts under the ignored
`runtime/test-corpus/visual` directory. A public URL is not permission to commit a file:
the manifest's redistribution and Git decisions remain authoritative.

`manifest.json` currently records 11 reviewed clips in `PARTIAL` state. The admitted
sources are one CC0 file and two United States federal-government public-domain files;
all source media remains local-only even when redistribution would legally be allowed.
The tracked source ledger records the reviewed pages, exact byte counts and SHA-256
digests. Contact sheets and downloaded files stay under ignored runtime storage.

The objective label dimensions are framing, subject scale and frame-area ratio, camera
angle, environment, lighting, baby visibility, motion, adult visibility, object state
and wide-content role. Mixed clips also carry relative temporal spans so a wide room
shot is not collapsed into the close-up or title frames that follow it.

Known first-stage gaps are `WIDE-02`, `OCC-03`, `NEG-01` and `NEG-02`. In particular,
the reviewed public video does not contain ten continuous seconds of an empty or
object-only crib, so the real-wide admission gate remains
`SKIP visual_corpus_real_wide_source_missing`. Synthetic scaling cannot close that
gate. The corpus becomes `READY` only after those exact scenarios are supported by
reviewed public or generated-synthetic media, and the empty/object-only wide role is
supported by real licensed video.
