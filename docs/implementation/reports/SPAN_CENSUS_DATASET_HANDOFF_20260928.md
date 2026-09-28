# Dataset handoff for US Code census and supervisor work

The producer saves comparison evidence and proposed work in
`justicedao/uscode-autoformal-span-cache`. It does not need access to a local
Accelerate supervisor database. Another machine can later verify and import a
published bundle into its own native supervisor database.

## Evidence and authority

Each census row retains the original source, complete available codec output,
compiler input and result, decompiler output, measured metrics, source identity,
and producer identity. The JSON capture columns preserve information outside the
indexed Parquet columns. Missing measurements remain missing. Family projection
agreement is a separate observation from strict compiler agreement; it cannot
erase an abstention or establish semantic equivalence.

The current corpus ingestion codec is `DeterministicModalLogicCodec`. Its output
is explicitly labeled `learned_autoencoder_execution=false`; exporting it does
not claim that an autoencoder checkpoint ran or trained. Retained-output exports
keep the historical compiler hashes and record that no codec was rerun.
Existing span-cache rows retain source text, its hash, span ID, and legal ID;
some do not retain the original entry CID or citation provenance. Exports label
that absence explicitly and retain the configured release ID. They do not infer
missing provenance. Retained source-batch receipts can supply richer provenance.

Goals carry source-bound repair packets or training proposals, acceptance
criteria, and references to the census evidence. They are proposals for later
review and execution. Uploading or importing them does not run their commands,
apply a source repair, train weights, or grant an admission. A database row,
projection, codec reconstruction, and successful build of a limited fixture are
not proofs of the statute. Lake remains the only Lean admission path; this
exchange does not change it. The Constitution remains unformalized.

## Durable production and publication

`scripts/ops/legal_ir/ingest_ipfs_uscode_corpus.py` stages census and goal bundles
before completing the corresponding DuckDB claims. A staging failure releases
claims. Upload failure leaves the bundle in the outbox; startup retries it even
when the span queue has no pending work. Worker processes do not own the DuckDB
writer. The legacy `--supervisor-database` argument does not enqueue goals.
The former automatic canary-training call at 256 processed spans is deferred to
the exported work items. Ingestion records `training_executed=false`; separately
launched training workers keep their own lifecycle and acceptance checks.

Every bundle consists of census Parquet, goals Parquet, and a manifest binding
the exact file hashes and row counts. Publication sends all three in one Hub
commit. Readers pin an immutable commit and verify the manifest before importing.
Dry-run generation never records a successful upload. The full resume checkpoint
is not replaced by a census publication.

Retained captures can be exported without rerunning inference:

```sh
python3 scripts/ops/legal_ir/publish_span_cache_exchange.py \
  --input-parquet /path/to/span-evidence.parquet \
  --provenance /path/to/span-evidence.provenance.json \
  --outbox /path/to/census-outbox \
  --agent-id machine-a --release-id release-id \
  --receipt /path/to/new-stage-receipt.json
```

Publish pending bundles, including those staged by an earlier process:

```sh
python3 scripts/ops/legal_ir/publish_span_cache_exchange.py \
  --retry-pending --outbox /path/to/census-outbox --upload \
  --receipt /path/to/new-upload-receipt.json
```

Run these scripts from this repository so `require_workspace_logic_tree()` can
verify the canonical compiler, parser, and decompiler origins. No HACC edits or
fallback imports are part of this workflow.

## Parallel consumers

Consumers download only the manifest and its two referenced files at the
published commit. Content identities make repeated imports idempotent. Existing
native task state, including claims and completed results, must survive replay;
a conflicting identity is an error. Native metadata points to verified local
full-context files so evidence does not have to be truncated to fit an intent
body.

Validate and plan an import first (without `--materialize`):

```sh
python3 scripts/ops/legal_ir/import_span_cache_exchange.py \
  --manifest-in-repo PATH_FROM_PUBLICATION_RECEIPT \
  --revision FULL_HUB_COMMIT_SHA --output /path/to/new-import-preview
```

Use the actual manifest path from the publication receipt. To create native
review records, add `--materialize --database /path/to/supervisor.duckdb
--accelerate-root /path/to/qualified/ipfs_accelerate_py-checkout`. The checkout
must contain `ipfs_accelerate_py/__init__.py`. Imported tasks have status
`blocked`, `review_only=true`, and `is_schedulable=false` until local execution
qualification. The original commands remain in the verified evidence; import
does not copy them into native execution fields.

Use a new output directory for each attempt. Replay can target an existing
database; retain the original downloaded bundle and packet directory so existing
native evidence references remain valid.

Use a common shard count and a distinct shard index when machines should divide
work. Keep dependency-linked work in the same shard. Two machines importing the
entire bundle provide replicated queues, not shared leases: Hugging Face is the
handoff log, and each supervisor owns its own claims. Execution requires the
local supervisor's review and acceptance process.

## Cost and operational limits

Full captures consume more storage than short summaries. Compression and bounded
bundles keep individual uploads and imports manageable; reuse the durable outbox
instead of paying inference cost on retries. Dataset publication does not move
weights into the task database or hold a database writer during training.

This work establishes the handoff and preserves evidence. It does not establish
a new training speed baseline, improve held-out legal IR accuracy, or complete
the federal corpus. Bridge timings require actual nonzero target counts and the
recorded bridge names, prover flag, cache state, workers, and sample count.

## Verified publication and replay

Published [Hugging Face commit e537edd812e6fb714647fbaef2134df7606cd3d2](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/commit/e537edd812e6fb714647fbaef2134df7606cd3d2)
contains three census rows, three repair goals, and one training goal. Its
manifest is
`autoformal/uscode/exchanges/retained-census-20260928/exchange-1134f171e6273eb20eeb9e0c5a8feb3d007be70a6b5d246b053541a7e8317a9b.manifest.json`.

These are retained source-backed observations for 7 USC 2006d, 5 USC 8410, and
16 USC 6809. Complete codec and compiler captures were compared against their
original producer receipt after download. All three strict compiler abstentions
remain gaps. The codec is deterministic, and no learned checkpoint ran or trained
during this handoff test. The 16 USC 6809 evidence explicitly requested training;
that request survives alongside its compiler repair goal.

Three consumer processes downloaded only the manifest and its two Parquet files
at that immutable commit, then imported disjoint shards into three separate
native supervisor databases on one host:

| Shard | Tasks, goals and plans created | Tasks added on replay | Task/goal/plan/event state |
| --- | ---: | ---: | --- |
| 0 of 3 | 1 each | 0 | Unchanged |
| 1 of 3 | 1 each | 0 | Unchanged |
| 2 of 3 | 2 each | 0 | Unchanged |

Both ordinary and automatic ready-task queries returned zero. A separate native
CAS fixture also verified that replay preserves a task already moved to
`claimed`; no worker executed that fixture. The five preexisting Hub files,
including the resume checkpoint, retained their original Git object identities.
The protected restart12 checkpoint retained SHA-256
`1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd`.

The final combined suite passed **216 tests in 27.72 seconds**, including the
three semantic gates and empty-vocabulary abstention, complete capture,
immutable publication recovery, malicious/corrupt input bounds, sparse
checkpoint restart behavior, and native importer integration.

Machine-readable receipts and test results are in
[`evidence/span-census-handoff-20260928`](evidence/span-census-handoff-20260928).
The initial local `outbox-r1` attempt was retained for diagnosis and never
uploaded; the qualified publication uses `outbox-r2`.
