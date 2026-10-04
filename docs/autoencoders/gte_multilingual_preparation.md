# Multilingual 768D embedding preparation

The 768D source producer and corpus handoff are implemented alongside the existing 8D and 384D paths. The [cache reuse step](gte_embedding_reuse.md) comes first: reuse matching existing receipts and encode only missing native 768D tasks. The same archived 384D vectors and cached GTE-small assets remain available and are preserved. Real target inference is currently unavailable because the readable cache/workspace inventory found no pinned multilingual weights/code or populated 768D receipts. No target weights were downloaded, no 768D vectors were generated, and no training ran.

Use the [migration plan](gte_multilingual_migration_plan.md) for the November transfer sequence. This producer creates source embeddings; the learned 768→384 bridge, native 768D IR decoder and teacher-supervision exporter remain separate work items. The [parallel model workers](gte_parallel_model_workers.md) retain the verified 8D/384D smoke; all 23 files bound by its numerical receipt were preserved.

## Implemented contracts

| Component | Behavior |
| --- | --- |
| [Local asset inspector](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_multilingual_profile.py) | Authenticates seven files against published SHA256 and byte counts without model imports or downloads |
| [Source producer](../../ipfs_datasets_py/logic/formalization/autoencoder/source_embeddings_768.py) | CPU float32, eager attention, right padding, CLS pooling and L2 normalization |
| [Corpus handoff](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_multilingual_corpus.py) | Recomputes the entire 384D audit, preserves memberships and target hashes, and prepares exact sources |
| [Offline CLI](../../scripts/ops/autoencoder/prepare_gte_multilingual.py) | Prepares tasks, inspects assets or explicitly attempts embedding; publishes fresh, hash-bound outputs |

The model revision is 9bbca17d9273fd0d03d5725c7a4b0f6b45142062. Its implementation is separately pinned to Alibaba-NLP/new-impl at 40ced75c3017eb27626c9d4ea981bde21a2662f4. The representation ID includes both revisions, 768 dimensions, CLS/L2, CPU float32 and the 8192-token rejection policy.

The [pinned configuration](https://huggingface.co/Alibaba-NLP/gte-multilingual-base/blob/9bbca17d9273fd0d03d5725c7a4b0f6b45142062/config.json) sets 768 hidden dimensions and an 8192-position limit. The [tokenizer metadata](https://huggingface.co/Alibaba-NLP/gte-multilingual-base/blob/9bbca17d9273fd0d03d5725c7a4b0f6b45142062/tokenizer_config.json) advertises 32768. This producer explicitly enforces **8192 tokens including special tokens**, with truncation disabled, before any model forward pass. Target token counts are separate from GTE-small's 512-token counts.

Only id and exact source_text enter the producer. Targets, group/document IDs, original 384D vectors, teacher predictions and metadata remain outside neural input. Each receipt binds the UTF8 source hash, unpadded token-ID hash, token count, representation ID, asset manifest hash and finite normalized 768D vector. A declaration alone does not independently prove encoder execution.

Requests admit at most 4096 rows, 65536 characters and 262144 UTF8 bytes per source, 16 MiB source bytes total and 262144 tokens total. Batch size defaults to 1 and is bounded to 1–16. These are admission bounds; eager 8192-token attention memory still needs measurement on the intended hardware.

The loader compiles the two verified modules under a private namespace and directly loads local safetensors. It does not resolve remote AutoModel code or execute a package initializer. Missing assets return unavailable before Torch/Transformers imports. Malformed assets, changed hashes, unsupported weights, unknown executable files and symlinks fail admission. Assets are rechecked after loading and inference.

## Retained evidence

The [input provenance](../../../../artifacts/gte-multilingual-preparation-20261001/inputs-01/provenance.json) records reconstruction from all 16 pinned datasets through the exact archived adapter. The complete recomputed audit equals the existing run-02 audit. The input snapshot contains original 384D vectors and reference payloads; it is a provenance input, not a neural worker input.

| Outcome | Count |
| --- | ---: |
| Archived input rows | 2640 |
| Eligible source tasks | 1920 |
| Retained training tasks | 1440 |
| Retained validation tasks | 480 |
| Quarantined archived test/canary rows | 720 |
| Generated 768D vectors | 0 |

[Preparation run-01](../../../../artifacts/gte-multilingual-preparation-20261001/run-01/summary.json) exports task metadata and target hashes without target content or 384D vectors. Its manifest SHA256 is 2f95b3ac6691c87f2dd16712f3d314b59d0aefb37a9cfa948c70d54693b24cdb.

[Embedding attempt embed-01](../../../../artifacts/gte-multilingual-preparation-20261001/embed-01/summary.json) reports unavailable assets, zero receipts and all 1920 task IDs missing. Its manifest SHA256 is 26915112dd4c883abed8531ddbe8feb7e78864cf99875732feef433db4ec1556. Exit code 1 is the expected unavailable outcome. It did not execute a model.

The [latest asset inspection](../../../../artifacts/gte-multilingual-preparation-20261001/asset-availability-02.json) reports missing model and code directories. Earlier inspection evidence is preserved. The [verification record](../../../../artifacts/gte-multilingual-preparation-20261001/verification.json) binds implementation, tests, artifacts and the preserved numerical receipt.

## Stage the next step

The [asset manifest template](../../configs/autoencoders/gte_multilingual_local_assets_v1.json) lists authenticated content; it does not establish that the files exist. Its SHA256 is 8beb874aa7b06599346173fde12e95f9f926b3028942d5014cdd2f99c4385166.

Stage ordinary files from the pinned [model revision](https://huggingface.co/Alibaba-NLP/gte-multilingual-base/tree/9bbca17d9273fd0d03d5725c7a4b0f6b45142062) and [implementation revision](https://huggingface.co/Alibaba-NLP/new-impl/tree/40ced75c3017eb27626c9d4ea981bde21a2662f4) in separate private directories:

- Model: config.json, tokenizer_config.json, special_tokens_map.json, tokenizer.json and model.safetensors.
- Code: configuration.py and modeling.py.

The first profile supports one unsharded safetensors file. Hugging Face snapshot symlinks must be materialized into ordinary files. A changed revision or weight format needs a separately reviewed profile.

Run from the repository with fresh report/output paths:

~~~bash
python scripts/ops/autoencoder/prepare_gte_multilingual.py inspect-assets \
  --asset-manifest configs/autoencoders/gte_multilingual_local_assets_v1.json \
  --expected-asset-manifest-sha256 8beb874aa7b06599346173fde12e95f9f926b3028942d5014cdd2f99c4385166 \
  --model-directory /home/barberb/lift_coding/artifacts/gte-multilingual-assets/model \
  --code-directory /home/barberb/lift_coding/artifacts/gte-multilingual-assets/code \
  --report-file /home/barberb/lift_coding/artifacts/gte-multilingual-preparation-20261001/asset-availability-03.json

python scripts/ops/autoencoder/prepare_gte_multilingual.py embed \
  --tasks-file /home/barberb/lift_coding/artifacts/gte-multilingual-preparation-20261001/run-01/tasks.json \
  --expected-tasks-sha256 887dc1d23a9f0ed7a99c2b2f7c2500833f9328ddd97afd3ef750ddbffa5eb826 \
  --asset-manifest configs/autoencoders/gte_multilingual_local_assets_v1.json \
  --expected-asset-manifest-sha256 8beb874aa7b06599346173fde12e95f9f926b3028942d5014cdd2f99c4385166 \
  --model-directory /home/barberb/lift_coding/artifacts/gte-multilingual-assets/model \
  --code-directory /home/barberb/lift_coding/artifacts/gte-multilingual-assets/code \
  --output-directory /home/barberb/lift_coding/artifacts/gte-multilingual-preparation-20261001/embed-02 \
  --batch-size 1
~~~

Run cache admission before the explicit embed command; this older embed command always processes the tasks supplied to it. If receipts cover the cohort, no local assets or encoder call are required for reuse. Otherwise inspect existing compatible multilingual assets before staging missing files, and use only the exported missing-task list for encoding. First use a small audited source cohort for native numerical qualification and resource measurement. Reports record batch/attention/padding policy and dependency versions. Local hashes do not establish multilingual accuracy, actual 8192-token behavior, target semantics, teacher readiness or three-model concurrent resource admission.

The prepare subcommand accepts a hash-pinned transfer-row JSON list and its complete hash-pinned 384D audit. It recomputes the audit before publishing tasks and empty receipt bindings. The retained input snapshot hash is 1bf8fd385e0b484c4c99ef6465b1be9cfedfb24bcc252d354959a9610e73f0f3; archived corpus-audit.json hash is 588dde10f54207476e429323ad0f6834d9b1bffb501dd7df5913e89bd9f180a1. Use --help for its flags.

## Validation and remaining gates

All 324 focused tests passed: 179 existing checks plus 57 asset, 35 handoff, 31 producer and 22 multilingual CLI checks. Producer numerical and token-boundary tests use a synthetic backend. Subprocess tests verify that preparation, inspection and unavailable embedding do not import model libraries.

WP04 remains in progress until the real tokenizer/weights produce reference fixtures, exact-source receipts and measured resources, including actual boundary inputs. WP06 can then fit the frozen 768→384 bridge against paired original-source embeddings or build a reference-supervised baseline. Screened teacher KD additionally requires WP02/WP05. The native 768D IR decoder and its parallel model worker remain unavailable; 8D and 384D continue under their separate contracts.
