# Fixed optimizer-view vocabulary diagnostic

The new diagnostic in
[`legal_ir_view_vocabulary_diagnostic.py`](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_view_vocabulary_diagnostic.py)
compares the existing LegalIR view head under one explicit prediction vocabulary.
The standalone diagnostic and probe add new files without changing official
evaluation, training loss, Pareto checks, rollback or checkpoint serialization.
The separately attributed training observer is integrated below.
Native a-01 passed **95 cases across three complete modules**, including 44 new
diagnostic cases, in 1.739 JUnit seconds (42.63100290996954 native seconds).
Its 144 declared source pins stayed exact; all fifteen retained files total
43,393 bytes, and the selected storage claim was released. The separate retained
checkpoint probe b-01 also passed on the original source cohort: two tuning rows,
two saved checkpoints and 163 exact pins in 48.48552621877752 native seconds.
Its sixteen files total 102,977 bytes and its storage claim was released.
These a-01/b-01 observations precede integration of the published training
observer. The combined source then passed **122 tests** and a fresh original-asset
replay, with unchanged numerical results, as recorded below.

## Why this comparison is separate

The [retained three-arm head experiment](legal_ir_head_training_probe_20261015.md)
used two repeatedly inspected tuning rows with four and six target labels. The
existing scorer unions target labels with checkpoint keys. Inserting neutral
keys can therefore change normalization and CE without a useful logit update.
Both historical view proposals remain rejected. Their saved candidate files are
rolled-back copies of the parent; they do not retain the rejected proposal
weights and cannot reproduce those proposals' diagnostic scores.

The fixed profile comes from the actual optimizer target owner,
`logic/bridge/multiview.py`: its six declared core lanes plus the preserved ZKP
lane, minus exclusions. Its seven ordered labels are:

```text
CEC.native
deontic.ir
external_provers.router
modal.frame_logic
TDFOL.prover
knowledge_graphs.neo4j_compat
zkp.circuits
```

This is the `optimizer_bridge_contract_lane` namespace, not
the payload-contract registry or aggregated reporting-family names. The payload
`modal.ir_decompiler` maps to `modal.frame_logic` in this target owner. A separate
raw fallback such as `ui_ux_ir.formalize` or reconstruction prior
`modal.autoencoder` is unsupported by this diagnostic. Unknown labels, including
zero-valued or disabled-head entries, refuse rather than being renamed, dropped
or added to prediction support. The profile binds the mapper and registry source
bodies, independently of observed row support and checkpoint keys.

## Numeric and model contract

The pure reducer takes bounded closed rows with sample ID, effective logits and
target distribution. Missing known logits mean zero. It normalizes nonnegative
finite target mass and calculates CE using stable shifted log-sum-exp, target
entropy and CE minus entropy. The uniform reference is `ln(7)` for every row.
Official CE retains its existing `1e-12` probability floor; these arithmetic
profiles have separate names and neither result replaces the other.

The model adapter accepts exact supported model/state/sample types, Python
compute, no codec features and no legacy plugins. It copies the state and the
existing target/loss context, then creates isolated feature and candidate caches.
It calls the existing effective-logit head with all seven labels and sample
memory disabled. Caller state, configuration, caches, ordered sample fields and
producer bodies must remain current through the operation. Formula order is
part of the diagnostic input, because the existing head extracts transition
features from that order; the usual sorted serializer cannot substitute for it.

The report binds actual state identity/revision, state architecture, model
configuration, ordered sample snapshot, targets, evaluator context and profile.
The supplied checkpoint/family/schema/task/dimension/encoder/token context is an
explicit caller declaration. This API does not read or authenticate a checkpoint
file. An outer retained-asset probe must independently verify those bytes.
Legacy encoder revision or token metadata may be explicitly unknown. Dimensions
8, 384 and 768 remain separate declared paths; there is no automatic checkpoint
migration, new model registration or upload.

A head with zero scale is reported inactive but retains all seven prediction
classes. Entirely inactive finite heads have uniform predictions and CE `ln(7)`.
This does not establish that every checkpoint, optional codec or bridge extension
fits this initial diagnostic. No new persistent metric cache is introduced.

## Retained comparison and qualification

The original two tuning rows, their 384D GTE-small embeddings, original target
configuration, target bundles, parent state and accepted structural state are
independently bound by
[`retained-head-inputs.json`](evidence/legal-ir-fixed-view-vocabulary-20261015/retained-head-inputs.json)
and its
[provenance audit](evidence/legal-ir-fixed-view-vocabulary-20261015/asset-provenance.json).
The retained target loader must use the complete original `TargetSnapshotConfig`.
Constructing a new configuration from today's package would invalidate those
historical targets and would not be the requested asset reuse.

One compressed target expands to 38,424,601 bytes and the other to 23,906,265
bytes. The probe uses the existing explicit 64-MiB per-target expansion bound.
Both checkpoints exceed the native launcher's 4-MiB individual source-pin limit;
small descriptors and separately bounded stable file/hash checks cover them.
The source-pin ceiling, global resource policy and storage cap stay unchanged.
No historical source, target, embedding or checkpoint is rewritten.

Both retained checkpoints have zero effective view logits on these rows. Their
fixed seven-class CE is **1.9459101490553132**, exactly the uniform reference
`ln(7)`; mean target entropy is 1.5455736746904711 and excess CE is
0.400336474364842. The existing scorer gives 1.3862943611198906 (`ln(4)`) and
1.7917594692280547 (`ln(6)`) on the respective rows for both states. These are
different normalization supports, not an improvement from the structural update.
The structural embedding improvement remains a separate historical finding.
The reports show no stored rows in any supported view-logit head. This result
does not establish decoder saturation; it describes these retained view heads
and the two inspected inputs.
All original nineteen files stayed exact through 37 guarded public operations.
No encoder, training, full decoder, compiler or solver was called.

The standalone sample exports use the historical sorted-formula serializer.
They preserve that archived JSON contract but cannot regenerate the adapter's
ordered-input digest by themselves. The probe binds the original source/record
inputs and producer; the adapter verifies its ordered dataclass snapshot. The
independent metadata auditor verifies matching reported ordered-input/context
commitments across checkpoints without claiming to reconstruct every ordered
cache alias from the sorted sample exports.

Two launcher setup omissions were corrected before the native attempt opened:
the required resource-ledger argument and the initially empty attempt directory.
The unchanged request was then admitted normally. The
[setup record](evidence/legal-ir-fixed-view-vocabulary-20261015/launcher-cli-preflight.json)
and original missing-directory stderr preserve those refusals; neither ran the
productive comparison child.

The unit qualification selects three complete ordinary-file modules: the new
numeric/model diagnostic cases, existing nonview-projection/rollback regression,
and existing payload-view contract tests. Counts from those modules and the
standalone retained probe must remain separate. A successful unit or replay
check does not turn compiler targets into reviewed legal meanings.

## Concurrent observer work

A later read-only survey found overlapping work in the dirty canonical checkout:
`modal_autoencoder_view_diagnostic.py` and optional training observers in its
modified `modal_autoencoder.py`. At that observation, those files were
uncommitted foreign work and were preserved. The generic observer accepts a caller-declared vocabulary,
warms existing feature caches and records baseline/proposal/final observations.
Our standalone diagnostic pins the actual seven-lane generation, refuses unknown
stored labels and isolates the readout with complete input/state witnesses.
Their different profiles and receipt boundaries must remain explicit; neither
is a drop-in alias for the other. The original a-01/b-01 runs did not qualify
that observer.

The author subsequently published the observer in `origin/main` commit
`3421e861ac06662a18c23b342acfbd8e4e3cf0df`. It changes the core model source;
the a-01/b-01 results above apply to their original pinned source and cannot be
relabeled as qualification of that incoming code. A normal merge integrates its
unchanged contribution and the actual primary-graph corpus export. Fresh combined
qualification passed after that merge. Preserve both profiles and boundary adapters;
sharing the pure numerical reducer can be considered later. The training
observer can retain rejected proposal observations in future runs; old
rolled-back checkpoint files cannot supply those missing measurements.

The author's [fresh-target training probe](legal_ir_fixed_view_probe_20261015.md)
already retains those observations: proposed fixed CE is 1.900527/global and
1.897565/feature, from 1.945910, while both proposals fail the existing native
acceptance rule. That separately attributed run uses newly compiled targets;
this standalone replay deliberately reuses the historical complete targets.
Neither is an independent holdout or a legal reconstruction result. The author's
240-case fixture-alias qualification remains distinct from our combined strict
ordinary-file qualification; overlapping cases must not be added together.

After the normal merge, native **a-02 passed 122 unique cases across four
complete modules**, with no failures, errors or skips. It includes the original
95-case roster and the observer author's complete 27-case module. JUnit reports
1.857 seconds; native ownership reports 41.96363989007659 seconds, 146 unchanged
source pins and fifteen retained files totaling 53,237 bytes, with the selected
storage claim released. This uses the existing strict ordinary-file profile.
It qualifies these selected tests on the combined source rather than rerunning
the author's broader 240-case roster or repeating training.

Native **b-02** then passed the same standalone original-asset comparison on the
combined source: 165 unchanged declared pins, 48.04187000985257 native seconds,
sixteen retained files totaling 102,986 bytes and a released storage claim.
The nineteen original input hashes, two checkpoint state identities, seven-lane
profile, target/loss and evaluator-context commitments stayed identical to b-01.
Every fixed-view metric and existing dynamic-support readout also stayed
identical. Producer source hashes correctly record the updated model core.
The observer helper and its tests retain their published bodies unchanged.

The [comprehensive corpus plan](legal_ir_uscode_corpus_improvement_plan_20261015.md)
still requires independent legal/formal targets, exact reconstruction measures,
scoped graph closure and actual Lean builds. A view-classification diagnostic
alone measures none of those outcomes. The next semantic experiment needs a
reviewed connected definition/norm/use component, complete dependency/exposure
partitions and separate exact-text, semantic-AST, view and embedding metrics.
Compare correct, shuffled and absent latents and declared source/retrieval
controls before qualifying a task-specific teacher. Historical rejected updates
cannot be accepted retroactively or used as independent holdout evidence.
