# Register LegalIR 4096D source representation assets

`ir_model_manager_import.import_ir_model_manager_records_v2` adds an explicit
metadata registration route for the retained LegalIR source/span decoder.
Existing v1 imports, record IDs, detached components and the twelve-cell
inventory retain their original contracts.

The v2 plan uses `ir-model-manager-import-plan/v2` and the existing closed
model/checkpoint/release envelope. It accepts unchanged legacy records alongside
`ir-source-representation-binding/v2` records. A source binding declares
`legal_ir`, dimension4096, role `source_input_representation_width`, and task
`source_text_and_representation_to_legal_ir`. The source/span checkpoint schema
is explicitly either `native-4096-source-span-checkpoint/v1` or
`bound-native4096-source-span-checkpoint/v1`.

Use `ir_model_source_record_id_v2` to calculate the new record ID. It binds the
checkpoint's saved-file SHA256, checkpoint schema, task, declared role and
source representation declaration. Evidence content hashes identify the same
logical evidence after a locator change; import still authenticates every
explicit locator. Keep an owner's semantic checkpoint digest separately from
the SHA256 of the serialized file used for publication and import.

The closed `source_representation` declaration uses
`ir-native4096-source-profile/v1`. It carries the existing seven-field
`expected_producer` declaration, including model, worker, source and library
hashes; last pooling, L2 normalization, causal attention,512tokens and one
sequence; required source text; and one to eight pinned historical evidence
files. It retains `evidence_scope=pinned_historical_metadata_only` and
`ordinary_receipt_is_capability=false`. Both existing lazy-mmap v2 and
layer-reclaim v3 producer profile names are supported as declarations.

The decoder's IO explicitly includes plaintext plus float32[4096], with a text
LegalIR output. This width describes source input, separately from the internal
projection and recurrent state. The October17 pilot used hidden8, token
embedding4 and projection4 alongside source text. Larger owner defaults describe
different configurations; neither route establishes vector-only reconstruction.

Keep `profile_id` and `format_id` null and
`complete_runtime_io_contract=false`. The metadata must explicitly retain false
native-execution verification, source-compatibility verification and restored
live-capability flags. Runtime readiness, teacher qualification and proof
authority also remain false. Evidence files are hash-checked as opaque bytes;
the importer does not independently verify that the claimed native run occurred,
interpret model tensors or restore a process/thread-bound capability.

The existing publisher supplies immutable file publication receipts. The
existing manager import loop checks all conflicts before mutation, preserves
identical records and activity, and requires driver-owned fresh persisted
readback. A successful injected readback does not prove that the driver reopened
storage. This extension opens no DB, runs no encoder, uploads no model, refreshes
no supervisor and changes no selected runtime.

Actual delivery still requires authenticating the selected original checkpoint
files, publishing missing decoder assets through the existing publisher,
importing into the explicitly configured manager and verifying real persistence.
The separate4096 inventory/routing profile, decoder runtime delivery and legal
evaluation retain their own gates. The67GB upstream Leanstral model need not be
copied into the bounded decoder release stage.

The retained October17 assets have now completed that publication and
retained-catalog registration path. All three original checkpoints are public at
[the immutable Hugging Face release](https://huggingface.co/Publicus/legal-ir-autoencoder-4096d/tree/7f1621e79eef7592d0cfdb06cbc2f11370e24dc5);
anonymous downloads matched every published payload hash. The existing selected
`external/ipfs_accelerate/model_manager.duckdb` catalog grew from687 to690
records, with per-insert native readbacks, cold native readback, a genuine cold
manager reload and three typed catalog resolutions. All687 baseline records'
metadata/activity and the schema/indexes were preserved. The compatible typed
reader is merged in [Accelerate PR295](https://github.com/endomorphosis/ipfs_accelerate_py/pull/295).

The original registration owner finalized its compute/storage reservation and
writer lock; both source READ leases were released. The configured MCP service's
separate state database and other running manager instances were not refreshed.
These remain two-example smoke-test checkpoints with zero decoded examples, no
held-out statutes, and false runtime/teacher/proof flags.
[The delivery evidence](../autoformalization/evidence/native4096-retained-assets-20261020.json)
records artifact identities,94 catalog controls,42 import-safety controls and
the remaining inventory, runtime, supervisor and legal-evaluation gates.
