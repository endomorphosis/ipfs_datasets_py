# Source-margin reconstruction comparison — 2026-10-04

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
this evidence directory.

## Evidence access

The manifest maps raw artifacts to the ordered `evidence.tar.xz.part-*` files.
Concatenate the parts in numeric order to reconstruct `evidence.tar.xz`.
The archive references the authenticated preceding evidence chain for unchanged
inputs. Encoder weights and installed libraries remain external; local asset
hashes and frozen producers are recorded. No encoder weights are bundled.

See [the implementation guide](../../../../autoencoders/source_margin_training.md)
for the objective, API switches, gradient ownership and evaluation boundary.
