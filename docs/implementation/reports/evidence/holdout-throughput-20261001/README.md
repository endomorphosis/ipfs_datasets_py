# Holdout and throughput evidence, 2026-10-01

The [training guide](../../../../autoencoders/reconstruction_training.md) gives
public APIs, thread settings, commands and measured limits. `summary.json`
contains all six fresh held-out formula outcomes and both throughput campaigns.
The augmentation is not promoted: its exact held-out rules worsen at two seeds,
even though token loss improves. All failed predictions are retained.

The archive contains full checkpoints, native embeddings and source joins,
compiler weak labels, generated formulas, losses, optimizer reports, source
plans, cross-lineage freeze barrier, profiling probes, raw diagnostic records,
authentic test receipts, and actual Lean files/build logs. It excludes archived
teacher weights, semantic encoder weights and `.lake` build products. The
139 MB legacy development record is retained once inside the compressed archive;
its field-size receipt explains why it is large. No compact receipt replaces
or discards that underlying evidence.

There are 482 verified archive members and 413 unique payloads.
Byte-identical files use ordinary tar hardlinks. Every payload and hardlink was
verified against the relative SHA-256/byte manifest after writing, using a
streaming read. The archive is 19904875 bytes with SHA-256:

```
610bed9a3190f45f572d06c8aa16348d3299dbdcfc833da69f38fe18da17bcce
```

Original absolute paths in receipts preserve execution provenance; archive
paths are relative and listed in `artifact-manifest.json`. Reconstruct the
validated code from package base `43c8c6e42690d82798ddd12d19c454de98d72a2e`
plus the thirteen listed additions in `release-tree.json`. Captured sources
are also under `validated-source/`. The isolated validation commit is local,
not a separately published branch. Unrelated checkout edits were excluded.

`tests.json` counts 340 unique passing tests from the final suites. Earlier
failed test/profiling attempts are retained and explained in
`execution-attempts.json`; they are not counted as passing. All six current
heads and both legacy trained models were frozen before either evaluator
opened the sealed sources. These eight sources are now exposed development
data for any later training choice, not reusable independent holdouts.

Sixteen generated-schema builds and one canonical `lake build Legal` pass.
Those structural results coexist with wrong generated formulas. Compiler
weak labels, numeric loss, and schema builds do not establish legal meaning
or full logic-family qualification. Bridge metrics were disabled, so these
are training throughput measurements, not bridge-on legal-IR speed claims.
The Constitution remains unformalized.
