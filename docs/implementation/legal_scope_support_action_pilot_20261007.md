# Support and action residuals improve authored proposals, with a refusal tradeoff

This opt-in continuation fixes the selected predicted-trigger class readout and
fits new support and action endpoint residuals. The MLP improves exact emitted
proposals from 28/64 to 39/64 on a fresh authored panel and raw action spans from
48/64 to 62/64. Unsupported emissions increase from 7/64 to 12/64. These results
do not qualify a default replacement or reviewed statutory autoformalization.

The parent is the selected step-240 checkpoint from the
[trigger readout pilot](legal_scope_trigger_readout_pilot_20261007.md), exact
file SHA256 `6e4be3abad5eafa47cc8a496bea561a8b0ea4ccb54db27273278e82e88facd4f`.
All 26,685 parent parameters remain frozen, including its trained class adapter,
ordered byte encoder, BiGRU, support/presence and every original pointer head.
Original full Adam states remain embedded as exact parent JSON provenance;
they are not resumed. The new residual optimizer starts with empty moments.
This model reads source text; it does not consume 8D/384D/768D legal latents.

## Declared comparison and targets

The linear arm has 195 trainable parameters; the tanh-MLP arm has 6,339, with
hidden width 32. They use the same frozen 64-wide mean token states for support
and 64-wide per-token states for action start/end. All three final projections
start at zero, preserving the measured parent function at update zero. This
compares equal data and optimizer budgets, not equal parameter capacities.
Class logits, optional presence and every nonaction pointer stay byte-exact in
all measured source-only panels. The new implementation reuses the original
private tensor path and predicted-trigger feature calculation; it does not
modify the trained producers or call their old frozen-parent training contract.

Each arm completes 240 AdamW steps with seed 24604, learning rate 0.003, zero
weight decay and gradient clip 5. Each batch contains eight supported and eight
unsupported records. Unlike the preceding class-only fit, all 16 are encoded:
support BCE uses every record, while half the sum of action start/end CE uses
only the eight positives. Across both arms this is 480 joint optimizer calls,
7,680 encoded source presentations, 3,840 positive action presentations and
3,840 unsupported support presentations. Support and action update counts refer
to these same calls, not 960 separate steps. All-negative API calls update
support but leave action gradients, weights, moments and action counters idle.

The new corpus contains 512+512 TRAIN and 64+64 selection/final records. Its
1,280 normalized sources and 640 paired groups are disjoint from both earlier
banks together, with 2,560 sources and 1,280 groups. Observed/declared nonmodal
facets, semantic heads and declared content words are also excluded across
splits and from the earlier banks. All eight action lemmas occur in each of the
eight templates: eight instances each in TRAIN and one each in evaluation.
Nullable cells, four unsupported categories, caller premises, Unicode and
repeated occurrences have explicit ledgers. Modal aliases, templates and the
declared anagram permutations remain shared. The labels are construction
premises, mechanically checked before fitting, not independent legal gold.

Selection candidates are updates 0, 120 and 240. Updated candidates must preserve
the parent selection panel's positive emission count, not increase its positive
learned refusals and not decrease its positive exact count. Eligible candidates
maximize positive whole exactness plus learned unsupported refusals, then fewer
unsupported emissions, more positive exactness and earlier update. Step zero
is the fallback. These aggregate floors prevent reject-all winning; they do not
guarantee per-case retention or a hard unsupported-emission ceiling. Both arms
select update 120 despite completing 240 updates. The final and both earlier
retention references enter neither fitting nor selection. Both choices are
durable before their numerical reference parsing; all nine source-only panels
are durable before any evaluation reference join. Authors reviewed construction
labels beforehand, so the barrier is numerical, not an authors-blind claim.

## Fresh authored final

Each column evaluates the same 64 supported and 64 unsupported sources.

| Endpoint | Fixed trigger parent | Linear residual | MLP residual |
| --- | ---: | ---: | ---: |
| Actual joint optimizer calls | 0 | 240 | 240 |
| Selected update | — | 120 | 120 |
| Raw modality exact | 45/64 | 45/64 | 45/64 |
| Raw action span exact | 48/64 | 58/64 | 62/64 |
| Raw all-five-span exact | 47/64 | 56/64 | 58/64 |
| Exact emitted positive proposal | 28/64 | 37/64 | 39/64 |
| Whole exact with nonempty condition | 10/32 | 16/32 | 17/32 |
| Positive proposal emitted | 44/64 | 55/64 | 55/64 |
| Positive learned refusal | 16/64 | 7/64 | 6/64 |
| Positive structural block | 4/64 | 2/64 | 3/64 |
| Unsupported learned refusal | 56/64 | 51/64 | 50/64 |
| Unsupported incidental block | 1/64 | 2/64 | 2/64 |
| Unsupported proposal emitted | 7/64 | 11/64 | 12/64 |
| Raw support TP/FN/FP/TN | 48/16/8/56 | 57/7/13/51 | 58/6/14/50 |

Unsupported means outside the declared single-rule profile, not legally false.
The parent emits seven modal-anagram cases. Linear/MLP emit ten/eleven anagram
cases and one extra-exception case each. Neither updated arm removes an earlier
unsupported emission. Supported gains retain all 28 parent whole successes,
with nine/eleven additions and zero observed losses on this panel. That does not
neutralize the four/five added unsupported emissions.

Fixed class and nonaction spans cap whole correctness at 43/64 even with perfect
support/action repair. MLP reaches 39/64; the remaining 21 sources need changes
outside these heads. The exact gerund-agent template is
`gerund_object_agent_modal_condition`: raw actions improve 6/8 to 7/8 to 8/8,
and whole proposals improve 4/8 to 5/8 to 6/8. Other gerund templates have separate
ledgers. Raw action exactness is not whole proposal exactness. Last-TRAIN panels
at actual update 240 give linear/MLP 505/512 and 512/512 raw action spans, and
313/512 and 323/512 whole proposals; unsupported emissions are 103/512 and
107/512. These diagnostic panels do not select the checkpoints or add updates.

## Earlier exposed retention panels

| Endpoint | Parent | Linear | MLP |
| --- | ---: | ---: | ---: |
| Earlier scope cohort: exact proposal | 29/64 | 36/64 | 40/64 |
| Earlier scope cohort: raw action exact | 50/64 | 58/64 | 64/64 |
| Earlier scope cohort: unsupported emitted | 4/64 | 7/64 | 8/64 |
| Earlier trigger cohort: exact proposal | 30/64 | 37/64 | 39/64 |
| Earlier trigger cohort: raw action exact | 54/64 | 55/64 | 64/64 |
| Earlier trigger cohort: unsupported emitted | 6/64 | 12/64 | 12/64 |

All 256 original parent prediction dictionaries exactly replay their archived
panels. Class/nonaction outputs remain fixed. Both arms retain every parent
whole success on these measured cohorts, but add three/four unsupported
emissions on the earlier scope cohort and six each on the earlier trigger
cohort. The previously broken gerund-agent action spans reach 8/8 under MLP on
both older panels; whole exactness reaches only 2/8 in each. Refusal/class/other
facets still matter. These cohorts are postfit exposed retention, not new
holdouts, fresh model selection or independent legal review.

## Output custody and reproduction

A separate **label-informed posthoc diagnostic** intersects the saved parent and
candidate emission statuses. It permits a candidate proposal only when both
models emitted on that exact source, including the parent's structural boundary.
All six composite panels are saved before their own reference joins, and every
allowed candidate is revalidated by the pure proposal owner. This procedure runs
no neural forward or optimizer update and changes no selected checkpoint.

Fresh composite whole exactness is 29/64 for either arm, compared with parent
28/64; unsupported emissions remain 7/64. Earlier scope composites give 31/64
for either arm with 4/64 unsupported emissions; earlier trigger composites give
30/64 linear and 32/64 MLP with 6/64 unsupported emissions. All parent whole
successes are retained in these observed composites. Their emission sets are
subsets of the parent's by construction, so they cannot add unsupported
emissions on the checked sources. That preserves existing unsupported emissions
and most parent refusals. It is not proof of legal fidelity or a newly learned
support probability. The filter was proposed after seeing exposed final results;
its scores are posthoc engineering diagnostics, not fresh policy evaluation or
qualification. It must be predeclared and tested on a new panel before use as a
selection or runtime policy. Raw model results above remain unchanged.

Every emitted prediction passes through the existing canonical occurrence
proposal owner with all five admission masks zero and null formal output.
Caller attachment is copied only for a predicted nonempty condition. Conditions
remain opaque, coverage/context unresolved and legal semantics unreviewed.
Exceptions, multiple rules, quantifier scope, family lowering and
`lake build legal` qualification remain open. No existing latent weights,
runtime registry, teacher or default asset is replaced.

Custom `legal-scope-support-action-checkpoint/v1` JSON containers preserve exact
parent UTF8 bytes, new residual tensors, full new Adam moments, separate support
and action progress, producer hashes and the closed feature/loss recipe. Restore
rejects changed producers, schemas, inventories, moments, counters or nonfinite
values. Linear selected SHA256 is
`741ea06a018d603b268e0acc8efc21d8ae1b9d0e3d1780212746c8a6cfdae2f1`;
MLP selected SHA256 is
`48559399bb22de0fe68908919d225d391880a38f4fab659026d526e19ffc9155`.
The trained source SHA256 is
`ce7abc45032bee6ac950720d79c8f329c03a68961140c0f2ad9ade8ea923988c`.

```python
import hashlib, json
from pathlib import Path
from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_support_action as head

checkpoint = json.loads(Path("checkpoint.json").read_text())
model, optimizer, support_steps, action_steps = head.restore_support_action_checkpoint(checkpoint)
source = "The clerk shall submit notice if notice arrives."
result = head.predict_support_action(model, source, "rule",
    expected_source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest())
```

This is an unscored experimental API example. It is not a statutory translation.
Validation passes 131 distinct decoder/proposal tests and eight pure selection
fixtures. The byte-identical guardian retains its earlier 23 pure-test evidence.
Separate read-only replay reproduces all 768 complete selected outputs across
three cohorts, preserving the exact parent, residuals, full new Adam state,
head counters, modes and RNG with zero additional updates and no references read.
Actual resource admission and cleanup succeed; the child exits zero and is
reaped, and only its own lease/disk claim is released. Thirty-five model-phase
RSS samples peak at 787,025,920 bytes with maximum observed gap 1.076 seconds.
This is a non-atomic sampled group sum, not an absolute peak or kernel quota.
The numerical runner takes 20.46 seconds; guardian admission/import/final
inventory are separate. Hosted CI availability is recorded separately.

Selected weights and complete evidence: [support/action experiment](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/f2e6e9ad6b693a605066146dd8985f036fcaa50a/experiments/support-action-20261007/run-01).
The next hypothesis needs stronger malformed-trigger refusal and a predeclared
output boundary alongside these action gains. Reusing this exposed final to
retune a threshold or promote a model is not permitted by the experiment plan.
