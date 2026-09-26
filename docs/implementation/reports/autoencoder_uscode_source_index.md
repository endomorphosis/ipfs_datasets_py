# Pinned U.S. Code inputs and a frozen cross-batch index

Implementation milestone, 2026-09-25, continuing
[verified corpus batches](autoencoder_verified_corpus_batches.md) and the
[federal-law training plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md).

## Source adapter

The new `autoencoder_uscode_import.py` adapter reads the explicitly pinned
`publicus-ir-graphrag/v2` direct-root manifest profile. It verifies the raw
manifest SHA and the publisher's separate body digest, resolves only explicitly
selected family descriptors, checks shard bytes and Parquet schema, and decodes
bounded batches of the five wrapper columns. Row JSON hashes, wrapper/payload
identities, canonical legal IDs and release points must agree. Recovery rows,
missing text, malformed rows and unsupported identities remain explicit
dispositions; the adapter does not substitute headings or citations for text.

Canonical identity reuses `uscode_identity.py`, retaining appendix, note,
granule, edition, subsection and range distinctions. Document grouping removes
edition for cross-release lineage while the original legal identity and edition
remain in the import receipt. The corpus's `entry_cid` values in this profile
are typed `sha256:` identifiers; they are not relabeled as CIDv1/IPFS roots.

Extracted UTF-8 files contain the exact published `text` field. Their receipt
links the pinned HF revision, root manifest, shard, physical row ordinal, row
JSON hash and derived text hash. They are dataset-derived text artifacts, not
verified original OLRC XML bytes. Historical `source_checksum` values can be
synthetic, and the publisher's `verification_result` can default to `verified`.
Those fields are retained as unauthenticated claims. The retrieval disposition
named `admitted` is never interpreted as a Lean admit.

Extraction and embedding joins revalidate their input row objects against the
pinned root and physical shard rows. A caller cannot change an in-memory text,
CID, row position or source claim while retaining the original provenance
labels. Revalidation groups selected rows by shard, so it rereads each relevant
shard once per operation instead of once per selected row. Checked file handles
are hashed before and after decoding to detect changed input bytes.

## Embedding joins

`autoencoder_uscode_embeddings.py` checks all rows of the explicitly supplied
vector shards and joins by exact published entry identity. It verifies row
integrity, model/revision/vector-space agreement, dimension, finite values and
normalization; duplicates and missing matches stay visible. It does not select
the first vector per CID or invent chunk order/selectors. Uniqueness concerns
the scanned selection, not the rest of the release.

The inspected vector profile omits the exact input hash, projection settings,
actual backend receipt and binding to the producer's model artifacts. Existing
producer code can use a deterministic projection while retaining the named
model's identity. Therefore a successful published-identity join still reports
`missing_input_binding` and **zero corpus-training eligibility**. Finding the
same model revision already cached locally cannot repair that missing evidence.

Actual supplied vectors can be exposed explicitly for diagnostic inspection;
no mock fallback or `EmbeddingProvenance` is fabricated. Corpus assembly rejects
these vectors. This milestone neither regenerates embeddings nor trains a model.

## Frozen index

`autoencoder_corpus_index.py` stores bounded immutable record summaries rather
than full text or vector arrays. It binds exact source-aware record identities,
sample/vector digests, source selectors, release metadata and declared embedding
provenance. It forms transitive groups by legal document across releases, source
artifact and normalized content using hash-indexed unions, avoiding the existing
split builder's pairwise near-duplicate scan.

A fixed seed and integer split proportions determine train, validation, canary
and holdout assignments before any model evaluation. Empty partitions fail when
requested; there is no automatic retry with a new seed. Batch verification
recomputes record summaries and enforces training and validation membership.
Canary and holdout rows cannot enter either training or line-search validation.
The index reuses the existing split-operation vocabulary.

The bound is 65,536 summaries and 64 MiB of index bytes. Declared release roots
and selection identity are part of the index scope. Source-byte verification
remains the source adapter/batch manifest's responsibility. The index establishes
separation only within its declared selection; it does not establish semantic
paraphrase isolation, complete amendment lineage, unseen checkpoint history,
global held-out generalization or full federal coverage.

At this milestone the index was an explicit preparation/dispatch guard.
The subsequent [v5 job integration](autoencoder_indexed_training_jobs.md)
requires a pinned index and enforces it independently in owner and worker,
with an immutable variant binding across runs. Existing v4 bytes remain
unchanged and do not automatically acquire that index contract.

## Native qualification

The [native audit receipt](evidence/autoencoder_control_plane_plan/uscode-source-index-20260925.json)
passed on the pinned workspace tree. It used the
[publisher manifest at the fixed HF revision](https://huggingface.co/datasets/justicedao/ipfs_uscode/blob/5016b86a273ce5e4ffd066c5ae9f5fe494dd417e/manifest.json),
`data/corpus/part-000015.parquet` and its corresponding vector shard. The
[acquisition receipt](../../../workspace/test-logs/federal-corpus-inputs/5016b86a273ce5e4ffd066c5ae9f5fe494dd417e/acquisition-20260925.json)
records the three downloaded artifacts: 7,513,188 bytes total, with exact sizes
and SHA-256 checks. No model weights were downloaded.

| Check | Observed result |
|---|---|
| Corpus wrappers, identities, text and hashes | 1,491 rows scanned; all `ready_published_text` |
| Published source/vector identity joins | 1,491 unique joins; all `missing_input_binding`; zero training-eligible embeddings |
| Extracted selection | First 64 usable rows in physical shard order, chosen before model evaluation |
| Frozen partitions | 54 train, 3 validation, 1 canary, 6 holdout; 64 groups |
| Saved diagnostic batch | 57 train/validation records; seven protected records excluded |
| Reopen checks | Exact batch/index verification reproduced; source bytes rechecked |
| Rejection checks | Protected partition rejected for training; unqualified vectors rejected by corpus mode |
| Retained audit artifacts | 3,173,376 bytes, plus the 344,395-byte audit receipt |

The manifest declares 62,931 corpus rows across 16 shards. This run verified
one complete shard, not the full release or official OLRC source provenance.
Those declared counts belong to this revision and must not be combined with
the historical 60,077/60,068-row source/retrieval receipts.

Reported local audit time was 2.1646 seconds: source reading 0.2838 seconds,
embedding audit 1.0688 seconds, extraction 0.4990 seconds, and index construction
0.0196 seconds. These are input-validation timings after earlier file inspection;
OS caches were not evicted. They are **not** compiler, training, per-span or
bridge-on evaluation timings. No bridges, provers, model inference or training
ran, and no held-out canary was qualified. The reported zero eligibility is a
provenance rejection, not a faster legal-IR result.

The importer, embedding join, frozen index and existing corpus-manifest suites
passed together: **189 tests in 0.72 seconds**. They cover byte tampering,
forged in-memory source/release objects, ambiguous joins, resource bounds,
cross-release grouping, split intrusion and immutable reopen behavior.

## Opportunity cost and next steps

The bounded acquisition selected approximately 7.5 MB of metadata and source/
vector shards, rather than fetching an entire release or any model weights.
Verification work is amortized per shard, and row decoding uses bounded Arrow
batches. Published vectors live inside `record_json`, so this wrapper does not
offer zero-copy numeric vector access. A future Arrow materialization should
decode these bytes once and preserve exact identities; changing storage cannot
supply the missing embedding-input evidence.

First try to recover existing embedding input/backend receipts for the exact
published vectors. If those are unavailable, the next corpus-training
prerequisite is an explicit embedding production
receipt binding exact source chunks, ordered selectors, normalized input hash,
tokenization/truncation, actual backend, model/tokenizer/pooling artifact hashes
and vector bytes. Existing cached weights may support a separately qualified
regeneration path without downloads. Regeneration must retain the current
context limit and make every truncation or chunk boundary explicit.

Then bind the frozen index into the durable owner/job contract, reconcile the
selected source release with official-source provenance, and prepare shared
targets from that exact membership. Corpus-wide split freezing requires the
complete selected source inventory and explicit lineage relationships. Continue
the reviewed held-out canary, aggregate resource reservations, DuckLake adapter
qualification and HF release packaging from the master plan.

| Next implementation | Benefit | Cost and acceptance evidence |
|---|---|---|
| Bind index artifact and selection to owner/job schemas | Parallel batches cannot silently choose different split assignments | Preserve historical job identities; reject mismatched selection, changed index bytes and protected rows in owner and worker tests |
| Recover producer evidence, or generate qualified embeddings with already cached weights | Makes real corpus inputs eligible without mock substitution | Recovering existing receipts avoids regeneration; otherwise record exact chunks, truncation, producer artifacts and vector digests before any training |
| Inventory all selected source shards and explicit lineage | Freezes campaign-wide membership before target generation | Additional I/O/storage and source review; account for every exclusion and authenticate official-source links |
| Materialize numeric inputs/targets once in Arrow | Avoids repeating JSON decoding across workers | Extra derived storage and hash verification; preserve numeric parity and measure end-to-end wall time/PSS before defaulting to it |
| Prepare shared targets and run bounded parallel candidates | Reuses the implemented sparse-checkpoint and single-owner path on qualified data | Record five-bridge configuration, cold preparation separately, per-span/evaluate time, eligible sample count and disjoint evaluation membership |

No historical receipt or pinned checkpoint is overwritten. No Constitution
span becomes `roundtrip_ok`; the Constitution remains not formalized. Only an
actual `lake build <Lib>` is a Lean admit.
