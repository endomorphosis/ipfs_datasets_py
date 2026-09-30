# API and command map

[Handbook](README.md) · [Inputs](artifacts_and_inputs.md)

This maps tasks to public entrypoints. Start with the linked guide rather than
following internal class calls. Linked modules own validation and defaults.

## Native modalities

| Task | Entry point | Guide |
| --- | --- | --- |
| Prepare UI compiler views | [ui_targets.py](../../ipfs_datasets_py/logic/formalization/autoencoder/ui_targets.py): `prepare_ui_targets` | [Modalities](modalities.md) |
| Prepare explicit DOM/IDL training rows | [ui_training_inputs.py](../../ipfs_datasets_py/logic/formalization/autoencoder/ui_training_inputs.py): `prepare_ui_training_row` | [UI datasets and bindings](ui_datasets_and_bindings.md) |
| Train, resume or infer from local UI JSONL | [run_ui_feature_training.py](../../scripts/ops/ui_ux_ir/run_ui_feature_training.py); [ui_feature_training.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/ui_feature_training.py) | [UI commands and fixtures](ui_datasets_and_bindings.md#bounded-local-commands) |
| Validate mediated IDL request/result data | [idl_projection.py](../../ipfs_datasets_py/logic/ui_ux_ir/runtime/idl_projection.py): `project_idl_request`, `project_idl_result` | [UI binding boundaries](ui_datasets_and_bindings.md#local-route-and-current-boundaries) |
| Prepare Intent routes or Security source-bound declarations | [domain_targets.py](../../ipfs_datasets_py/logic/formalization/autoencoder/domain_targets.py): `prepare_intent_targets`, `prepare_security_targets` | [Modalities](modalities.md) |
| Bind exact Security source and native model | [code_logic_projection.py](../../ipfs_datasets_py/logic/security_ir/code_logic_projection.py): `CodeLogicEvidence` | [Modalities](modalities.md) |
| Validate/load native targets | `DomainTargetEnvelope.from_dict`, `.to_dict`, `.digest` | [Artifacts](artifacts_and_inputs.md) |
| Define model compatibility and local capabilities | [autoencoder_modality_contracts.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_modality_contracts.py): `ModalityContract`, `ProjectionSpec`, `require_compatible_contracts`, `ModalityAdapterRegistry` | [Modalities](modalities.md) |
| Fit vocabulary and concrete contract | [autoencoder_projection_features.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_projection_features.py): `build_feature_space`, `build_native_feature_contract` | [Quickstart](native_feature_quickstart.md) |
| Train/resume, infer, register | Same module: `train_projection_features`, `infer_projection_features`, `register_feature_candidate` | [Quickstart](native_feature_quickstart.md), [inference](inference_and_qualification.md) |

No generic nonlegal distributed CLI is installed by these APIs. The existing
`scripts/training/train_intent_autoencoder.py` is a separate script, not an alias
for this backend; check its format before reusing output.

## Legal lifecycle

| Task | Entry point | Guide |
| --- | --- | --- |
| Local incremental inference/training | [run_incremental_autoencoders.py](../../scripts/ops/legal_ir/run_incremental_autoencoders.py) | [Training](legal_training.md), [inference](inference_and_qualification.md) |
| Owner/remote worker protocol | [run_distributed_autoencoders.py](../../scripts/ops/legal_ir/run_distributed_autoencoders.py) | [Control plane](control_plane_and_sync.md) |
| Hardware-aware worker waves | [run_autoencoder_fleet.py](../../scripts/ops/legal_ir/run_autoencoder_fleet.py) | [Operations](operations_and_troubleshooting.md) |
| Shared legal targets | [prepare_shared_autoencoder_targets.py](../../scripts/ops/legal_ir/prepare_shared_autoencoder_targets.py); [autoencoder_target_preparation.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_target_preparation.py): `prepare_training_targets` | [Training](legal_training.md) |
| Semantic-embedding input verification | [autoencoder_feature_inputs.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_feature_inputs.py): `verify_feature_training_inputs` | [Inputs](artifacts_and_inputs.md) |
| One immutable worker job | [autoencoder_training_worker.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_worker.py): `execute_training_job`, `execute_training_job_file` | [Training](legal_training.md) |
| Independent bounded job dispatch | [autoencoder_training_coordinator.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_coordinator.py): `run_training_jobs` | [Control plane](control_plane_and_sync.md) |
| Candidate qualification | [autoencoder_candidate_qualification.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_candidate_qualification.py) | [Qualification](inference_and_qualification.md) |
| Local feature selection | [autoencoder_feature_training.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_feature_training.py): `run_feature_incremental_training` | [Training](legal_training.md) |
| Distributed feature generation | [autoencoder_distributed_features.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_distributed_features.py): `execute_feature_assignment`, `owner_feature_verifier`, `advance_feature_generation` | [Control plane](control_plane_and_sync.md) |

Check script `--help` before adapting a recipe. CLI names, config dataclasses,
and numerical-model argument names can differ. Do not bypass bounded worker
deadlines or qualification by calling an unbounded lower-level method.

## Storage and runtime

| Responsibility | Owning module |
| --- | --- |
| Artifacts, variants, versions, leases, publication metadata | [autoencoder_registry.py](../../ipfs_datasets_py/duckdb_control/autoencoder_registry.py): `AutoencoderRegistry` |
| Scoped remote operations | [autoencoder_quack.py](../../ipfs_datasets_py/duckdb_control/autoencoder_quack.py), [wire schema](../../ipfs_datasets_py/duckdb_control/autoencoder_quack_wire.py) |
| Fenced generations and span attempts | [autoencoder_span_campaign.py](../../ipfs_datasets_py/duckdb_control/autoencoder_span_campaign.py) |
| DuckLake delivery | [autoencoder_ducklake.py](../../ipfs_datasets_py/duckdb_control/autoencoder_ducklake.py) |
| Legal feature checkpoint/update/report exchange | [autoencoder_feature_exchange.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_feature_exchange.py): `stage_feature_update`, `publish_feature_update`, `download_feature_update` |
| Qualified incremental Hub exchange | [autoencoder_incremental.py](../../ipfs_datasets_py/huggingface/autoencoder_incremental.py), [download](../../ipfs_datasets_py/huggingface/autoencoder_incremental_download.py) |
| Legal full/Arrow/sparse loaders | [modal_autoencoder_checkpoint.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder_checkpoint.py), [Arrow weights](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder_arrow_weights.py), [sparse checkpoints](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder_sparse_checkpoint.py) |
| Verified Arrow embedding buffers | [autoencoder_arrow_inputs.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_arrow_inputs.py): `write_embedding_inputs_ipc`, `load_embedding_inputs_ipc` |
| Resource and retained-storage accounting | [autoencoder_daemon_resources.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py): `DaemonResourceReservation` |
| Capacity planning | [autoencoder_capacity.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_capacity.py) |
| Frozen source | [autoencoder_source_snapshot.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_source_snapshot.py): `prepare_snapshot`, `verify_snapshot`, `run_snapshot` |
| Concurrent source integration | [merge_autoencoder_source.py](../../scripts/ops/legal_ir/merge_autoencoder_source.py), [autoencoder_source_merge.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_source_merge.py) |

The [control plane guide](control_plane_and_sync.md) identifies which process
owns each operation. These modules do not permit independent writers to open
one shared DuckDB file across machines.

## Evidence lookup

| Question | Inspect |
| --- | --- |
| Did optimization improve? | Before/after objective, per-projection regressions, attempted/selected work, stop reason |
| Was legal IR actually evaluated? | Nonzero `legal_ir_target_count`, bridge names, losses, cache/prover/worker/sample flags |
| Did inference mutate weights? | Inference result and checkpoint identity checks |
| Why was an update rejected? | Selection/qualification report and owner decision, not just process exit code |
| Can another machine replay it? | Exact parent/dependencies, published references, reconstructed full-state digest and generation |
| Was a formula admitted? | Source-locked legal Lake receipt, separately from feature/transport scores |

See [operations](operations_and_troubleshooting.md) for troubleshooting and
bounded validation commands. Dated reports provide deeper run-specific evidence.
