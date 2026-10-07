# Selected normative decoders can replay their original cached inputs

The opt-in `normative_legal_ir_runtime` API prepares and opens the saved
`normative-wording-zero` and `normative-wording-ce` selected states at 384D and
768D. Recipes, weights, frozen transforms, original donor and cached vectors
remain unchanged. The original contextual runtime continues to require its
separate `continue-lr0001` recipe.

The two lazy gateways also appear in `checkpoint_hub`:

```python
from ipfs_datasets_py.logic.formalization.autoencoder import checkpoint_hub

request = {
    "ir_family_id": "legal_ir",
    "dimension": 384,
    "dimension_role": "input_embedding",
    "task_id": "semantic_IR_reconstruction",
    "checkpoint_sha256": checkpoint_pin["sha256"],
    "decoder_contract_id": "normative-selected-cached-legal-ir/v1",
    "training_recipe_name": "normative-wording-ce",
}
plan = checkpoint_hub.prepare_normative_legal_ir_runtime(
    request, checkpoint_pin=checkpoint_pin, preprocessing_pin=preprocessing_pin,
    donor_checkpoint_pin=donor_checkpoint_pin, source_inputs_pin=source_inputs_pin,
    source_contexts_pin=source_contexts_pin, source_owner_pins=source_owner_pins,
    row_ids=row_ids,
)
```

Each pin has a canonical absolute `path`, positive bounded `bytes` and exact
`sha256`. Source pins cover all fifteen files in
`normative_legal_ir_runtime.SOURCE_OWNER_NAMES`, including this adapter and the
registration identity helper. Preparation imports no tensor library and does
not load a model, read the ModelManager store or use the network.
`open_normative_legal_ir_autoencoder` accepts the same arguments and explicitly
restores the existing numerical owner. Its handle exposes `describe()` and
`infer_cached()`; the caller configures one CPU thread.

## Selection and cached inputs

The closed seven-field request separates family, input dimension, dimension
role, task, checkpoint bytes, execution contract and training recipe. Only exact
saved recipe weights `0.0` and `0.05` are accepted. Integer/bool zero, alternate
weights and extra fields refuse. Both `selected=True` and `role="selected"`
are mandatory: last-attempt aliases also carry `selected=True`.

The original 32-value lexical codec and ordering are checked explicitly. Shared
checks authenticate all 32 state entries, raw donor tensors, float32/int64
geometry, initializer, frozen projection, TRAIN transforms/normalizations/count
prior and source/context inventory joins. Only the original saved preprocessing
validation split is supported, preserving selected row order and target-free
packet fields. Other families, dimensions, latent roles and prose tasks refuse.

Paragraph vectors retain caller-pinned byte custody rather than new encoder
producer authentication. Width-specific native paragraph/clause vectors receive
the saved TRAIN transform before zero padding to eight, followed by separate
frozen decoder feature normalizations. No new embeddings or padded 384D-to-768D
substitute inputs are introduced.

Preparation emits the exact ten-field `model_manager_selector` for the already
registered selected state, using the genuine identity helper after origin
checks. `model_manager_binding_resolved` remains false because this API does not
read the store. A separate genuine read-only catalog observation resolved all
four emitted selectors to their registered original checkpoint pins.

File and loaded-origin checks repeat at preparation, after restoration and
before/after inference. Refusals retain actual model-call started/returned flags
and available candidates after completed inference. These are cooperative
endpoint fences, not atomic snapshots.

## Completed validation and limits

Independent review found and resolved a foreign cached-registry origin gap
before replay. Controls cover 194 distinct passing cases: 163 existing runtime
and 31 normative cases, with zero failures/errors/skips. The 28 normative cases
repeated across two receipts are counted once.

All four actual states replayed 48 original cached validation rows each, on one
CPU thread, batch size 8, greedy generation and a 512-token output cap. Every
state produced 48 EOS outcomes; weights, inputs and ambient RNG stayed unchanged.
A separate process compared durable outputs to the original contextual parents:
all four had 48/48 exact token/status/EOS parity. This measures parent-output
retention; gold was not rescored and new semantic or prose fidelity was not
measured. No encoder, fitting, optimizer, database or network action ran during
generation. The read-only catalog check was a separate invocation.

[Workspace evidence](https://github.com/endomorphosis/lift_coding/tree/main/artifacts/normative-decoder-runtime-20261007)
retains reviews, controls, input/source identities, plans, actual candidates,
catalog resolutions and reproduction scripts. Weights/caches stay at their
original retained paths and in the existing public releases.

The execution contract versions this opt-in API. Native IR schema/profile/format
remain null; complete runtime IO, native output validation, teacher/quality/
runtime-release and proof qualification remain false. No supervisor default or
checkpoint promotion is activated. Candidates need the existing independent
source-fidelity, native/formal and applicable proof checks before index admission.

The inherited 512-token experiment setting is not a new encoder-producer claim.
Historical original 768D cache provenance used an 8192-token producer profile;
this replay neither re-encodes it nor qualifies a new long-span decoder path.
Arbitrary fresh-source IO needs a versioned producer/span contract and its own
reviewed compatible input closure.

The [newest training observation](reconstruction_gap_followup_20261006.md) finds
both auxiliary states exact on current original/normative TRAIN cohorts. Keep
its balanced independently reviewed wording proposal: another same-bank modality
loss does not address a demonstrated TRAIN reconstruction error. Nonempty
qualifiers, exact original-text reconstruction and 8D/384D-to-768D transfer
remain separate decoder/data/qualification tasks.

For a separately bound existing source cohort, see the additive
[retained native-cache runtime](normative_cached_legal_ir_runtime.md). The
original split gate described here remains unchanged.
