# LegalIR actor context feature prototype — 2026-10-13

`SpanActorFeaturesAdapterDecoder` combines the earlier masked attention design
with the copied actor boundary head. The implementation and 19 detached contract
tests are ready. **The first training attempt was refused by storage accounting
before a child or model was created; it completed zero updates.** There are no
trained weights or accuracy results for this prototype yet.

The earlier trained CE and hinge models remain available in the
[actor boundary](legal_actor_boundary_training_20261013.md) and
[actor ranking](legal_actor_ranking_training_20261013.md) reports. This prototype
is opt-in and does not replace either model or the default decoder.

For each frozen source-token feature `h_i`, a masked query computes context
`c = sum_i softmax((h_i · q)/sqrt(64)) h_i`. The actor head receives
`h_i + a * h_i * c`, with elementwise products. This interaction can change
relative token scores. Both the query `q` and gate `a` start at zero. A custom
addition derivative preserves the original feature bits and strides at a zero
residual while allowing the gate to receive gradients. The first update must
keep the query and its Adam moments exactly zero and demonstrate nonzero gate
and residual gradients; later updates record feature learning explicitly.

The model has 40 parameter tensors: 34 frozen base tensors and six Adam tensors.
Of 908 stored trainable scalars, 258 are active: 130 actor pointer values plus
64 query and 64 gate values. The other 650 copied pointer values retain exact
values, zero gradients and zero moments. Modality, optional presence, and five
nonactor boundary heads retain their original routes.

The fixed experiment starts from the same N4 checkpoint as the completed CE and
hinge controls, SHA256
`95bd50a7cc6e25381ad126e3d955f0816c31470ec469fb22ceca297e35115035`.
It specifies fresh Adam, learning rate 0.001, gradient clip 5, batch size 12,
seed and order seed 1729, and 32 updates over 384 occurrences of the same 168
training examples. The hinge stays disabled. Controls are read from frozen
outputs and incur zero new model calls. Equal model size or FLOPs are not
claimed.

Before any update, all 632 source outputs must match the parent bit for bit.
After training, protected outputs must remain exact. Scoring starts only after
all 62 outputs are frozen. Evaluation compares all seven IR fields, actor ranks,
candidate coverage, token contrasts and optional-role errors, with every paired
gain and regression reported against both controls.

The 19 contract tests use detached standard-library fixtures. Eleven independent
scalar calculus checks validate the interaction equations and derivatives.
These checks do not establish PyTorch execution or model accuracy. The guarded
numerical parity and training checks remain outstanding.

The first attempt hit the existing 145 GB campaign accounting cap. This counts
apparent bytes in four named roots plus every outstanding full reservation.
Physical free disk space is a separate check. No cap, retained claim, published
artifact or foreign worktree was changed to retry the run.

The subsequent qualified census measured a 17,161,848-byte accounting shortfall
for the requested reservation, with 234,852,433,920 bytes physically free.
All 536 existing reservation records were unchanged, and the refused attempt
created no persistent claim. An explicit closeout of the earlier failed actor
boundary attempt's own reservation is under review; it has not been performed
in this report.

All planned scored references are exposed authored engineering examples. Eight
statutory sources stay unscored. Latent conditioning remains disabled; 384D
vectors are placeholders. Independent US Code fidelity, logic-family compliance,
`lake build legal`, and genuine 8D/384D/768D latent decoding remain separate
qualification tasks.

The [training design](../implementation/reports/evidence/legal-actor-features-20261013-01/training-design-v01.json),
[source review](../implementation/reports/evidence/legal-actor-features-20261013-01/trainer-source-independent-review-v01.json),
and [storage diagnostic](../implementation/reports/evidence/legal-actor-features-20261013-01/actor-features-storage-diagnostic-v01.json)
record the current evidence and its limits.
