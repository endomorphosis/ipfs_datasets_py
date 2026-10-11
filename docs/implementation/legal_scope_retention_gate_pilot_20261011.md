# Positive-retention objective trial rejects negative case substitutions

The matched BCE versus positive-parent-margin trial completes 240 AdamW updates
per arm and selects the actual cold step 0 in both. All four trained checkpoints
retain the baseline's 38 exact positive cases and 52 emitted positive cases on
selection, but introduce unsupported emissions. This is a reproducible negative
result for the proposed loss and a stronger selection implementation; it is no
selected accuracy improvement or model-default promotion.

Both opt-in `FrozenRetentionGate` arms use the same predicted-trigger pooling,
frozen contextual 64 and ordered Conv3 byte 33 features, 97→32 Tanh→1 residual,
3,169 trainable parameters, seed 24606 and identical initial tensors. Parent
48559399… is the exact selected support/action MLP at support/action steps120/120,
with every class, presence and pointer tensor and its complete old Adam unchanged.
All six older numerical producers remain byte-exact. This source-only occurrence
track does not consume native 8D, 384D or 768D legal latent vectors.

The control optimizes mean support BCE on all16 records. Treatment adds λ1 mean
`relu(clamp(detached_parent_logit, 0, 1) - candidate_logit)^2` over supported TRAIN
rows where the actual frozen parent emits a proposal; an empty anchor is exactly
zero. All16 teacher transports share the existing frozen-parent tensor pass,
with zero additional parent forwards. Each arm has1,468 anchor presentations;
the diagnostic hinge is nonzero in143 control updates and76 treatment updates,
but only treatment adds it to the loss. This is a soft penalty, not a retention
guarantee. Public prediction never accesses the teacher/hinge or training labels.

The new pure selector keeps all four aggregate floors and additionally preserves
every baseline exact/emitted positive ID and forbids newly emitted negative IDs.
Eligible candidates rank fewer negatives, more exact positives, more learned
negative refusals and earlier actual update; the measured cold state is fallback.
These constraints govern selection only and provide no guarantee on later data.

| Selection: 64 supported +64 unsupported | Update | Whole exact | Positive emitted | Positive learned refusal | Unsupported emitted | Eligible |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| bce | 0 | 38 | 52 | 9 | 13 | yes |
| bce | 120 | 40 | 54 | 7 | 13 | no |
| bce | 240 | 40 | 55 | 5 | 14 | no |
| positive_margin | 0 | 38 | 52 | 9 | 13 | yes |
| positive_margin | 120 | 39 | 55 | 6 | 17 | no |
| positive_margin | 240 | 40 | 55 | 6 | 14 | no |

BCE120 passes all old aggregate floors: whole38→40 and negatives13→13. It removes
two old negative emissions while adding two different ones; the new casewise
floor rejects that substitution. BCE240 and margin240 each remove two and add
three negatives; margin120 adds four without removing any. All fitted states lose
zero baseline whole/emitted positives. The matched treatment therefore does not
show an additional positive-retention benefit on this panel. No final-driven
loss, seed, threshold or policy adjustment or additional fit occurs.

The authored bank contains1,280 sources/640 groups: TRAIN512+512 and selection/final
64+64. It excludes all four previous banks'5,120 normalized sources/2,560 groups,
1,068 content words and the declared/observed facets and semantic heads. Every
action lemma occurs in each of eight templates and each split; null, category,
Unicode and repeated-occurrence ledgers are explicit. Each batch contains eight
actual positive/negative parent pairs, two per negative category, and every TRAIN
source appears three or four times. Grammar, modal aliases and corruption families
are shared and declared. These constructed references are no independently
reviewed statutory gold. Unsupported means outside this authored single-rule
profile, not legally false. The initial author protocol's plain-hinge wording was
corrected to squared hinge before fitting, with its draft preserved; all seven
source/reference/schedule payload files remain byte-identical to that draft.

The two choices and checkpoint hashes are durable before parsing fresh-final or
any of four exposed retention references. All15 parent/selected output panels
are durable before evaluation joins. Reference bytes may be read for hashes;
the assertions and prediction patches are not a syscall-level file sandbox.
Only selected cold states are evaluated on these panels, never rejected fitted
states. All512 archived full parent prediction dictionaries match exactly.

| Selected cold states / parent identical | Whole exact /64 | Raw action /64 | Unsupported emitted /64 | Frozen whole ceiling /64 |
| --- | ---: | ---: | ---: | ---: |
| fresh_final | 36 | 59 | 8 | 43 |
| earlier_scope | 40 | 64 | 8 | 50 |
| earlier_trigger | 39 | 64 | 12 | 43 |
| earlier_support_action | 39 | 62 | 12 | 42 |
| earlier_support_gate | 38 | 61 | 13 | 41 |

On the new final, positive statuses are51 emitted/11 learned refusal/2 structural
blocks; negatives are8 emitted/54 learned refusal/2 incidental blocks. Every
negative emission is a modal misspelling. Raw support TP/FN/FP/TN is53/11/10/54,
class exact49/64 and all-span exact55/64. The fixed structural whole ceiling43/64
is independent of changing the support gate. All selected paired gains/losses
are zero. The preceding38/64 final is a different bank, now separately retained
as `earlier_support_gate`, and must not be treated as this fresh panel's baseline.

| Last TRAIN diagnostic: 512 supported +512 unsupported | Whole exact | Positive emitted | Unsupported emitted | Clipped probability BCE |
| --- | ---: | ---: | ---: | ---: |
| parent | 272 | 391 | 94 | 0.427308 |
| bce | 290 | 407 | 87 | 0.350296 |
| positive_margin | 285 | 405 | 94 | 0.375351 |

Saved postfit TRAIN diagnostics do not trigger more forwards or reselection.
BCE loses1/gains19 baseline whole cases and loses7/gains23 positive emissions;
margin loses0/gains13 whole cases and loses3/gains17 positive emissions. BCE
removes11/adds4 negative emissions; margin removes4/adds4. The soft penalty
reduces observed TRAIN positive losses, with a refusal/aggregate-accuracy tradeoff;
this is no unseen-data guarantee or selected gain.
Treatment's aggregate TRAIN metrics are weaker than control on whole exactness,
unsupported emissions and BCE. Lower training loss alone is not qualification.
Across both arms there are480 actual support-only optimizer calls and7,680
encoded source presentations, including3,840 supported and3,840 unsupported;
no class/action update, ignored negatives or old Adam continuation occurs.
All480 shared parent tensor paths and7,680 teacher row decodes are accounted.

Current validation is78 new-model/old-gate and101 pure-selector cases, all passing
with distinct source-qualified XML identities. Independent corpus, model/selector,
103-artifact protocol and actual saved-result/resource reviews bind the evidence.
The unchanged guardian's23 historical tests were not rerun. Local and downloaded
selected checkpoints each reproduce all1,280 full outputs without opening target
reference files or updating optimizer/tensors/modes/flags/progress/CPU Torch RNG.
Read-only replay uses2 CPU threads and claims no training lease.

The admitted fitting uses2 CPUs/1,536MiB/one child/200MB. Child and guardian return0,
the child is reaped, and only the owned lease/claim is released.34 model-phase RSS
samples peak at820,355,072 bytes (~782.35MiB), with maximum observed gap1.191s.
This is sampled cooperative enforcement, not an absolute peak or kernel cap.
Numerical runner time33.22s, sampler model phase35.54s and guardian elapsed81.40s
have distinct start/end scopes. All500 foreign record bodies are equal across a
saved post-reap→post-final interval. The first snapshot's original admission-phase
label was inaccurate: its timestamp is after pre-finalize, and independent equality
does not cover fitting/admission. The original snapshot is preserved with a
separate correction receipt. The earlier hash-only compatibility receipt does
not establish full prior-record immutability. The14.881s terminal lease-observation
gap occurs after the child is reaped. Finalization accounts75,379,178B;7,552B of
later terminal receipts lie outside that released accounting. Exact scopes are
retained in the actual resource review.

[All six original states, two selected aliases and full evidence](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/eb1890f255b096ef81a8a2364bd28fef296bbfd8/experiments/positive-retention-20261011/run-01) retain
exact checkpoint containers and immutable file identities. Original trained
120/240 states are labeled selection-ineligible research artifacts; selected0
aliases alone are final/retention evaluated. Existing Hub identities and defaults
are preserved.

## Integration and remaining work

The fresh-main audit incorporates native384 retained-wording availability and the
new US Code census, paired-feed and lossless new-write fixes. A second remote
refresh also integrates the concurrently published Source384 Unicode byte-span
fix and archived-target reconciliation (source9e5df0d19, rootc976b4f8a7). All103
scientific artifact bindings stay exact after this fast-forward; fitting remains
at the original pinned a1b5c73e5 source generation. No branch-only
completed source fit supersedes the prior gate experiment; protected historical
worktrees are retained. Native384 reconstruction and source-span proposals have
different inputs, targets and denominators and remain separate lineages.

The original full-occurrence census retains128/60,077 sections,18,342 occurrences
and2,165 archived joins. The newer archived-target reconciliation reuses that
seed and reaches24,191 observed occurrences,2,806 exact archived joins and21,385
outside-target observations, with cursor199:64 and441,098 archived IDs pending.
Outside-target observations are aggregate accounting, not a full identity
inventory; neither source scanning nor reconciliation is complete. The
[concurrent progress report](https://github.com/endomorphosis/ipfs_datasets_py/blob/9e5df0d19b62268cdda356077754fad43bdf65fa/docs/autoencoders/uscode_span_continuation_20261011.md)
records375 intake and70 Source384 historical checks; they were not rerun here.
No model inference, new fit or proof ran in that inventory contribution.
At observed immutable pin
3bdc4d526ec7d83f870c9f481c9c80f43c20adf7, `justicedao/open-us-law-span-cache`
contains only a51-jurisdiction count manifest, with no reviewed text/formulas or
embedding targets. The inspected cache evidence does not establish independently
reviewed statutory semantic gold. These are pinned observations, not live totals.

Before a real US Code fit, extend the genuine native-cache adapter beyond its
fixed216-vector assay while preserving the old48-paragraph/180-clause fixtures;
bind arbitrary source text to authentic native embedding/checkpoint lineage,
explicit input dimension and versioned target. Acquire/review source-context
targets covering exceptions, definitions, cross-references, multiple rules and
quantifiers. Route only representable targets through the declared logic-family
lowerers and compare source meaning separately from syntax/build results.

For another engineered support trial, predeclare a capacity-matched trainable
ordered-byte hypothesis and negative-case retention/contrast pairs with fresh
excluded groups before fitting; this frozen-feature ablation does not prove a
capacity bottleneck. Do not reuse this exposed final for tuning. Native
8D/384D/768D conditioning, broader family reconstruction, reviewed real-law
fidelity and `lake build legal` remain open. All five admission masks stay zero,
formal output stays null and proof/default authority stays false.
