# Bounded entity snapshot re-import

Entity snapshot re-import now selects at most 64 local keys before joining rich
entity/context fields. Both sides of that join are restricted to the selected
IDs and key range. Empty intersections advance to the next window. Complete
snapshot validation, immutable-field/context equality, local claim ownership,
transaction rollback and the final file hash check remain unchanged.

The focused capture passed **152 tests and 12 separate output-decoder checks**.
Ten added cases exercise sparse/empty overlap, page boundaries, late conflicts,
claim preservation, remote-only IDs and rollback after final hash failure. The
existing semantic gates and historical roundtrip pilot also passed.

A subsequent source-only capture independently verified **180,257 original
entities and contexts**, **120,136 relationships** and **360,516 snapshot rows**.
Re-importing the snapshot into the reopened database left all five table counts
and content digests unchanged. This verifies same-database observation; it does
not qualify restoration into a fresh database or formalization of those rows.

## Observed full-corpus comparison

| Phase | Previous R2 | Bounded-window R3 |
|---|---:|---:|
| Snapshot self-observation | 196.773 s | 103.969 s |
| Whole child operation | 545.018 s | 439.092 s |
| Whole audit including provenance/quiet window | 630.679 s | 522.211 s |
| CLI export with validation | 117.279 s | 112.882 s |

The measured self-observation took **47.2% less wall time**. This is one paired
full-overlap comparison with identical pinned inputs and unchanged independent
oracles. Filesystem caches were **uncontrolled**; this is not a cold-cache or
repeated statistical benchmark. Other phases also varied, so the whole-audit
difference should not all be attributed to this query change. It establishes
no native model-training or legal-IR evaluation speedup.

Both source runs used one CPU, a 750 MB storage reservation, a 1 GiB memory
bound and a 1,200-second deadline under the approved **62 GB campaign cap**.
The per-worker 50 GB policy is unchanged. The source corpus contains entities
and relationships, not a count of formalized legal spans. Bridge names, prover
settings, metric-cache state, sample-memory scoring and wall time per legal span
or bridge-on evaluation are not applicable: those operations did not run.

## Memory and evidence limits

The previous R2 receipt passed periodic checks but its reported lifetime peak
exceeded 1 GiB; its original receipts and released reservation remain unchanged.
R3 adds a terminal Linux reaped-child lifetime-peak check before accepting the
source result or releasing its reservation, alongside periodic combined-group
RSS checks. Two stdlib boundary checks verify that exactly the limit passes
and one byte above it fails.

R3's terminal and child-reported peak was **1,070,927,872 bytes**, below the
**1,073,741,824-byte** limit by only **2,813,952 bytes**. This run met the bound;
it does not establish comfortable memory headroom or a kernel-enforced quota.
The child exited, its reservation was released, all 79 prior ledger records
were preserved, and the original failed R1 claim remains retained. The source,
dependency, protected-checkpoint and independent content guards all passed.

## Cost of sparse observations and next step

Local-key paging visits every local window even when the remote snapshot is
empty or sparse. That can add empty comparisons; sparse-import latency was not
measured here. This change's performance result applies to complete
self-observation with equal local and remote entity sets. It is not a benchmark
of sparse autoencoder weight updates.

Before changing the traversal again, compare empty, sparse, foreign-heavy and
full-overlap fixtures under the same validators. Remote-first paging reduces
the number of comparison windows when remote observations are sparse but can
increase that count when remote rows are mostly foreign. Selecting the smaller side or materializing a narrow key
intersection adds complexity and, in the latter case, temporary storage. Keep
the current transactional and final-hash barriers in every option.

Native model/checkpoint validation and actual Hub uploads remain deferred.
No model, prover, Quack listener, native DuckLake operation or Lake build ran in
this source-only capture. Only Lake can supply a Lean admit. The Constitution
remains unformalized.

## Receipts

- [Focused tests](evidence/autoencoder_control_plane_plan/entity-v2-resume-window-tests.json) and [decoder checks](evidence/autoencoder_control_plane_plan/entity-v2-resume-window-decoder.json)
- [Full-source audit](evidence/autoencoder_control_plane_plan/entity-v2-source-r3-audit.json) and [independent source receipt](evidence/autoencoder_control_plane_plan/entity-v2-source-r3-receipt.json)
- [Terminal boundary checks](evidence/autoencoder_control_plane_plan/entity-v2-source-r3-peak-boundary.json) and [resource release](evidence/autoencoder_control_plane_plan/entity-v2-source-r3-release.json)
- [Earlier export change and R2 qualification limits](entity_cache_export_memory.md)
