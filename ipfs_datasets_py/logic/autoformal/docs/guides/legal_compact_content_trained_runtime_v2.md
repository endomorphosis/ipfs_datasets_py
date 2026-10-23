# Trained compact-content inference v2

`legal_compact_content_trained_runtime_v2.py` consumes the current weights in the
existing `legal-compact-content-training-checkpoint/v2` envelope without creating
an optimizer. It adds scoring, bounded continuation, deterministic replay, and a
single-observation adapter to the existing CONTENT batch contract. It does not
change the original head, trainer, token grammar, selector, or evaluator.

The canonical implementation is
`ipfs_datasets_py/logic/formalization/autoencoder/legal_compact_content_trained_runtime_v2.py`.
Its [owning tests](../../../../../tests/unit/logic/autoformal/test_legal_compact_content_trained_runtime_v2.py)
and [prepared v3 consumer](legal_compact_content_prepared_runtime_v3.md) already exist.
Source presence and each separately retained execution qualification have distinct scopes.

## Checkpoint compatibility and lineage

The accepted checkpoint belongs to the installed training owner with SHA256
`3ff34b8094a8bb19315741a03873c95f7d809654b35717fd4cee97e074fd2b59`.
Its original v1 head remains a weights-only initialization with zero compact
training steps. The new owner neither relabels a v2 checkpoint as v1 nor edits the
trainer to make historical checkpoints appear compatible.

Inspection retains and checks the complete checkpoint commitment, current model
state and weights commitment, permanent original v1 checkpoint and weights
commitments, immediate v2 parent commitment, exact parameter order, full retained
training population, named Adam state, deterministic progress, original codec,
source implementation pins, and false authority/mask fields. The runtime retains
384-dimensional supplied conditioning, 537 vocabulary entries, and a maximum of
512 IDs including the supplied prefix. The inherited configuration determines the
tiny decoder dimensions. These constraints do not establish compatibility with
768D, native 4096D, another grammar, or the optional-predicate catalog profile.

The original codec requires every declared context predicate to occur in a
completed formula. Another codec with the same number of lexical IDs is not an
interchangeable codec. The full codec bytes and their hash are checked.

The permanent initialization and immediate trained parent serve different
purposes. The generation and score reports retain both, along with current
weights, progress, and the full supplied checkpoint identity. Those commitments
are not authentication of historical training, the parent chain, source meaning,
or data permission. Genuine historical update evidence remains in the separate
training execution and fixture records. Inference itself performs zero updates.

## Structural inspection without numerical allocation

```python
checked = inspect_compact_content_trained_checkpoint_v2(
    checkpoint,
    expected_checkpoint_sha256=checkpoint_sha256,
)
```

The expected hash is supplied independently of the offered object. Inspection
returns a detached, structurally checked checkpoint. It composes the pinned pure
contracts from the original head and training owner: original-head validation,
fixed codec validation, exact finite float32 state shapes, complete training
population validation, named moment validation, and implementation identities.
It does not call either owner's allocating public checkpoint validator.

Recorded runtime fields are checked as a closed CPU/float32 declaration. Recorded
Adam policy is compared using canonical JSON bytes, so booleans cannot replace
numeric values by exploiting Python equality. The policy permits only the
original defaults, clipping, batch size, row order, and objective; the historical
optional `decoupled_weight_decay` field may be absent or explicitly false. Adam
moment metadata is inspected as ordinary JSON, without creating tensors or an
optimizer. Neither inspection nor a terminal-prefix operation imports the
numerical owner or Torch. It does not claim that the recorded runtime was
independently exercised during historical training.

## Scoring and model-only restoration

```python
score = score_compact_content_trained_v2(
    checkpoint, conditioning, prefix_ids, context_raw,
    expected_checkpoint_sha256=checkpoint_sha256,
    expected_context_sha256=context_raw_sha256,
)
```

Conditioning is exactly 384 finite, bounded ordinary numeric scalars. It remains
`caller_supplied_unverified_conditioning_vector`; no source encoder is inferred
from its length or a successful forward. `context_raw` is immutable UTF-8 JSON
bytes pinned by its raw SHA256. The existing grammar validates the prefix and
context before a numerical operation.

If the existing prefix owner exposes no permitted next token, the result has
`status="no_forward"`, null logits/selection/output shape, and unchanged prefix
IDs. `model_restore_performed`, `numerical_forward_executed`, `runtime_verified`,
and `runtime_torch_version_verified` are all false. A complete supplied target is
therefore a terminal-input control, not learned generation.

Otherwise, the private `_forward` seam imports the pinned numerical owner and
checks the actual runtime against the recorded training runtime. This includes
Python, architecture, Torch version and build, thread configuration, CPU float32,
MKLDNN, and deterministic-algorithm settings. A mismatch refuses inference; this
owner does not alter those settings to obtain admission.

The model uses the existing projection and GRU architecture. It restores only
current trained model tensors, strictly checks their complete parameter order and
values, enters evaluation/inference mode, and executes one genuine forward over
the offered prefix. The full 537-score vector and output geometry are retained.
The existing selector chooses among grammar-permitted IDs. Model construction
uses the shared numerical owner's RNG-preserving method; closing checks require
unchanged ambient CPU RNG and live runtime.

No Adam constructor, optimizer restore, optimizer tensor allocation, or optimizer
step occurs on this path. The score explicitly records
`optimizer_constructed=False`, `optimizer_executed=False`, and
`optimizer_state_restored=False`. `compact_training_steps` and
`training_progress` refer to the checkpoint's recorded historical progress, not
work performed by this score operation.

## Bounded continuation and replay

```python
report = generate_compact_content_trained_v2(
    checkpoint, conditioning, [1], context_raw,
    expected_checkpoint_sha256=checkpoint_sha256,
    expected_context_sha256=context_raw_sha256,
    max_new_tokens=2,
    prefix_origin="bos_seed",
    context_origin="caller_supplied_unverified",
)
report_sha256 = compact_content_trained_generation_sha256(report)
```

The caller must set `max_new_tokens` explicitly between 1 and 512. The complete
sequence may contain at most 512 IDs. A BOS origin requires the prefix to be
exactly `[1]`. Other accepted prefix origins are `authored_fixture`,
`target_derived_label`, and `caller_supplied_unverified`. Context origins use the
same list without `bos_seed`. These labels describe exposure; they are not
permission attestations.

Every selected ID has a retained score report binding the exact checkpoint,
current weights, original supplied inputs, codec, and allowed prefix. The final
grammar report and token decode are retained. `generated_ids` includes supplied
prefix IDs; only `selected_token_ids` were emitted by numerical decisions.
`raw_argmax_ids_by_step` contains raw maxima along the constrained selected
trajectory, not a separately autoregressed unconstrained sequence.

Possible dispositions are `complete`, `supplied_complete`, `blocked`, and
`step_budget_exhausted`. A two-step BOS fixture exercises numerical wiring but
cannot establish complete formula generation or legal accuracy. Generation
records score calls and numerical forwards separately, with
`training_executed=False`, `compact_optimizer_executed=False`,
`optimizer_constructed=False`, and `optimizer_state_restored=False`.

```python
replayed = validate_compact_content_trained_generation_v2(
    report, checkpoint, conditioning, [1], context_raw,
    expected_report_sha256=report_sha256,
    expected_checkpoint_sha256=checkpoint_sha256,
    expected_context_sha256=context_raw_sha256,
    max_new_tokens=2,
    prefix_origin="bos_seed",
    context_origin="caller_supplied_unverified",
)
```

The validator checks the independent report commitment, regenerates from the
original inputs, and compares the entire canonical report. A real replay costs
the same number of numerical forwards as the original trajectory. Hashing alone
does not replay or authenticate a numerical observation. Original and replay
forwards must be counted separately in experiment accounting.

## Existing CONTENT adapter and denominators

`prepare_compact_content_trained_batch_prediction_v2` accepts the same original
checkpoint, conditioning, prefix, context, and generation settings, plus the
immutable original `legal-relational-batch-population/v1` bytes, independent
population and generation hashes, and one exact occurrence ID. It validates the
entire population and all unique row identities before numerical replay. The
existing population contains 1–64 rows; the chosen occurrence must occur exactly
once. The adapter itself performs one complete replay, so callers should not add
another validator call unless they intend to charge for that additional work.

The returned `predictions` uses the existing
`legal-relational-content-token-batch-predictions/v1` schema. Its generation kind
is `decoder_declared`, its latent dimension is 384, and its encoder hash is null.
There is no invented encoder identity. The model-facing context is retained
separately from the original population context commitment. That distinction
does not assert a verified source-to-context correspondence.

One adapter call contributes one observation. Every other occurrence remains in
the caller's unchanged original population and is missing if no observation is
submitted. The existing evaluator does not automatically authenticate this new
trace and grants no comparison credit to its unverified decoder declaration.
An emitted prefix, successful execution, or matching body cannot silently remove
missing slots or promote model output to evaluation gold.

## Bounds, custody, and authority

Inputs use ordinary JSON-compatible containers and immutable raw context and
population bytes. Cycles, nonfinite numbers, booleans in numeric slots, duplicate
population keys, unknown fields, changed commitments, and over-bound artifacts
are refused. Current whole-object limits are 64 MiB for a checkpoint, 512 KiB for
context, 128 KiB for population, 192 MiB for an operation's captured inputs, and
96 MiB for a report. Bounds refuse rather than truncate.

The owner checks pinned regular single-link source files and their metadata at
operation boundaries and verifies public module origins. It snapshots inputs and
checks original and captured values on exit, including failure. These checks are
finite custody checks; they do not attest arbitrary loaded bytecode or provide a
hermetic interpreter. The surrounding existing source lease and qualification
runner supply process/resource custody. This module adds no scheduler or resource
authority.

All semantic, source binding, context permission, learned-source encoder,
held-out generation, legal accuracy, acceptance, and Lean authority flags remain
false. `training_mask=0` and `evaluation_gold_mask=0` remain explicit. Numerical
execution is a reportable fact, not evidence that an output has the right legal
meaning, that training data was eligible, or that a constraint is safe to enforce.

## Qualification scope and remaining work

The proposed local fixture reuses the exact retained two-step authored training
checkpoint; it performs no training. An independent GRU reference should verify
the full trained logits and contrast them with the retained initial v1 weights.
Public score, two-step BOS generation, replay, and CONTENT intake should execute
the trained weights without constructing an optimizer. A separately labeled
complete target-prefix control should execute zero numerical operations. All
forward counts, source/input commitments, failure controls, and missing population
slots need retained evidence before the new owner is described as qualified.

That fixture is an inference integration test, not a reconstruction or holdout
study. It does not add source encoding, source-to-grammar training, pretrained
statutory targets, complete autoregressive legal decoding, multi-width support,
formal proof, or corpus-level Lean admission. Those remain separately gated work.
No training, model download, statutory source acquisition, solver invocation,
compilation, publication, or repository push is part of this owner.
