# Visual regression corpus fixture

This directory contains contracts, source/license metadata, deterministic preparation
recipes and reviewed observational baselines only. It never contains downloaded or
generated media.

Use the repository corpus tool to place private local artifacts under the ignored
`runtime/test-corpus/visual` directory. A public URL is not permission to commit a file:
the manifest's redistribution and Git decisions remain authoritative.

`manifest.json` currently records 13 reviewed clips in `PARTIAL` state. The admitted
sources are one CC0 file, two United States federal-government public-domain files and
one Pixabay Content License file; all source media remains local-only. The Pixabay
source may not be redistributed as a standalone file.
The tracked source ledger records the reviewed pages, exact byte counts and SHA-256
digests. Contact sheets and downloaded files stay under ignored runtime storage.

The objective label dimensions are framing, subject scale and frame-area ratio, camera
angle, environment, lighting, baby visibility, motion, adult visibility, object state
and wide-content role. Mixed clips also carry relative temporal spans so a wide room
shot is not collapsed into the close-up or title frames that follow it.

Known first-stage gaps are `WIDE-02` and `NEG-01`. `NEG-02` is backed by reviewed
object-only public stock footage, while `OCC-03` is a human-reviewed deterministic
majority-obstruction derivative. The reviewed real videos still do not contain ten
continuous seconds of an empty crib/room wide view, so the real-wide admission gate remains
`SKIP visual_corpus_real_wide_source_missing`. Synthetic scaling cannot close that
gate. The corpus becomes `READY` only after those exact scenarios are supported by
reviewed public or generated-synthetic media, and the empty/object-only wide role is
supported by real licensed video.

Operator workflow:

```text
make alpha-visual-corpus-validate
make alpha-visual-corpus-prepare
make alpha-visual-regression
make alpha-visual-regression-compare
make alpha-visual-corpus-codec-gate
make alpha-visual-regression-long
```

The 2026-08-29 closure replay processed all 13 admitted clips and 825 frames with no
decode, worker, dropped-frame or queue-backlog errors. Worst per-clip processing p95 was
636.517 ms and pipeline p95 was 771.144 ms. The isolated loopback codec gate decoded the
prepared 2560x1440 HEVC profile without camera access or production-service changes.
The earlier 11-clip bounded long run processed 1,807 media seconds in 143 clip runs with
no decode, worker, duplicate-event or backlog errors and 48.105 MiB RSS growth; it was
not rerun or relabelled as 13-clip sustained evidence. These are observational
regression and performance results, not accuracy labels. No baseline is tracked while
the manifest is `PARTIAL`; promotion must continue to fail closed.

An optional private local overlay has a separate contract and never changes this public
manifest or its readiness. Its tracked descriptor contains only an opaque asset ID,
media facts, scenario IDs and closed review states; the asset mapping, media, sampled
frames, review receipt and results remain under ignored owner-private runtime. A valid
private overlay may report `LOCAL_READY` while this public corpus remains `PARTIAL`, but
private results are prohibited from public baseline generation, comparison and
promotion. See `docs/runbooks/PRIVATE_VISUAL_CORPUS_OVERLAY.md`. Real capture remains a
separately supervised Task 8 action and is not part of the software closure.
