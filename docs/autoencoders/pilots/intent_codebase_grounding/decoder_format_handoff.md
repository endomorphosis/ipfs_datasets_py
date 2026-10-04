# Decoder formats, checkpoints and ablation runs

Keep four IR families and three dimension sizes as twelve stable inventory,
storage and Hugging Face lanes. Within each lane, select a learned decoder by
its output format/schema version and task. Each training or ablation run has
its own immutable checkpoint files and lineage inside the appropriate lane.
Each family/size lane owns its inventory, DuckDB/DuckLake database and Hugging
Face repository; formats, tasks and runs have namespaces inside that lane.
An ablation does not need another database or repository simply because its
seed, loss coefficient, learning rate or parameter-freezing policy changes.

The distinction is between a compatible output contract and an individual
trained state. Two runs may share the same format, architecture and ordered
codec while producing different weights. A fragment, a complete document and
original-text reconstruction have different contracts and need separate head
identities. Sharing an encoder or inheriting compatible parameters does not
make those decoder checkpoints interchangeable.

## What the preserved checkpoints actually output

| Preserved asset | Observed output contract | Task and limits |
| --- | --- | --- |
| CodebaseIR 8D | `codebase-ir-source-bound-feature-targets@1` structural feature reconstruction | 53 compiler-derived input features to an 8D latent; width does not identify an 8-coordinate GTE embedding or a learned source-text decoder |
| SecurityIR 384D | `{kind: program_expression, document: …}` fragment under `program-ir/v1` | Original GTE-small source vectors to one ProgramExpression fragment; full SecurityIR documents are a different output contract |
| IntentIR 384D | `{kind: intent_rich_ast, document: …}` fragment under `intent-rich-grammar/v1` | Original GTE-small source vectors to a rich AST fragment; complete IntentIR documents are a different output contract |
| LegalIR 384D | One canonical rule under `CanonicalRoundTripIR@1`, projection `typed_deontic_rule_v1` | Parser/sparse-core-assisted formula generation; the formula head does not reconstruct original legal prose |

The Security and Intent validators accept additional document forms. Validator
capability does not show that these original heads were fitted on those forms.
All sixteen original Security targets are ProgramExpression fragments, and all
sixteen Intent targets are rich-AST fragments. The checkpoint fitting and
validation manifests bind the original twelve and two rows respectively. The
preserved inventories do not establish available native 768D checkpoints.

These are authenticated metadata and fitting-corpus observations. They do not
qualify semantic truth, numerical quality, original wording recovery or proof.
The Codebase asset is a structural checkpoint in its own lineage; it must not
be relabeled as a Legal formula decoder or a native GTE input checkpoint.

## Identity and storage rules

A format profile needs the IR family, dimension and dimension role, task,
output format/schema version, architecture and implementation generation,
ordered codec/token mapping, source producer and span/token policy. A concrete
checkpoint binding adds the immutable checkpoint and original fitting-data
receipts. Run IDs, seeds, ablation configurations and training steps identify
experiments under that profile. Record these roles separately so comparisons
do not group incompatible formats merely because their numerical widths match.

For example, keep one IntentIR/384 lane with namespaced releases for the rich
AST head, a future complete-document head and a future source-text head. Each
has its own checkpoint binding and promotion pointer. An unchanged original
corpus and vector cache can be referenced by multiple compatible experiments;
there is no need to regenerate or duplicate its embeddings.

DuckDB/DuckLake rows must carry the format profile, task, codec, producer,
checkpoint and run identities in addition to the existing family/size routing.
A Hugging Face lane can retain immutable paths such as
`decoders/<task>/<format>/<schema-version>/<run-id>/<checkpoint-sha>/`.
Do not use one unqualified `latest` pointer for all heads in a lane. A binding
manifest can refer to shared immutable backbone weights and a separate learned
head, but each decoder release still needs an independently selectable identity.
These are migration requirements; this phase creates no physical stores or
Hugging Face releases.

Deterministic IR-to-FOL/TDFOL/other logic projections remain versioned adapters.
Bind their implementation and target logic versions in proof-cache keys. They
need a separate learned decoder checkpoint when a trainable output head is
introduced for that task. Changing only a deterministic serializer does not
require inventing a new trained model, although it changes the projection/cache
identity and requires its own validation.

## Opt-in format checking for the original fragment heads

The new `checkpoint_hub.open_ir_decoder_format_autoencoder` API keeps the
existing five-field family/cell request and requires a separate closed
`format_request`. The supported original formats are:

| Family | `target_format_id` | `schema_version` | `task_id` |
| --- | --- | --- | --- |
| IntentIR | `intent_ir/intent_rich_ast` | `intent-rich-grammar/v1` | `source_to_native_ir` |
| SecurityIR | `security_ir/program_expression` | `program-ir/v1` | `source_to_native_ir` |

The version names identify the source-bound fragment contract even though each
fragment does not contain a top-level schema-version field. Preparation checks
the exact package, corpus, full original fitting/validation manifests, ordered
codec and format-specific implementation receipts. All original targets must
match the selected fragment contract, including unselected rows and splits.
Mismatched family, format, version or task is rejected before the fixed loader.
The existing API remains available for explicitly labeled legacy replay.

After inference, the wrapper checks the Domain report identity, captured row
IDs/source hashes, statuses and the structural format of decoded fragments.
Invalid-output rows remain in the attempted-row denominator. A foreign format
is refused with the returned raw report retained when it is valid JSON. Loader
and inference observations distinguish an attempt starting from a call returning;
an exception does not turn an attempted owner call into a metadata-only refusal.
These checks do not execute native grammar validators or qualify source semantics.

```python
format_request = {
    "target_format_id": "intent_ir/intent_rich_ast",
    "schema_version": "intent-rich-grammar/v1",
    "task_id": "source_to_native_ir",
}

decoder = checkpoint_hub.open_ir_decoder_format_autoencoder(
    directory_plan_pin, inventory_pins, cell_request,
    format_request=format_request,
    package_manifest_pin=package_manifest_pin,
    corpus_pin=original_corpus_pin,
    corpus_split="test", row_ids=original_test_row_ids,
)
```

All inputs to the numerical owner remain the original `id`, `source_text` and
`embedding`; gold targets and native evidence stay evaluator-side. Selecting
the format does not create new vectors, fit a codec, train a model or rewrite
an old checkpoint. Loading an original checkpoint still requires its matching
historical implementation generation; the format check does not make an
incompatible modern runtime compatible.

This API covers the two original 384D fragment heads. Legal, Codebase, other
sizes, complete documents, legal-text reconstruction and learned logic-output
heads need their own explicitly implemented format/runtime contracts. Their
absence is not handled by falling back to these fragment decoders.

## Training and ablation procedure

1. Preserve each authentic parent checkpoint, original corpus, vectors and
   source/codec implementation receipts. Assign an explicit output profile
   before starting a candidate. Record inherited versus newly initialized
   parameters and any optimizer-state mapping or reset.
2. Create one candidate checkpoint lineage per ablation run. Keep the same
   declared format and evaluation contract when comparing loss weights,
   learning rates, seeds, freezing schedules or compatible architecture trials.
   Architecture changes still need a new architecture/implementation identity.
3. Record original-data exposure, training/validation selections and retained
   unselected states. Compare target-free generation, critical-field accuracy,
   exact IR, coverage and failure/abstention counts alongside teacher-forced
   loss. Vocabulary or format changes require explicit inherited token-row
   mappings and a separately described comparison.
4. Promote a checkpoint only within its declared format/task/profile. Authentic
   but inaccurate weights can initialize a candidate without qualifying their
   predictions as teacher labels. Preserve failed candidates and denominators.
5. For legal-text reconstruction, create a separate learned surface/residual
   channel and text head, then evaluate from predicted IR/channel with raw
   source, gold IR and source-hash lookups withheld. Report exact UTF-8 and
   normalized text metrics separately from canonical-rule accuracy, rendering
   and retained-source restoration.
6. Warm-start each 768D format with compatible retained 8D/384D parameters and
   codecs. Retain original teacher inputs with an explicitly typed connector.
   Native multilingual-GTE alignment needs authentic retained 768D producer
   receipts for the same sources; do not pad, crop or relabel the original
   vectors. The 8,192-source-token profile needs separate span and target-cap
   evaluation for each decoder format.

Several different wordings can map to the same semantic rule. Exact original
wording therefore requires additional recoverable surface information. A
retained-source lookup can restore a document, while a learned text decoder
must reconstruct from its predicted IR and learned surface channel under the
withheld-source evaluation above. Keep those measurements separately named.

The [upstream multilingual-GTE model card](https://huggingface.co/Alibaba-NLP/gte-multilingual-base),
checked on 2026-10-04, specifies 768 embedding dimensions and an 8,192-token
input limit. Those are encoder properties; they do not set a trained decoder's
target length or guarantee reconstruction of that span. Pin the model and
tokenizer revisions, pooling, normalization and truncation policy in each
producer receipt. An 8D structural feature head needs an explicit transfer
mapping before its parameters can contribute to a different decoder task.

For the first ablations, compare a frozen authentic-parent replay, inherited
384D weights with a trained input connector, and the same inherited weights
with staged unfreezing. Add a compatible 8D donor in a separate run so its
contribution can be measured. Keep source/target selections, codec and evaluation
fixed for these comparisons. Longer-span curricula and a new output schema
then get their own profiles; do not mix their scores with the fixed-contract
ablation cohort. A parameter donor becomes a distillation teacher only after
target-free semantic evaluation passes the family/task-specific acceptance
thresholds recorded before training.

This refines the [previous improvement plan](original_corpus_replay_handoff.md).
The next numerical work remains source-conditioned semantic generation with
inherited weights and retained embeddings, followed by independently gated
teacher supervision. Format separation prevents mismatched selection; it does
not itself repair the previously measured semantic errors.

## Validation and implementation boundary

The finite format and replay regression cohort passed 437 cases: 199 new
format-contract cases and 238 existing cell/original-corpus cases. All 1,311
test phases passed, with no skips, denied imports or denied effects. The
metadata-only guardian verified 149 project source receipts and 452 external
Python source receipts; actual package initializers ran and the numerical
loader was replaced by an inert test fixture. This checks contract routing,
drift fences and report handling. It grants no numerical, grammar, semantic,
teacher, proof, native-store or release qualification.

The [machine-readable handoff](decoder_format_handoff.json) records these
decisions and the authenticated asset/control receipts. The implementation is
an opt-in wrapper for the two preserved Intent/Security 384D fragment heads.
Migrating all inventory/store records to format profiles and implementing
Legal/Codebase/full-document/text/768D heads remain planned work. Original
weights, corpora and embeddings were preserved; this phase performed no
training or embedding generation.
