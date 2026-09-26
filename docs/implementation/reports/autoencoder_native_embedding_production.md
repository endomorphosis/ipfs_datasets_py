# Exact local embedding production and v6 corpus inputs

Implementation milestone, 2026-09-25, continuing
[durable index enforcement](autoencoder_indexed_training_jobs.md) and the
[federal-law training plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md).

Follow-up: [produced-corpus training with mapped Arrow inputs](autoencoder_produced_corpus_arrow_training.md)
implements the bounded numeric adapter, shared-target candidate comparison and
parallel owner qualification described below. This report preserves the
earlier embedding-production and input-only audit scope.

## Producer and evidence

The new producer consumes bounded `EmbeddingInput` records with exact source
artifacts, UTF-8 selectors and legal metadata. It checks the source bytes before
loading a model. It loads the already cached GTE-small revision
`17e1f347d17fe144873b1201da91788898c639cd` from a local path with remote code
disabled and offline loading required. Nine required asset hashes and byte
counts are checked before and after production. No model weights are downloaded.

Production uses CPU float32, one CPU thread, seed 0, evaluation mode, inference
mode, the existing 512-token ceiling, mean pooling and the model's Normalize module. The producer
counts tokens without truncation, compares them with the captured tensors, and
passes those same tensors directly to the model. It records exact unpadded
token IDs, masks and type IDs for successful rows. Oversized inputs receive a
`token_limit_exceeded` disposition, an untruncated token count and digest, and
no vector. There is no automatic truncation or chunk substitution.

One model load serves a bounded batch of inputs, with at most 16 rows per
forward pass. The execution profile records the actual batch size; right
padding is checked and active tokens must be a contiguous prefix. Vectors
retain the exact produced float32 bits. Conversion to
Python numbers preserves those values exactly; it does not change any existing
autoencoder weights. The receipt also records model files, producer code and
runtime versions. The library's offline guard is reversible; the dedicated
native audit additionally denies network syscalls with Linux seccomp.

The strict sidecar codec checks closed fields, canonical bytes, row coverage,
token evidence, vector shape and normalization, and resource bounds. It reloads
source bytes when generating corpus records or checking a supplied batch. A
sidecar can serve multiple batches; each worker verifies only its batch's exact
source closure. Published vectors remain unqualified and are never relabeled
as outputs of the new producer.

These checks establish artifact and input/vector consistency under the stated
producer profile. They do not cryptographically prove inference, authenticate
official source authority or establish legal formalization. Injected-fixture
profiles cannot convert to corpus records. Unit tests of declared profiles are
software-contract evidence, separate from the actual native producer run.

## Durable job binding

Opt-in v6 jobs extend v5's frozen index and explicit validation requirements
with a bounded `embedding_production_artifact`. Every supplied record must bind
its embedding provenance to the exact sidecar SHA-256, and its source, metadata
and vector must match a successful sidecar row. A registered variant also pins
`embedding_production_binding: {artifact: {sha256, bytes}}`. It refuses older
jobs that omit this contract. Owner and worker verify independently before
model loading or dispatch, and the owner compares the resulting receipt.

The default job schema remains v4, and archived v1–v5 serializations remain
separate compatibility contracts. No database schema change, worker database
connection, DuckLake activation, head promotion or publication is introduced.

Regenerated vectors change record identities. The native audit therefore
creates a new index and variant, uses the original split policy, and checks
that unchanged source groups retain their assignments. The previously frozen
source selection is not reseeded or chosen again based on model evaluation.

## Native qualification

The [final-code native audit](evidence/autoencoder_control_plane_plan/native-embeddings-20260925-r2.json)
passed in 18.0349 seconds overall. Exact cached-model input production took
15.9638 seconds for the same 64 source rows selected before model evaluation:

| Result | Count |
|---|---:|
| Exact native float32 vectors | 51 |
| Explicit `token_limit_exceeded`, with no vector | 13 |
| Missing input | 0 |
| Retained training / validation / holdout rows | 43 / 3 / 5 |
| Retained canary rows | 0 |

The original canary was among the 13 oversized rows. No substitute was moved
into that partition. All retained source groups kept their original split
assignments. This input audit cannot qualify a held-out canary or establish
that the checkpoint has never seen these laws.

The 434,558-byte producer receipt covers all 64 dispositions. Owner and worker
both verified the 46-record training/validation batch against that receipt,
exact source bytes and the frozen index. Their results agreed and survived
DuckDB reopen, including both immutable variant bindings. The audit run stayed
queued and unleased; there was no autoencoder training output. It retained
34,614,671 bytes, including its staged checkpoint copy and database. The pinned
25,895,338-byte checkpoint remained unchanged.

Production averaged 0.2494 seconds per selected source row, including length
rejections and local model loading. That is one observation with a fresh
producer process, pre-existing cached weights, CPU thread count 1 and batch
size 16. OS file-cache warmth was uncontrolled. There was no bridge evaluation;
these numbers cannot be compared to cold legal-IR evaluation timings.

The [initial regression receipt](evidence/autoencoder_control_plane_plan/native-embeddings-tests-20260925.json)
records 426 control/embedding tests and 66 semantic/router tests passing. The
three semantic gates, empty-vocabulary abstention and Constitution safeguards
remain green. A subsequent review caught the new optional field displacing
`schema_version` in fully positional legacy constructors. Moving that field
after `schema_version` preserves the existing signature. The worker suite then
passed 128 tests, including the new regression; all other tested source files
were unchanged.

The [final validation receipt](evidence/autoencoder_control_plane_plan/native-embeddings-final-validation-20260925.json)
binds those tests to the final source hashes. All 39 archived v1–v4 job payloads
and hashes remain unchanged, and both prior native v5 jobs round-trip exactly.
The [first native run](evidence/autoencoder_control_plane_plan/native-embeddings-20260925.json)
is retained: it took 16.2693 seconds for production and produced a byte-identical
producer receipt. The final-code run requalifies owner/worker integration after
the constructor fix. The two runs provide repeatability evidence, without a
before/after performance claim.

## Remaining work and opportunity cost

This producer supplies an explicit preparation artifact that can be reused
across independent candidates. Batched CPU inference amortizes model loading
and avoids both remote weight lookups and repeated source/vector production.
Verification still reads immutable inputs at the owner and worker boundaries.
That cost should remain separate from target preparation, projection updates,
checkpoint replay and bridge-on evaluation in subsequent timings.

The next implementation sequence is:

1. Bind an optional, uncompressed Arrow IPC vector artifact to the canonical
   producer receipt, exact ordered record IDs, dimensions and float32 values.
   Verify all values once at sealing and independently on worker open. Require
   read-only, zero-copy numeric views when requested; do not silently copy or
   call a tuple-converting adapter zero-copy. Existing `SampleRecord` and
   `LegalSample` conversions still allocate Python values, so a qualified
   numeric-view adapter is required before the training path can claim this.
2. Prepare complete shared targets for a bounded, predetermined train/validation
   subset of the successful rows. Use the existing lossless target bundle and
   keep every bridge, rejection and failure disposition. Profile source/frame
   construction, target generation, encoding, hashing and hydration separately.
   Bound rich-object memory as well as final bytes before expanding to all 46.
3. Run equivalent fresh-target and reused-target v6 jobs with the same source
   records, checkpoint, validation membership and numeric precision. Capture
   accepted sparse updates; require owner replay and durable candidate identity
   parity. Report five bridge names, target counts, provers false, metric cache
   0, sample memory false, one bridge worker and wall time per span/evaluation.
   A fresh process using shared targets is still a target-reuse measurement.
4. Qualify two independent candidate workers through the existing single DuckDB
   owner. Send sealed update artifacts and receipts, keeping remote SQL out of
   numerical operations. Measure total wall time, owner replay/lease delay,
   peak PSS, retained bytes and temporary/WAL usage. Maintain the 50 GB campaign
   budget. Registration remains separate from promotion and publication.

The raw numeric payload here is only 78,336 bytes (51 × 384 × 4), while the
producer receipt is 434,558 bytes. Arrow may remove repeated conversion and
share buffers across workers, but this subset does not justify expecting large
speedups from vector storage alone. Complete target generation and replay must
be measured first. The previously qualified Arrow feature-weight table remains
opt-in: it preserved results but did not improve complete-job latency on the
three-gate comparison. Mapping additional weight families requires a profile
showing a useful payoff and exact update/rollback/checkpoint parity.

The first native audit is preparation evidence, not a repeated-inference
baseline or legal-IR speed result. Its one-time cost can be amortized by reusing
the sealed producer artifact; do not hide that cost in subsequent comparisons.

Oversized source rows still need explicit source-aware chunking with complete
byte coverage and reviewed split continuity. Full-release inventory, official
source authentication, unseen-checkpoint history, reviewed semantic support,
durable proof storage and publication qualification remain separate work.
The Constitution is not formalized. Only an actual `lake build <Lib>` is a
Lean admit.
