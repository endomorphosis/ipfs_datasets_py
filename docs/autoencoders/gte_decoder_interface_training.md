# Train the new input connections while preserving learned decoders

The bounded reference trainer reuses the learned 8D and 384D decoder bodies,
their original codecs, source assets, cached input replay and original targets.
It fits only the four new tensors that connect native 768D inputs to those
copied heads. The independent 8D and 384D runtime lanes and their saved
generations remain available throughout. The multilingual encoder stays outside
this trainer: it consumes admitted cached vectors and never downloads assets or
regenerates old embeddings.

## What this pilot learns

The [trainer](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_interface_training.py)
loads a private copy of the original dual-donor initialization. All 26 learned
decoder tensors remain frozen and must retain their exact values after every
update. Only these tensors enter the fresh AdamW optimizer:

| Interface | Role |
| --- | --- |
| `primary.input_adapter.weight` and `.bias` | Map the native 768D input into the copied primary decoder's 384D input convention |
| `auxiliary_connector.weight` and `.bias` | Map the shared primary condition into the copied 8D grammar head's original latent convention |

Auxiliary grammar loss reaches both connections through the frozen primary
conditioner. Each head divides reference cross-entropy by its own eligible
next-token count; positive declared head weights combine scalar losses. The
vocabularies and logits remain separate. Detached donor distributions stay
bound to their original inputs and prefixes for future qualified per-head KD.
They are not used as training labels by this reference pilot.

The [native batch contract](gte_decoder_native_inputs.md) admits the complete
242-source V2/8D audit before selecting the fixed 16 primary and two auxiliary
training rows. All 18 selected rows need exact matching native receipts. A
ready selected batch can still have missing receipts elsewhere, including
validation; this pilot does not establish held-out fidelity or complete cache
coverage. The two auxiliary examples are the original authored synthetic 8D
training examples and retain that provenance.

This first runner starts from `original_initialization`, including its seeded
new connections. Its decoder bodies already contain the original learned
weights. It does not consume an affine-aligned generation or resume optimizer
state. The [train-only affine fit](gte_affine_alignment.md) and
[aligned student handoff](gte_aligned_decoder.md) remain the intended preceding
steps for the larger November experiment. Training from that separately
identified handoff is implemented by the separate
[aligned-start trainer](gte_aligned_interface_training.md), which preserves this
original-start runner and its checkpoint format.

## Bounded execution and checkpoint identity

The trainer uses CPU float32, one thread and evaluation mode with gradients
enabled. It computes before/after losses, checks finite nonzero gradients on
all four interfaces, clips their global norm, executes the declared optimizer
steps and records per-step losses and gradient diagnostics. It verifies absent
gradients and unchanged values on every inherited tensor after each update.
All four interfaces must change to publish a trained generation. Loss
improvement and semantic fidelity are measured outcomes, not enforced success
claims. The optimizer starts empty and imports no donor moments.

The [trained checkpoint contract](../../ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_interface_checkpoint.py)
stores the four updated float32 interface tensors and links to the immutable
original initialization and donor pins. It binds the native plan, replay,
codecs, current implementation, full 30-tensor inventory and training report.
Its representation ID begins `gte-768-dual-reference-interfaces:sha256:` and
differs from the historical initialization and any affine-aligned generation.
It stores no optimizer state and supports no resume.

The training report records actual post-update output hashes for every
selected native/reference forward: primary logits, auxiliary logits, shared
condition and auxiliary latent. The trainer compares an independent reload
directly against the live post-training model. The command then authenticates
the saved checkpoint and separate report, requires their reports to match,
and replays those recorded outputs from two private saved reloads. All 30
tensors and selected outputs must match exactly, and model storage must be
disjoint. Comparing two reloads alone would not establish preservation of the
live trained export.

The standard-library inspector verifies consistency before Torch loads. It
does not independently authenticate that an optimizer or native encoder ran.
The numerical receipt establishes replay of the recorded trained state and
outputs; it does not grant teacher qualification, production KD eligibility,
source fidelity or proof authority.

## Preparation and later execution

The [command](../../scripts/ops/autoencoder/run_gte_decoder_interface_training.py)
authenticates the completed native preparation's entire input, parent, source,
implementation and output closure. Both original donor implementation roots
and all input namespaces are protected from output writes. Outputs use a fresh
directory, and the completion manifest is written only after saved-artifact
checks and final byte rechecks.

The [pinned configuration](../../configs/autoencoders/gte_decoder_interface_training_v1.json)
uses `mode: prepare`, eight planned steps, learning rate 0.001, maximum gradient
norm 1 and equal head weights. Preparation runs no numerical model, even for a
ready batch. From the repository root, reproduce it into a fresh directory:

~~~bash
python scripts/ops/autoencoder/run_gte_decoder_interface_training.py \
  --config configs/autoencoders/gte_decoder_interface_training_v1.json \
  --expected-config-sha256 444fe404e703b3932559de9eb1fefc90fab2a126ad1cb3b2f1d366710f812bae \
  --output-directory /home/barberb/lift_coding/artifacts/gte-decoder-interface-training-preparation-20261002/reproduction-01
~~~

For a later pilot, publish a new ready native-preparation generation using exact
receipts for the original sources. Create a new configuration that pins that
generation, its native batch and unchanged original initialization/replay
inputs, and set `mode: train`. Recompute the external configuration file hash.
The command admits 1 to 64 steps, learning rates from 0.000001 to 0.01, gradient
norm bounds from 0.01 to 100 and positive head weights up to 100. Process memory
and CPU time are bounded before Torch loads. Incomplete native inputs still
produce an explicit unavailable or partial result with zero optimizer steps.

Preparation saves `native-inspection.json`, `summary.json` and `manifest.json`.
Actual training additionally saves the resource receipt, trained interfaces,
separate training report, checkpoint inspection and saved reload verification.
Exit code 0 denotes prepared or trained/unqualified, 1 denotes completed
preparation with missing native inputs, and 2 denotes invalid inputs or execution
failure. An incomplete numerical run receives no completion manifest.

## Actual result and remaining November work

The [completed preparation](../../../../artifacts/gte-decoder-interface-training-preparation-20261002/run-01/manifest.json)
reported `unavailable`: 18 selected sources, zero ready native rows and 18
missing rows. It planned eight updates and performed zero. It created no
optimizer or trained checkpoint, loaded no numerical model, performed no
encoding or downloads and preserved the original donor weights and caches.
The [execution receipt](../../../../artifacts/gte-decoder-interface-training-preparation-20261002/execution.json)
binds the command, exit code, logs and completion manifest. Missing tasks remain
in the earlier [source-only native task generation](gte_decoder_native_inputs.md).

The next experiment should reuse matching native receipts first and encode only
missing original sources with the pinned multilingual assets. Fit the primary
boundary on training pairs and select it on validation, then use the
[aligned-start runner](gte_aligned_interface_training.md) with the authenticated
aligned generation. Train the auxiliary connector
with its separately declared grammar objective. Evaluate free-running original
source reconstruction against the donors and inherited initialization before
expanding the cohort or changing codecs.

Admit per-head KD only after the respective donor's independent scope and
supervision masks qualify. Selective unfreezing, direct 768D conditioner
promotion, vocabulary migration and 8192-token experiments follow their
separate gates in the [migration plan](gte_multilingual_migration_plan.md).
Encoder input capacity does not increase the inherited heads' output limits.
The separate 8D and 384D paths keep their original model and embedding identities.

Validation passed **173 focused checks across two runs**: 85 checkpoint checks,
16 numerical training checks, 25 command checks and 47 retained native objective
checks. The runs took 506.38 seconds in total. Numerical tests use explicitly
synthetic native receipts and real optimizer updates; those receipts stay out
of production caches. Tests cover actual four-tensor updates, unchanged donor
weights, independent per-head loss, clipping, RNG/thread restoration, live
trained output preservation, strict admission and altered saved-artifact
rejection. The
[test receipt](../../../../artifacts/gte-decoder-interface-training-preparation-20261002/tests-01/result.json)
binds both successful commands, test sources and logs. The
[verification receipt](../../../../artifacts/gte-decoder-interface-training-preparation-20261002/verification.json)
binds current artifacts, original files and preserved document generations.

## Compare generated reconstructions

The [source-only evaluation runner](gte_decoder_source_evaluation.md) compares
the original donors and available original, aligned and aligned-trained 768D
generations on identical source IDs. It currently consumes a completed aligned
training parent; original-start trained checkpoints retain their separate
format and are not silently admitted as aligned-start generations. Reference
loss and saved reference-forward equality remain implementation evidence.
Free-running comparison uses fixed inherited budgets and generated prefixes,
then scores references. The original validation split is exposed regression
evidence and the two auxiliary training examples are diagnostics; independent
fidelity still requires a fresh sealed cohort.
