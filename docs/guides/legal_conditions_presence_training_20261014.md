# LegalIR conditions-presence training — 2026-10-14

Completed 2026-10-14. A copied condition-presence head above the exact trained
N10 actor-context decoder improves complete IR from **153 to 154/168 on training**
and **45 to 46/72 on authored_dev**. There are no raw or joint complete-IR losses
across the nine scored scopes. **Condition false negatives nevertheless worsen
on authored_eval, fresh_dev and fresh_test.** This candidate remains opt-in and
is not promoted to a default model or deployment pointer.

The starting checkpoint is the completed N10 model, SHA256
`b4ea8a502789f6dddba6e159eb7ecebb753d8344a833b0afb9109cfd6830bcd3`.
All 40 trained parent tensors—including its learned actor attention/query/gate—
remain frozen. The new full8×64 presence projection plus bias has 520 stored
values, of which only 130 conditions values (rows2:4) are active. The other 390
retain exact values, zero gradients and zero Adam moments. This gives 42 tensors,
with two new Adam tensors. The unchanged parent forward runs under no_grad;
one additional frozen span-feature pass supplies the copied head. Only the
conditions presence pair is replaced. No label, oracle, lexical rule or repair
routine is an inference input.

The fixed recipe uses fresh Adam, learning rate 0.001, clip 5, batch size 12,
seed/order seed 1729, 32 updates and 384 occurrences of the same 168 training
sources. Its sole loss is condition-presence CE averaged over every batch row;
there is no reweighting, mined batch, hinge or threshold fitting. Conditions
are absent in 96 training sources and present in 72. Parent control outputs are
reused from their complete freeze with zero new parent forwards or updates.

Before training, all 632 initial full head vectors matched the trained parent
bit for bit. After training, all 632 modality/boundary/other-presence vectors
remain exact. Actor score vectors and full rank records are unchanged. All 32
permission IDs in the legacy scope remain P in raw and joint outputs without
abstentions. Frozen score heads can still yield different selected spans through
overlap and abstention coupling, so all seven IR fields were checked separately.

All results below are previously exposed authored engineering diagnostics,
including the panels named eval/test. They are not blind generalization or
statutory accuracy estimates. Complete IR includes modality and all six roles.
The table shows joint complete IR; raw/joint complete-IR gains/losses and IDs
are retained in the evidence. FP/FN refer to the conditions head decision;
selected raw/joint presence and ambiguity/abstention are independently counted.

| Authored scope | Joint complete IR, parent → candidate | Condition FP | Condition FN |
| --- | ---: | ---: | ---: |
| training168 | 153 → 154 / 168 | 1 → 0 | 0 → 0 |
| old_tune | 94 → 94 / 96 | 0 → 0 | 0 → 0 |
| fresh_tune | 19 → 19 / 36 | 0 → 0 | 0 → 0 |
| fresh_challenge | 25 → 25 / 36 | 0 → 0 | 0 → 0 |
| old_authored_eval | 51 → 51 / 72 | 0 → 0 | 2 → 2 |
| authored_dev | 45 → 46 / 72 | 11 → 9 | 0 → 0 |
| authored_eval | 33 → 33 / 72 | 0 → 0 | 5 → 6 |
| fresh_dev | 0 → 0 / 36 | 12 → 12 | 0 → 2 |
| fresh_test | 0 → 0 / 36 | 12 → 12 | 2 → 3 |

Training gain: `matched-temporal-train-plain_deadline-1-p-present`.
Authored development gain:
`targeted-loss-authored_dev-plain_deadline-1-p-present`.
Both previously abstained because of a false positive condition. The trained
head reaches the gold-dependent fixed-pointer training ceiling 154/168; that
oracle is a diagnostic, never a model input or trained-performance forecast.
Twelve actor-duration errors and two condition-boundary errors remain. More
presence-only training cannot repair those frozen pointer errors.

Authored development condition FP falls11→9, while condition FN increases5→6
on authored_eval,0→2 on fresh_dev, and2→3 on fresh_test. Complete IR on those
three panels is unchanged because the affected examples already had other
errors; that does not make the new missing conditions acceptable. The next
recall-preserving experiment and span-head work are documented separately.

The actual guardian returned all 32 updates and62 output files. There were 1280
new inference forwards plus 32 training-batch forwards, totaling 1312 calls and
1,664 new source occurrences. Six parent files / 240 captured rows were copied as
opaque frozen bytes and add zero model calls. Three frozen feature paths run
per candidate forward; external embedding encoder calls remain zero. The 86
model-phase RSS samples peaked at 768,995,328 bytes. Monitoring is sampled,
not an absolute peak or kernel-enforced cap. The 200 MB claim was durably
released, and all 537 prior record bodies remained exact.

An initial readonly capacity preflight refused before any claim/model. A later
qualified census passed at 141,338,429,395 charged bytes against 145,000,000,000,
including the requested 200 MB, with 3,661,570,605 bytes headroom. No files, claims
or limits were changed to obtain that pass; usage changed between observations.
The inherited artifact archives are preserved outside the four counted roots.

The archive includes the checkpoint, all 62 frozen outputs, public runtime
receipts, exact source, tests and recipes. Nine detached stdlib controls and
the actual numerical parity/training checks passed. An independent implementation
recounted all 30 panels/27 authored score sets/nine paired scopes, all primary
optional-presence confusion and gold-split abstentions, all 32 permissions,
632 initial/protected head comparisons and all 32 training traces.

Checkpoint SHA256: `34080a8ad491e5a351aeea0adfc6f3e29e76d0ae93c1f8a8cee3ebf536a7b9fd`.
Checkpoint bytes: 9337558. Its recursive parent lineage is retained;
flattening that format is planned before further adapter stacking. Recipes
retain machine-specific ancestral input paths; this is an experimental archive,
not a standalone deployment package.

Eight statutory examples remain unscored. Latent conditioning is disabled;
384D inputs are placeholders. Genuine 8D/384D/768D latent decoding, independent
US Code fidelity, broader logic-family compliance and `lake build legal`
remain unqualified. No semantic/legal correctness or proof-authority claim is
made. No default promotion, checkpoint selection or follow-up training occurred.

The prior [actor-context comparison](legal_actor_features_training_20261013.md)
provides the frozen trained parent. The new weights and full output/analysis
archive use [this additive Hub release](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/main/releases/20261014-conditions-presence-v1).

Repository evidence:

- [Fixed training design](../implementation/reports/evidence/legal-head-repair-20261014-01/training-design-v01.json)
- [Independent result review](../implementation/reports/evidence/legal-head-repair-20261014-01/result-independent-review-v01.json)
- [Public result summary](../implementation/reports/evidence/legal-head-repair-20261014-01/public-result-summary-v01.json)
- [Gold-dependent oracle diagnostic](../implementation/reports/evidence/legal-head-repair-20261014-01/conditions-presence-oracle-diagnostic-v01.json)
- [Next experiment gaps](../implementation/reports/evidence/legal-head-repair-20261014-01/next-experiment-gaps-v01.json)

The full [analysis](https://huggingface.co/Publicus/legal-ir-autoencoder/blob/main/releases/20261014-conditions-presence-v1/evidence/conditions-presence-result-analysis-v01.json)
and [independent recount](https://huggingface.co/Publicus/legal-ir-autoencoder/blob/main/releases/20261014-conditions-presence-v1/evidence/conditions-presence-independent-recount-v01.json)
remain in the Hub archive. Git retains their exact hashes and compact summaries.
Hosted CI passing is not claimed.

Immutable Hub publication verified at
[`702caba2da183f9d98a0ffd12f1240243167aab2`](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/702caba2da183f9d98a0ffd12f1240243167aab2/releases/20261014-conditions-presence-v1).
All164 added files (71,689,458 bytes) match their downloaded and original bytes;
all5,105 prior file identities are preserved (5,269 total). The checkpoint stays
experimental, with no default pointer change.
