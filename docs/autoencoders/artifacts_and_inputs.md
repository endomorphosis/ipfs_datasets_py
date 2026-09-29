# Inputs, artifacts, and compatibility

[Handbook](README.md) · [API map](api_map.md) · [Control plane](control_plane_and_sync.md)

Choose the representation and checkpoint family first. File extensions, equal
vector dimensions, and source-language labels do not establish compatibility.
Use schema classes and artifact writers; do not copy old manifest hashes.

## What to have before starting

| Route | Application inputs | Persistent outputs |
| --- | --- | --- |
| Legal feature training | Training/validation JSONL; verified embedding manifest and producer/source artifacts; immutable legal parent; target supervision; owner/resource/source configuration | Input verification, targets, attempt reports, selected full-state identity, dependencies, owner generation receipts |
| Legal qualified training | Supported records/checkpoint; policy and validation rows; source-locked compiler/decompiler/family/Lake facilities | Candidate, qualification reports and referenced proof/source files, owner decision |
| Legal inference | Exact immutable checkpoint, input/validation data, separate inference state directory | Evaluation and qualification receipts with state/source/input bindings |
| Native structural training | Native models or source-bound typed Security evidence; envelopes; selected projections; training-only basis; disjoint fixed tuning panel; contract | Contract, basis, state including Adam moments, report, version and exact parent ID |
| Native structural inference | Saved contract/basis/state plus compatible envelopes | Latents, reconstructed projection features, known/unknown atom coverage |

Schema verification does not prove source meaning or the quality of supplied
vectors and modeling declarations.

## Legal source rows

The worker's [SampleRecord](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_worker.py)
accepts:

| Field | Meaning |
| --- | --- |
| `title`, `section` | Nonempty source title and section strings |
| `text` | Exact nonempty source text |
| `citation` | Optional citation string |
| `embedding_model` | Model identity; default `mock:stable-sha256` is diagnostic |
| `embedding_vector` | Optional nonempty finite vector; required for a non-mock model |

`SampleRecord.from_dict()` checks the closed row shape. It does not replace
embedding provenance verification. Legal `ModelVariant` restricts the frontend
to English, US jurisdiction, and `typed_deontic_ir`.

[`verify_feature_training_inputs(manifest_path, training_path, validation_path)`](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_feature_inputs.py)
checks producer receipts, exact vector bits/text, artifact hash/size, and
training/validation disjointness without training or evaluating a canary.

Supported manifest schema names are `autoencoder-feature-inputs/v1` and legacy
`parallel-training-verified-embedding-split/v1`. The normal manifest binds
`model`, `embedding_production_receipt`, `source_artifacts`, selected input IDs,
and `artifacts.training` / `artifacts.validation`; the legacy form retains its
original diagnostic split and `tuning` role. See the verifier and
[legal input recipe](legal_training.md); these are not arbitrary JSONL wrappers.

Keep exact source selection and text. Expanding context, truncating, backfilling,
or relabeling mock vectors changes the evidence. Successful local verification
does not imply `global_holdout_verified` or corpus-wide training eligibility.

## Producing verified legal embeddings and the feature manifest

This is a preparation workflow, separate from training. Its inputs must already
have exact source artifacts and selectors. Keep a preselected document-level
training/tuning/canary split; do not select easier rows after seeing losses.

1. Construct `EmbeddingInput(source, title, section, text, citation)` using an
   identity-normalized `SourceSpan`, or use
   `EmbeddingInput.from_source_record(record)`. The source record classes live
   in [autoencoder_corpus_manifest.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_corpus_manifest.py);
   [autoencoder_embedding_production.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_embedding_production.py)
   owns the input and receipt classes.
2. Provide a resolver mapping each referenced artifact's exact hash/size to its
   existing local path. `validate_embedding_inputs(inputs, resolver=resolver)`
   checks that the source selection reproduces the text.
3. In a dedicated bounded producer process, call
   `produce_native_embedding_receipt(inputs, resolver=resolver,
   snapshot_path=local_snapshot, batch_size=16)` from
   [autoencoder_embedding_runtime.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_embedding_runtime.py).
   This profile supports the already-local pinned GTE-small revision
   `17e1f347d17fe144873b1201da91788898c639cd`, exact model assets, CPU float32,
   and batches of 1–16. It has no network fallback. Inputs above the existing
   512-token ceiling receive `token_limit_exceeded` and no vector; they are not
   truncated or replaced.
4. Use `receipt.save(new_path, resolver=resolver)` to write canonical bytes and
   obtain `{path, sha256, bytes}`. `receipt.status_counts` records dispositions.
   `receipt.to_corpus_records(resolver=resolver)` returns only successful native
   English US Code rows, with exact embedding provenance. Keep rejected source
   dispositions too; do not silently backfill split members.
5. Write each chosen successful record's sample fields as JSONL in the same
   order as that role's `input_ids`. The producer input ID, not the new corpus
   record ID, belongs in the feature manifest. Preserve exact float32 values
   when serializing to JSON numbers. Retain source artifacts and the model's
   production receipt beside the selection manifest.
6. Construct the normal manifest with the fields below, using actual artifact
   descriptors, then run `verify_feature_training_inputs` before target work.

This is a **shape illustration**, not valid ready-to-run evidence; replace every
descriptor and identity with values from the actual producer and files:

```json
{
  "schema": "autoencoder-feature-inputs/v1",
  "model": "COPY THE COMPLETE model OBJECT FROM THE PRODUCER RECEIPT",
  "embedding_production_receipt": {"path": "/absolute/receipt.json", "sha256": "ACTUAL_SHA256", "bytes": 123},
  "source_artifacts": [{"path": "/absolute/source.jsonl", "sha256": "ACTUAL_SHA256", "bytes": 456}],
  "artifacts": {
    "training": {"rows": {"path": "/absolute/train.jsonl", "sha256": "ACTUAL_SHA256", "bytes": 789}, "count": 1, "input_ids": ["sha256:ACTUAL_PRODUCER_INPUT_ID"]},
    "validation": {"rows": {"path": "/absolute/tune.jsonl", "sha256": "ACTUAL_SHA256", "bytes": 987}, "count": 1, "input_ids": ["sha256:DIFFERENT_PRODUCER_INPUT_ID"]}
  }
}
```

The illustrative `model` string must be replaced by the receipt's object, not a
handwritten model name. Hashes cover file bytes, so reformatting JSONL requires
new descriptors. The verifier joins every row back to successful producer
results. Missing cached weights or receipts remain missing prerequisites;
there is no supported download-or-mock shortcut in this campaign.

## Native domain target envelopes

[`DomainTargetEnvelope`](../../ipfs_datasets_py/logic/formalization/autoencoder/domain_targets.py)
uses `autoencoder-domain-targets/v1` and immutable canonical bytes. `to_dict()`
returns a detached copy; `from_dict()` validates structure and readiness.

| Field | Purpose |
| --- | --- |
| `domain_id`, `source_digest` | Domain/source identity for batch membership and disjointness |
| `projections` | Native expressions, unique IDs, family or explicit role, native profile, properties, representation, producer |
| `validation` | Validator, target/qualification stage, required flag, status, details |
| `unsupported` | Missing target work; blocks readiness |
| `qualification_gaps` | Missing semantic/execution evidence; never a passed check |
| `ready_for_training` | Nonempty targets, required target checks passed, no unsupported target entries |
| `qualified`, `admitted`, `formalized` | Always false for feature envelopes |

Use the native `prepare_*_targets` adapters for real observations. The generic
builder serializes declarations; it does not attest a trusted compiler run.
Security needs exact bytes and explicit `CodeLogicEvidence`; a CWE label cannot
create semantics. See [modality inputs](modalities.md).

## Native basis, contract, and state

`build_feature_space(domain, projection_ids, training_targets)` fits a frozen
per-projection vocabulary. It retains training source identities, target digest,
ordered argument paths, excluded projections, and normalization. Fitting on
tuning or canary rows leaks information. New rows may use this basis, with
unknown atoms reported instead of implicitly expanding it.

`build_native_feature_contract(...)` binds the space to projection semantics,
implementation/codec identities, objective, validator policy, and latent width.
`ModalityContract.from_dict()` loads a saved contract; compatibility with the
installed implementation is still required. A declared publication namespace
does not mean a Hub transport exists for that model.

| Training result entry | What must be preserved |
| --- | --- |
| `state` | `native-projection-feature-state/v1`, contract/basis digest, architecture, four parameter tensors, Adam moments/steps, selected epoch count, optimizer settings, tuning target digest, false authority flags |
| `report` | Configuration and parent-state binding, before/after per-projection metrics, attempted/selected epochs, deadline outcome, coverage, feature-only evidence |

Registration stores `contract`, `feature_space`, `state`, and `report` together.
Persist all four. Resume registration requires the exact parent version whose
numerical state matches `report.base_state_sha256`. Registration does not
promote a head or publish to Hub. The [quickstart](native_feature_quickstart.md)
shows save/load/resume.

## Formats are distinct

| Format | Contents | Consumer |
| --- | --- | --- |
| Legal modal full JSON | Existing `ModalAutoencoderTrainingState` | Legal checkpoint loaders |
| Legal sparse checkpoint/patch | Changes and exact base/dependencies | Legal sparse replay |
| Legal shared target JSON/Arrow | Legal targets and producer/config bindings | Legal target worker |
| Arrow embedding inputs | Verified source-bound embedding buffers | Explicit embedding input loader; not a weight codec |
| Existing mapped Arrow weights | Supported legacy feature weight representation | Declared modal loader; not all parameters/optimizer state |
| Native domain envelope | Modality compiler output and validation observations | Native target/structural APIs |
| Native structural JSON state | Parameters, Adam and selection identities | Native train/infer APIs |
| Legal feature Hub v1 manifest | Legal checkpoint/update/evidence exchange | US Code feature exchange; not nonlegal transport |

Memory mapping does not imply zero-copy mutable training. Buffer lifetime,
dtype/layout, optimizer state, and update ownership still matter. The native
state has no Arrow or sparse transport codec yet.

## Directories and retention

Use private attempts and immutable parents. This is an illustrative application
layout, not a runner-generated schema:

```text
campaign/
  input/                 source rows, split and embedding receipts
  targets/               immutable prepared targets
  source/                frozen producer/runtime references
  attempts/<attempt>/    private candidate and reports
  inference/             separate inference state and receipts
  control/               owner database and artifact store
```

Keep dependencies reachable while checkpoints/receipts are retained. Deleting
an anchor, target shard, proof, or producer artifact may break resume even if
the final checkpoint remains. Inspect resource ownership before cleanup. Never
overwrite restart12 or its hardlinked archive. See [recovery](operations_and_troubleshooting.md).
