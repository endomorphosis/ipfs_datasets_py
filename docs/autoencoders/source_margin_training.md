# Source-margin training experiment

The opt-in source-margin objective tests whether a formula decoder can preserve
useful source-head evidence while learning its recurrent output. It is a private
Legal formula-sidecar experiment for 8D, 384D and 768D input systems. It does not
modify the historical 8D linguistic teacher or qualify a model for autoformalization.

## Entry points

- `long_span_source_value_training.train`: existing curriculum trainer;
  `generated_source_margin_replay=True` enables the new execution path.
  `generated_source_margin_weight=0.01` enables its auxiliary derivatives.
- `generated_source_margin_training`: source-only greedy collection, authenticated
  training-label alignment, margin selection and shared boundary/scalar replay.
- `scripts/ops/autoencoder/benchmark_source_margin_training.py`: the fixed
  three-arm, two-seed comparison across all three input widths.
- `authored_scalar_holdout`: a separate authored evaluation cohort with new
  wording families. References and source-only encoder inputs are separate.
- `fresh_scalar_source_inputs`: offline source preparation with the existing
  representation profiles and a 512-token limit.

Disabled defaults preserve the existing training path. Margin replay is mutually
exclusive with generated-field replay. It requires the ordered-clause recurrent
decoder, contextual source inputs, the existing boundary objective and every-step
cadence. None of these switches change inference or checkpoint qualification.

## Objective and gradient ownership

Collect the complete ordinary greedy rollout before consulting training labels.
At an available scalar site, let `y` be the authenticated training label, `s` the
cached source-head logits actually used by that rollout, and `z` the combined
logits. Both margins use every vocabulary token except `y` as a competitor:

```
source_margin   = s[y] - max(s[j] for j != y)
combined_margin = z[y] - max(z[j] for j != y)
penalty         = relu(stop_gradient(source_margin) - combined_margin)
```

A site is eligible only when the source full-vocabulary argmax is `y` and its
margin is positive. Select the first eligible eroded margin for each of actor,
action, modality and object, at most four sites per row. Selection is fixed from
the completed rollout. Average selected sites within each active row, then average
active rows. A replayed zero penalty remains in that denominator. Source-wrong
sites receive no penalty: recurrence may usefully correct them.

The additional reverse pass requests gradients for an explicit eleven-tensor
recurrent-path inventory: initial conditioning, token embedding, GRU, output,
paragraph conditioning and clause conditioning. It does not directly update the
scalar heads, count head or frozen projection. The ordinary loss still trains
its existing parameters. Add the detached weighted auxiliary gradients after
ordinary backward, then perform the unchanged single global clip and optimizer
step. Shared clipping can change the final scaling of excluded heads' gradients;
their updates are not claimed to be identical.

At coefficient zero, perform the same collection, selection and replay diagnostics
but skip auxiliary autograd and gradient attachment entirely. This execution
control is necessary because replay batch geometry alone can alter a floating
point training trajectory. Bulk replay retains the existing strict tolerance and
one original-batch incremental retry; it cannot loosen parity to obtain a result.

## Fixed comparison and evaluation boundary

The comparison uses the original boundary trainer, margin replay at zero, and
margin replay at 0.01; each runs seeds 1729 and 2718 at 8D, 384D and 768D. The
primary contrast is 0.01 versus the execution-matched zero control. Each fit has
the existing 340-update curriculum and unchanged training and development data,
learning rates, AdamW decay, clipping, checkpoint selection and deadline policy.
The original arm must reproduce its archived numerical evidence, excluding only
registered timing fields and the digest that contains those timings.

The existing 48 development paragraphs have been repeatedly inspected. They
cannot establish fresh generalization. The separate authored cohort contains
48 paragraphs, balanced across 1/2/4/8 clauses and three new syntactic template
families. Its 180 clauses use the existing closed 32-token target codec. Actor/action
pair strata derive solely from the training inventory. Prior training,
development, test and canary literals are excluded. Whole paragraphs are encoded
directly; clause embeddings are not averaged to create paragraph inputs.

All recipes are sealed before this cohort is prepared. Its references never enter
training, scheduling or selection. Save all registered selected and final-state
source-only predictions before scoring fresh references. The final attempt is
the primary endpoint; the existing development-selected state is secondary.
Reusing these results to choose another objective makes this cohort development
data for the next experiment.

The 8D representation remains a diagnostic linguistic-feature hash, not a verified
semantic embedding. The 384D and 768D representations use their distinct verified
local encoders. No weights are downloaded, no context/output ceiling is raised,
and temperature remains zero. Saved training-only normalization and count buffers
are reused without fitting them to the evaluation cohort.

## Receipts and limits

Training receipts retain actual generated prefixes, selected full-vocabulary
margins, replay parity, active-site counts, restricted parameter names, auxiliary
gradient norms and elapsed time, combined preclip norm and the shared clipping
factor. The extra reverse pass and replay are additional work; report them along
with fit wall time, updates per second and row presentations per second.

This is a closed-vocabulary authored reconstruction experiment. Identity input
reconstruction is not learned reconstruction; exact formula reconstruction is not
statutory semantic fidelity. It neither expands logic-family coverage nor grants
proof authority. Only `lake build <Lib>` can admit the corresponding Lean artifact.
No Constitution span becomes formalized or `roundtrip_ok` from these results.
