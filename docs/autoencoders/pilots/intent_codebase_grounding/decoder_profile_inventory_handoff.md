# Decoder profile inventory and run selection

This phase implements the next step in the
[format/checkpoint plan](decoder_format_handoff.md): a detached catalog over the
existing twelve family/dimension inventories. It preserves those inventories,
their database and Hugging Face destinations, and the referenced weights and
cached embeddings. The catalog is a metadata export; it creates no DuckDB,
DuckLake or Hugging Face store and performs no model training or inference.

## Three identities

| Identity | Includes | Used for |
| --- | --- | --- |
| Format | IR family, output format, schema version, decoder task, output scope and target kind | Distinguishing a fragment, full document, text reconstruction or learned logic head |
| Profile | Format, dimension/role, architecture, ordered codec, implementation generation, inference configuration, declared producer and token policy | Comparing compatible training and ablation runs |
| Checkpoint/run binding | Exact checkpoint path/bytes/SHA, package, original corpus and fitting manifests, complete checkpoint configuration and explicit run alias | Selecting an immutable saved state |

The prior format-contract hash includes a checkpoint and corpus. It remains a
concrete asset binding. The new format/profile IDs have separate meanings and
exclude those asset locators, fitting-data selections and run aliases.

The profile excludes the explicitly identified experiment settings: seed,
epochs, batch size, learning rate, patience, reconstruction-loss weight and
training time limit. Producer elapsed time and vector-execution count are also
observations outside the profile. The complete original settings remain in
the checkpoint record. Other configuration and producer fields are retained
conservatively, so an unknown field cannot silently become a compatibility
promise. Changing architecture, codec, output budget or producer declaration
changes the profile. Matching profile IDs do not establish numerical geometry,
semantic accuracy or teacher quality.

An inventory run alias is assigned by the catalog operator. An original
checkpoint without an authenticated run ID does not acquire one retrospectively.
Multiple aliases can refer to the same preserved checkpoint without copying its
weights or implying that another training run happened.

## Scope of registration

The initial formats registered within this detached catalog are the preserved SecurityIR 384D
ProgramExpression fragment and IntentIR 384D rich-AST fragment. Registration
uses the existing format preparation checks, complete original corpus, ordered
training/validation manifests, codec and implementation receipts.

Every lane preserves its original checkpoint declarations and distinguishes
hash-verified bytes, missing references and an absent supported format binding.
Unsupported checkpoint payloads are hashed without loading their models. A lane
with no registered fragment head can still contain useful initialization or
structural donor weights.

In particular, LegalIR/768 contains an inherited initialization with separate
384D and 8D decoder vocabularies. Its parameters were inherited, but input
alignment and training remain required; native encoder, source-fidelity and
teacher qualifications remain false. CodebaseIR/8 retains its 53-feature to
8D-latent structural checkpoint. CodebaseIR/384 retains its recorded SecurityIR
payload, which does not become a CodebaseIR source decoder merely by occupying
that lane. Unknown historical task declarations remain unknown.

## Selection and asset reuse

The builder takes explicitly pinned directory/cell inventories and closed
bindings containing the legacy cell request, format request, package/corpus
pins and run alias. It derives original training-row membership from the
authenticated corpus. Gold targets, native evidence, source text and vector
bodies from that corpus are not copied into the exported registry.

The resolver requires the registry pin, exact five-field cell request, explicit
format/schema/task request, profile ID and run alias. It rebuilds the entire
catalog from its bound inputs before selecting one exact checkpoint record.
There is no automatic `latest` pointer, width-only or family fallback. A changed unselected asset
or a forged profile/qualification field invalidates the snapshot too.

Selection returns captured replay bindings for the existing format runtime.
Callers supply their own explicitly authenticated corpus split and row IDs to
that runtime. This phase adds metadata selection; it does not add another
numerical loader or qualify historical implementation generations for a modern
runtime. Catalog and file observations are repeated endpoint checks, not an
atomic snapshot or continuing currentness guarantee.

## Accelerate ModelManager registration

The catalog currently has no ModelManager registration call. A separate
read-only audit on 2026-10-04 found zero rows in the observed repository-default
`external/ipfs_accelerate/model_manager.duckdb` model-metadata table. The file
was unchanged after the query. That does not establish the contents of an
active supervisor/MCP manager using a different configured store.

Manager synchronization must project exact checkpoint/profile/run records into
declared metadata and read them back by their immutable identity. GTE embedding
encoders need their own registrations; they are not aliases for learned IR
decoders. Initialization-only weights should remain discoverable as donor
assets without acquiring serving, trained-native-input, source-fidelity or
teacher claims. No serving configuration, deployment/router binding or generic
embedding-generation operation should be invented for these decoder records.

The manager's registration method also persists data and invokes provenance,
knowledge-graph and optional service hooks. Its integration needs an explicit
target manager/store, bounded side effects and persisted read-back evidence.
The read-only registration audit did not instantiate that manager or modify its
store; the new profile catalog does not imply durable manager registration.

## Next integrations

1. Connect the exact records to the intended Accelerate ModelManager store,
   preserve initialization/qualification status, and verify durable read-back.
   Import the detached records into each lane's inventory, then add
   format/profile/run foreign keys to its DuckDB/DuckLake training, embedding,
   evaluation and proof-index rows. Preserve asset receipts and explicit task
   bindings through that migration.
2. Use the same profile and checkpoint/run identities in Hugging Face paths
   and promotion pointers. Reference shared backbone weights and preserved
   embedding caches; require explicit compatibility mappings for a different
   learned head or tokenizer.
3. Add Legal canonical-rule and Codebase structural-feature format contracts,
   then separate full-document and legal-text decoder heads. Exact text,
   normalized text, exact IR and retained-source restoration keep their own
   metrics and attempted-row denominators.
4. Bind source-conditioned training and ablations to these records. Start from
   retained parameters, record newly initialized components, and declare
   acceptance thresholds before using predictions as distillation labels.
5. Connect Intent planning and proof caches to repository revisions/spans,
   decoder profiles/checkpoints and versioned verifier/projection policies.
   Formalized candidates remain distinct from verified proofs.
6. Admit authentic same-source 768D vectors and explicit 8D/384D transfer
   mappings before native multilingual-GTE training. Preserve the original
   vectors and evaluate larger source spans and decoder target limits separately.

## Validation and saved snapshot

The finite metadata controls passed 504 cases (437 existing and 67 new), with
no failed, skipped or deselected cases. The actual-asset catalog build preserved
all twelve lanes, produced two formats, two profiles and two exact checkpoint
records, and checked all sixteen original corpus targets for each supported
head. Both exact routes succeeded; fourteen foreign or incomplete selectors
were rejected. These checks did not execute decoder tensors, generate new
embeddings, train a model, or establish reconstruction quality.

The saved [actual catalog](../../../../../../artifacts/ir-decoder-profile-inventory-20261004/controls/runs/actual-inventory-v3/profile-inventory.json)
has SHA256 `7124e191e7f6decc204b449dd9d8db3720f123278ba2cf8b7d4f1517bf63d641`.
The catalog is an external handoff artifact; its absolute pin and the twelve
lane views are recorded in [the machine-readable handoff](decoder_profile_inventory_handoff.json).
Local locators must be preserved or explicitly rebound when this work is moved.

`build_ir_decoder_profile_inventory` creates the catalog from pinned inputs.
`resolve_ir_decoder_profile_route` takes an exact registry pin, cell request,
format request, profile ID and run alias. Its `replay_binding_options` return
the six bindings accepted by the existing format preparation API. A caller
must additionally choose explicit corpus splits and row IDs; registry membership
does not permit inventing or widening a fitting/evaluation split.

ModelManager registration remains pending. The read-only audit of the observed
default store found zero model rows, and this phase made no manager writes.
The branch is a local successor to the format/checkpoint phase, with an
incremental bundle and separate preservation evidence; it does not update
GitHub `origin/main`, publish Hugging Face assets, or migrate a physical store.
