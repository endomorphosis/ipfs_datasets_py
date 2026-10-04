# Frozen checkpoint representation comparison

This opt-in development experiment compares three actual learned endpoints of
a retained source384 checkpoint with the saved raw GTE-small vectors. Its
purpose is to test whether a formula/reconstruction-trained representation
serves retrieval. Author-created reference relevance and input-vector
preservation are reported separately from source fidelity and proof coverage.

The [configuration](../../configs/autoencoders/alignment_checkpoint_development_v1.json)
selects immutable assets before observing retrieval results. Run the
[command](../../scripts/ops/legal_ir/run_alignment_checkpoint_experiment.py)
in the installed native Python environment, with a fresh output directory:

```bash
/home/barberb/.local/bin/python scripts/ops/legal_ir/run_alignment_checkpoint_experiment.py \
  --config configs/autoencoders/alignment_checkpoint_development_v1.json \
  --output-directory /tmp/checkpoint-comparison-01
```

The lightweight workspace `.venv` supports contract tests; it does not contain
the model stack used by the native experiment. No model download, source
encoding, parameter update, formal generation or prover call is needed.

## Selected states and endpoint identities

| Selection | Native input width | Inspected learned state | Experiment status |
| --- | ---: | --- | --- |
| Local spaCy linguistic checkpoint after two epochs | 8 | Populated categorical logits, but all 13 vector-weight tables are empty | Serialized readiness inspection; vector endpoint not executed |
| Retained source384 neural decoder | 384 | Trained residual projector and formula conditioning | Three projection-only endpoints executed |
| Multilingual GTE source backbone | 768 | Native source vectors available; selected coexistence catalog has no trained autoencoder checkpoint | Learned-state endpoint unavailable for that selection |

The spaCy bundle and complete historical 8D teacher are different assets. The
latter has unrecorded original semantic-encoder provenance. Neither an empty
vector-weight table nor an 8D width establishes a trained compressed state.
This readiness inspection does not measure the populated categorical heads,
reload the spaCy runtime, or prove that no other checkpoint exists.

For the selected 384D checkpoint, let `x = (raw - mean) / scale`:

| Endpoint | Width | Exact layer operation | Interpretation |
| --- | ---: | --- | --- |
| `residual_branch_8` | 8 | `tanh(projection_down(x))` | Narrow activation for the residual correction; reconstruction also requires `x`. |
| `residual_projection_384` | 384 | `x + projection_up(branch)` | Learned projected vector in normalized checkpoint coordinates. |
| `formula_condition_32` | 32 | `tanh(condition(projected))` | Initial conditioning state for the formula GRU; the GRU is not called. |

The selected input transform is identity. The residual branch is not a
complete compressed encoding: the skip connection retains the 384D input.
The 8D branch is a representation of the 384D lane, rather than the separate
spaCy lane. The 32D condition is not an embedding of a proof trace or token
sequence. Retrieval preserves each declared width without padding or truncation.

## Preserved checkpoint admission

The current full `source_training_v2.Runtime` rejects this donor's complete
implementation manifest because one cross-domain UI-decoder source pin has
changed. The experiment leaves that loader and the checkpoint unchanged. The
new [representation reader](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_checkpoint_representations.py)
has a separately named `frozen-source384-projection-endpoints/cpu-float32/v1`
profile; it does not admit the full decoder.

Before importing Torch, the existing `gte_bridge_teacher.inspect_teacher`
validates the checkpoint hash, closed serialized schema, geometry, source
representation declaration, codec, input transform, and fourteen pinned files
in the preserved donor source tree. The current numerical projector source
must still match its checkpoint pin. Source text is retained for identity;
only the saved source384 vector enters the neural layers. No parser features,
expected outputs, formal targets, reference tokens or supplied context enter
the forward operation.

The existing original-model constructor loads all thirteen exact float32
tensors privately. The selected model has 25,224 parameters. Extraction runs
on CPU float32 with one thread, evaluation mode, inference mode, no gradients,
and a row batch size of one. The CPU context restores inherited threads and
RNG state. A separately loaded existing numerical model supplies bitwise
projection/condition parity checks for every row. The checkpoint and loaded
weight digests are checked before and after extraction. No sample memory or
target-assisted safety readout is used.

Both sparse lineage `encode()` methods can use a safety projection toward the
supplied input, even when sample memory is disabled. `decode(encode())` is
therefore unsuitable as the primary learned-state control. Future sparse
state comparisons should use the existing pre-safety raw-projection endpoint
and disclose parser-derived features and any populated learned weight tables.

The standard-library representation validator rechecks source/checkpoint and
vector linkage, widths, values, hashes, norms and execution scope without a
model call. It does not independently reproduce float32 outputs or attest the
runtime. Diagnostic fixtures have a separate status and execution record and
cannot be relabelled as observed native extraction.

## Ranking, scoring and numerical assays

The [retrieval helper](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_representation_retrieval.py)
ranks the same sixteen declared TRAIN sources for each of eighteen development
inputs under raw-vector and three checkpoint-endpoint cosine controls. It
normalizes vectors only for ranking, preserves original endpoint values, and
breaks ties by input ID. It accepts zero vectors as serialized outputs, then
records unavailable rankings if a query or member of the fixed candidate pool
has no direction. It never silently removes such candidates.

All eighteen queries receive diagnostic rankings. The posthoc scorer uses
authored targets for the eight positive, context-free queries only. The eight
unsupported/ambiguous cases have no semantic score; the two explicit-context
cases retain unavailable interpretation outcomes because their assumptions
were withheld from this source-only checkpoint. A valid development-target
mutation leaves the complete ranking receipt unchanged and changes only the
posthoc scoring receipt.

Relevance reuses the existing seven-facet, equal-weight multiset Jaccard and
linear-gain nDCG definitions. The ideal ordering uses the same training pool.
Qualifier identity coverage is separate from core-scoped qualifier and full
rule counts. Exact-counterpart recall is unavailable where that pool contains
no exact target. This experiment does not train a ridge head, contrastive
adapter, or new autoencoder, and it does not select an endpoint for production.

The numerical assay reverses the checkpoint transform and compares the learned
384D projection with the original native vector using norms, coordinate MSE,
L2 correction and cosine. The raw identity baseline has zero reconstruction
error. Preserving or changing its values cannot establish source meaning or
retrieval superiority. Source/normalized-source/vector hash intersections with
the checkpoint's declared training/tuning manifests use metadata only; no
original corpus rows are opened. Zero intersections do not authenticate
semantic source-group independence.

## Saved evidence and checks

The [runner](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_checkpoint_experiment.py)
binds the preceding successful context generation, the saved raw inputs and
native lanes, authored panel, pending review bundle and receipt, selected
checkpoint assets, listed executing sources and protected protocol. It
rechecks them before writing a fresh generation containing:

- `representation_plan.json` and `readiness.json`;
- `representations.json`, including the unchanged native source receipts;
- `rankings.json`, `scores.json` and `numeric_assay.json`;
- `report.json`, with per-endpoint summaries and scope limits.

The resource deadline is cooperative. Listed source integrity is not a full
dependency closure or cryptographic runtime attestation. All 34 independent
review items remain pending; successful extraction and authored retrieval
scoring leave fidelity, production admission and proof authority false.

Focused verification:

```bash
/home/barberb/lift_coding/.venv/bin/python -m pytest -q \
  tests/unit/logic/formalization/autoencoder/test_alignment_checkpoint_representations.py \
  tests/unit/logic/formalization/autoencoder/test_alignment_checkpoint_experiment.py \
  tests/unit/logic/formalization/autoencoder/test_gte_bridge_teacher.py \
  tests/unit/logic/formalization/autoencoder/test_alignment_richer_retrieval.py
```
