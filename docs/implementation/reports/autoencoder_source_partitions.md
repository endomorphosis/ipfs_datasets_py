# Source partitions frozen before embedding exclusions

Implementation report, 2026-09-26. The complete pinned U.S. Code inventory now
has a source-only partition artifact covering all **62,931 physical rows**.
The final offline capture passed **362 checks** and materialized the first
three eligible entries of its frozen training partition. No embeddings,
autoencoder training, checkpoint evaluation or publication ran.

This follows the [whole-release source inventory](autoencoder_uscode_source_inventory.md).
Existing `CorpusIndex` v1 groups embedding-bearing records. Its group IDs include
every key in a connected component, so rebuilding it after filtering failed or
oversized inputs can change assignments. The new
[`autoencoder_source_partitions.py`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_source_partitions.py)
freezes the complete source grouping first, without placeholder vectors or
changes to existing index/job schemas.

Every physical shard/ordinal has its own source-row identity, bound to the
inventory SHA. The unchanged grouping algorithm connects canonical document
lineage, exact extracted-text SHA and normalized-content SHA. A Parquet shard
hash is not a text grouping key. Excluded rows remain connectors whenever their
metadata is available; incomplete source coverage or grouping metadata refuses
partition construction. Verified empty text contributes grouping keys without
requiring a valid embedding input. Duplicate entry CIDs remain unselectable.

The codec stores immutable canonical partition bytes and rederives every group
and assignment from the supplied inventory on load. Expected artifact hashes
must come from a trusted descriptor: metadata consistency is not official source
authentication. Limits remain 65,536 physical rows and 64 MiB of partition
metadata. The inventory and partitions are separate immutable artifacts.

`entry_cids_for` preserves physical order and fails empty requested partitions
without reseeding. `binding_for` identifies a specific eligible occurrence.
`authorize` applies the existing training/validation/canary operation policy;
holdout is not authorized for those operations. `materialize_partition_inputs`
authorizes before source I/O, reuses the existing exact-byte extractor, and
persists a receipt binding partition identity, operation, source selectors,
input IDs, frozen assignments and the underlying inventory-selection receipt.

`project_records` matches supplied `SourceSampleRecord` objects to explicit
entry CIDs through their exact reconstructed `EmbeddingInput` identities. Its
detached result binds record/vector/provenance summaries to the original source
group and split, without regrouping the retained subset. This helper does not
authenticate the producer, reread source bytes or authorize a training job.
The future immutable projection codec and owner/worker integration remain
separate work; this result is not a replacement for `CorpusIndex` v1.

Projection preflights the complete selection before serializing records:
at most 256 records, 1 MiB text per record, 64 MiB total text, 4,096 numeric
entries per vector and 98,304 numeric entries overall. The aggregate numeric
budget fits 256 current 384-dimensional outputs and also permits smaller batches
with larger dimensions. Missing embeddings are rejected. These bounds avoid
the generic source-record codec's much larger per-vector construction limit.

The offline
[`freeze_uscode_source_partitions.py`](../../../scripts/ops/legal_ir/freeze_uscode_source_partitions.py)
requires an exact inventory SHA and explicit seed. It denies sockets before
package imports, checks the canonical tree and source hashes, writes exclusively,
reopens the saved partition artifact and optionally materializes a bounded
training selection. Source-release reload uses the inventory's frozen import
limits, including supported nondefault limits.

The [final audit](../../../workspace/test-logs/federal-corpus-audits/source-partitions-20260926/freeze-r2/audit-receipt.json)
and [partition report](../../../workspace/test-logs/federal-corpus-audits/source-partitions-20260926/freeze-r2/partitions/source-partitions-report.json)
record the fixed seed `uscode-source-partitions-5016b86a-v1` with integer policy
80%/10%/5%/5%. Assignment uses connected groups, so row counts need not match
those proportions exactly.

| Frozen assignment | Physical source rows |
|---|---:|
| Training | 50,282 |
| Validation | 6,358 |
| Canary | 3,147 |
| Holdout | 3,144 |

There are **59,511 groups** and **62,839 unique source input identities**.
The 92 additional physical occurrences sharing input identities remain in the
inventory and partitions. Materialization retains the existing prohibition on
duplicate input selectors within a producer batch. Future campaign production
must account explicitly for aliases and exclusions rather than silently dropping
rows or producing unrelated model variants for each shard.

The partition artifact is **12,187,351 bytes**, SHA-256
`12700969970aac52107eb570167fc09da6e326536335d9e1c00c61b73c9bf45d`.
It binds the 47,531,987-byte source inventory with SHA-256
`38734c403fa9b7bbba8b80f8d4c0ac0529327ae4bc9534b9cf56dd59f4d6caef`.
The final artifact is byte-identical to the first successful capture; the later
CLI correction preserves nondefault source limits and does not affect this
default-limit corpus.

| Recorded scope | Wall seconds |
|---|---:|
| Inventory load, partition freeze and save | 6.888522 |
| CLI including reopen, three materializations and final source guard | 14.491483 |
| Offline fixture tests | 4.324428 |
| Resource-wrapped tests and source capture | 26.165341 |

These are nested source-preparation timings, not additive phases or evidence of
a model speedup. One worker process used one reserved CPU slot; source OS page
cache was uncontrolled, so no cold-cache claim is made. The metric disk-cache
environment flag was `0`, but no legal-IR bridges or provers ran. This is not a
per-span formalization or bridge-on evaluation measurement.

The [regression receipt](../../../workspace/test-logs/federal-corpus-audits/source-partitions-20260926/freeze-r2/tests/source-partitions-tests-r1-receipt.json)
records 362 passed, zero skipped/errors/failures. The 87 new cases cover
independent grouping parity, excluded transitive connectors, aliases, strict
artifact integrity, protected operations, exact source-record projection,
pre-serialization limits, source mutation and CLI handling of nondefault limits.
The [resource release](../../../workspace/test-logs/federal-corpus-audits/source-partitions-20260926/freeze-r2/resource-release.json)
confirms durable artifacts and released reservations under the existing budget.
The [closeout](evidence/autoencoder_control_plane_plan/source-partitions-closeout-20260926-r1.json)
binds the evidence and confirms all 7,748 package source hashes, test inputs,
owned code and protected checkpoints unchanged at closeout.

The next integration needs a sealed producer-receipt set and immutable
produced-record projection with source/producer verification, then explicit v8
job, variant, staged-artifact, worker, owner and daemon binding. Preserve v1–v7
contracts. Put immutable inventory/partition references in the existing
DuckDB/Quack control plane, not the full metadata payload in every weight update.
Loading this codec currently revalidates the whole grouping; measure that cost
before introducing guarded session reuse. No per-job default should switch on
the basis of this source-only capture.

These assignments cover one declared release. They do not establish official
source authority, semantic paraphrase isolation, independence from checkpoint
history or a globally held-out evaluation. Native training qualification remains
deferred. Constitution source selectors/frontend, production DuckLake/HF delivery
and semantic coverage remain outstanding. Constitution is still unformalized;
only actual `lake build <Lib>` evidence can supply the required Lean admission.
