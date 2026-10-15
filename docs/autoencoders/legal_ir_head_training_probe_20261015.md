# LegalIR 384D head-training diagnostic, 2026-10-15

Three matched CPU sparse training arms completed in **113.482 seconds**, with
peak worker RSS **1,098,657,792 bytes** (1.099 GB). One structural epoch was
accepted; both view-head proposals were rejected and rolled back. This is a
six-training-row/two-tuning-row diagnostic. The same tuning rows were inspected
previously; they are not an independent holdout. No model was promoted.

| Arm | Accepted epochs | State changed | Reconstruction MSE on repeated tuning rows | Proposed trainable view CE |
| --- | ---: | --- | --- | ---: |
| Structural decoded embedding | 1 | Yes | 0.001972491 → 0.001917703 (−2.7776%) | 1.589027, unchanged |
| Global view logits | 0 | No; strict rollback | Unchanged | 1.747088, rejected |
| Feature/semantic-slot view logits | 0 | No; strict rollback | Unchanged | 1.744227, rejected |

Structural raw embedding cosine increased from 0.827653 to 0.847531. Its deontic
IR cosine remained 0.984895 and IR cross-entropy remained 0.645913. This does not
show improved formula decoding or legal reconstruction. The view arms had real
nonzero gradients/updates, included the view losses in the objective, and were
rejected for worse objective/Pareto terms. They did not fail from a timeout,
zero gradient or omitted loss. Their committed candidate states equal the
original parent; retain those rejections unchanged.

## Why the view comparison needs a separate diagnostic

The bounded static audit verified actual raw target view IDs: the two tuning
rows have support sizes **4 and 6**, and the six training rows have a union of
six raw IDs: `CEC.native`, `TDFOL.prover`, `deontic.ir`,
`external_provers.router`, `knowledge_graphs.neo4j_compat`, `modal.frame_logic`.
These are observed labels, not the complete LegalIR schema vocabulary. They
are also a different classification level from aggregated reporting families.

The recorded implementation builds prediction support from target-row keys
plus state key presence; missing global logits default to zero. Both view
proposals inserted six global keys. Expanding the four-label row to six with
neutral logits alone increases the mean two-row CE by
`0.5 × (ln(6) − ln(4)) = 0.202732554054`.

The original mixed-support baseline is 1.589026915174. A uniform six-label
reference is `ln(6) = 1.791759469228`. The actual global/feature proposals are
0.044671585379 / 0.047532185235 below that expanded uniform reference, yet
remain 0.158060968675 / 0.155200368819 worse than their original baseline.
This corroborates a material support-comparison confound. It does **not**
rescore the models, prove they pass a corrected objective, or retroactively
accept either proposal. Per-attempt prediction class lists were not retained;
the conclusion combines sealed target supports, recorded six-key updates and
the pinned code path.

The source generation recorded by this run is `90a10fe576640cea47bc8b8843bc00bb9fd785007b2c4b5167a2705a8351125f`
(8,760 Python files). At main commit `1b63e750ac3bee68b6f94c022aa4d4132f51d8a0`,
[modal_autoencoder.py](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py)
has SHA256 `ad1a964c1b6b15592aaabe5550af331cb97721b6d362f768c148a62cfd442990`.
Relevant owners are `_legal_ir_view_distribution`,
`_legal_ir_view_family_candidates`, `_legal_ir_view_logits_for`,
`_invalidate_legal_ir_view_family_candidates`, the global/feature logit nudges,
`_softmax` and `train_generalizable_projection`. The existing
[nonview projection regression](../../tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_nonview_projection.py)
already demonstrates four-versus-six support inflation after view-head updates.

## Timing scope and next bounded experiment

All measurements used the same five bridge names: `modal_frame_logic`,
`deontic_norms`, `fol_tdfol`, `cec_dcec`, `external_prover_router`; provers false,
metric disk cache 0, one legal-IR worker, one adapter worker and sample memory
false. Preparing eight new targets took 48.944 seconds in combined bridge
preparation (**6.118 seconds/span**), or 144.497 seconds including source,
custody and I/O checks (**18.062 seconds/span**). Fresh process and disabled
metric/multiview caches do not establish an OS-cold run; OS/dependency caches
were uncontrolled.

The six before/after evaluations reused the verified targets: **1.229–1.679
seconds per two-sample bridge-on evaluate**, **0.614–0.840 seconds/span**.
Compilation/preparation is excluded from that interval, so this is not a full
cold-path speedup. Numerical update batches took 0.544 / 0.0133 / 0.342 seconds
inside 14.147 / 12.847 / 13.891 second training calls. Nested profile categories
must not be summed; source-guard cost was not independently isolated. This
profile supplies no reason to switch to CUDA-resident projection updates.

Add an explicitly versioned **fixed-schema-vocabulary diagnostic**, keeping
official scoring and acceptance gates unchanged. Declare the applicable raw
view vocabulary from the modality/schema profile, independently of target-row
support and sparse head keys; do not declare these six observed IDs exhaustive.
Evaluate identical baseline/candidate rows under that one diagnostic profile
and retain both old and diagnostic results. Test zero-key insertion, epsilon
continuity, inactive heads, unknown labels, checkpoint/profile compatibility,
candidate-cache invalidation and cold/warm agreement. Include genuinely bad
updates to verify strict rejection. Only then run fresh matched training;
do not start by increasing learning rate, epochs or weakening Pareto checks.

Exact immutable local artifact paths and SHA256 commitments are retained in the
[compact evidence record](../implementation/reports/evidence/legal_ir_head_training_probe_20261015.json).
No new scoring or training was executed by the static audit. No weights were
downloaded or parent checkpoint overwritten. All five bridge reports are
supervision diagnostics, not proof of every logic-family semantics. Lake was
not run in this head probe: only an actual `lake build <Lib>` can be a Lean
admit. There is no source-meaning, independent holdout, formula-decoder,
training/gold or corpus qualification; the Constitution remains unformalized.
