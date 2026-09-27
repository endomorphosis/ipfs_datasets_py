# Bounded entity snapshot export and full-source integrity

The entity v2 snapshot exporter now combines already validated 64-row pages
into Arrow row groups bounded by 1,024 rows and 8 MiB. It flushes at each record
kind boundary and releases the writer before reopening the snapshot for
validation. The reader closes explicitly on success and failure. The schema,
row order, validation limits, input bindings and atomic publication remain
unchanged.

The guarded focused capture passed **142 tests and 12 separate CLI-output
decoder checks**. The semantic gates, empty-vocabulary abstention and historical
roundtrip pilot passed. The harness accepts only the exact canonical-tree pin
preamble followed by one bounded JSON record; it does not suppress arbitrary
output or permit HACC imports.

The full-source retry independently compared all **180,257 entities** and their
contexts against the original pinned files, projected **120,136 relationships**,
and compared all **360,516 snapshot rows**. Reopening the same database and
importing its snapshot preserved all five table counts and content digests.
This is a same-database observation check; fresh-database restoration is not
qualified. These source entities are not a census of formalized federal laws.

## Resource qualification

The raw audit passed its periodic RSS and disk checks. The child lifetime peak
was **1,077,260,288 bytes**, exceeding the **1,073,741,824-byte** bound by
**3,518,464 bytes**. Therefore **strict 1 GiB memory qualification failed**.
The original passing audit and released reservation are preserved as recorded;
the separate resource assessment makes this limitation explicit. Future source
captures must check the reported lifetime peak before releasing their claim.
No failed historical reservation was released or rewritten.

The retry used the approved 62 GB campaign cap, unchanged 50 GB per-worker cap,
one CPU, 750 MB storage reservation, 1 GiB memory bound and 1,200-second wall
limit. It finished in **630.679 seconds** including provenance and quiet-window
checks; the child operation took **545.018 seconds**. Sources and dependencies
remained unchanged during capture. Native training and Hub uploads remain
deferred.

## Observed cost

| Operation | Seconds |
|---|---:|
| Resumed CLI ingestion (after 1,536-row prefix) | 18.080 |
| Containment preparation | 73.133 |
| Snapshot export including validation | 117.279 |
| CLI total (includes preceding three rows) | 208.665 |
| Independent original-row/context readback | 103.020 |
| Independent snapshot readback | 8.969 |
| Resume summary | 22.348 |
| Snapshot self-observation | 196.773 |

The snapshot shrank from **60,087,631** to **28,899,436 bytes** for the same
pinned source inputs. Footer lengths are recorded in the resource assessment.
The older run failed before independent readback, and filesystem caches were
uncontrolled. Its export took 111.283 seconds; this retry does **not** demonstrate
faster export or an end-to-end training speedup. Snapshot self-observation is a
measured expensive phase. Its repeated broad joins are a candidate for bounded
key-window validation, with exact conflict and rollback tests required.

During the full-source retry, no compile, model, bridge evaluation, prover,
Quack listener, native DuckLake operation, Lake build or Hub upload ran. Bridge names, prover/cache flags,
worker count and wall time per legal span/evaluate are not applicable to this
source-only capture. No legal-IR speed claim or admit is made. The Constitution
remains unformalized.

## Evidence

- [Full-source receipt](evidence/autoencoder_control_plane_plan/entity-v2-source-r2-receipt.json)
- [Raw audit](evidence/autoencoder_control_plane_plan/entity-v2-source-r2-audit.json) and [recorded release](evidence/autoencoder_control_plane_plan/entity-v2-source-r2-release.json)
- [Resource assessment and exact artifact hashes](evidence/autoencoder_control_plane_plan/entity-v2-source-r2-resource-assessment.json)
- [Focused tests](evidence/autoencoder_control_plane_plan/entity-v2-export-memory-tests.json) and [decoder checks](evidence/autoencoder_control_plane_plan/entity-v2-export-memory-decoder.json)
- [Prior cap migration and failed attempt](campaign_storage_cap_62gb.md)
