# Reuse existing model assets and embedding caches

The migration reuses the existing 8D and 384D decoder assets and cached data.
Keep their original weights, codecs, transforms, source identities and splits.
Do not rerun the old encoders to recreate embeddings that already exist. The
new cache-admission command also reuses compatible multilingual 768D receipts
before listing the sources that still need an embedding.

## Existing assets and vectors

The October 2 audit verifies every migration vector against its original file,
without loading a model or changing any coordinates:

| Existing resource | Verified content | Reuse |
| --- | --- | --- |
| V3 source-native archives | 2640 vectors of width 384 across 16 files; exact vector, source, reference, group and split matches with the migration snapshot | Keep these same archived vectors as the 384D side of future alignment pairs |
| Earlier V2 reconstruction archives | 1320 cached 384D vectors with matching original vector/source hashes | Keep the earlier donor's own replay and evaluation cohort; it has no exact ID/source overlap with V3 |
| GTE-small cached assets | All nine declared files match both V2 and V3 asset manifests, totaling 67691071 bytes | Reuse the existing tokenizer, weights and pooling files whenever the 384D producer is needed |
| Historical and local linguistic 8D caches | Two backend-specific cohorts, each with 58 width-8 feature vectors | Preserve each backend's independent lane and diagnostic inputs; do not mix their coordinates |
| Learned 8D/384D decoder heads | All 26 tensors already copied in the dual-donor initialization | Continue from those learned weights through the aligned-student handoff |

The [decoder knowledge replay](gte_decoder_knowledge_transfer.md) uses the
compatible V2 Legal training cache first and reconstructs the learned 8D head's
original two raw latents from its saved synthetic inputs. Both are checked
against their exact donor training manifests. The newer V3 references are
outside the selected 384D head's vocabulary, so their cached vectors may supply
alignment pairs while reference-prefix training needs a new codec generation.

The existing source-model snapshot is
~~~text
/home/barberb/.cache/huggingface/hub/models--thenlper--gte-small/snapshots/17e1f347d17fe144873b1201da91788898c639cd
~~~
Its normal Hugging Face cache symlinks resolve to existing blobs whose bytes
match the archived pins. No assets were downloaded or copied into a new model
directory. The reuse audit records both snapshot paths and resolved file hashes.

All 2640 migration vectors match their original embedding JSON digests without
float conversion, normalization or truncation. Their source text, references,
groups and splits also remain unchanged. The V3 execution report declares 1920
development rows; byte equality across the full archive does not independently
authenticate every prior encoder execution. Historical CUDA production remains
recorded as CUDA; existing vectors are not relabeled as new CPU encoder outputs.

The 8D linguistic caches use distinct backend identities and deterministic
linguistic features. Their source cohorts do not overlap the current V3 transfer
corpus, and their coordinates differ from the experimental learned grammar
head's inputs. Preserve these caches for their original lane. They cannot be
silently joined to unrelated sources or treated as the grammar head's latent
targets. The two modal schema vectors are explicitly synthetic fixtures.

## Reuse multilingual receipts before encoding

The [reuse helper](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_embedding_reuse.py)
admits existing receipts under the exact source ID/hash, 768D profile, token
policy and selected asset-manifest hash. It preserves receipt content, including
numeric leaf types, and exports only missing original tasks. Duplicates,
unexpected task IDs, changed sources, wrong dimensions/profiles and different
asset generations fail admission. IDs and source hashes are not remapped.

The [command](../../scripts/ops/autoencoder/prepare_gte_embedding_reuse.py) also
authenticates the archived 384D rows, complete audit, original tasks and cache
file by their external hashes. It recomputes the tasks from the same audited
archive. Existing quarantine decisions, source text, references and partition
memberships remain unchanged. A complete 768D cache works with no local model
directory, Torch, Transformers or producer import. Partial coverage retains all
valid cached receipts and reports the exact missing cohort.

The [checked-in configuration](../../configs/autoencoders/gte_embedding_reuse_v1.json)
points to the same existing row/audit/task/receipt files. From the repository
root, use a fresh output directory:

~~~bash
python scripts/ops/autoencoder/prepare_gte_embedding_reuse.py \
  --config configs/autoencoders/gte_embedding_reuse_v1.json \
  --expected-config-sha256 1788b021e8c4a71471b9fbfdbfb0e7d671d140aeb55274864f4ec9dd257692bc \
  --output-directory /home/barberb/lift_coding/artifacts/gte-embedding-reuse-20261002/reproduction-01
~~~

Outputs are receipts.json, missing-tasks.json, binding.json, reuse.json, summary
and completion manifest. Ready coverage exits 0; partial/unavailable coverage
exits 1 with completed evidence; invalid input exits 2. No branch of this
command downloads assets, generates embeddings, loads a model or trains.

After authenticated 768D receipts become available, bind their new cache file
in a new configuration and reuse it across decoder experiments. A separate
explicit encoder invocation may process only missing-tasks.json. Join its
results with retained receipts into a new pinned cache, validate the complete
cohort again, then feed that cache to bridge/alignment preparation. Never
overwrite an older cache or reuse a vector after its exact source/profile
identity changes.

The old 384D vectors are retained training targets and teacher inputs. A native
Alibaba 768D input needs that producer's own coordinates; old 8D/384D vectors
cannot acquire that identity by padding or relabeling. Only missing native 768D
vectors need new encoding. Existing decoder bodies and the entire 384D cache
remain reusable before that encoding occurs.

## Current receipt and evidence

Artifacts and the archive reuse audit are under
~~~text
/home/barberb/lift_coding/artifacts/gte-embedding-reuse-20261002/
~~~
The current cache file is the original empty multilingual receipt list. The
reuse command retains all 2640 archived 384D vectors and exports 1920 missing
768D tasks, with zero generated embeddings or encoder calls. The Legal subset
still has 480 eligible tasks. This unavailable status describes 768D cache
coverage; the old model assets and cached 384D vectors are available.

The asset search covered the user's default Hugging Face cache, readable
workspace, relevant artifacts, test-log caches and data. It found the existing
GTE-small snapshot, but no pinned multilingual weights/code or populated 768D
receipt cache. An inaccessible root-owned cache was outside that search, so no
machine-wide absence is claimed. Missing proposed staging directories alone
are not an inventory of all existing assets.

| Receipt | SHA256 |
| --- | --- |
| archive-reuse-audit.json | 4218b8d58fc09cb6b06610936b13855f4f0a6fb0447f6ec5473332941c89c593 |
| run-01/manifest.json | 0322b44cd7cadedbf407d0217adbd06dbbf732e4867bc498c32e5b87e9e56687 |
| Retained 384D migration input | 1bf8fd385e0b484c4c99ef6465b1be9cfedfb24bcc252d354959a9610e73f0f3 |

Prior documents were snapshotted before edits. Earlier decoder, initialization,
source, parallel-run and alignment receipts remain immutable. Cache-consistency
checks do not qualify a teacher or establish student fidelity. The independent
8D, 384D and 768D lanes retain their own writers, optimizer state and identities.

Validation passed **186 targeted checks**: 64 new helper checks, 31 new command
checks and 91 existing corpus/receipt/pair checks. Complete-cache cases work
without assets or model-library imports; partial cases preserve exact receipt
content and expose only missing original tasks. Compilation and document links
also passed. The prior 1158-test migration receipt remains preserved separately.
