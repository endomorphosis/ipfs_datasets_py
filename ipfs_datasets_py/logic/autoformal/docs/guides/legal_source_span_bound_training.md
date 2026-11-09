# Bound source span checkpoint construction and training

Use `legal_span_bound_training.build_bound_checkpoint` and
`train_bound_decoder` to enforce the qualified zero-latent consumer binding
before the existing source-span owner constructs or restores numerical state.
These explicit entry points accept authored engineering or disclosed weak
targets under the existing binding profile.

Create each `SourceSpanBoundBatch` from a prepared binding and the original
four input populations described in the
[consumer binding guide](legal_source_span_consumer_binding.md):

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.checkpoint_content_guard import (
    CheckpointContentGuard,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_bound_training import (
    SourceSpanBoundBatch,
    build_bound_checkpoint,
    train_bound_decoder,
)

training = SourceSpanBoundBatch(
    training_binding, training_rows, split_manifest,
    training_eligibility, training_exposure,
)
tuning = SourceSpanBoundBatch(
    tuning_binding, tuning_rows, split_manifest,
    tuning_eligibility, tuning_exposure,
)
checkpoint = build_bound_checkpoint(training, tuning, seed=1729)
checkpoint_pin = CheckpointContentGuard(checkpoint).sha256
result = train_bound_decoder(
    checkpoint, training, tuning,
    expected_checkpoint_sha256=checkpoint_pin,
    max_steps=100, max_seconds=60,
)
```

The example seals the newly constructed producer output before its first
continuation. For an externally supplied checkpoint, obtain the expected
canonical pin from the previously sealed experiment record. Hashes of arbitrary
JSON file bytes use a separate namespace.

`SourceSpanBoundBatch` is a frozen container for the binding and original input
references. Nested dictionaries remain ordinary caller inputs. Each entry point
checks them again and passes detached rows to the numerical owner. A container
alone supplies no eligibility or review authority.

The checks finish before either numerical entry point runs:

| Check | Required correspondence |
| --- | --- |
| Batch role | Training uses a ready `training` binding; tuning uses a ready `hparam_selection` binding. |
| Joint partition | Both batches commit to the same complete split manifest. The span owner's existing cross-split validator also checks IDs and source texts. |
| Profile | Zero latent dimension only. The fixed signatures do not accept latent routes or arbitrary options. |
| Resume identity | The complete ordinary-JSON checkpoint matches the independently expected canonical pin. Its ordered row digests and exact integer counts match both supplied populations. |
| Resume header | Schema, lineage, false authority flags, implementation identity, parent hash and progress/cursor metadata satisfy the supported profile. |
| Numerical validation | The existing owner retains full configuration, tensor, finite-value and Adam-state validation after input authorization. |

An invalid or blocked member prevents the entire operation. There is no implicit
subset selection. Use `tuning=None` for an explicitly absent tuning population;
its checkpoint count and canonical empty-list digest must agree. A supplied
empty batch is not a substitute for that choice.

Build options are `learning_rate`, `batch_size`, `seed`, `hidden_size`,
`embedding_dim`, `projection_width` and `residual_scale`, with the existing
owner's defaults and bounds. Training options are `max_steps` and `max_seconds`.
The source owner uses a soft deadline checked before numerical batches;
wrapper validation precedes that clock. Use existing resource admission and an
outer task deadline for the whole operation.

The wrappers return the owner's checkpoint or `{checkpoint, report}` unchanged.
They preserve exact Adam continuation, source-span checkpoint schema, lineage
and authority flags. Retain the original binding receipts and experiment pins
as companions; they are not inserted into the checkpoint schema. Tuning remains
the owner's teacher-forced loss diagnostic, without automatic checkpoint
selection.

Direct calls to `legal_span_formula` remain separate interfaces. This integration
does not automatically cover other trainers, retrieval, negative mining or
prediction workers. It grants no reviewed statutory targets, evaluation gold,
process-wide reference isolation or legal accuracy. Definition dependencies,
authenticated meaning review, latent profiles and relational graph/Lean4
integration retain their own requirements.

The enclosing workspace's
`artifacts/legal-source-span-bound-training-20261016-01/` records input-boundary
qualification separately from the tiny numerical continuation fixture. Synthetic
fixture updates do not advance the scientific training frontier.
