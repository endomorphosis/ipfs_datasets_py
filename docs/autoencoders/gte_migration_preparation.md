# GTE migration preparation tools and audits

The first preparation stage for the [384D to 768D migration](gte_multilingual_migration_plan.md) now has runnable local tools. They inventory checkpoint tensors and audit source/target/vector joins before a training experiment. The tools use only the Python standard library and do not import a model runtime.

The initial run inspected nine archived checkpoints and 2,640 authored diagnostic rows across Legal, Intent, Security, and UI/UX. It found 1,440 training rows and 480 tuning rows with complete fields and no detected partition conflict. Their typed targets, source semantics, and embedding producers still require independent validation. All 720 archived test/canary rows share composition groups across those partitions and were quarantined by the transfer audit. No split was rewritten and no original artifact was modified.

## Run the preparation

Use [prepare_gte_migration.py](../../scripts/ops/autoencoder/prepare_gte_migration.py) with the [current pinned local configuration](../../configs/autoencoders/gte_migration_preparation_20261001_repin.json) from the enclosing workspace. The configuration names exact local paths and SHA256 values. Use a fresh output directory each time:

```bash
cd /home/barberb/lift_coding
python3 external/ipfs_datasets/scripts/ops/autoencoder/prepare_gte_migration.py prepare \
  --config external/ipfs_datasets/configs/autoencoders/gte_migration_preparation_20261001_repin.json \
  --output-directory artifacts/gte-migration-preparation-20261001/new-run
```

Preparation prints a completion manifest SHA256. Keep that value outside the run directory and pass it explicitly when verifying. Verification checks the five output files, checkpoint/data inputs, and listed implementation/evidence bytes against the recorded bindings. Missing completion manifests and changed inputs fail; an existing output directory is never overwritten.

The current retained run has manifest SHA256 `1268cc515b46993d8f033471a1c34de90d5bbfb1a46942db87f7b8084c83352d`:

```bash
python3 external/ipfs_datasets/scripts/ops/autoencoder/prepare_gte_migration.py verify \
  --output-directory artifacts/gte-migration-preparation-20261001/run-02 \
  --expected-manifest-sha256 1268cc515b46993d8f033471a1c34de90d5bbfb1a46942db87f7b8084c83352d
```

Supply `--workspace-root` when relocating the exact relative input tree. Active source edits may invalidate the configuration or verification; preserve the original run and produce a new pinned configuration/run for changed inputs. This binding covers listed files, not the full repository or transitive runtime dependencies.

The first run and its [original configuration](../../configs/autoencoders/gte_migration_preparation_v1.json) are preserved. Its historical manifest SHA256 is `611b6394e2f538ce2c3f43ff1c3d4b5a5ff92a7ab8e7040ae8810ff9d56f251e`. Later shared-checkout edits changed `checkpoint_hub.py` and `autoencoder_runtime_registry.py`, so the old manifest now rejects the current source tree. The [source drift receipt](../../../../artifacts/gte-migration-preparation-20261001/source-drift-run-02.json) records both old and current hashes. Run 02 pins those current sources, passed explicit verification, and reproduces the same inventory/corpus counts without changing any partitions.

## Checkpoint capability inventory

[gte_migration_inventory.py](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_migration_inventory.py) provides `inspect_checkpoint(path, max_bytes=...)` and `snapshot_files(root, relative_paths)`. It checks strict JSON, bounded file reads, declared numerical shapes, codec identities, and supported schema families. An unknown schema remains explicitly unsupported. Shape compatibility is a transfer candidate, not a proof that a runtime will accept a checkpoint.

| Inspected path | Models | Actual input and transfer relevance |
| --- | ---: | --- |
| Shared source sequence | 4 | 384D source embeddings to Torch decoder logits; 13 tensors per model; suitable for a differentiable adapter pilot after teacher qualification |
| Structured Legal source | 2 | 384D embeddings to NumPy projection/classifiers; 6 tensors each; use exported alignment or supervision rather than an assumed autograd path |
| Complete Legal family features | 1 | 31,274 structural feature columns and latent width 8; 4 tensors; separate from GTE source embedding transfer |
| Intent paired copy | 1 | Custom lexical tokens, attention and copying; 14 tensors; separate lexical width and 192-token ceiling |
| Published Legal sparse package | 1 | Embeddings plus parser-derived features and sparse core, then a bound formula head; 13 formula tensors; replay/export its exact pipeline |

The Legal source-sequence candidate is `artifacts/source-reconstruction-v2-20261001/run-01/legal_ir/raw_ce-1729-checkpoint.json`. It has hidden width 32, token embedding width 16, projection width 8, 384 input dimensions, and no input centering in that saved configuration. Its presence resolves the earlier uncertainty about a concrete differentiable Legal candidate. The corpus audited below is a later corrected authored panel; this stage has not joined checkpoint predictions to that panel or executed a decoder.

The inventory classifies dimension-dependent projection/conditioning tensors, architecture-compatible recurrent tensors, and token-identity-mapped lexical/output tensors. It records optimizer-state presence without asserting resume compatibility. All teacher qualification and external-producer verification flags remain false in this inspection report.

## Corpus joins and partition audit

[gte_transfer_corpus.py](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_transfer_corpus.py) exposes `audit_transfer_rows(rows, dimension=384, vector_space_id=..., max_rows=...)`. Its closed row contract preserves domain, sample, document/group identities, split, source, vector, target origin, language declaration, and evaluation role.

The audit connects related rows through document/group IDs, exact and normalized source identity, and numeric vector identity. Cross-partition connections and conflicting reference targets quarantine the entire connected component. Exact duplicate inputs are counted and deduplicated without rewriting original partitions. Unicode normalization is used only for conservative leakage checks; exact source bytes remain separately hashed.

| Domain | Training fields complete | Tuning fields complete | Test rows quarantined | Canary rows quarantined |
| --- | ---: | ---: | ---: | ---: |
| Legal | 360 | 120 | 120 | 60 |
| Intent | 360 | 120 | 120 | 60 |
| Security | 360 | 120 | 120 | 60 |
| UI/UX | 360 | 120 | 120 | 60 |
| Total | 1,440 | 480 | 480 | 240 |

Every vector has 384 finite coordinates and a measured norm within `1e-4` of one. Norms range from approximately 0.999999921 to 1.000000099. This numerical check does not authenticate the declared GTE producer.

The corrected source panel is under `artifacts/source-native-v3-20261001/run-02`. It provides synthetic composition groups but no original document spans. The configuration explicitly uses those synthetic groups as document units, declares authored target origins, and marks all evaluation inputs as exposed development artifacts. Canary and test variants share the same five groups in each domain. Their quarantine identifies that relationship; it does not mean the historical reports claimed independent canary groups.

The audit exports hashes, identities, eligibility, and counts. It does not export source text, targets, or vector payloads. Archived embedding metadata is represented by a digest rather than copied wholesale. Teacher predictions, if later supplied, remain distinct from reference targets and do not qualify as reference fitting rows. Missing vectors/targets, malformed rows, contradictions, and quarantine reasons remain in accounting.

Fresh sealed roles are caller declarations in this preparatory schema. The reports explicitly set `evaluation_seals_verified=false`; accepting a role does not establish independent sealing. All test/canary roles stay outside fitting/selection exports regardless of that declaration. A later campaign needs a separate sealed-cohort procedure and receipt.

## Retained evidence and validation

The [first run directory](../../../../artifacts/gte-migration-preparation-20261001/run-01/summary.json) contains:

- [Checkpoint inventory](../../../../artifacts/gte-migration-preparation-20261001/run-01/checkpoint-inventory.json), including pipeline, tensor, codec, and optimizer-state declarations.
- [Dataset inventory](../../../../artifacts/gte-migration-preparation-20261001/run-01/dataset-inventory.json), including origin, exposure, and document-identity policy.
- [Corpus audit](../../../../artifacts/gte-migration-preparation-20261001/run-01/corpus-audit.json), including all 2,640 bindings and quarantine decisions.
- [Completion manifest](../../../../artifacts/gte-migration-preparation-20261001/run-01/manifest.json), binding 25 input files, 25 source/evidence files, and five output files.

The three focused suites passed **77 tests**. They cover strict JSON and tensor shapes, incorrect dimensions, unknown schemas, filesystem boundaries, source/vector collisions, contradictory targets, connected quarantine, duplicate numeric identities, missing coverage, metadata payload exclusion, exposure declarations, and changed inputs/outputs/implementation. Both retained runs passed explicit verification against the source bytes present when they were produced; current-source verification uses run 02.

WP01 and WP03 are **in progress**. The inventory and reusable audit are implemented, but broader runtime replay, native target validation, external provenance verification, original-document/context contracts, and fresh sealed evaluation cohorts remain outstanding. A separate [CPU model-worker smoke](gte_parallel_model_workers.md) completed a three-source Legal384D replay concurrently with a trained linguistic8D model. The next independent work is WP04's versioned 768D producer. Teacher-logit exports and distillation still depend on WP02's source-fidelity gate. The [parallel lane contract](parallel_lineage_execution.md) keeps 8D and 384D work active during that development and requires immutable donor snapshots for transfer.
