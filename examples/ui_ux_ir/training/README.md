# Local UI/IDL feature fixtures

These six small rows are authored structural fixtures. They declare a delete
button, its explicit versioned interface binding, a state model and synthetic
events. They contain no observed human trace, backend execution or Hugging Face
data. Their group separation exercises the pipeline; it does not establish
generalization across real applications.

Files are `train-001.jsonl` (two rows), `train-002.jsonl` (one incremental row),
`tuning.jsonl` (two fixed selection rows) and `inference.jsonl` (one test row).
The inline descriptor CID is computed from its actual descriptor. Every row
uses the closed `ui-bound-training-row/v1` input schema.

Follow the [UI training and dataset guide](../../../docs/autoencoders/ui_datasets_and_bindings.md),
using this directory as `UI_INPUTS`. Choose a new state directory beneath an
existing resource-ledger root. The guide covers planning, training, exact-parent
resume and separate inference. No command invokes the declared delete method.

The [input adapter tests](../../../tests/unit/logic/formalization/autoencoder/test_ui_training_inputs.py)
contain the matching fixture constructor and negative schema/join cases.
