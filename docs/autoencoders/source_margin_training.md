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
The authored contract interprets passive “may be” as permission. This does not
establish that the same wording is unambiguous in a natural legal document.

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

## Completed comparison: 2026-10-04

The opt-in objective produced a small, mixed reconstruction gain and increased fit
cost. Keep the default trainer unchanged. All 18 fits completed 340 updates;
all six original baselines reproduced their archived numerical results. The
3,208 selected regression tests passed. Sixteen inherited incompatible 384D setup
cases were outside this selection and are not counted as passing or skipped.

The following primary endpoints are final attempts, including states rejected by
existing development selection. Each count has 96 predictions: the same 48 fresh
authored paragraphs evaluated for two seeds, not 96 independent examples.

| Input system | Original exact | Zero-control exact | Margin 0.01 exact | Zero CE | Margin CE | Fit time increase vs zero |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 8D | 0/96 | 0/96 | 0/96 | 0.744744 | 0.685030 | 3.8% |
| 384D | 61/96 | 60/96 | 61/96 | 0.028533 | 0.029280 | 4.6% |
| 768D | 95/96 | 96/96 | 96/96 | 0.017629 | 0.015409 | 6.0% |

CE is teacher-forced full-vocabulary token cross-entropy; it is separate from
greedy reconstruction. The 768D final attempts retained 96/96 exact with 12.6%
lower CE than the execution control. The 384D result added one exact prediction,
matched the original arm, and worsened CE by 2.6%. The 8D diagnostic sidecar had
lower CE but no exact paragraphs; this does not measure the preserved linguistic
teacher’s fidelity. Two seeds and this authored cohort cannot establish statistical
robustness or convergence. The representations differ, so this is not a pure
dimensionality ablation.

The unchanged development gate accepted both 384D positive final states. It
retained epoch zero for both 768D positive runs because generated extra rules
regressed on the existing development set. The fresh exact totals for the
development-selected positive states were 0/96 at 8D, 61/96 at 384D and 0/96 at
768D. The selected zero-control totals were 0/96, 32/96 and 0/96, respectively.
The 768D final-attempt result must therefore not be described as a promoted or
accepted checkpoint. Fresh results did not change that decision.

On the previously exposed development set, both 384D positive runs first reached
48/48 at a saved validation checkpoint at update 292. One zero-control run never
reached 48/48 and the other first reached it at update 316. This is progress per
update on exposed data; per-epoch wall time was not recorded.

### Cost and inference scope

| Input system | Zero fit seconds, two seeds | Margin fit seconds, two seeds | Margin training presentations/s | Margin greedy seconds/span |
| --- | ---: | ---: | ---: | ---: | ---: |
| 8D | 108.80 | 112.92 | 43.22 | 0.004041 |
| 384D | 153.57 | 160.69 | 30.37 | 0.007668 |
| 768D | 204.19 | 216.37 | 22.55 | 0.009446 |

Each fit presents 2,440 training rows over 340 updates. The six positive fits
took 489.97 seconds versus 466.55 for zero controls (+5.0%) and 407.34 for the
original path (+20.3%). This comparison holds ordinary exposure fixed, not wall
time or auxiliary work. It does not demonstrate a throughput improvement.

Greedy timing uses the saved fresh source vectors and measures final-state
decoding only, pooled over 96 predictions per width. It excludes encoder creation,
checkpoint restoration and reference scoring. A single CPU worker ran on a shared
host, with bridge names `[]`, provers false, metric disk cache off, temperature 0
and both limits 512. `legal_ir_target_count` is zero for this diagnostic: none of
these timings is a bridge-on Legal-IR speed measurement.

Fresh source preparation produced 216 unique texts per width. Measured source
production was 3.642 seconds for 8D diagnostic features, 7.203 for verified local
384D embeddings and 25.580 for verified local 768D embeddings. Inputs were freshly
encoded; existing local model assets were reused. The preparation runner took
46.863 seconds and its guarded wrapper 81.991. The evaluation runner took 50.890
seconds for all 1,728 predictions plus restoration/scoring; its guarded wrapper
took 136.970 seconds. These scopes should not be interchanged. Resource checks
were sampled, and all three owned reservations were released; no absolute peak
RSS or continuous lease coverage is claimed.

### Remaining reconstruction gap

The positive 384D final states recovered every actor, action and object in the
360 clause predictions, but only 301/360 modalities. Paragraph exact was 32/32
for passive wording, 15/32 for topicalized wording and 14/32 for nominal wording.
By length it was 22/24, 16/24, 13/24 and 10/24 for 1, 2, 4 and 8 clauses. This
points to modality generalization as the next hypothesis to test with separate
training examples and another untouched evaluation cohort. This cohort is now
exposed and must not be called fresh in a subsequent tuning experiment.

One predetermined example (seed 1729, positive 768D final attempt, first
one-clause reference) is “The notice must be approved by the trustee.” Its decoded
authored Legal IR matches the reference:

```json
{"rules":[{"actor":"trustee","action":"approve","modality":"O","object":"notice","conditions":[],"exceptions":[],"temporal":[]}]}
```

The empty facets are part of this authored fixture, not evidence that temporal
conditions or exceptions are generally absent. This study covers no additional
logic families or modalities, invokes no Lake build or external prover, and
confers no statutory semantic validation, admission or checkpoint promotion.

Raw trajectories, states, formulas, fixed examples, independent audits, provenance
and resource receipts are retained in
[the published evidence](../implementation/reports/evidence/decoder-source-margin-20261004/README.md).
