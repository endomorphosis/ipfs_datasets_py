# Complete physical U.S. Code rows for DuckDB and portable releases

Implemented and qualified for offline source delivery, 2026-09-26. This adds an actual text and provenance
package for the pinned release's complete declared corpus family. It does not
establish complete federal-law coverage or formalization. Native training
validation remains deferred.

## Why this is the next integration

The existing inventory, source partitions and embedding receipt set bind whole
release membership. Selected training packages and the existing summary export
do not expose every original row as queryable text. The selected-input extractor
also rejects aliases and excludes ineligible rows; it cannot provide a complete
source export. Existing Hugging Face release builders collect full row lists and
tables. The new adapter reuses the canonical source decoder and metadata roots,
then writes bounded Parquet batches without collecting the full text corpus.

This gives DuckDB a local `read_parquet` data source and prepares portable files
for later DuckLake materialization and Hugging Face delivery. Numeric weights
remain local to training workers. This change does not fetch parameters through
Quack or rewrite model versions for every source row.

## Row identity and meaning

Each physical source ordinal produces one row, in the frozen inventory's shard
and row order. `source_row_id` uses the existing inventory identity and physical
selector. Repeated legal IDs, duplicate entry CIDs and aliases are preserved.
Split assignments join through the physical selector; embedding outcomes join
only through eligible input membership. An excluded row never borrows a producer
result from an eligible alias with the same input identity.

The row includes the exact verified record JSON and available published text,
original and effective source dispositions, original shard descriptor, text and
record hashes, canonical identity where known, frozen group/split, alias count,
and the original receipt/result reference. Missing partition information stays
null. Eligible inputs without a receipt-set root have `embedding_status` set to
`unavailable`; `unattempted` is reserved for that explicit sealed disposition.
Ineligible sources use `source_ineligible`. Historical `missing_input` records
do not prove that a source is currently absent.

Invalid wrappers retain their physical rows and dispositions, with unknown
verified fields left null. Original corpus files remain in the package for exact
byte recovery, including malformed records. Text columns contain published text,
not authenticated original OLRC XML or HTML.

Every exported row has `formalization_status="not_observed"`, `formalized=false`
and `admitted=false`. Published retrieval admission labels inside `record_json`
remain historical source claims. They do not satisfy the legal admission gate.
Only `lake build <Lib>` establishes a Lean admit. The Constitution remains
unformalized and is outside this U.S. Code release adapter.

## Portable package and verification

The package contains queryable shards under `data/source_rows/`, original corpus
files under `source/corpus/`, exact provenance roots, producer receipt leaves
and nonmissing producer-input text artifacts. A README exposes an explicit
Hugging Face `corpus` configuration. That physical dataset split is a catalog;
the separate `split` column preserves source partitions without granting training
permission or declaring a held-out result.

The exporter creates a new destination exclusively and writes `source-export.json`
last. Partial failures retain their files without a successful completion result.
Byte and file bounds apply to copied and generated artifacts. Reopening requires
an independently supplied manifest hash, verifies the closed package namespace
and every file, reconstructs the canonical source/provenance objects from package
files, and compares every decoded Parquet row with the regenerated expected row.
Counts alone are insufficient. Final source and output checks reject drift.

The local command `scripts/ops/legal_ir/export_pinned_uscode_corpus.py` takes a
pinned local artifact map and explicit root hashes. It denies networking before
package imports, pins the canonical logic tree, retains before/after source
observations, exports the package and independently reopens it. It runs inside
the existing resource-controlled operation wrapper. No training, downloads,
production database mutation or upload occurs.

## Opportunity cost and limits

| Choice | Benefit | Cost or limit |
|---|---|---|
| One row per physical source occurrence | Prevents hidden gaps and alias collapse | More rows than unique producer inputs |
| Reuse immutable inventory, partitions and receipt roots | Preserves original membership and outcomes | Existing metadata codecs remain resident; this is not zero-copy metadata |
| Reuse the bounded canonical shard decoder | Preserves wrapper and exclusion semantics | One complete bounded shard remains resident despite batched Arrow reads |
| Write bounded Arrow batches to Parquet | Avoids a full-corpus Python text list/table | Conversion, compression and row validation still copy and allocate |
| Retain original corpus and producer evidence | Enables portable verification of raw bytes and claims | Additional storage beyond the query projection; seal at release boundaries |
| Regenerate all rows during independent readback | Detects forged projection data even after hashes are resealed | Adds a full source decode and comparison pass |
| Keep proof observations separate from source claims | Preserves the Lake-only success criterion | This source package alone contains no formalization result |

## Guarded complete-source capture

The [passed audit](evidence/autoencoder_control_plane_plan/uscode-corpus-export-audit-20260926-r2.json)
and [tests](evidence/autoencoder_control_plane_plan/uscode-corpus-export-tests-20260926-r2.json)
bind 392 passing cases, with no failures, errors or skips, to 7,780 package files
and 1,302 dependencies. All source, input, output, harness and protected-checkpoint
guards passed. The semantic gates, five-case pilot and authorized 24-hour deadline
identity check retained their original per-case baselines. No native model,
checkpoint, external prover or Lake job executed.

The [export receipt](evidence/autoencoder_control_plane_plan/uscode-corpus-export-export-20260926-r2.json)
and [DuckDB checks](evidence/autoencoder_control_plane_plan/uscode-corpus-export-query-20260926-r2.json)
verify all 62,931 physical rows across 16 declared corpus files, 62,839 eligible
unique inputs, 92 additional aliases and 59,511 groups. Frozen physical split
counts are train 50,282; validation 6,358; canary 3,147; holdout 3,144. Producer
membership is 51 embedded inputs, 13 token-limit exclusions and 62,775 unattempted
unique inputs (62,867 physical unattempted rows). All 15 DuckDB checks passed,
including exact text/record hashes, group isolation and receipt references.
Historical published retrieval labels are preserved inside record JSON; all
62,931 top-level admission/formalization fields remain false.

| Measured operation | Wall time | Scope |
|---|---:|---|
| Source export | 35.193998 s | 62,931 rows; 0.000559247 s per physical row |
| Independent packaged-source verification | 41.694211 s | Regenerate and compare every row |
| DuckDB queries | 1.878093 s | 15 checks over explicit local Parquet paths |
| Whole CLI invocation | 86.864022 s | Imports, root loading, export, readback and guards |
| Complete guarded capture | 203.722967 s | Stability window, tests, export, queries and final guards |

The package has 103 files totaling 263,671,066 bytes, including 16 query shards
totaling 140,713,155 bytes. Its
[manifest](evidence/autoencoder_control_plane_plan/uscode-corpus-export-package-manifest-20260926-r2.json)
SHA-256 is `02e7534050b95e5971e30767e3d1a4a85b266ee6ea4f0fd4c8a0207d8bfcd19c`.
The full package remains at
`workspace/test-logs/federal-corpus-audits/uscode-corpus-export-20260926-r2/capture-r2/export/run/package`;
only small evidence files are included in Git.

Arrow CPU and I/O pools and DuckDB each used one thread. The owner reserved one
CPU slot, 2,048 MiB and 750,000,000 bytes, including a 100,000,000-byte external
fixture charge. Child lifetime high-water RSS through report construction was
968,085,504 bytes; this is an observation, not a memory-improvement comparison.
The [release](evidence/autoencoder_control_plane_plan/uscode-corpus-export-release-20260926-r2.json)
records 375,622,773 charged attempt bytes and confirms no live owned children.
The campaign limit remains 60,000,000,000 bytes.

The first attempt's [audit](evidence/autoencoder_control_plane_plan/uscode-corpus-export-audit-20260926-r1.json)
and [tests](evidence/autoencoder_control_plane_plan/uscode-corpus-export-tests-20260926-r1.json)
remain failed: all 392 tests passed, but the launcher incorrectly expected 78
receipt-set cases rather than 81, and its three count guards stopped the run
before export. The fresh r2 corrected only that declaration and attempt paths,
and pinned the original evidence and retained claim. No implementation or test
was weakened; the original claim was not released or relabeled.

File-cache state was uncontrolled; this is not a cold-cache benchmark. Metric
disk cache was disabled, bridge names were not invoked, and bridge sample/target
counts are not applicable. These are source I/O times, not legal-IR compile,
bridge-on evaluation or training times, and no baseline speedup is claimed.

## Remaining delivery integration

Next, bind this manifest, exact row schema and explicit shard list to a durable
DuckDB dataset relation managed by the owner. Quack should pass immutable release
descriptors and operation results; numeric training buffers remain local. Use
that same release identity for a durable DuckLake source-table adapter, with
restart, idempotency and lost-reply checks. Existing isolated model-history event
delivery does not qualify corpus-table materialization.

Then create a dataset-specific sealed Hugging Face publication plan using the
existing file-descriptor and publisher infrastructure. The portable package and
its corpus README are ready for that adapter; no upload occurred in this capture.
Production DuckLake ingestion, Hugging Face delivery, Constitution source
integration, source-authority authentication, native training validation and
legal formalization remain unfinished.
