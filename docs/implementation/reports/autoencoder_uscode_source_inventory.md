# Whole-release U.S. Code source inventory and bounded input materialization

Implementation report, 2026-09-26. The source-only inventory run verified
all 16 declared corpus shards and all 62,931 physical rows at the pinned dataset
revision, then materialized three exact source inputs. The final `scan-r2`
capture passed 275 regression checks and source/protected-artifact guards after
fixing mixed valid/invalid duplicate-wrapper accounting. Its inventory bytes
equal the earlier `scan-r1` result. Native training and evaluation remain deferred.

This continues the [pinned-source and selection-index milestone](autoencoder_uscode_source_index.md)
and the [federal-law training plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md).
The earlier workflow verified one 1,491-row shard and selected 64 rows. The new
path enumerates the complete declared corpus family before source selection or
embedding production, while retaining the existing bounded extractor and
embedding-input contract. It does not generate vectors, prepare legal-IR
targets, assign partitions, train a model or publish a release.

The implementation is in
[`autoencoder_uscode_inventory.py`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_uscode_inventory.py).
The small accompanying
[`autoencoder_uscode_import.py`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_uscode_import.py)
refactor exposes an internal reader retaining verified duplicate wrapper rows
and original wrapper failures, plus a pure decoder for already verified wrappers.
Public reader duplicate filtering and dispositions remain unchanged.

| API | Implemented behavior |
|---|---|
| `build_uscode_source_inventory(release, *, resolver, limits, batch_size)` | Enumerates every declared corpus descriptor, reads one shard at a time, preserves physical ordinals and dispositions, checks global duplicate entry identities, and rechecks successful shard bytes and the root before returning. |
| `USCodeSourceInventory` | Immutable canonical bytes with `sha256`, `to_bytes`, detached `to_dict`, `summary` and exclusive `save`. |
| `load_uscode_source_inventory(path, *, expected_sha256, expected_size_bytes, limits)` | Checks bounded canonical metadata and exact artifact identity. Reopening does not reread the source release. |
| `materialize_uscode_inventory_inputs(inventory, entry_cids, output_directory, *, release, resolver)` | Requires a complete recorded corpus inventory, revalidates selected physical rows, extracts exact source text and returns existing `EmbeddingInput` objects plus extraction and bound selection receipts. |

Every declared physical ordinal remains represented. Initially missing or
corrupt shards receive explicit statuses and make the inventory incomplete;
they cannot silently reduce its denominator. If a successfully scanned shard
changes while a later shard is being processed, the final rehash fails the
build. Root drift also fails. These boundary checks do not prove the absence
of transient external writes between checks.

Verified wrapper metadata retains row JSON, exact UTF-8 text and normalized
content hashes, text byte counts, and canonical document lineage where
available. Exact source-only `EmbeddingInput.input_id` values are computed while
text is resident. Shared release identity is stored once; no global text or
vector collection is retained. Bad wrappers are not labeled identity-verified.
Excluded overlong rows and verified local duplicates retain available metadata.
Original row dispositions remain separate from global `duplicate_entry_cid`
quarantine; repeated legal/document IDs are not deduplicated merely for repeating.

The scope is **the pinned release's declared corpus family**. Other-family
descriptors and the recovery-exclusion declaration are retained without
claiming those files were scanned. `complete` and
`declared_corpus_closure_verified` describe recorded build-time corpus coverage.
The generic summary sets `current_all_shard_bytes_reverified=false` and
distinguishes `grouping_metadata_complete` from physical coverage. Reopening
metadata is not source authentication. Original official-source verification,
full federal coverage, global holdout verification, training eligibility and
admission remain false.

Materialization checks selected row/shard/byte budgets before rereading,
preserves explicit requested order, compares fresh physical metadata and exact
input identities, and reuses `extract_uscode_rows` and
`validate_embedding_inputs`. Its result exposes `.inputs`, `.extraction`,
`.selection_receipt` and `.selection_receipt_artifact`. The persisted
`inventory-selection.json` binds inventory/root descriptors, ordered entry/input
IDs, selected shards and the extraction receipt. Source files contain the exact
published text field, not authenticated original OLRC XML/HTML.

The selection receipt verifies current selected bytes and explicitly records
`unselected_current_shards_reverified=false`; it does not renew the inventory's
whole-release boundary. Missing, duplicate or ineligible requested entries
fail. There is no mock vector, heading substitution, alternate selection or
incomplete-inventory bypass, and existing output directories are not
overwritten. The returned objects feed the existing embedding producer without
claiming that embeddings were produced or that the inputs qualify for training.

The offline CLI,
[`inventory_pinned_uscode_sources.py`](../../../scripts/ops/legal_ir/inventory_pinned_uscode_sources.py),
takes explicit source root, repository, immutable revision, manifest SHA and
new output-directory arguments, with optional repeated `--select-entry-cid`.
It denies sockets before package imports, checks the workspace tree and source
hashes, and retains an inventory/report with explicit success or failure.
It performs no acquisition, embedding inference, parser/compiler execution,
training or publication.

Bounds are 65,536 declared rows, 256 corpus shards, 4 GiB of declared compressed
corpus bytes and 64 MiB of canonical metadata. Existing per-shard
compressed/expanded and wrapper-record bounds still apply. Materialization is
limited to 256 unique eligible entries and the tighter importer/producer
budgets, including 64 MiB of exact input text. These bounds do not guarantee RSS:
Parquet decoding and canonical JSON validation can hold multiple representations
of a bounded shard or metadata artifact.

The final
[regression receipt](../../../workspace/test-logs/federal-corpus-audits/uscode-source-inventory-20260925/scan-r2/tests/inventory-tests-r1-receipt.json)
and [JUnit output](../../../workspace/test-logs/federal-corpus-audits/uscode-source-inventory-20260925/scan-r2/tests/inventory-tests-r1.xml)
record **275 passed, zero skipped, failures or errors**, with source, selected
test and protected-artifact guards unchanged. The capture reports 2.167669
seconds of wrapper wall time. It ran the inventory, importer, published
embedding-join, embedding-production codec and corpus-index suites with a
verified seccomp socket-denial guard. These were offline fixtures, not native
model production or semantic qualification. The
[inventory tests](../../../tests/unit/optimizers/logic_theorem_optimizer/test_autoencoder_uscode_inventory.py)
cover physical accounting, missing/corrupt inputs, later shard/root mutation,
local/global duplicates, repeated lineage, excluded metadata, exact ordered
materialization, reopening, no overwrite, changed selected source/metadata,
unselected-current-closure limits and strict bounds.

The separate
[acquisition-r2 receipt](../../../workspace/test-logs/federal-corpus-audits/uscode-source-inventory-20260925/acquisition-r2/acquisition-receipt.json)
records complete file coverage for `justicedao/ipfs_uscode` at revision
`5016b86a273ce5e4ffd066c5ae9f5fe494dd417e`: **16 corpus Parquet files totaling
52,219,760 bytes**. Fifteen requested files account for 50,929,559 bytes; the
previously available final shard completes the closure. Only dataset corpus
files were requested, with no vectors or model weights. Acquisition and its
checks took 21.739792 seconds according to that receipt, not row-inventory,
parsing, training or evaluation time. Its
[resource-release record](../../../workspace/test-logs/federal-corpus-audits/uscode-source-inventory-20260925/acquisition-r2/resource-release.json)
records released resources after durable artifacts under the unchanged
50,000,000,000-byte named-root campaign budget.

The failed
[acquisition-r1 receipt](../../../workspace/test-logs/federal-corpus-audits/uscode-source-inventory-20260925/acquisition-r1/acquisition-receipt.json)
remains intact. The installed HF CLI rejected simultaneous `--local-dir` and
`--cache-dir` arguments before transfer. R2 corrected that invocation without
weakening byte checks or increasing limits. File acquisition does not verify
decoded rows or official legal authority.

The [scan-r2 audit receipt](../../../workspace/test-logs/federal-corpus-audits/uscode-source-inventory-20260925/scan-r2/audit-receipt.json)
and [inventory report](../../../workspace/test-logs/federal-corpus-audits/uscode-source-inventory-20260925/scan-r2/inventory/inventory-report.json)
record the corrected implementation's complete scan on 2026-09-26; the audit directory retains its
20260925 name. All 16 declared shards verified, all 62,931 declared rows were
scanned, and every row had `ready_published_text` status. There were zero duplicate
entry CIDs and complete grouping metadata. `eligible_input_count=62931` means
source-input eligibility only: token limits, embedding production, global split
membership and training qualification were not established.

The canonical inventory is **47,531,987 bytes**, within the unchanged 64 MiB
metadata bound, with SHA-256
`38734c403fa9b7bbba8b80f8d4c0ac0529327ae4bc9534b9cf56dd59f4d6caef`.
The first three physical rows of `data/corpus/part-000015.parquet` were
materialized and validated through the existing exact-byte input contract. Their
[selection receipt](../../../workspace/test-logs/federal-corpus-audits/uscode-source-inventory-20260925/scan-r2/inventory/selected-inputs/inventory-selection.json)
binds the inventory, release, selected shard and ordered input IDs, and explicitly
leaves `unselected_current_shards_reverified=false`.

| Recorded scan-r2 scope | Wall seconds |
|---|---:|
| Inventory build, save and summary | 18.615990 |
| Inventory CLI, including three materializations and source guard | 21.984275 |
| Resource-wrapped regression and complete scan | 32.127501 |

These are nested source-processing measurements, not additive phases or
parser/span, bridge-evaluation or training timings. No comparative speedup is
claimed. Source OS page-cache state was uncontrolled: this is not a cold-cache
claim. The source scan used one worker process, 64-row Parquet read batches and
one reserved CPU slot. `IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE=0` was set, but
no bridge names, provers or checkpoint evaluation ran. The combined capture
passed 275 checks with no failures, errors or
skips, and all 7,747 package Python sources, selected tests and protected
artifacts stayed unchanged across its tests and scan. The audit receipt is
13,153 bytes with SHA-256
`af12c5265580b92e8a0bfb2c7588523d36242ffd78033cb2b4b43c42e2d79192`.
Its [resource-release record](../../../workspace/test-logs/federal-corpus-audits/uscode-source-inventory-20260925/scan-r2/resource-release.json)
confirms release after durable evidence, no live child processes at final
accounting, and compliance with the existing named-root campaign budget.

Review found that the public importer's legacy duplicate disposition can
overwrite an invalid occurrence when the same CID also has two verified
wrappers. The private reader now retains original wrapper failures separately;
the inventory preserves those failures while still excluding every duplicate
occurrence. Four regression cases cover invalid wrapper, hash, JSON and identity
failures, and check that public importer behavior stays unchanged. `scan-r2`
qualifies this correction. The retained `scan-r1` inventory has exactly the same
bytes because this release contains no duplicate entry CIDs.

The [closeout](evidence/autoencoder_control_plane_plan/uscode-source-inventory-closeout-20260926-r1.json)
binds these receipts, inventory and code identities. It also verifies all 7,747
source hashes, test inputs, acquired source files and protected checkpoints
unchanged at closeout. This is a recorded boundary, not a guarantee against
later workspace edits or authority to reuse stale producer targets.

The subsequent [source-partition milestone](autoencoder_source_partitions.md)
implements partition freezing over this complete declared release. Existing
`CorpusIndex` membership binds exact source/sample/vector records. Its connected
group identity includes all group keys, so independently rebuilding indexes
after embedding exclusions can move assignments. Freeze one complete source
grouping before production, preserve exclusions and assignments, then bind
bounded produced records without reseeding. Exact text/document grouping still
does not establish semantic paraphrase isolation or unseen model lineage.

Broader same-variant training also requires a bounded producer-receipt-set root.
Current v6/v7 variants pin one immutable producer receipt with a 256-input bound.
The extension needs exact membership in a sealed set of bounded receipts and
owner/worker verification. Raising one receipt's bound or creating unrelated
variants per shard is not equivalent. Existing shared target/report codecs and
failure accounting can then reuse that source/split/producer membership.

Attempting all 62,931 rows needs at least **246 bounded producer batches** under
the current 256-input limit; aggregate byte budgets may require more, and token
exclusions will change produced membership. Keep the 47.5 MB inventory immutable
in artifact storage and send its identity through the DuckDB/Quack control
plane. Rewriting that metadata per weight update would add avoidable storage
churn. The current materializer reparses and validates the complete inventory
per call; measure that cost before introducing session reuse or an index. Any
reuse must retain the exact verified inventory identity, frozen membership and
current selected-source checks. No corpus-training throughput estimate follows
from this source-processing measurement.

Constitution source inventory, original byte selectors and a source-aware
training frontend remain separate work. Production conversion still requires
English U.S. Code. This milestone leaves Constitution `formalized=false`, grants
no `roundtrip_ok`, and supplies no Lean admission. Only an actual
`lake build <Lib>` provides the required Lean admission evidence.
