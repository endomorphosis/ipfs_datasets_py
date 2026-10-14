# LegalIR actor context feature training — completed 2026-10-14

Completed 2026-10-14. This release combines masked source-token attention with
a copied actor boundary head. **It produced no complete-IR gains or losses
against either the earlier CE-only or hinge-trained control in any of the nine
scored authored scopes.** It is an archival experimental candidate; no default
model or deployment pointer is changed.

`SpanActorFeaturesAdapterDecoder` uses frozen token features `h_i`, masked
attention context `c`, and actor-only features `h_i + a * h_i * c`. Both the
64-value query and 64-value gate start at zero. All 632 initial source outputs
matched the common parent bit for bit. The real numerical run verified the
expected zero first-step query gradient, nonzero gate/residual gradients, and
subsequent query learning. All protected heads stayed bit equal after training.

The model contains 40 tensors: 34 frozen base tensors and six trainable tensors.
There are 258 active trainable scalars, compared with 130 for each actor-head
control. The other 650 stored copied-head scalars retain exact values and zero
gradients/Adam moments. Equal model size or FLOPs are not claimed.

The fixed recipe used the common N4 checkpoint, fresh Adam, learning rate 0.001,
clip 5, batch size 12, seed/order seed 1729, and 32 updates over 384 occurrences
of the same 168 training examples. The hinge is disabled. Both prior comparators
were recounted from frozen outputs, with zero new control forwards or updates.

Complete IR includes modality and all six roles. All references below are
previously exposed authored engineering diagnostics; these are not blind legal
accuracy estimates. Raw and joint complete-IR gain/loss counts against both
controls are zero for every row of this table. The joint complete-IR counts are
identical for all three models. Lower actor rank sum is better.

| Authored scope | Joint complete IR, all three models | CE actor rank sum | Hinge actor rank sum | Context actor rank sum |
| --- | ---: | ---: | ---: | ---: |
| training168 | 153/168 | 206 | 208 | 205 |
| old_tune | 94/96 | 96 | 96 | 96 |
| fresh_tune | 19/36 | 250 | 257 | 248 |
| fresh_challenge | 25/36 | 158 | 161 | 154 |
| old_authored_eval | 51/72 | 126 | 126 | 124 |
| authored_dev | 45/72 | 116 | 118 | 115 |
| authored_eval | 33/72 | 91 | 92 | 91 |
| fresh_dev | 0/36 | 312 | 318 | 314 |
| fresh_test | 0/36 | 1785 | 1783 | 1783 |

Training actor top1 remains 156/168 for all three; top8 and top16 coverage remain
168/168. Filtered training hinge means are CE 0.2569550673, hinge 0.2554120279,
and context 0.2538065797. These secondary changes do not establish an accuracy
improvement. On authored_eval, actor top1 is CE 64/72, hinge 63/72, context 64/72;
joint actor extraction is unchanged. The worse fresh_dev rank sum versus CE is
reported above rather than hidden by the improved training margin.

Six training examples have incorrect frozen modality decisions, and two others
have incorrect frozen optional-presence decisions. An actor-only feature change
cannot repair those fixed outputs. The next controlled work should address
these explicit blockers and independently reviewed statutory references before
further actor-only sweeps or a promotion decision.

The guarded run returned all 32 updates and all 62 output files. It used 1,552
model forwards: 1,520 inference and 32 training calls, with 1,904 total source
occurrences. The 69 model-phase RSS samples peaked at 758,239,232 bytes over a
70.295-second model phase; this is sampled monitoring, not a kernel memory cap
or measured absolute peak. The 200 MB reservation was released after durability.
All 536 existing storage record bodies were preserved relative to the reviewed
post-recovery baseline. A separately audited release of the earlier failed
actor-boundary claim retained every failed-attempt file and changed no foreign
claim; the initial N10 refusal created no child, update or persistent claim.

Scoring began after the 62-file freeze. An independent implementation recounted
all primary complete-IR/modality/role/actor-coverage counts, paired gain/loss IDs,
632-row parity checks, and all 32 feature-learning trace entries. Optional-role
confusion tables and token-contrast diagnostics are source-qualified secondary
analysis and were not separately numerically recounted.

The archive includes the checkpoint, all 62 frozen results, public runtime
receipts, source modules, detached contract tests, exact recipes, and public
qualification evidence. Checkpoint SHA256: `b4ea8a502789f6dddba6e159eb7ecebb753d8344a833b0afb9109cfd6830bcd3`.
Checkpoint bytes: 6464267. Parent SHA256:
`95bd50a7cc6e25381ad126e3d955f0816c31470ec469fb22ceca297e35115035`.
Source recipes retain machine-specific paths to reviewed ancestral inputs;
this archive does not claim a standalone deployment package.

Eight statutory examples remain unscored. This is source-text actor decoding:
latent conditioning is disabled and its 384D vectors are placeholders. Genuine
8D/384D/768D latent semantics, independent US Code fidelity, broader logic-family
compliance and `lake build legal` are not qualified by this run. No semantic
accuracy, legal correctness, or proof-checking claim is made.

The experimental weights and full outputs use the additive
[Hugging Face release path](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/main/releases/20261013-actor-features-v1).
The earlier [actor boundary](legal_actor_boundary_training_20261013.md) and
[actor ranking](legal_actor_ranking_training_20261013.md) reports retain their
original findings.

Repository evidence:

- [Fixed retry design](../implementation/reports/evidence/legal-actor-features-20261013-01/training-design-v02.json)
- [Runtime qualification](../implementation/reports/evidence/legal-actor-features-20261013-01/actor-features-ce-runtime-review-v01.json)
- [Output freeze](../implementation/reports/evidence/legal-actor-features-20261013-01/actor-features-output-freeze-v01.json)
- [Independent result review](../implementation/reports/evidence/legal-actor-features-20261013-01/result-independent-review-v01.json)
- [Public result summary](../implementation/reports/evidence/legal-actor-features-20261013-01/public-result-summary-v01.json)
- [Next experiment gaps](../implementation/reports/evidence/legal-actor-features-20261013-01/next-experiment-gaps-v01.json)

Local qualification includes 19 detached standard-library model contract tests,
11 independent scalar derivative controls, the guarded numerical run and
independent primary metric recount. Detached/scalar tests alone do not prove
PyTorch behavior. Hosted CI passing is not claimed by this report.

The full [analysis](https://huggingface.co/Publicus/legal-ir-autoencoder/blob/main/releases/20261013-actor-features-v1/evidence/actor-features-result-analysis-v01.json)
and [independent recount](https://huggingface.co/Publicus/legal-ir-autoencoder/blob/main/releases/20261013-actor-features-v1/evidence/actor-features-independent-recount-v01.json)
are archived on Hugging Face; their exact hashes are retained in the repository
review and summary, avoiding duplicate large analysis blobs in Git.

Publication completed and independently verified at Hub revision `f91692a0a695d91b793a00936dd525fbe2bafcac`: all 174 downloaded files match their original SHA256 hashes, and all 4,931 previous file identities are preserved. The final repository has 5,105 files.
