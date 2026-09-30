---
configs:
  - config_name: retained_outputs_v1
    data_files:
      - split: train
        path: autoformal/uscode/outputs/**/*.parquet
  - config_name: census_v3
    data_files:
      - split: train
        path: autoformal/uscode/census-v3/**/*.parquet
  - config_name: census_v2
    data_files:
      - split: train
        path: autoformal/uscode/census/**/*.parquet
  - config_name: supervisor_goals_v2
    data_files:
      - split: train
        path: autoformal/uscode/goals/**/*.parquet
---

# US Code autoformalization observations and deferred repair goals

This repository contains source-backed observations from the legal autoencoder
and deterministic compiler, plus portable goals for later review by an
`ipfs_accelerate_py` agent supervisor. It is a work-in-progress evidence corpus.
An uploaded observation, compiled rule, decompiled sentence, reconstruction
score, or bridge target does not establish formalization. Lake admission
requires a separate source-bound `lake build <Lib>` receipt. The Constitution
is not formalized.

## Choose a dataset configuration

| Configuration | Read this for |
| --- | --- |
| `retained_outputs_v1` | Queryable historical autoencoder vectors, compiler rules and decompiled text, metrics, and links to deferred goals |
| `census_v3` | New complete census observations, with explicit autoencoder/compiler columns and captured source-derived logic targets |
| `census_v2` | Original historical observations; complete retained outputs remain in `input_json` |
| `supervisor_goals_v2` | Full repair packets and training goals, source context, acceptance criteria, and evidence hashes |

Each configuration has a separate schema. The `train` split name is a storage
label and does not assert qualification for training. The progress ledger and
older operational tables are not included in these observation configurations.

```python
from datasets import load_dataset

observations = load_dataset(
    "justicedao/uscode-autoformal-span-cache",
    "retained_outputs_v1",
    split="train",
    streaming=True,
    revision="<immutable-commit-sha>",
)
for row in observations:
    if row["compiler_rule_count"]:
        print(row["source_span_id"], row["compiler_rules_json"])
```

Use an immutable commit revision when comparing runs or importing evidence.
Multiple observations of the same source may have different compiler/model
identities. Join goals by `census_sha256`; retain `source_span_id`,
`source_text_sha256`, `code_identity`, and `model_identity` as provenance.

## What the autoencoder emitted

The legacy CUDA campaign reconstructs eight-dimensional diagnostic vectors.
The input representation is `mock:stable-sha256/8`; it has no verified semantic
embedding provenance. Its raw decoder embedding, cosine similarity, and
reconstruction loss are distinct from its target-conditioned safety-projected
embedding and scores. These observations do not establish legal understanding.

The model does not emit legal formulas or reconstructed legal sentences in
this campaign. Empty `autoencoder_text` and `autoencoder_compiled` remain empty.
Compiler formulas and source-derived target documents are retained under their
own names, never relabeled as learned model outputs. This campaign performs
diagnostic inference, not training or weight publication.

## Compiler and logic artifacts

`compiler_rules_json` exposes retained structured rules.
`compiler_components_json` in census v3 preserves individual clause outcomes;
`compilation_complete` distinguishes a complete compilation from partial
evidence. `compiler_status`, `compiler_reason`, and `compiler_decompiled` expose
success, abstention, and text reconstruction. The full original observation
and producer context remain in `input_json`.

`logic_target_observation_json` captures the independent source-derived target
used during evaluation. `bridge_names_json` reports adapters invoked;
`observed_logic_views_json` records actual view names and
`observed_logic_families_json` records explicitly declared family metadata.
These fields do not certify that every requested logic family compiled or
passed a syntax validator. External prover evaluation is disabled in this
legacy diagnostic campaign.

Large graph payloads inside newly captured target documents use the lossless
`recursive-zlib-json/v1` document encoding. Compact formal views stay readable;
compressed nested payloads retain their exact uncompressed byte lengths and
SHA-256 digests. The canonical checkout provides `unpack_document` in
`ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_span_logic_artifacts`
to reconstruct and verify the full document within explicit bounds. Packing
does not discard graph evidence or convert a target into model output.

From the canonical checkout, decode a retained observation with:

```python
import json
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_span_logic_artifacts import (
    DOCUMENT_ENCODING, unpack_document,
)

observation = json.loads(row["logic_target_observation_json"])
document = observation.get("document") if observation else None
if document is not None and observation.get("document_encoding") == DOCUMENT_ENCODING:
    document = unpack_document(document, max_decoded_bytes=16 * 1024 * 1024)
```

The helper verifies each compressed field and the aggregate decoded document
bound. The indexer itself preserves the packed observation without expanding it.

Older v2 exports may contain a target hash without the full target document.
Historical indexing cannot recover artifacts that were never recorded. Those
derived rows explicitly report `logic_target_availability=not_recorded_in_source`.

## Deferred compiler-improvement goals

`supervisor_goals_v2` stores `packet_json`, `task_json`, packet/task hashes, and
the associated `census_sha256`. New packets retain observation context and
references needed to review compiler errors alongside autoencoder diagnostics.
The goals remain `handoff_status=dataset`, `enqueued=false`; publishing them
does not execute a supervisor task or authorize a source change.

The canonical repository's `scripts/ops/legal_ir/import_span_cache_exchange.py`
validates an exact exchange manifest before planning a later import. An explicit
native import creates review-only blocked work. Dataset-supplied commands are
not automatically adopted as validation commands. Existing admission and
compiler acceptance requirements still apply.

## Immutable bundles and historical backfill

Exchange manifests under `autoformal/uscode/exchanges/` bind a census parquet
and a goals parquet using exact hashes and row counts. Derived output manifests
under `autoformal/uscode/outputs/` bind their output parquet and the original
manifest/census/goals at a pinned commit. Derived tables never replace the
original evidence, progress ledger, or weights.

The first historical output index contains 32 observations, including one
retained compiler rule, and was published at
[`df7e8af9dd824ab8b364fab1e28646d9dc6267f8`](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/commit/df7e8af9dd824ab8b364fab1e28646d9dc6267f8).
Its [queryable parquet](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/blob/df7e8af9dd824ab8b364fab1e28646d9dc6267f8/autoformal/uscode/outputs/retained-output-index/outputs-1423fd643d03e8a25cbcd78ba4916ad0e083d999649e44633db8de9d7a56d5dd.parquet)
exposes the already retained evidence without rerunning inference. This is a
bounded sample, not a count of all conversions in the repository.

The backfill command is
`scripts/ops/legal_ir/index_span_exchange_outputs.py`. It processes explicit
pinned manifests within byte and row caps, validates hashes and source closure,
and optionally appends content-addressed tables with a parent-commit CAS.
No model loading, weight download, inference, training, or goal execution occurs
during indexing. `inference_executed=false` in a derived index describes that
indexing operation; the original producer execution remains in its retained
observation.
