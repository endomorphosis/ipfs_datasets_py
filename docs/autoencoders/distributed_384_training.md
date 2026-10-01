# Local workers and versioned exchange for the 384d IR decoders

`scripts/ops/autoencoder/run_distributed_384.py` prepares a reproducible training
round, runs several numerical workers on one machine, and merges their results
into a candidate checkpoint. The same round can later be partitioned across
machines and exchanged through Hugging Face. Each machine owns its own DuckDB
journal and artifact directory.

The supported domains are `intent_ir`, `security_ir`, `ui_ux_ir`, and `legal_ir`.
The default parents are immutable, SHA-checked `structured_native_v3` development
releases in the corresponding `Publicus/*-ir-autoencoder` model repositories.
Run `profiles` to see the exact repository commits, manifest/checkpoint hashes,
native family inventory, and candidate corpus adapters:

```bash
python scripts/ops/autoencoder/run_distributed_384.py profiles \
  --domain security_ir
```

These published parents were trained on authored composition controls. Their
profile's CVEFixes, SkillCenter, and US Code corpus references are possible
sources for a reviewed typed export; they do not imply that the parent was
trained on those corpora.

## What the workers train

This implementation fits a new structured ridge head over the complete declared
training round. It preserves the inherited Legal projection, target schema, and
class vocabulary. Each worker computes projected feature factors and sparse
class coordinates for a disjoint set of complete source groups. The coordinator
combines every unique shard, computes global centering from training data only,
and selects a ridge using validation exact reconstruction and semantic leaf
accuracy. Validation rows never enter worker fitting.

The update format is `low_rank_sparse_labels/v1`: feature factors are dense
384-dimensional rows; labels are sparse indices. Workers do not exchange dense
Gram matrices or repeatedly copy the frozen projection. These updates are not
neural gradient deltas. A checkpoint alone does not preserve the sufficient
statistics of its old training corpus, so every round must include all examples
intended for the new fit. There is no averaging of independently trained heads.

The input embeddings are already computed. Local workers perform CPU numerical
work; this command does not generate embeddings, launch a language model, or
implicitly choose an embedding model. Keep the exact embedding pipeline and
source/target export provenance with the corpus descriptor.

## Prepare the input export

Provide `train.json`, `validation.json`, and `source.json`. A row file may be a
JSON list or a closed object with the single key `rows`. Every row has exactly
these fields:

| Field | Contract |
| --- | --- |
| `id` | Unique example identity. |
| `group_id` | Leakage group shared by all source variants and related compositions that must stay together. |
| `split` | Literal `train` or `validation`, matching the containing file. |
| `source_text` | Original nonempty source text. |
| `embedding` | Exactly 384 finite numbers from the declared embedding pipeline. |
| `target` | A native typed target accepted by the selected domain and the parent's frozen target schema. |

The current bounds are 2,048 training rows and 4,096 validation rows. The audit
rejects cross-split group, example, source, normalized-source, and numerical
embedding overlap. Alternative source renderings belong in the same group;
`group_id` is a leakage boundary and need not imply identical targets. Training
groups stay intact when shards are formed, so a group can exceed the desired
`--shard-size`. Test and canary files are not accepted as fitting splits.

Targets must be exported and reviewed before this workflow. A vulnerability
label, unpaired span, or raw instruction is not automatically a typed IR target.
New classes or structures outside the parent's schema require a separate
schema/training workflow; this round cannot silently extend the vocabulary.

The [reviewed pair importer](reviewed_384_pair_exports.md) checks source/target
bindings, embedding provenance, and transitive leakage groups before exporting
these files. After merging, use the additive
[native projection command](distributed_384_projection_context.md) to validate
actual checkpoint predictions with explicit source-bound context and fresh
Lake/SANY execution, without rewriting the completed round.

For an initial local round, `source.json` can be:

```json
{
  "schema": "ir384-corpus-source/v1",
  "description": "Reviewed SecurityIR export; record the source revision, labeling method, and embedding pipeline here.",
  "redistribution_allowed": false
}
```

If the export comes from Hugging Face, also record `huggingface` with
`repository_id`, `repo_type` (`dataset` or `model`), and a full immutable
40-character `revision`. This upstream descriptor supplements the hashes of
the exact exported rows; it does not replace them. Set
`redistribution_allowed` to `true` only after reviewing permission to publish
the actual source text, targets, and embeddings. Public input publication sends
those full artifacts to the model repository.

## Run one machine with four workers

Run from the repository root in the environment containing its numerical,
DuckDB, and Hugging Face dependencies. Limit nested BLAS threading before
launching the worker pool:

```bash
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1

python scripts/ops/autoencoder/run_distributed_384.py prepare \
  --domain security_ir \
  --training data/security/train.json \
  --validation data/security/validation.json \
  --source data/security/source.json \
  --output-dir work/security-round-001 \
  --shard-size 32 --machine-count 1 \
  --result work/security-round-001-prepared.json

python scripts/ops/autoencoder/run_distributed_384.py work \
  --round-dir work/security-round-001 \
  --database work/security-host-0.duckdb \
  --artifact-root work/security-host-0-artifacts \
  --machine-index 0 --workers 4 \
  --result work/security-round-001-workers.json

python scripts/ops/autoencoder/run_distributed_384.py merge \
  --round-dir work/security-round-001 \
  --database work/security-host-0.duckdb \
  --artifact-root work/security-host-0-artifacts \
  --result work/security-round-001-merge.json
```

The default parent is downloaded by immutable revision if it is absent from the
cache. `prepare --local-files-only` requires local availability. An explicit
`--base /path/to/checkpoint.json` selects a compatible checkpoint and binds its
exact content to the round; it does not alter the published default.

One process owns the DuckDB file and serializes its short journal operations;
the worker threads receive numerical work, not database handles. Lease fences,
content-addressed artifacts, and compare-and-set checks prevent stale or
conflicting completion records. A repeated worker run can reuse completed
shards. Do not start two owning processes against the same database. With fewer
shards than workers, fewer workers can make progress; parallelism does not
guarantee a throughput improvement for small inputs.

Commands print JSON, with diagnostics on stderr. `--result` additionally saves
the returned JSON as an immutable artifact. Identical writes are idempotent;
different contents require a new result path. Keep a new round directory for a
changed dataset, base, recipe, machine count, or projection policy.

## Exchange one round between machines

Prepare a separate round with the intended `--machine-count`, for example two,
using the same inputs and a descriptor that permits their redistribution:

```bash
python scripts/ops/autoencoder/run_distributed_384.py prepare \
  --domain security_ir \
  --training data/security/train.json \
  --validation data/security/validation.json \
  --source data/security/public-source.json \
  --output-dir work/security-shared-001 \
  --shard-size 32 --machine-count 2

python scripts/ops/autoencoder/run_distributed_384.py publish-inputs \
  --round-dir work/security-shared-001

python scripts/ops/autoencoder/run_distributed_384.py publish-inputs \
  --round-dir work/security-shared-001 --upload \
  --result work/security-shared-001-input-reference.json
```

The first publication command only stages locally. The `--upload` command uses
the configured Hugging Face credentials and returns an immutable reference
containing the exact repository revision and artifact bindings. Share that JSON
reference with the other host. Both hosts need the same producer code: the
round also pins its numerical recipe, and stale or foreign updates are rejected.

On host 0, run its partition and publish completed updates:

```bash
python scripts/ops/autoencoder/run_distributed_384.py work \
  --round-dir work/security-shared-001 \
  --database work/security-shared-host-0.duckdb \
  --artifact-root work/security-shared-host-0-artifacts \
  --machine-index 0 --workers 4 --upload
```

On host 1, fetch the same immutable inputs and run its partition:

```bash
python scripts/ops/autoencoder/run_distributed_384.py fetch \
  --reference security-shared-001-input-reference.json \
  --output-dir work/security-shared-001

python scripts/ops/autoencoder/run_distributed_384.py work \
  --round-dir work/security-shared-001 \
  --database work/security-shared-host-1.duckdb \
  --artifact-root work/security-shared-host-1-artifacts \
  --machine-index 1 --workers 4 --upload
```

Each machine index must be within the count frozen into the plan. Each host has
a separate database and artifact directory. Exchange immutable JSON artifacts
through Hugging Face; do not share the DuckDB file over a network filesystem.
Updates are stored under
`training/structured384/<plan_id>/updates` in the domain's model repository.
Factored updates retain information about the examples; they are not an
anonymization mechanism.

Factored statistics can exceed the bytes of a small checkpoint, so their compact
representation does not establish an aggregate bandwidth saving. In the initial
four-domain live exchange, checkpoint postimage payloads were 65–72% smaller than
the corresponding full checkpoints. That measurement concerns checkpoint
payloads only; include input bundles, worker statistics, manifests, and retries
when measuring total transfer cost.

After all partitions finish, merge on host 0:

```bash
python scripts/ops/autoencoder/run_distributed_384.py merge \
  --round-dir work/security-shared-001 \
  --database work/security-shared-host-0.duckdb \
  --artifact-root work/security-shared-host-0-artifacts \
  --discover --upload \
  --result work/security-shared-001-merge.json
```

`--discover` resolves and validates the plan's published updates. For an offline
transfer, use repeated `--update-path /path/to/update.json` instead. Merge
requires exactly one consistent update for every declared shard; retrying a
delivery must not count its rows again. Content hashes prove artifact identity,
not honest computation by an arbitrary remote worker.

Merged versions normally use a parent-bound checkpoint patch. Add
`merge --full-anchor` when a complete checkpoint is wanted for periodic
rehydration anchors. A patch may still be large if most fitted head values
change. Every reconstructed checkpoint must match its declared hash; neither
publication nor a successful download promotes it to a default runtime model.

## Continue from a downloaded candidate

A successful `merge --upload --result work/security-shared-001-merge.json` stores
the immutable checkpoint reference in the result's `publication` field. Receive
and verify that version through the shared exchange API:

```python
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import exchange
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.contracts import read_json, write_json

reference = read_json("work/security-shared-001-merge.json")["publication"]
received = exchange.receive_bundle(
    reference,
    "work/security-downloaded-candidate",
    parent_path="work/security-shared-001/base.json",
)
write_json("work/security-resume-base.json", read_json(received["payload_path"]))
```

For a checkpoint patch, `parent_path` must contain the exact original parent
bytes declared by the manifest; an equivalent JSON object with different
serialization is insufficient. Retain the previous round's `base.json`. A full
anchor has no parent dependency, so omit `parent_path` when receiving that
reference. The receiver verifies the immutable revision, payload, reconstructed
checkpoint hash, and native decoder contract before returning the artifact.

Use the verified candidate explicitly in a new round:

```bash
python scripts/ops/autoencoder/run_distributed_384.py prepare \
  --domain security_ir \
  --training data/security/next-train.json \
  --validation data/security/next-validation.json \
  --source data/security/next-source.json \
  --base work/security-resume-base.json \
  --output-dir work/security-round-002 \
  --shard-size 32 --machine-count 1
```

Then run `work` and `merge` against the new round and its host-local journal.
The complete declared training corpus is still required: include retained
examples as well as additions when they should influence the new fit. The new
base supplies the frozen projection/schema and validation baseline, not the
historical training statistics. Explicit resumption does not change the
published default checkpoint or automatically promote the candidate.

## Interpret reconstruction and projection results

The merge reports selected validation reconstruction alongside the parent
baseline. This is tuning-set evidence. Measure generalization separately on a
sealed, group-disjoint evaluation export after the candidate is frozen; repeated
tuning improvements do not establish a new holdout score. Inspect row counts,
shard coverage, wall-clock timings, worker count, and serialized update sizes
before claiming throughput or transfer savings.

Native projection coverage is distinct from reconstruction accuracy. The
default policy requests the domain's native families. `--require-family` may be
repeated at preparation time to declare a narrower policy, for example
`--require-family program` for a deliberately limited SecurityIR expression
experiment. This changes the declared policy, not the capability of a target.

Each candidate is sent unchanged through the applicable native projection
routes. Results retain `supported`, `missing_context`, or `failed` per family.
The current SecurityIR expression route checks exact source binding within its
narrow typed program grammar. Other security families need their own explicit
CodeUnit/model evidence. UI frame projections expose their limited structural
scope and unprojected facets; IntentIR and LegalIR use their native typed
adapters. Unsupported context is never filled with invented entities or axioms
merely to make a projection succeed.

A valid typed target can participate in training while missing projection
context remains reported and blocks full projection qualification. These
reports do not run Lean `lake build`, prove source meaning, authorize execution,
or automatically promote a checkpoint. Use the source-bound Lake and supervisor
qualification workflows separately where they apply.

## Python API

The CLI delegates to
`ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.runner`:

```python
prepare_round(domain, training_path, validation_path, output_dir,
    source_descriptor=source, base_path=None, cache_dir=None,
    local_files_only=False, shard_size=32, machine_count=1,
    required_families=None)
publish_inputs(round_dir, upload=False)
fetch_inputs(reference, output_dir, local_files_only=False)
run_local(round_dir, database_path, artifact_root,
    machine_index=0, workers=4, upload=False)
merge_round(round_dir, database_path, artifact_root,
    update_paths=(), discover=False, upload=False, full_anchor=False)
```

`profiles.get_profile(domain)` exposes immutable parent provenance and family
coverage. `profiles.project_candidate(domain, target, source_text,
required_families=None)` returns the scoped native projection report without
rewriting the candidate.
