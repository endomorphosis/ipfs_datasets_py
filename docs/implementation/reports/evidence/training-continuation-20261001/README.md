# Training continuation evidence, 2026-10-01

See [the training guide](../../../../autoencoders/reconstruction_training.md) for
APIs, commands, results and limits. `summary.json` contains the compact release
results. `legacy-resume.json` retains the full three-arm continuation report;
the full six-arm current-model report and all twelve scored/probe heads are in
the archive. No candidate was promoted or qualified.

The archive includes the shared native embeddings, source sentences, compiler
weak labels, complete predictions, optimizer reports, saved session and manual
restart bundles, source plans and hashes, actual Lean sources/build logs,
canonical gates, diagnosis and curation, and authentic test logs/JUnit receipts.
It excludes semantic encoder weights, archived teacher weights and `.lake`
build products. Receipt paths preserve their original execution provenance;
archive paths are relative and listed in `artifact-manifest.json`.

All 255 members were verified against their SHA-256 and byte count after the
archive was written. Identical contents use ordinary tar hardlinks (224 unique
payloads). The archive is 15572573 bytes with SHA-256:

```
ab431cde49de86cda2776f33ead23594e0182b117ea48e6c174332415d05f5a5
```

Reconstruct the validated code from package base
`021e499f743b90122551cd781e6d209ad9ffc751` plus the eight owned additions listed
in `release-tree.json`, or inspect their captured bytes under `validated-source/`
in the archive. The isolated validation commit is a local export commit, not a
separately published branch. Unrelated concurrent checkout edits were excluded.

The six tuning examples are exposed development data, repeatedly observed across
three seeds. Compiler agreement is weak labeling; schema Lake builds establish
structural validity, not legal meaning. The eight schema builds and one canonical
`lake build Legal` do not grant qualification to these models. Bridge metrics
were disabled throughout; there is no bridge-on speed result. The Constitution
remains unformalized.
