# Producer receipt sets over frozen source membership

Implementation report, 2026-09-26. The new
[`autoencoder_embedding_receipt_set.py`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_embedding_receipt_set.py)
defines one immutable campaign membership artifact over successive bounded
embedding-production receipts. It binds the exact source partitions and one
exact producer profile, records each selected producer result, and retains an
explicit `unattempted` disposition for every remaining eligible input. This
lets a campaign retain one model identity as production advances through the
source release instead of treating each batch as an unrelated model variant.

The guarded offline capture passed **440 tests**, including 78 new receipt-set
cases, and reconstructed the exact 64 inputs of an archived producer receipt
from local pinned Parquet. All 7,749 package source hashes, tests, harness code,
source artifacts and protected checkpoints remained unchanged. No native
embedding execution, autoencoder training or evaluation,
production DuckLake activation or Hugging Face upload is part of this change.
Native validation remains deferred.

The prerequisite is the complete
[source partition artifact](autoencoder_source_partitions.md), frozen before
embedding exclusions. Its physical rows remain the source denominator. The
receipt set stores one disposition per distinct eligible `EmbeddingInput`
identity and derives the physical aliases from that exact partition artifact.
`binding_for(entry_cid)` identifies the requested eligible occurrence, its
unchanged source group and split, and its selected leaf/result ordinal. Source
rows excluded by inventory eligibility remain in the physical source count;
they do not become successful inputs or disappear from reporting.

For the previously frozen pinned release, the source artifacts contain 62,931
physical rows and 62,839 unique eligible input identities. The receipt-set
capture independently retained those counts. The 92 additional physical
occurrences remain aliases with their own source bindings. Coverage summaries
report both unique-input and eligible-physical-row counts for each disposition,
plus the separate excluded-row count. A vector reused by physical aliases does
not count as additional unique producer work. Distinct legal input identities
with the same exact source text remain distinct inputs.

The supported dispositions are `unattempted`, `embedded`,
`token_limit_exceeded` and `missing_input`. Every result in every selected leaf
must appear exactly once at its original result ordinal. Missing or oversized
results remain visible; a root with no unattempted inputs can still have
embedding failures. A failed attempt that produced no valid receipt remains
unattempted in this artifact and needs the separate job ledger for attempt/error
history. The codec does not invent a generic failure status or infer missing
source content from `missing_input`.

At most one selected receipt may own an input. Overlapping retries are rejected
even if they contain equal vectors. An explicit selection of the retained
attempt must happen before sealing; selecting a replacement produces a new
root. This makes retry choice reviewable without rewriting old receipts or
letting completion order choose the authoritative result. The set does not
choose retries, schedule work, merge gradients or reconcile concurrent updates.
Selection is currently at whole-leaf granularity: a one-input retry cannot be
combined with an older multi-input leaf that still owns that input. Retaining
the older leaf's other results requires a complete replacement batch or a
future versioned result-selection contract. Do not manufacture new native
receipts by relabeling archived vectors to work around this restriction.
Before any leaf exists, the source partitions remain the denominator artifact;
the current receipt-set schema requires at least one member.

Each member retains the existing producer limits: at most 256 inputs and
64 MiB of receipt bytes. A set allows at most 1,024 receipts, 65,536 unique
eligible inputs, 64 MiB of root JSON and 4 GiB of declared leaf bytes. Callers
can lower these limits, but cannot raise the hard caps. Descriptor counts,
individual sizes and total declared bytes are checked before leaf resolution.
Leaves are processed sequentially rather than retaining every decoded vector
in memory together. Per-leaf source-selector uniqueness still applies; the set
does not silently relax that production contract.

All selected leaves must have byte-equivalent canonical profile metadata:
model ID, pinned revision, dimension, execution settings including batch size
and execution kind, model/tokenizer asset manifests, producer code SHA and
runtime versions. A receipt from a different batch size or runtime profile
requires a different set even if its model label matches. Input/source
membership and all nonmissing declared source selectors are verified when
building the set. Previously verified leaf and source files are rehashed at
the end so a later resolver call cannot hide mutation of earlier files.

The present embedding codec accepts only the pinned 384-dimensional
`thenlper/gte-small` profile. It does not establish a general multilingual model
registry or qualify other encoders. Multiple autoencoder versions and languages
remain a control-plane/registry requirement: future profiles need explicit
qualification and schema decisions, with separate artifacts for incompatible
models, tokenizers, dimensions or execution policies. Batch identity should not
be substituted for model version identity.

Successful `SourceSampleRecord` provenance continues to name the original
producer **leaf receipt SHA**, preserving existing exact vector/provenance
checks. The set SHA supplies the campaign membership reference; it does not
replace leaf provenance. The source partition SHA independently supplies the
denominator and assignment reference. An immutable produced-record projection
will need both of these identities and explicit source occurrence bindings.

The root uses strict canonical JSON with sorted unique leaf references and an
exhaustive sorted list of eligible input identities. Each input either has no
producer ownership (`unattempted`) or names exactly one known leaf and result
ordinal. Construction and reload revalidate the source partitions against their
inventory. Exclusive save and directory synchronization preserve existing
immutable-file behavior. Reload requires the expected root SHA and supports an
exact expected byte size, rejecting corrupt or noncanonical bytes and unsafe
file indirection through the existing verified-file reader. A caller must obtain
that expected identity from a trusted descriptor; self-consistent hashes do not
authenticate official source authority or the runtime that made a claim.

Verification has explicit scopes:

| Operation | What it verifies | What remains outside its claim |
|---|---|---|
| Metadata-only load and `summary()` | Exact root bytes, profile shape, exact supplied source partitions, exhaustive ownership and denominator accounting | Current leaf/source bytes, model execution and training eligibility |
| `build_embedding_receipt_set` | Root construction from every selected verified leaf, one exact profile, eligible membership and all nonmissing declared source inputs, with final closure rehashes | Absence of missing inputs, authenticated inference, official source authority and job admission |
| `verify_all` | Every current selected leaf, complete ordered result membership, shared profile and every nonmissing declared source input, with final closure rehashes | Source absence, unattempted inputs, global holdout qualification and training admission |
| `verify_records` | Authorized requested source occurrences; exact record/input, selected successful leaf, vector and provenance; selected source selectors and final selected-file rehashes | Unselected leaf/source bytes, global holdout qualification, runtime attestation and job admission |

`summary()` keeps `current_leaf_bytes_verified` and
`current_source_bytes_verified` false: a root cannot carry forward a claim
about the current filesystem merely because its builder checked files earlier.
`verify_all` explicitly returns current leaf verification and a count/scope for
nonmissing source verification. It keeps the generic source-verification flag
false because a `missing_input` disposition does not prove absence. Selected
record verification reports that unselected leaves and sources were not
reverified. Source projection and operation authorization happen before the
selected receipt/source reads, preserving the existing prohibition on using
holdout entries for training or other protected operations.

Homogeneous `injected_fixture` sets are supported for diagnostic tests; they
cannot verify native corpus records. Mixed fixture/native profiles are
rejected. Conversely, a profile declaring `native` remains a declaration, not
cryptographic proof that an inference process ran. Runtime attestation,
authenticated source authority, global holdout verification, training
eligibility and admission are not granted by this codec. Source partition
assignment also does not prove independence from historical checkpoint data.

The intended control-plane use is to store compact immutable references in
DuckDB through the existing Quack interface and, where configured, DuckLake.
A campaign advances by registering a new root reference with explicit parent,
model-variant and job bindings. The control plane stores exact root and leaf
references. Leaf receipts and their vector payloads remain immutable artifacts;
they do not need to be rewritten or placed in every sparse weight update.
Stage bounded leaf receipts as production completes, then seal at explicit
campaign or checkpoint boundaries. Resealing after every batch would rewrite
metadata proportional to the entire eligible input universe. Independent
workers can produce disjoint bounded receipts, while the owner selects attempts
and seals a consistent root. This module supplies
the artifact contract only; transactional registration, concurrent publication
policy and owner/worker integration are not implemented here.

The efficiency opportunity and remaining costs are bounded:

| Choice | Benefit | Cost or limitation |
|---|---|---|
| One exhaustive root over bounded leaves | Retains coverage across batches and one exact producer profile | Every new root still serializes the eligible input universe; it is not a constant-size incremental update |
| Compact control-plane references | Avoids sending vector payloads with routine job/status/sparse-weight updates | Requires durable artifact resolution and later explicit job bindings |
| Sequential full verification | Bounds simultaneous decoded leaf data and catches source/leaf mutation | Reads and rehashes all selected leaves and nonmissing sources; closure costs grow with the campaign |
| Requested-record verification | Avoids loading unrelated leaves and staging unrelated source inputs for a bounded batch | Each selected leaf is still loaded and validated in full; the claim is deliberately limited to requested records/sources |
| Immutable source partitions | Preserves assignment when producer failures remove vectors | Current construction/reload revalidates the complete inventory/grouping; repeated loads can become a setup cost |
| Separate optional Arrow weight path | Can support training-local arrays and bounded updates without database weight churn | This JSON receipt-set codec adds no zero-copy weight or vector path and establishes no end-to-end speedup |

The [offline audit](../../../workspace/test-logs/federal-corpus-audits/embedding-receipt-set-20260926/probe-r2/audit-receipt.json)
and [artifact probe](../../../workspace/test-logs/federal-corpus-audits/embedding-receipt-set-20260926/probe-r2/probe/receipt-set-report.json)
reuse the existing 434,558-byte producer leaf, SHA-256
`0ec481a6f3a51041d72c95c3ee7f7971463404cba22ee48a3c6ed1d201c9e0fa`.
Its historical native declaration is preserved; the probe performs no inference
or new native qualification. Exact reconstruction verified all 64 original
inputs, and full leaf verification rechecked their source selectors. The set
contains one real archived leaf; the multi-leaf case is covered by an explicitly
injected 258-input/two-leaf test, not a new production campaign.

| Disposition | Unique inputs | Physical eligible occurrences |
|---|---:|---:|
| Embedded | 51 | 51 |
| Token limit exceeded | 13 | 13 |
| Missing input | 0 | 0 |
| Unattempted | 62,775 | 62,867 |

The immutable root is **9,557,340 bytes**, SHA-256
`fdeb6de13bfa66914baad8703f2caa85694d17c2d2c6a3024e275f5984cf95c7`.
It binds the unchanged 12,187,351-byte source partitions, SHA-256
`12700969970aac52107eb570167fc09da6e326536335d9e1c00c61b73c9bf45d`.
This makes the cost of resealing the full denominator concrete: even this
single-leaf campaign root is about 9.6 MB. Store its reference in routine
control updates and avoid unnecessary new roots.

| Separately timed preparation phase | Wall seconds |
|---|---:|
| Inventory load | 1.144742 |
| Source partition load/revalidation | 2.876603 |
| Exact reconstruction of 64 source inputs | 3.701534 |
| Receipt-set build, including partition revalidation | 6.209541 |
| Root save | 0.027265 |
| Root reopen/revalidation | 3.115489 |
| All declared leaf/source verification | 0.079130 |
| Decode 51 archived records and validate all 64 sources | 0.046325 |
| Verify one selected training-partition record | 0.046483 |

These are individual measured phases from one process. The full probe took
18.895245 seconds, the offline tests 5.929941 seconds, and the resource-wrapped
capture 34.632413 seconds; those enclosing durations are not additive to the
phase table. The selected record was the first embedded archived input whose
new frozen source assignment is training (10 U.S.C. § 7657). Its original leaf
provenance remained unchanged. The probe did not reuse the older batch's split
assignments or establish a held-out result.

One worker used one reserved CPU slot under a 2,048 MiB cooperative RAM limit
and 250 MB disk reservation. The attempt occupied approximately 17.5 MB when
released. Five-second RSS observations are not a peak-memory measurement.
OS page-cache state was uncontrolled: no cold-cache claim is made. The metric
disk-cache flag was `0`, bridge names were `[]`, prover evaluation was false,
and the configured worker count was one; no bridge evaluation occurred. These
are source/artifact preparation timings, not per-span formalization or
bridge-on model evaluation timings and not an end-to-end speed comparison.

The [regression receipt](../../../workspace/test-logs/federal-corpus-audits/embedding-receipt-set-20260926/probe-r2/tests/embedding-receipt-set-tests-r1-receipt.json)
records 440 passed, zero failures/errors/skips. Cases cover aliases and excluded
rows, dispositions, profile mismatches, overlap, corruption/symlinks, bounds,
protected splits, exact vectors/provenance and mutation of earlier files by
later resolvers. Selected-only verification succeeds with unrelated leaves
and source files absent. The
[resource release](../../../workspace/test-logs/federal-corpus-audits/embedding-receipt-set-20260926/probe-r2/resource-release.json)
confirms durable evidence, no surviving child process and released reservations.
The [closeout](evidence/autoencoder_control_plane_plan/embedding-receipt-set-closeout-20260926-r2.json)
binds these artifacts and the final source/protected-artifact guard. An earlier
capture also passed its run-time guards, but a later external edit to
`logic/autoformal/supervisor_router.py` invalidated that attempt's current-tree
closeout. Its evidence remains preserved. This second capture repeated the
offline checks and passed the immediate closeout against the new source revision;
the receipt-set artifact is byte-identical across both captures.

Measure larger sets and peak memory before adding guarded session reuse.
Selected verification avoids a full coverage-summary
scan, but each new root build/load still revalidates the complete partitions.
Long-lived guarded session reuse is future work. Compare artifact/database
bytes written per accepted sparse update as well as training wall time. Never
attach or rewrite the full root payload in those sparse updates. Cached objects
must remain tied to exact source, partition, producer and code identities;
bypassing provenance checks is not a speed optimization. A future paged
coverage codec or incremental validation scheme requires an explicit version
and must preserve the exhaustive denominator and verification contract. The
current hard caps will require a separately designed hierarchy if a corpus
outgrows this bounded release. The codec alone cannot remove parser/bridge
costs or qualify an Arrow backend switch.

The subsequent [immutable produced-record projection](autoencoder_produced_record_projection.md)
now preserves the complete source partition identity, explicit eligible
occurrence bindings and selected producer leaf provenance. Its follow-up
verification also captures resolver paths once per call before final file
rehashes; fresh byte checking remains required. Next are explicit v8 variant,
job, staged-artifact, worker, owner and daemon bindings, then durable control
plane registration and publication closure. Existing v1–v7 contracts remain
unchanged; in particular, their single-producer binding must not silently become
a receipt-set binding. A Hugging Face package must carry enough exact artifacts
to restore and verify its declared closure, rather than publishing a root that
cannot resolve its members.

This offline artifact/test evidence establishes the codec's checked behavior only.
Any later training qualification must still preserve source and checkpoint
provenance, bridge names, prover/cache flags, worker/sample counts and the
existing semantic gates. A bridge-disabled result is not a legal-IR speed
measurement. No compile, vector, target, database row, autoencoder loss or
decompiled sentence is a Lean admit. Temperature remains 0, context is not
raised, no Mathlib is imported and no weights are downloaded for this work.
The Constitution remains unformalized and cannot receive `roundtrip_ok`; only
actual `lake build <Lib>` evidence can provide the required Lean admission.
